"""Core serializable models for Flowdesk analysis definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

SourceStage = Literal["raw", "compensated", "transformed"]
GateType = Literal["rectangle", "polygon", "range", "boolean"]
GateAxisScale = Literal["linear", "log10", "asinh"]
CompensationSource = Literal["fcs_metadata_spillover", "user_defined", "imported"]


class DerivedFailurePolicy(StrEnum):
  """Action taken when one derived parameter cannot be evaluated."""

  FAIL_RUN = "fail_run"
  FAIL_SAMPLE = "fail_sample"
  EMIT_NAN_WITH_WARNING = "emit_nan_with_warning"


@dataclass(frozen=True)
class ChannelSpec:
  """A measured FCS channel or computed parameter usable in plots, gates, and export."""

  id: str
  name: str
  short_name: str | None = None
  detector: str | None = None
  unit: str | None = None
  metadata: dict[str, Any] = field(default_factory=dict)
  fcs_parameter_index: int | None = None
  stain: str | None = None


@dataclass(frozen=True)
class SampleSpec:
  """A sample entry that references an FCS file without copying raw data."""

  id: str
  name: str
  path: str
  group_id: str | None = None
  metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompensationMatrixSpec:
  """A spillover or compensation matrix definition aligned to named channels."""

  id: str
  name: str
  source: CompensationSource
  channels: tuple[str, ...]
  matrix: tuple[tuple[float, ...], ...]
  created_by: str | None = None
  created_at: str | None = None
  notes: str = ""

  def __post_init__(self) -> None:
    size = len(self.channels)
    if len(self.matrix) != size or any(len(row) != size for row in self.matrix):
      raise ValueError("compensation matrix must be square and match channels")


@dataclass(frozen=True)
class DerivedParameterSpec:
  """A safely evaluated computed parameter such as a fluorescence ratio."""

  id: str
  name: str
  expression: str
  source_stage: SourceStage = "compensated"
  input_parameters: tuple[str, ...] = field(default_factory=tuple)
  output_channel_id: str | None = None
  output_label: str | None = None
  unit: str | None = None
  invalid_value_policy: DerivedFailurePolicy = (
    DerivedFailurePolicy.EMIT_NAN_WITH_WARNING
  )
  legacy_source_stage_policy: Literal["reject"] | None = None
  notes: str = ""

  def __post_init__(self) -> None:
    if self.source_stage not in {"raw", "compensated", "transformed"}:
      raise ValueError(f"invalid derived source stage: {self.source_stage!r}")
    if (
      self.source_stage == "transformed"
      and self.legacy_source_stage_policy != "reject"
    ):
      raise ValueError(
        "legacy transformed source requires legacy_source_stage_policy='reject'"
      )
    if (
      self.source_stage != "transformed"
      and self.legacy_source_stage_policy is not None
    ):
      raise ValueError(
        "legacy_source_stage_policy is only valid for transformed source"
      )
    if self.output_channel_id is not None and (
      not isinstance(self.output_channel_id, str) or not self.output_channel_id
    ):
      raise ValueError("derived output channel ID must be a non-empty string")
    if self.unit is not None and not isinstance(self.unit, str):
      raise ValueError("derived unit must be a string or null")
    raw_policy = self.invalid_value_policy
    if raw_policy == "division_by_zero_to_nan":
      raw_policy = DerivedFailurePolicy.EMIT_NAN_WITH_WARNING
    try:
      policy = DerivedFailurePolicy(raw_policy)
    except ValueError as exc:
      choices = ", ".join(policy.value for policy in DerivedFailurePolicy)
      raise ValueError(
        f"invalid derived failure policy {self.invalid_value_policy!r}; "
        f"expected one of: {choices}"
      ) from exc
    object.__setattr__(self, "invalid_value_policy", policy)

  @property
  def output_id(self) -> str:
    """Stable channel ID produced by this definition."""
    return self.output_channel_id or self.id


@dataclass(frozen=True)
class TransformSpec:
  """A transform definition applied to one parameter before plotting or gating."""

  id: str
  name: str
  transform_type: Literal[
    "linear",
    "log",
    "asinh",
    "legacy_logicle_approximation",
  ]
  parameter: str
  settings: dict[str, Any] = field(default_factory=dict)
  notes: str = ""


@dataclass(frozen=True)
class GateSpec:
  """A reproducible gate stored in data coordinates or transformed data coordinates."""

  id: str
  name: str
  gate_type: GateType
  parent_population_id: str | None = None
  x_parameter: str | None = None
  y_parameter: str | None = None
  x_scale: GateAxisScale = "linear"
  y_scale: GateAxisScale = "linear"
  transform_id: str | None = None
  compensation_id: str | None = None
  coordinates: tuple[tuple[float, float], ...] = field(default_factory=tuple)
  thresholds: dict[str, Any] = field(default_factory=dict)
  notes: str = ""


@dataclass(frozen=True)
class GatingStrategySpec:
  """A named collection of gates and parent-child population relationships."""

  id: str
  name: str
  gates: tuple[GateSpec, ...] = field(default_factory=tuple)
  root_population_id: str = "all_events"
  notes: str = ""


@dataclass(frozen=True)
class PopulationResult:
  """Population statistics produced by running a gating strategy on a sample."""

  sample_id: str
  population_id: str
  event_count: int
  frequency_of_parent: float | None
  frequency_of_total: float | None


@dataclass(frozen=True)
class PopulationMembership:
  """Read-only boolean membership mask for a population in a sample.

  The ``mask`` is a full-length boolean array aligned with the original event
  data.  It is made immutable before being returned so that external code
  cannot accidentally modify the gating result.
  """

  sample_id: str
  population_id: str
  mask: NDArray[np.bool_]

  def __post_init__(self) -> None:
    mask = np.array(self.mask, dtype=np.bool_, copy=True)
    mask.setflags(write=False)
    object.__setattr__(self, "mask", mask)

  @property
  def event_count(self) -> int:
    """Number of events in this population (mask.sum())."""
    return int(self.mask.sum())


@dataclass(frozen=True)
class ExportRecord:
  """A serializable row for CSV or TSV population statistics export."""

  sample_id: str
  population_id: str
  metric: str
  value: int | float | str | None
