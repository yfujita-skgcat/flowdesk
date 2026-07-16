"""Core serializable models for Flowdesk analysis definitions."""

from __future__ import annotations

import math
from datetime import datetime
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

SourceStage = Literal["raw", "compensated", "transformed"]
GateType = Literal["rectangle", "polygon", "range", "ellipse", "boolean"]
GateAxisScale = Literal["linear", "log10", "asinh"]
GateOverrideGeometryMode = Literal["delta", "full"]
GatePurpose = Literal["technical_cleanup", "comparison_critical"]
CompensationSource = Literal["fcs_metadata_spillover", "user_defined", "imported", "calculated"]
CompensationBindingScope = Literal["sample", "group", "execution_profile"]
CompensationRegressionMethod = Literal["linear", "median"]
CompensationOutlierPolicy = Literal["iqr", "zscore", "none"]
StatisticMetric = Literal[
    "count",
    "frequency_of_parent",
    "frequency_of_total",
    "mean",
    "median",
    "geometric_mean",
    "stddev",
    "cv",
    "mad",
    "percentile",
]
StatisticSource = Literal["raw", "compensated", "transformed"]
StatisticValuePolicy = Literal["full_events"]
StatisticStatus = Literal["ok", "empty", "undefined", "error"]
StatisticUndefinedReason = Literal[
    "empty_population",
    "all_nan",
    "nonfinite_values",
    "all_nonpositive_geometric_mean",
    "zero_mean_for_cv",
    "invalid_percentile",
    "calculation_error",
]


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


AnnotationValue = str | int | float | bool | None
AnnotationSource = Literal["fcs", "workspace", "imported"]
SampleGroupRole = Literal[
  "all_samples",
  "compensation_controls",
  "panel",
  "acquisition",
  "qc",
  "user",
]


@dataclass(frozen=True)
class AnnotationSpec:
  """A typed, non-destructive value associated with one sample keyword."""

  sample_id: str
  keyword: str
  value: AnnotationValue
  source: AnnotationSource

  def __post_init__(self) -> None:
    if not self.sample_id or not self.keyword:
      raise ValueError("annotation sample_id and keyword must be non-empty")
    if self.source not in {"fcs", "workspace", "imported"}:
      raise ValueError(f"invalid annotation source: {self.source!r}")
    if isinstance(self.value, (list, dict)):
      raise ValueError("annotation value must be a scalar or null")


@dataclass(frozen=True)
class SampleGroupSpec:
  """Explicit and rule-based collection of samples for analysis assignment.

  ``membership_rule`` is a JSON-serializable restricted rule AST evaluated by
  :mod:`flowdesk_core.groups`; it is never interpreted as Python code.
  """

  id: str
  name: str
  role: SampleGroupRole = "user"
  color: str | None = None
  sample_ids: tuple[str, ...] = field(default_factory=tuple)
  membership_rule: dict[str, Any] | None = None

  def __post_init__(self) -> None:
    if not self.id or not self.name:
      raise ValueError("sample group ID and name must be non-empty")
    if self.role not in {
      "all_samples", "compensation_controls", "panel", "acquisition", "qc", "user"
    }:
      raise ValueError(f"invalid sample group role: {self.role!r}")
    if any(not sample_id for sample_id in self.sample_ids):
      raise ValueError("sample group IDs must be non-empty")
    if len(set(self.sample_ids)) != len(self.sample_ids):
      raise ValueError("sample group sample IDs must be unique")
    if self.membership_rule is not None and not isinstance(self.membership_rule, dict):
      raise ValueError("sample group membership_rule must be an object or null")


@dataclass(frozen=True)
class GroupStrategyBindingSpec:
  """Bind one gating strategy and optional statistics to one sample group."""

  id: str
  group_id: str
  gating_strategy_id: str
  statistic_ids: tuple[str, ...] = field(default_factory=tuple)

  def __post_init__(self) -> None:
    if not self.id or not self.group_id or not self.gating_strategy_id:
      raise ValueError("binding ID, group ID, and gating strategy ID must be non-empty")
    if any(not statistic_id for statistic_id in self.statistic_ids):
      raise ValueError("binding statistic IDs must be non-empty")
    if len(set(self.statistic_ids)) != len(self.statistic_ids):
      raise ValueError("binding statistic IDs must be unique")


@dataclass(frozen=True)
class CompensationManualEditSpec:
  """One auditable cell change made only on a duplicated matrix."""

  row_channel_id: str
  column_channel_id: str
  old_value: float
  new_value: float
  edited_at: str | None = None
  edited_by: str | None = None
  reason: str = ""

  def __post_init__(self) -> None:
    if not self.row_channel_id or not self.column_channel_id:
      raise ValueError("manual edit channel IDs must be non-empty")


