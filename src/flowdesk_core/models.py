"""Core serializable models for Flowdesk analysis definitions."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, cast

import numpy as np
from numpy.typing import NDArray

SourceStage = Literal["raw", "compensated", "transformed"]
GateType = Literal["rectangle", "polygon", "range", "ellipse", "boolean"]
GateOverrideGeometryMode = Literal["delta", "full"]
GatePurpose = Literal["technical_cleanup", "comparison_critical"]
AutoGateAlgorithm = Literal["quantile_rectangle"]
MagneticGateAlgorithm = Literal["largest_gap_range"]
TetheredGateAlgorithm = Literal["translated_rectangle"]
CloneConflictPolicy = Literal["leader_wins", "reject_conflict"]
PlotType = Literal["dot", "scatter", "pseudocolor", "density", "contour", "histogram", "cdf"]
BatchPlotTarget = Literal["all", "explicit", "group"]
BatchPlotFormat = Literal["svg", "png", "jpg", "pdf"]
BatchPlotCollisionPolicy = Literal["fail", "replace", "suffix"]
BatchPlotLayoutPolicy = Literal["current_view", "shared_ranges"]
BatchPlotRasterResolutionMode = Literal["legacy_pixel_dimensions", "dpi_scaled"]
VectorScatterMode = Literal["full_vector", "compact_vector", "hybrid_raster"]
InteractionMode = Literal["pan", "select", "gate"]
OverlayMode = Literal["manual_only", "manual_plus_comparison", "comparison_only"]
ComparisonRole = Literal[
  "reference", "target", "positive_control", "negative_control", "control"
]
OverlayNormalization = Literal["count", "mode", "unit_area"]
MarkerShape = Literal["circle", "square", "triangle", "cross", "plus"]
LineStyle = Literal["solid", "dashed", "dotted", "dashdot"]
LegendPosition = Literal["right", "left", "top", "bottom", "inside"]
PlotTitleMode = Literal["current_sample", "overlay_sample_titles"]
FitStatus = Literal["success", "failed"]
ManualOverridePolicy = Literal["preserve_until_reset", "refit_on_input_change"]
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
StatisticNonFinitePolicy = Literal["strict", "exclude_invalid"]
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


@dataclass(frozen=True)
class BatchPlotExportSpec:
  """Persisted, deterministic selection and naming contract for plot batches."""

  id: str
  name: str
  target: BatchPlotTarget = "all"
  sample_ids: tuple[str, ...] = field(default_factory=tuple)
  group_id: str | None = None
  plot_view_id: str = "main-view"
  formats: tuple[BatchPlotFormat, ...] = ("png",)
  width: int = 800
  height: int = 600
  dpi: int = 96
  raster_resolution_mode: BatchPlotRasterResolutionMode = "legacy_pixel_dimensions"
  vector_scatter_mode: VectorScatterMode = "hybrid_raster"
  hybrid_scatter_dpi: int = 600
  aspect_1_to_1: bool = False
  layout_policy: BatchPlotLayoutPolicy = "current_view"
  include_title: bool = True
  include_axis_labels: bool = True
  include_ticks: bool = True
  include_gates: bool = True
  include_legend: bool = True
  include_status_banner: bool = False
  filename_template: str = "{sample_title}_{sample_id}_{plot_id}"
  collision_policy: BatchPlotCollisionPolicy = "fail"
  strict: bool = True

  def __post_init__(self) -> None:
    if not self.id or not self.name or not self.plot_view_id:
      raise ValueError("batch plot export id, name, and plot_view_id are required")
    if self.target not in {"all", "explicit", "group"}:
      raise ValueError(f"invalid batch plot target {self.target!r}")
    if self.target == "explicit" and not self.sample_ids:
      raise ValueError("explicit batch plot target requires sample_ids")
    if self.target == "group" and not self.group_id:
      raise ValueError("group batch plot target requires group_id")
    if not self.formats or any(value not in {"svg", "png", "jpg", "pdf"} for value in self.formats):
      raise ValueError("batch plot formats must contain svg, png, jpg, or pdf")
    if self.width <= 0 or self.height <= 0:
      raise ValueError("batch plot dimensions must be positive")
    if self.dpi <= 0:
      raise ValueError("batch plot dpi must be positive")
    if self.raster_resolution_mode not in {"legacy_pixel_dimensions", "dpi_scaled"}:
      raise ValueError(
        f"invalid batch plot raster resolution mode {self.raster_resolution_mode!r}"
      )
    if self.vector_scatter_mode not in {"full_vector", "compact_vector", "hybrid_raster"}:
      raise ValueError(f"invalid vector scatter mode {self.vector_scatter_mode!r}")
    if not 72 <= self.hybrid_scatter_dpi <= 2400:
      raise ValueError("hybrid scatter dpi must be between 72 and 2400")
    if self.layout_policy not in {"current_view", "shared_ranges"}:
      raise ValueError(f"invalid batch plot layout policy {self.layout_policy!r}")
    if self.collision_policy not in {"fail", "replace", "suffix"}:
      raise ValueError(f"invalid collision policy {self.collision_policy!r}")


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
class ComparisonMemberSpec:
  """One display-only member of a generalized comparison set."""

  sample_id: str
  role: ComparisonRole = "target"

  def __post_init__(self) -> None:
    if not self.sample_id:
      raise ValueError("comparison member sample_id must be non-empty")
    if self.role not in {
      "reference", "target", "positive_control", "negative_control", "control"
    }:
      raise ValueError(f"invalid comparison role: {self.role!r}")


@dataclass(frozen=True)
class ComparisonSetSpec:
  """Display-only relation that supports pairs and one-to-many comparisons."""

  id: str
  name: str
  members: tuple[ComparisonMemberSpec, ...]
  role_colors: dict[str, str] = field(default_factory=dict)

  def __post_init__(self) -> None:
    if not self.id or not self.name:
      raise ValueError("comparison set ID and name must be non-empty")
    if len(self.members) < 2:
      raise ValueError("comparison set requires at least two members")
    sample_ids = [member.sample_id for member in self.members]
    if len(sample_ids) != len(set(sample_ids)):
      raise ValueError("comparison set member sample IDs must be unique")
    for role, color in self.role_colors.items():
      if role not in {
        "reference", "target", "positive_control", "negative_control", "control"
      }:
        raise ValueError(f"invalid comparison role color key: {role!r}")
      _validate_display_color(color, "comparison role color")

  def member(self, sample_id: str) -> ComparisonMemberSpec:
    for member in self.members:
      if member.sample_id == sample_id:
        return member
    raise KeyError(sample_id)


def _validate_display_color(value: str, field_name: str) -> None:
  if (
    not isinstance(value, str)
    or len(value) != 7
    or value[0] != "#"
    or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
  ):
    raise ValueError(f"{field_name} must be a #RRGGBB color")


@dataclass(frozen=True)
class PopulationDisplaySpec:
  """Display-only color and outline settings for one resolved Population."""

  population_id: str
  color: str | None = None
  gate_outline_color: str | None = None
  use_population_color_for_outline: bool = False
  z_order: int | None = None

  def __post_init__(self) -> None:
    if not self.population_id:
      raise ValueError("population display population_id must be non-empty")
    if self.color is not None:
      _validate_display_color(self.color, "population color")
    if self.gate_outline_color is not None:
      _validate_display_color(self.gate_outline_color, "gate outline color")
    if self.z_order is not None and (
      isinstance(self.z_order, bool) or self.z_order < 0
    ):
      raise ValueError("population display z_order must be non-negative")


@dataclass(frozen=True)
class IntegratedOverlayState:
  """Serializable display state kept independent from scientific definitions."""

  active_sample_id: str | None = None
  display_population_id: str = "all_events"
  selected_gate_id: str | None = None
  manual_overlay_sample_ids: tuple[str, ...] = ()
  manual_overlay_colors: dict[str, str] = field(default_factory=dict)
  automatic_overlay_sources: tuple[OverlaySourceSpec, ...] = ()
  comparison_set_definitions: tuple[ComparisonSetSpec, ...] = ()
  overlay_mode: OverlayMode = "manual_only"
  population_display_colors: tuple[PopulationDisplaySpec, ...] = ()
  plot_presentation: PlotPresentationSpec | None = None

  def __post_init__(self) -> None:
    if not self.display_population_id:
      raise ValueError("display_population_id must be non-empty")
    if self.overlay_mode not in {
      "manual_only", "manual_plus_comparison", "comparison_only"
    }:
      raise ValueError(f"invalid overlay mode: {self.overlay_mode!r}")
    if any(not sample_id for sample_id in self.manual_overlay_sample_ids):
      raise ValueError("manual overlay sample IDs must be non-empty")
    if len(set(self.manual_overlay_sample_ids)) != len(self.manual_overlay_sample_ids):
      raise ValueError("manual overlay sample IDs must be unique")
    for sample_id, color in self.manual_overlay_colors.items():
      if sample_id not in self.manual_overlay_sample_ids:
        raise ValueError(
          f"manual overlay color has no selected sample: {sample_id!r}"
        )
      _validate_display_color(color, "manual overlay color")
    comparison_ids = [comparison.id for comparison in self.comparison_set_definitions]
    if len(comparison_ids) != len(set(comparison_ids)):
      raise ValueError("comparison set IDs must be unique")
    population_ids = [
      display.population_id for display in self.population_display_colors
    ]
    if len(population_ids) != len(set(population_ids)):
      raise ValueError("population display IDs must be unique")

  def to_mapping(self) -> dict[str, Any]:
    """Return JSON-compatible display state without scientific result data."""
    def json_value(value: Any) -> Any:
      if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
      if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
      return value

    return cast(dict[str, Any], json_value(asdict(self)))

  @classmethod
  def from_mapping(cls, value: dict[str, Any] | None) -> IntegratedOverlayState:
    """Load current or old B7.1 display state without inferring new meanings."""
    raw = dict(value or {})
    comparisons = tuple(
      ComparisonSetSpec(
        id=str(item["id"]),
        name=str(item.get("name", item["id"])),
        members=tuple(
          ComparisonMemberSpec(
            str(member["sample_id"]),
            cast(ComparisonRole, str(member.get("role", "target"))),
          )
          for member in item.get("members", [])
        ),
        role_colors=dict(item.get("role_colors", {})),
      )
      for item in raw.get("comparison_set_definitions", [])
    )
    def source_from_mapping(item: dict[str, Any]) -> OverlaySourceSpec:
      source = dict(item)
      style = source.get("style")
      if isinstance(style, dict):
        source["style"] = SourceStyleSpec(**style)
      return OverlaySourceSpec(**source)

    automatic_sources = tuple(
      source_from_mapping(dict(item))
      for item in raw.get("automatic_overlay_sources", [])
    )
    population_colors = tuple(
      PopulationDisplaySpec(**dict(item))
      for item in raw.get("population_display_colors", [])
    )
    presentation = raw.get("plot_presentation")
    plot_presentation = None
    if isinstance(presentation, dict):
      presentation_data = dict(presentation)
      for font_key in ("title_font", "axis_label_font", "tick_font", "legend_font"):
        if isinstance(presentation_data.get(font_key), dict):
          presentation_data[font_key] = FontSpec(**presentation_data[font_key])
      presentation_data["source_styles"] = tuple(
        SourceStyleSpec(**dict(style))
        for style in presentation_data.get("source_styles", [])
      )
      presentation_data["legend_source_ids"] = tuple(
        presentation_data.get("legend_source_ids", ())
      )
      plot_presentation = PlotPresentationSpec(**presentation_data)
    return cls(
      active_sample_id=raw.get("active_sample_id"),
      display_population_id=str(raw.get("display_population_id", "all_events")),
      selected_gate_id=raw.get("selected_gate_id"),
      manual_overlay_sample_ids=tuple(raw.get("manual_overlay_sample_ids", ())),
      manual_overlay_colors=dict(raw.get("manual_overlay_colors", {})),
      automatic_overlay_sources=automatic_sources,
      comparison_set_definitions=comparisons,
      overlay_mode=cast(OverlayMode, str(raw.get("overlay_mode", "manual_only"))),
      population_display_colors=population_colors,
      plot_presentation=plot_presentation,
    )


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
  non_finite_policy: StatisticNonFinitePolicy = "strict"
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
    if self.non_finite_policy not in {"strict", "exclude_invalid"}:
      raise ValueError(
        f"invalid derived non_finite_policy {self.non_finite_policy!r}"
      )

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
  x_transform_id: str | None = None
  y_transform_id: str | None = None
  compensation_id: str | None = None
  coordinates: tuple[tuple[float, float], ...] = field(default_factory=tuple)
  thresholds: dict[str, Any] = field(default_factory=dict)
  notes: str = ""

  def __post_init__(self) -> None:
    object.__setattr__(self, "name", validate_gate_name(self.name))


def validate_gate_name(name: str) -> str:
  """Validate and normalize a user-visible gate name.

  ASCII ``/`` is reserved for display-only population hierarchy paths.
  Full-width slash remains a valid gate character.
  """
  if not isinstance(name, str):
    raise ValueError("gate name must be a string")
  normalized = name.strip()
  if not normalized:
    raise ValueError("gate name must not be empty")
  if "/" in normalized:
    raise ValueError(
      "Gate name must not contain '/'; '/' is reserved for population paths."
    )
  return normalized


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
class AutoGateTemplateSpec:
  """Shared automatic-gate definition; no sample-fitted geometry is embedded."""

  id: str
  name: str
  algorithm: AutoGateAlgorithm
  x_parameter: str
  y_parameter: str
  parent_population_id: str = "all_events"
  parameters: dict[str, Any] = field(default_factory=dict)
  algorithm_version: str = "quantile_rectangle.v1"
  manual_override_policy: ManualOverridePolicy = "preserve_until_reset"
  notes: str = ""

  def __post_init__(self) -> None:
    if not self.id or not self.name or not self.x_parameter or not self.y_parameter:
      raise ValueError("automatic gate template IDs and parameters are required")
    if self.algorithm != "quantile_rectangle":
      raise ValueError(f"unsupported automatic gate algorithm: {self.algorithm!r}")
    if not self.algorithm_version:
      raise ValueError("automatic gate algorithm_version must be non-empty")
    if self.manual_override_policy not in {
      "preserve_until_reset", "refit_on_input_change"
    }:
      raise ValueError(
        f"invalid automatic gate manual override policy: {self.manual_override_policy!r}"
      )


@dataclass(frozen=True)
class AutoGateFitResult:
  """Deterministic sample-specific automatic geometry and provenance."""

  template_id: str
  sample_id: str
  input_hash: str
  algorithm_version: str
  status: FitStatus
  gate: GateSpec | None = None
  diagnostics: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  failure_reason: str | None = None
  manual_override: bool = False

  def __post_init__(self) -> None:
    if not self.template_id or not self.sample_id or not self.input_hash:
      raise ValueError("automatic fit identity fields are required")
    if not self.algorithm_version:
      raise ValueError("automatic fit algorithm_version must be non-empty")
    if self.status not in {"success", "failed"}:
      raise ValueError(f"invalid automatic fit status: {self.status!r}")
    if self.status == "success" and self.gate is None:
      raise ValueError("successful automatic fit requires a fitted gate")
    if self.status == "failed" and not self.failure_reason:
      raise ValueError("failed automatic fit requires failure_reason")


@dataclass(frozen=True)
class MagneticGateTemplateSpec:
  """Shared definition for a deterministic magnetic-bead range gate."""

  id: str
  name: str
  algorithm: MagneticGateAlgorithm
  parameter: str
  parent_population_id: str = "all_events"
  parameters: dict[str, Any] = field(default_factory=dict)
  algorithm_version: str = "largest_gap_range.v1"
  manual_override_policy: ManualOverridePolicy = "preserve_until_reset"
  notes: str = ""

  def __post_init__(self) -> None:
    if not self.id or not self.name or not self.parameter:
      raise ValueError("magnetic gate template IDs and parameter are required")
    if self.algorithm != "largest_gap_range":
      raise ValueError(f"unsupported magnetic gate algorithm: {self.algorithm!r}")
    if not self.algorithm_version:
      raise ValueError("magnetic gate algorithm_version must be non-empty")


@dataclass(frozen=True)
class MagneticGateFitResult:
  """Sample-specific magnetic-gate geometry and provenance."""

  template_id: str
  sample_id: str
  input_hash: str
  algorithm_version: str
  status: FitStatus
  gate: GateSpec | None = None
  diagnostics: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  failure_reason: str | None = None
  manual_override: bool = False

  def __post_init__(self) -> None:
    if not self.template_id or not self.sample_id or not self.input_hash:
      raise ValueError("magnetic fit identity fields are required")
    if self.status == "success" and self.gate is None:
      raise ValueError("successful magnetic fit requires a fitted gate")
    if self.status == "failed" and not self.failure_reason:
      raise ValueError("failed magnetic fit requires failure_reason")


@dataclass(frozen=True)
class TetheredGateTemplateSpec:
  """Reusable geometry relation to a named anchor gate."""

  id: str
  name: str
  algorithm: TetheredGateAlgorithm
  anchor_gate_id: str
  x_offset: float = 0.0
  y_offset: float = 0.0
  parent_population_id: str | None = None
  algorithm_version: str = "translated_rectangle.v1"
  manual_override_policy: ManualOverridePolicy = "preserve_until_reset"
  notes: str = ""

  def __post_init__(self) -> None:
    if not self.id or not self.name or not self.anchor_gate_id:
      raise ValueError("tethered gate IDs and anchor are required")
    if self.algorithm != "translated_rectangle":
      raise ValueError(f"unsupported tethered gate algorithm: {self.algorithm!r}")


@dataclass(frozen=True)
class TetheredGateFitResult:
  """Sample-specific translated geometry and anchor provenance."""

  template_id: str
  sample_id: str
  input_hash: str
  algorithm_version: str
  status: FitStatus
  gate: GateSpec | None = None
  diagnostics: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  failure_reason: str | None = None
  manual_override: bool = False

  def __post_init__(self) -> None:
    if self.status == "success" and self.gate is None:
      raise ValueError("successful tethered fit requires a fitted gate")
    if self.status == "failed" and not self.failure_reason:
      raise ValueError("failed tethered fit requires failure_reason")


@dataclass(frozen=True)
class CloneSyncGroupSpec:
  """Explicit sample group and leader policy for cloned gate geometry."""

  id: str
  gate_id: str
  sample_ids: tuple[str, ...]
  leader_sample_id: str
  conflict_policy: CloneConflictPolicy = "leader_wins"
  algorithm_version: str = "clone_gate.v1"

  def __post_init__(self) -> None:
    if not self.id or not self.gate_id or not self.sample_ids:
      raise ValueError("clone sync group identity and samples are required")
    if self.leader_sample_id not in self.sample_ids:
      raise ValueError("clone leader must be a member of sample_ids")
    if self.conflict_policy not in {"leader_wins", "reject_conflict"}:
      raise ValueError(f"invalid clone conflict policy: {self.conflict_policy!r}")


@dataclass(frozen=True)
class CloneSyncResult:
  """Auditable clone operation with reversible before/after state."""

  group_id: str
  leader_sample_id: str
  applied_sample_ids: tuple[str, ...]
  conflict_sample_ids: tuple[str, ...] = field(default_factory=tuple)
  before: dict[str, Any] = field(default_factory=dict)
  after: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FontSpec:
  """Validated display-only font request."""

  family: str = "DejaVu Sans"
  size: float = 10.0
  weight: str = "normal"
  italic: bool = False

  def __post_init__(self) -> None:
    if not self.family or not math.isfinite(self.size) or not 1.0 <= self.size <= 96.0:
      raise ValueError("font family must be non-empty and size must be between 1 and 96")
    if self.weight not in {"normal", "bold", "light"}:
      raise ValueError(f"invalid font weight: {self.weight!r}")


@dataclass(frozen=True)
class SourceStyleSpec:
  """Typed display style for one overlay source."""

  source_id: str
  legend_label: str | None = None
  color: str | None = None
  alpha: float = 0.60
  marker_shape: MarkerShape | None = None
  marker_size: float = 1.5
  line_color: str | None = None
  line_width: float = 1.5
  line_style: LineStyle = "solid"
  histogram_fill_color: str | None = None
  histogram_outline_color: str | None = None
  histogram_alpha: float = 0.35
  manual_fields: tuple[str, ...] = ()
  provenance: dict[str, str] = field(default_factory=dict)

  def __post_init__(self) -> None:
    if not self.source_id:
      raise ValueError("source style source_id must be non-empty")
    for name, value, low, high in (
      ("alpha", self.alpha, 0.0, 1.0),
      ("histogram_alpha", self.histogram_alpha, 0.0, 1.0),
      ("marker_size", self.marker_size, 0.1, 100.0),
      ("line_width", self.line_width, 0.1, 100.0),
    ):
      if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    if self.line_style not in {"solid", "dashed", "dotted", "dashdot"}:
      raise ValueError(f"invalid line style: {self.line_style!r}")
    if self.marker_shape is not None and self.marker_shape not in {
      "circle", "square", "triangle", "cross", "plus"
    }:
      raise ValueError(f"invalid marker shape: {self.marker_shape!r}")


@dataclass(frozen=True)
class PlotPresentationSpec:
  """Persisted, display-only presentation independent of analysis identity."""

  title: str = ""
  title_mode: PlotTitleMode = "overlay_sample_titles"
  subtitle: str = ""
  x_axis_display_label: str | None = None
  y_axis_display_label: str | None = None
  background_color: str = "#ffffff"
  legend_visible: bool = True
  legend_position: LegendPosition = "right"
  legend_source_ids: tuple[str, ...] = ()
  title_font: FontSpec = field(default_factory=lambda: FontSpec(size=14, weight="bold"))
  axis_label_font: FontSpec = field(
    default_factory=lambda: FontSpec(size=14, weight="bold")
  )
  tick_font: FontSpec = field(
    default_factory=lambda: FontSpec(size=10, weight="bold")
  )
  legend_font: FontSpec = field(default_factory=FontSpec)
  gate_outline_color: str = "#e00000"
  gate_outline_width: float = 1.5
  gate_outline_style: LineStyle = "solid"
  axis_line_width: float = 2.0
  show_grid: bool = True
  colormap: str | None = None
  automatic_style_policy: str = "palette.v1"
  source_styles: tuple[SourceStyleSpec, ...] = ()

  def __post_init__(self) -> None:
    if self.title_mode not in {"current_sample", "overlay_sample_titles"}:
      raise ValueError(f"invalid plot title mode: {self.title_mode!r}")
    if self.legend_position not in {"right", "left", "top", "bottom", "inside"}:
      raise ValueError(f"invalid legend position: {self.legend_position!r}")
    if not math.isfinite(self.gate_outline_width) or not 0.1 <= self.gate_outline_width <= 100:
      raise ValueError("gate_outline_width must be finite and between 0.1 and 100")
    if not math.isfinite(self.axis_line_width) or not 0.5 <= self.axis_line_width <= 20:
      raise ValueError("axis_line_width must be finite and between 0.5 and 20")
    if self.gate_outline_style not in {"solid", "dashed", "dotted", "dashdot"}:
      raise ValueError(f"invalid gate outline style: {self.gate_outline_style!r}")
    source_ids = [style.source_id for style in self.source_styles]
    if len(source_ids) != len(set(source_ids)):
      raise ValueError("presentation source styles must have unique source IDs")
    if len(self.legend_source_ids) != len(set(self.legend_source_ids)):
      raise ValueError("legend source IDs must be unique")


@dataclass(frozen=True)
class OverlaySourceSpec:
  """One explicitly selected, sample-independent overlay source."""

  source_id: str
  sample_id: str | None
  population_id: str | None
  display_name: str
  x_parameter_id: str
  y_parameter_id: str | None = None
  x_transform_id: str | None = None
  y_transform_id: str | None = None
  unit: str | None = None
  x_unit: str | None = None
  y_unit: str | None = None
  x_semantic: str | None = None
  y_semantic: str | None = None
  visible: bool = True
  order: int = 0
  style: SourceStyleSpec | None = None
  template_source_role: str | None = None
  template_population_path: str | None = None
  analysis_revision: str | None = None

  def __post_init__(self) -> None:
    if not self.source_id or not self.display_name or not self.x_parameter_id:
      raise ValueError("overlay source identity and x parameter are required")
    if self.sample_id is None and not self.template_source_role:
      raise ValueError("overlay source requires sample_id or template_source_role")
    if self.population_id is None and not self.template_population_path:
      raise ValueError("overlay source requires population_id or template_population_path")
    if self.order < 0:
      raise ValueError("overlay source order must be non-negative")
    if self.style is not None and self.style.source_id != self.source_id:
      raise ValueError("overlay source style must reference the same source_id")


@dataclass(frozen=True)
class PlotViewSpec:
  """Persisted display definition; it never stores event values or masks."""

  id: str
  population_id: str = "all_events"
  x_parameter: str = ""
  y_parameter: str | None = None
  x_transform_id: str | None = None
  y_transform_id: str | None = None
  plot_type: PlotType = "scatter"
  viewport: dict[str, Any] = field(default_factory=dict)
  style: dict[str, Any] = field(default_factory=dict)
  aggregation: dict[str, Any] = field(default_factory=lambda: {"bins": 64})
  rendering_downsample: dict[str, Any] = field(
    default_factory=lambda: {"max_points": 20_000}
  )
  overlay_sources: tuple[OverlaySourceSpec, ...] = ()
  presentation: PlotPresentationSpec | None = None
  manual_overlay_sample_ids: tuple[str, ...] = ()
  manual_overlay_colors: dict[str, str] = field(default_factory=dict)
  overlay_mode: OverlayMode = "manual_only"
  population_display_colors: tuple[PopulationDisplaySpec, ...] = ()

  def __post_init__(self) -> None:
    if not self.id or not self.population_id or not self.x_parameter:
      raise ValueError("plot view ID, population, and x parameter are required")
    if self.plot_type not in {
      "dot", "scatter", "pseudocolor", "density", "contour", "histogram", "cdf"
    }:
      raise ValueError(f"unsupported plot type: {self.plot_type!r}")
    if (
      self.plot_type in {"pseudocolor", "density", "contour", "scatter", "dot"}
      and not self.y_parameter
    ):
      raise ValueError(f"plot type {self.plot_type!r} requires y_parameter")
    source_ids = [source.source_id for source in self.overlay_sources]
    if len(source_ids) != len(set(source_ids)):
      raise ValueError("plot view overlay sources must have unique source IDs")
    source_orders = [source.order for source in self.overlay_sources]
    if len(source_orders) != len(set(source_orders)):
      raise ValueError("plot view overlay sources must have unique order values")
    if self.overlay_mode not in {
      "manual_only", "manual_plus_comparison", "comparison_only"
    }:
      raise ValueError(f"invalid overlay mode: {self.overlay_mode!r}")
    max_points = self.rendering_downsample.get("max_points", 20_000)
    if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 0:
      raise ValueError("rendering downsample max_points must be a non-negative integer")
    if len(set(self.manual_overlay_sample_ids)) != len(self.manual_overlay_sample_ids):
      raise ValueError("plot view manual overlay sample IDs must be unique")
    for sample_id, color in self.manual_overlay_colors.items():
      if sample_id not in self.manual_overlay_sample_ids:
        raise ValueError(
          f"plot view overlay color has no selected sample: {sample_id!r}"
        )
      _validate_display_color(color, "manual overlay color")
    population_ids = [
      display.population_id for display in self.population_display_colors
    ]
    if len(population_ids) != len(set(population_ids)):
      raise ValueError("plot view population display IDs must be unique")


@dataclass(frozen=True)
class PlotViewRegistry:
  """Duplicateable persisted views with explicit linked-sample navigation."""

  views: tuple[PlotViewSpec, ...] = ()
  active_view_id: str | None = None
  linked_sample_navigation: bool = True

  def duplicate(self, view_id: str, duplicate_id: str) -> PlotViewRegistry:
    source = next((view for view in self.views if view.id == view_id), None)
    if source is None:
      raise ValueError(f"plot view is missing: {view_id!r}")
    if any(view.id == duplicate_id for view in self.views):
      raise ValueError(f"duplicate plot view ID: {duplicate_id!r}")
    duplicate = replace(deepcopy(source), id=duplicate_id)
    return PlotViewRegistry(self.views + (duplicate,), duplicate_id, self.linked_sample_navigation)


@dataclass(frozen=True)
class OverlaySpec:
  """Persisted population comparison definition without copied event data."""

  id: str
  population_ids: tuple[str, ...]
  parameter: str
  transform_id: str | None = None
  normalization: OverlayNormalization = "count"
  bins: int = 64
  styles: dict[str, dict[str, Any]] = field(default_factory=dict)
  sources: tuple[OverlaySourceSpec, ...] = ()
  presentation: PlotPresentationSpec | None = None

  def __post_init__(self) -> None:
    if not self.id or not self.population_ids or not self.parameter:
      raise ValueError("overlay ID, populations, and parameter are required")
    if self.normalization not in {"count", "mode", "unit_area"}:
      raise ValueError(f"invalid overlay normalization: {self.normalization!r}")
    if isinstance(self.bins, bool) or self.bins < 1:
      raise ValueError("overlay bins must be positive")
    source_ids = [source.source_id for source in self.sources]
    if len(source_ids) != len(set(source_ids)):
      raise ValueError("overlay sources must have unique source IDs")
    source_orders = [source.order for source in self.sources]
    if len(source_orders) != len(set(source_orders)):
      raise ValueError("overlay sources must have unique order values")


@dataclass(frozen=True)
class BackgatingSpec:
  """Persisted projection of a target membership through ancestor views."""

  id: str
  target_population_id: str
  ancestor_population_ids: tuple[str, ...]
  target_style: dict[str, Any] = field(default_factory=dict)
  ancestor_style: dict[str, Any] = field(default_factory=dict)
  background_style: dict[str, Any] = field(default_factory=dict)

  def __post_init__(self) -> None:
    if not self.id or not self.target_population_id or not self.ancestor_population_ids:
      raise ValueError("backgating ID, target, and ancestors are required")


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
  # ``population_id`` remains as a compatibility alias for the first target.
  # New persisted definitions use ``population_ids`` as the canonical ordered
  # target set. Keeping the alias here allows old Python callers and manifests
  # to round-trip without silently changing their meaning.
  population_id: str = ""
  parameter_id: str | None = None
  metric: StatisticMetric = "count"
  source_stage: StatisticSource = "compensated"
  transform_id: str | None = None
  value_policy: StatisticValuePolicy = "full_events"
  non_finite_policy: StatisticNonFinitePolicy = "strict"
  settings: dict[str, Any] = field(default_factory=dict)
  format: str | None = None
  notes: str = ""
  population_ids: tuple[str, ...] = field(default_factory=tuple)
  compute_enabled: bool = True

  def __post_init__(self) -> None:
    if not self.id:
      raise ValueError("statistic ID must be non-empty")
    if not self.name:
      raise ValueError("statistic name must be non-empty")
    targets = tuple(self.population_ids)
    if not targets:
      if not self.population_id:
        raise ValueError("statistic population_id must be non-empty")
      targets = (self.population_id,)
    if any(not isinstance(value, str) or not value for value in targets):
      raise ValueError("statistic population_ids must contain non-empty strings")
    if len(set(targets)) != len(targets):
      raise ValueError("statistic population_ids must not contain duplicates")
    if self.population_id and self.population_id != targets[0]:
      raise ValueError(
        "statistic population_id must match the first population_ids entry"
      )
    object.__setattr__(self, "population_ids", targets)
    object.__setattr__(self, "population_id", targets[0])
    if not isinstance(self.compute_enabled, bool):
      raise ValueError("statistic compute_enabled must be a boolean")
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
    if self.source_stage == "transformed" and not self.transform_id:
      raise ValueError(
        "transformed statistic source_stage requires an explicit transform_id"
      )
    if self.transform_id is not None and (
      not isinstance(self.transform_id, str) or not self.transform_id
    ):
      raise ValueError("statistic transform_id must be a non-empty string or null")
    if self.value_policy != "full_events":
      raise ValueError(
        f"invalid statistic value_policy {self.value_policy!r}"
      )
    if self.non_finite_policy not in {"strict", "exclude_invalid"}:
      raise ValueError(
        f"invalid statistic non_finite_policy {self.non_finite_policy!r}"
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
  n_total: int | None = None
  n_valid: int | None = None
  n_invalid: int | None = None
  invalid_fraction: float | None = None
  non_finite_policy: StatisticNonFinitePolicy = "strict"