@dataclass(frozen=True)
class CompensationProvenanceSpec:
  """Origin and reproducibility metadata kept separate from matrix binding."""

  source_sample_id: str | None = None
  source_metadata_key: str | None = None
  control_sample_ids: tuple[str, ...] = field(default_factory=tuple)
  control_population_ids: tuple[str, ...] = field(default_factory=tuple)
  algorithm: str | None = None
  algorithm_version: str | None = None
  software_version: str | None = None
  derived_from_matrix_id: str | None = None
  manual_edits: tuple[CompensationManualEditSpec, ...] = field(default_factory=tuple)

  def __post_init__(self) -> None:
    for label, values in (
      ("control sample", self.control_sample_ids),
      ("control population", self.control_population_ids),
    ):
      if any(not value for value in values):
        raise ValueError(f"{label} IDs must be non-empty")
      if len(set(values)) != len(values):
        raise ValueError(f"{label} IDs must be unique")
    if self.manual_edits and not self.derived_from_matrix_id:
      raise ValueError(
        "manual edit history requires derived_from_matrix_id; "
        "duplicate the source matrix before editing"
      )


@dataclass(frozen=True)
class CompensationBindingSpec:
  """Apply one immutable matrix to one explicitly identified project scope."""

  id: str
  matrix_id: str
  scope: CompensationBindingScope
  target_id: str
  created_at: str | None = None
  created_by: str | None = None
  notes: str = ""

  def __post_init__(self) -> None:
    if self.scope not in {"sample", "group", "execution_profile"}:
      raise ValueError(f"invalid compensation binding scope: {self.scope!r}")
    if not self.id or not self.matrix_id or not self.target_id:
      raise ValueError("binding ID, matrix ID, and target ID must be non-empty")


@dataclass(frozen=True)
class CompensationMatrixSpec:
  """An immutable spillover matrix aligned to stable channel IDs."""

  id: str
  name: str
  source: CompensationSource
  channels: tuple[str, ...]
  matrix: tuple[tuple[float, ...], ...]
  created_by: str | None = None
  created_at: str | None = None
  notes: str = ""
  provenance: CompensationProvenanceSpec = field(
    default_factory=CompensationProvenanceSpec
  )

  def __post_init__(self) -> None:
    size = len(self.channels)
    if len(self.matrix) != size or any(len(row) != size for row in self.matrix):
      raise ValueError("compensation matrix must be square and match channels")


@dataclass(frozen=True)
class CompensationCalculationControlSpec:
  """One detector's explicitly identified single-stain control sample."""

  detector_channel_id: str
  positive_population_id: str
  negative_population_id: str
  sample_id: str = "legacy-control"


@dataclass(frozen=True)
class CompensationCalculationSpec:
  """Configuration for calculating a spillover matrix from single-stain controls.

  References explicit control samples and their positive/negative populations,
  specifies the regression method, outlier policy, and minimum event
  thresholds. The result of calculation is an immutable CompensationMatrixSpec
  with source='calculated' and full provenance.
  """

  id: str
  name: str
  controls: tuple[CompensationCalculationControlSpec, ...]
  regression_method: CompensationRegressionMethod = "linear"
  outlier_policy: CompensationOutlierPolicy = "iqr"
  minimum_positive_events: int = 100
  minimum_negative_events: int = 50
  created_by: str | None = None
  created_at: str | None = None
  notes: str = ""

  def __post_init__(self) -> None:
    if not self.id:
      raise ValueError("calculation ID must be non-empty")
    if not self.controls:
      raise ValueError("calculation must have at least one control assignment")
    detector_ids = [c.detector_channel_id for c in self.controls]
    if len(set(detector_ids)) != len(detector_ids):
      raise ValueError("detector channel IDs must be unique across controls")
    for c in self.controls:
      if not c.sample_id:
        raise ValueError("control sample ID must be non-empty")
      if not c.detector_channel_id:
        raise ValueError("detector channel ID must be non-empty")
      if not c.positive_population_id:
        raise ValueError("positive population ID must be non-empty")
      if not c.negative_population_id:
        raise ValueError("negative population ID must be non-empty")
    if self.regression_method not in {"linear", "median"}:
      raise ValueError(f"invalid regression method: {self.regression_method!r}")
    if self.outlier_policy not in {"iqr", "zscore", "none"}:
      raise ValueError(f"invalid outlier policy: {self.outlier_policy!r}")
    if self.minimum_positive_events < 1:
      raise ValueError("minimum_positive_events must be positive")
    if self.minimum_negative_events < 1:
      raise ValueError("minimum_negative_events must be positive")


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
    "logicle",
    "legacy_logicle_approximation",
  ]
  parameter: str
  settings: dict[str, Any] = field(default_factory=dict)
  role: Literal["analysis"] = "analysis"
  notes: str = ""

  def __post_init__(self) -> None:
    if self.role != "analysis":
      raise ValueError(f"invalid transform role: {self.role!r}")


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
  x_transform_id: str | None = None
  y_transform_id: str | None = None
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
class GateOverrideSpec:
  """An explicit, sample-local geometry edit layered on a group strategy.

  The override deliberately contains no gate hierarchy or gate-type fields.
  Those are strategy edits and must remain shared across the group.
  """

  id: str
  sample_id: str
  base_gate_id: str
  base_version_hash: str
  geometry_mode: GateOverrideGeometryMode
  coordinates: tuple[tuple[float, float], ...] = field(default_factory=tuple)
  thresholds: dict[str, Any] = field(default_factory=dict)
  author: str = ""
  created_at: str = ""
  reason: str = ""
  gate_purpose: GatePurpose = "technical_cleanup"
  enabled: bool = True

  def __post_init__(self) -> None:
    if not self.id or not self.sample_id or not self.base_gate_id:
      raise ValueError("override IDs must be non-empty")
    if not self.base_version_hash:
      raise ValueError("override base_version_hash must be non-empty")
    if self.geometry_mode not in {"delta", "full"}:
      raise ValueError(f"invalid override geometry mode: {self.geometry_mode!r}")
    if self.gate_purpose not in {"technical_cleanup", "comparison_critical"}:
      raise ValueError(f"invalid gate purpose: {self.gate_purpose!r}")
    if not self.author or not self.created_at or not self.reason:
      raise ValueError("override author, created_at, and reason are required")
    try:
      datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
    except ValueError as exc:
      raise ValueError("override created_at must be an ISO-8601 timestamp") from exc
    if self.geometry_mode == "delta" and not self.coordinates and not self.thresholds:
      raise ValueError("delta override must contain geometry changes")


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


@dataclass(frozen=True)
class StatisticSpec:
  """A persisted definition of a population parameter statistic.

  Specifies which population and parameter to measure, the metric to compute,
  the data source stage (raw/compensated/transformed), optional settings for
  parameterized metrics (e.g. percentile q), and a display format.
  """

  id: str
  name: str
  population_id: str
  parameter_id: str | None = None
  metric: StatisticMetric = "count"
  source_stage: StatisticSource = "compensated"
  value_policy: StatisticValuePolicy = "full_events"
  settings: dict[str, Any] = field(default_factory=dict)
  format: str | None = None
  notes: str = ""

  def __post_init__(self) -> None:
    if not self.id:
      raise ValueError("statistic ID must be non-empty")
    if not self.name:
      raise ValueError("statistic name must be non-empty")
    if not self.population_id:
      raise ValueError("statistic population_id must be non-empty")
    valid_metrics: set[str] = {
      "count",
      "frequency_of_parent",
      "frequency_of_total",
      "mean",
      "median",
      "geometric_mean",
      "stddev",
      "cv",
      "mad",
      "percentile",
    }
    if self.metric not in valid_metrics:
      raise ValueError(f"invalid statistic metric {self.metric!r}")
    valid_stages: set[str] = {"raw", "compensated", "transformed"}
    if self.source_stage not in valid_stages:
      raise ValueError(
        f"invalid statistic source_stage {self.source_stage!r}"
      )
    if self.value_policy != "full_events":
      raise ValueError(
        f"invalid statistic value_policy {self.value_policy!r}"
      )
    if not isinstance(self.settings, dict):
      raise ValueError("statistic settings must be an object")
    if self.format is not None and not isinstance(self.format, str):
      raise ValueError("statistic format must be a string or None")
    if self.metric == "percentile":
      q = self.settings.get("q")
      if q is None:
        raise ValueError(
          "percentile metric requires 'q' in settings"
        )
      if not isinstance(q, (int, float)) or isinstance(q, bool):
        raise ValueError(
          "percentile 'q' setting must be a number"
        )
      if not math.isfinite(q):
        raise ValueError("percentile 'q' setting must be finite")
      if q < 0 or q > 100:
        raise ValueError(
          "percentile 'q' setting must be in [0, 100]"
        )


@dataclass(frozen=True)
class StatisticResult:
  """Computed result of a single statistic definition for one sample.

  ``value`` is ``None`` when the statistic cannot be computed (e.g. empty
  population).  ``status`` distinguishes between a valid zero, an empty
  population, an undefined calculation, and a hard error.
  """

  sample_id: str
  statistic_id: str
  population_id: str
  metric: str
  value: float | int | None = None
  unit: str | None = None
  status: StatisticStatus = "ok"
  undefined_reason: StatisticUndefinedReason | None = None
  statistic_name: str | None = None
