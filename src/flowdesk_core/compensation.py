"""Compensation matrix validation and application.

Compensation transforms raw fluorescence events by applying the inverse of a
spillover matrix. Raw events are never mutated; a new array is always returned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import (
  CompensationBindingSpec,
  CompensationCalculationSpec,
  CompensationMatrixSpec,
  CompensationProvenanceSpec,
)


class CompensationError(FlowdeskError):
  """Raised when compensation data or matrix is invalid."""

  def __init__(
    self,
    message: str,
    *,
    code: str = "invalid_compensation_matrix",
    details: dict[str, Any] | None = None,
  ) -> None:
    self.code = code
    self.details = details or {}
    super().__init__(message)


@dataclass(frozen=True)
class CompensationValidationDiagnostic:
  """One stable validation outcome suitable for later report conversion."""

  code: str
  severity: Literal["warning", "error"]
  message: str
  details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompensationValidationResult:
  """Matrix quality and channel-alignment result without applying events."""

  matrix_id: str
  channel_order: tuple[str, ...]
  channel_indices: tuple[int, ...] | None
  condition_number: float | None
  diagnostics: tuple[CompensationValidationDiagnostic, ...] = ()

  @property
  def is_valid(self) -> bool:
    """Return false only for error diagnostics; warnings remain applicable."""
    return not any(
      diagnostic.severity == "error" for diagnostic in self.diagnostics
    )


@dataclass(frozen=True)
class CompensationBindingResolution:
  """One reproducible matrix selection for a sample/profile combination."""

  matrix_id: str | None
  priority: Literal[
    "sample", "execution_profile", "group", "project_default", "none"
  ]
  binding_ids: tuple[str, ...] = ()
  target_ids: tuple[str, ...] = ()

  @property
  def binding_id(self) -> str | None:
    """Return the single binding ID, or none for multi-group/default choices."""
    return self.binding_ids[0] if len(self.binding_ids) == 1 else None


COMPENSATION_CONDITION_WARNING_THRESHOLD = 1e8
COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD = 1.0 / np.finfo(np.float64).eps


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def resolve_compensation_binding(
  bindings: Sequence[CompensationBindingSpec],
  *,
  sample_id: str,
  execution_profile_id: str,
  group_ids: Sequence[str],
  default_matrix_id: str | None,
  known_matrix_ids: set[str],
) -> CompensationBindingResolution:
  """Resolve one matrix without silently choosing among conflicting bindings."""
  seen_targets: dict[tuple[str, str], str] = {}
  for binding in bindings:
    key = (binding.scope, binding.target_id)
    previous = seen_targets.get(key)
    if previous is not None:
      raise CompensationError(
        "duplicate compensation bindings target the same scope and ID",
        code="compensation_binding_conflict",
        details={
          "scope": binding.scope,
          "target_id": binding.target_id,
          "binding_ids": [previous, binding.id],
        },
      )
    seen_targets[key] = binding.id

  def require_known(
    matrix_id: str, selected: Sequence[CompensationBindingSpec]
  ) -> None:
    if matrix_id in known_matrix_ids:
      return
    raise CompensationError(
      f"compensation binding references unknown matrix: {matrix_id!r}",
      code="unknown_compensation_matrix",
      details={
        "matrix_id": matrix_id,
        "binding_ids": [binding.id for binding in selected],
      },
    )

  sample_bindings = tuple(
    binding for binding in bindings
    if binding.scope == "sample" and binding.target_id == sample_id
  )
  if sample_bindings:
    selected = sample_bindings[0]
    require_known(selected.matrix_id, sample_bindings)
    return CompensationBindingResolution(
      selected.matrix_id, "sample", (selected.id,), (sample_id,)
    )

  profile_bindings = tuple(
    binding for binding in bindings
    if binding.scope == "execution_profile"
    and binding.target_id == execution_profile_id
  )
  if profile_bindings:
    selected = profile_bindings[0]
    require_known(selected.matrix_id, profile_bindings)
    return CompensationBindingResolution(
      selected.matrix_id,
      "execution_profile",
      (selected.id,),
      (execution_profile_id,),
    )

  group_id_set = set(group_ids)
  group_bindings = tuple(
    binding for binding in bindings
    if binding.scope == "group" and binding.target_id in group_id_set
  )
  if group_bindings:
    matrix_ids = {binding.matrix_id for binding in group_bindings}
    if len(matrix_ids) != 1:
      raise CompensationError(
        "applicable group bindings reference different compensation matrices",
        code="compensation_binding_conflict",
        details={
          "sample_id": sample_id,
          "group_ids": [binding.target_id for binding in group_bindings],
          "binding_ids": [binding.id for binding in group_bindings],
          "matrix_ids": sorted(matrix_ids),
        },
      )
    matrix_id = next(iter(matrix_ids))
    require_known(matrix_id, group_bindings)
    return CompensationBindingResolution(
      matrix_id,
      "group",
      tuple(binding.id for binding in group_bindings),
      tuple(binding.target_id for binding in group_bindings),
    )

  if default_matrix_id is not None:
    require_known(default_matrix_id, ())
    return CompensationBindingResolution(default_matrix_id, "project_default")
  return CompensationBindingResolution(None, "none")


def inspect_compensation_matrix(
  spec: CompensationMatrixSpec,
  available_channel_ids: Sequence[str] | None = None,
) -> CompensationValidationResult:
  """Return structured definition, numeric-quality, and alignment outcomes.

  A condition number of at least ``1e8`` is a warning because about eight or
  more decimal digits may be lost in float64 arithmetic. A condition number at
  least ``1 / eps`` is treated as numerically singular because ``kappa * eps``
  reaches one and no relative significant digit can be guaranteed.
  """
  diagnostics: list[CompensationValidationDiagnostic] = []
  size = len(spec.channels)
  condition_number: float | None = None
  channel_indices: tuple[int, ...] | None = None

  if size == 0 or len(spec.matrix) != size or any(
    len(row) != size for row in spec.matrix
  ):
    diagnostics.append(CompensationValidationDiagnostic(
      code="invalid_compensation_matrix",
      severity="error",
      message="compensation matrix must be non-empty, square, and match channels",
      details={"reason": "shape_mismatch", "channel_count": size},
    ))

  duplicates = sorted({
    channel_id for channel_id in spec.channels
    if spec.channels.count(channel_id) > 1
  })
  if duplicates:
    diagnostics.append(CompensationValidationDiagnostic(
      code="invalid_compensation_matrix",
      severity="error",
      message="compensation channels must be unique",
      details={
        "reason": "duplicate_matrix_channels",
        "duplicate_channel_ids": duplicates,
      },
    ))

  invalid_channel_ids = sorted({
    channel_id for channel_id in spec.channels if not channel_id
  })
  if invalid_channel_ids:
    diagnostics.append(CompensationValidationDiagnostic(
      code="invalid_compensation_matrix",
      severity="error",
      message="compensation channel IDs must be non-empty",
      details={"reason": "invalid_matrix_channels"},
    ))

  array: NDArray[np.float64] | None = None
  if not any(
    diagnostic.details.get("reason") == "shape_mismatch"
    for diagnostic in diagnostics
  ):
    array = np.asarray(spec.matrix, dtype=np.float64)
    if not np.all(np.isfinite(array)):
      diagnostics.append(CompensationValidationDiagnostic(
        code="invalid_compensation_matrix",
        severity="error",
        message="compensation matrix must contain finite values only",
        details={"reason": "nonfinite_values"},
      ))
      array = None

  if array is not None and not duplicates and not invalid_channel_ids:
    try:
      condition_number = float(np.linalg.cond(array))
    except np.linalg.LinAlgError:
      condition_number = float("inf")
    if (
      not np.isfinite(condition_number)
      or condition_number >= COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD
    ):
      diagnostics.append(CompensationValidationDiagnostic(
        code="invalid_compensation_matrix",
        severity="error",
        message="compensation matrix is singular and cannot be inverted reliably",
        details={
          "reason": "numerically_singular",
          "condition_number": condition_number,
          "fatal_threshold": COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD,
        },
      ))
    elif condition_number >= COMPENSATION_CONDITION_WARNING_THRESHOLD:
      diagnostics.append(CompensationValidationDiagnostic(
        code="compensation_condition_warning",
        severity="warning",
        message="compensation matrix is ill-conditioned; results may lose precision",
        details={
          "condition_number": condition_number,
          "warning_threshold": COMPENSATION_CONDITION_WARNING_THRESHOLD,
        },
      ))

  if available_channel_ids is not None:
    available = tuple(available_channel_ids)
    available_duplicates = sorted({
      channel_id for channel_id in available if available.count(channel_id) > 1
    })
    if available_duplicates:
      diagnostics.append(CompensationValidationDiagnostic(
        code="ambiguous_compensation_channel",
        severity="error",
        message="event channel IDs must be unique for compensation alignment",
        details={"duplicate_channel_ids": available_duplicates},
      ))
    else:
      lookup = {channel_id: index for index, channel_id in enumerate(available)}
      missing = [
        channel_id for channel_id in spec.channels if channel_id not in lookup
      ]
      if missing:
        diagnostics.append(CompensationValidationDiagnostic(
          code="missing_compensation_channel",
          severity="error",
          message=(
            "compensation channels not found in data: " + ", ".join(missing)
          ),
          details={"missing_channel_ids": missing},
        ))
      else:
        channel_indices = tuple(lookup[channel_id] for channel_id in spec.channels)

  return CompensationValidationResult(
    matrix_id=spec.id,
    channel_order=spec.channels,
    channel_indices=channel_indices,
    condition_number=condition_number,
    diagnostics=tuple(diagnostics),
  )


def validate_compensation_matrix(
  spec: CompensationMatrixSpec,
  available_channel_ids: Sequence[str] | None = None,
) -> CompensationValidationResult:
  """Validate matrix shape, channel alignment, and invertibility.

  Raises:
    CompensationError: If the matrix is not square, its dimension does not
      match the channel list, channel names are duplicated, values are
      non-finite, or the matrix is singular.
  """

  result = inspect_compensation_matrix(spec, available_channel_ids)
  error = next(
    (
      diagnostic for diagnostic in result.diagnostics
      if diagnostic.severity == "error"
    ),
    None,
  )
  if error is not None:
    raise CompensationError(
      error.message, code=error.code, details=error.details
    )
  return result


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def apply_compensation(
  spec: CompensationMatrixSpec,
  events: NDArray[np.float64],
  channel_names: list[str],
) -> NDArray[np.float64]:
  """Apply compensation to event data, returning a new array.

  The spillover matrix stored in ``spec`` is inverted and left-multiplied
  against the fluorescence columns of ``events``. Non-fluorescence columns
  (channels not listed in ``spec.channels``) are copied unchanged.

  Raw ``events`` are never mutated.

  Args:
    spec: Compensation matrix definition with named channels.
    events: 2-D array of shape ``(n_events, n_channels)``.
    channel_names: Column names aligned with ``events`` columns.

  Returns:
    A new ``NDArray`` of the same shape with compensated fluorescence values.

  Raises:
    CompensationError: If a compensation channel is missing from
      ``channel_names``, or if channel order cannot be resolved.
  """

  if events.ndim != 2:
    raise CompensationError("events must be a 2-D array")

  if events.shape[1] != len(channel_names):
    raise CompensationError(
      "events columns count must match channel_names length"
    )

  validation = validate_compensation_matrix(spec, channel_names)
  if validation.channel_indices is None:
    raise CompensationError(
      "compensation channel alignment did not produce column indices",
      code="invalid_compensation_alignment",
    )
  compensated = events.copy()
  col_indices = list(validation.channel_indices)

  spillover = np.array(spec.matrix, dtype=np.float64)
  inverse = np.linalg.inv(spillover)

  # compensated_fluorescence = inverse @ raw_fluorescence^T, then transpose back
  raw_block = compensated[:, col_indices]  # (n_events, n_fl)
  comp_block = inverse @ raw_block.T       # (n_fl, n_events)
  compensated[:, col_indices] = comp_block.T  # (n_events, n_fl)

  return compensated


# ---------------------------------------------------------------------------
# Calculation diagnostics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompensationCalculationChannelDiagnostic:
  """Per-detector diagnostic produced during spillover matrix calculation."""

  detector_channel_id: str
  positive_event_count: int
  negative_event_count: int
  median_positive: float
  median_negative: float
  median_background_subtracted: float
  spillover_row: tuple[float, ...]
  outlier_count: int = 0
  residual_rms: float | None = None
  warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompensationCalculationResult:
  """Full result of a spillover matrix calculation."""

  matrix_spec: CompensationMatrixSpec
  channel_diagnostics: tuple[CompensationCalculationChannelDiagnostic, ...]
  condition_number: float
  overall_warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


def _outlier_mask_iqr(
  values: NDArray[np.float64],
) -> NDArray[np.bool_]:
  """Return the IQR-based inlier mask without losing event correspondence."""
  q1 = float(np.percentile(values, 25))
  q3 = float(np.percentile(values, 75))
  iqr = q3 - q1
  if iqr <= 0:
    return np.ones(len(values), dtype=np.bool_)
  lower = q1 - 1.5 * iqr
  upper = q3 + 1.5 * iqr
  mask = (values >= lower) & (values <= upper)
  return mask


def _outlier_mask_zscore(
  values: NDArray[np.float64],
  threshold: float = 3.0,
) -> NDArray[np.bool_]:
  """Return the z-score inlier mask without losing event correspondence."""
  mean = float(np.mean(values))
  std = float(np.std(values, ddof=1))
  if std <= 0:
    return np.ones(len(values), dtype=np.bool_)
  z = np.abs((values - mean) / std)
  mask = z <= threshold
  return mask


def _outlier_mask(
  values: NDArray[np.float64],
  policy: str,
) -> NDArray[np.bool_]:
  """Apply the requested policy and retain the exact selected event rows."""
  if policy == "iqr":
    return _outlier_mask_iqr(values)
  elif policy == "zscore":
    return _outlier_mask_zscore(values)
  else:
    return np.ones(len(values), dtype=np.bool_)


def _compute_spillover_coefficient(
  positive_medians: NDArray[np.float64],
  reference_median: float,
) -> NDArray[np.float64]:
  """Compute spillover coefficients: fraction of reference signal in each detector."""
  if reference_median <= 0:
    return np.zeros(len(positive_medians), dtype=np.float64)
  return positive_medians / reference_median


def calculate_spillover_matrix(
  spec: CompensationCalculationSpec,
  events_by_sample: Mapping[str, NDArray[np.float64]] | NDArray[np.float64],
  channel_ids_by_sample: Mapping[str, Sequence[str]] | Sequence[str],
  population_masks_by_sample: (
    Mapping[str, Mapping[str, NDArray[np.bool_]]]
    | Mapping[str, NDArray[np.bool_]]
  ),
) -> CompensationCalculationResult:
  """Calculate a spillover matrix from single-stain control data.

  For each detector channel, the positive and negative control populations
  are used to determine background-subtracted median fluorescence across
  all detectors. The spillover coefficient for each detector pair is the
  ratio of background-subtracted median to the reference detector median.

  Args:
    spec: Calculation configuration with detector × population assignments.
    events_by_sample: Raw event arrays keyed by the explicit control sample ID.
    channel_ids_by_sample: Channel IDs aligned with each event array.
    population_masks_by_sample: Gated masks keyed by sample then population ID.

  Returns:
    ``CompensationCalculationResult`` containing the new ``CompensationMatrixSpec``
    and per-detector diagnostics.

  Raises:
    CompensationError: If a control reference is missing/ambiguous, has too
      few events, has invalid signal, or yields a non-invertible matrix.
  """
  # Compatibility adapter for callers that explicitly supplied one control
  # sample before sample IDs were introduced. Project execution never uses it.
  if isinstance(events_by_sample, np.ndarray):
    if not isinstance(channel_ids_by_sample, Sequence):
      raise CompensationError("legacy control channels must be a sequence")
    if not isinstance(population_masks_by_sample, Mapping):
      raise CompensationError("legacy population masks must be a mapping")
    return calculate_spillover_matrix(
      spec,
      {"legacy-control": events_by_sample},
      {"legacy-control": channel_ids_by_sample},
      {"legacy-control": cast(
        Mapping[str, NDArray[np.bool_]], population_masks_by_sample
      )},
    )
  if not isinstance(channel_ids_by_sample, Mapping):
    raise CompensationError("control channel IDs must be keyed by sample")
  sample_events = events_by_sample
  sample_channels = channel_ids_by_sample
  sample_masks = cast(
    Mapping[str, Mapping[str, NDArray[np.bool_]]], population_masks_by_sample
  )
  detector_ids = tuple(control.detector_channel_id for control in spec.controls)
  matrix_array = np.zeros((len(detector_ids), len(detector_ids)), dtype=np.float64)
  channel_diags: list[CompensationCalculationChannelDiagnostic] = []
  overall_warnings: list[str] = []
  for control_index, control in enumerate(spec.controls):
    events = sample_events.get(control.sample_id)
    channel_ids = sample_channels.get(control.sample_id)
    masks = sample_masks.get(control.sample_id)
    if events is None or channel_ids is None or masks is None:
      raise CompensationError(
        f"control sample {control.sample_id!r} is unavailable",
        code="calculation_control_sample_missing",
      )
    if events.ndim != 2 or events.shape[1] != len(channel_ids):
      raise CompensationError(
        f"control sample {control.sample_id!r} event/channel shape is invalid",
        code="calculation_control_data_invalid",
      )
    if len(set(channel_ids)) != len(channel_ids):
      raise CompensationError(
        f"control sample {control.sample_id!r} has duplicate channel IDs",
        code="calculation_channel_ambiguous",
      )
    missing_channels = sorted(set(detector_ids) - set(channel_ids))
    if missing_channels:
      raise CompensationError(
        f"control sample {control.sample_id!r} is missing detector channels: "
        f"{', '.join(missing_channels)}",
        code="calculation_channel_missing",
      )
    positive_mask = masks.get(control.positive_population_id)
    negative_mask = masks.get(control.negative_population_id)
    if positive_mask is None or negative_mask is None:
      raise CompensationError(
        f"control sample {control.sample_id!r} is missing a referenced population",
        code="calculation_population_missing",
      )
    for label, mask in (("positive", positive_mask), ("negative", negative_mask)):
      if mask.dtype != np.bool_ or mask.ndim != 1 or len(mask) != len(events):
        raise CompensationError(
          f"{label} population mask for {control.sample_id!r} is invalid",
          code="calculation_population_mask_invalid",
        )
    positive = events[positive_mask].astype(np.float64, copy=False)
    negative = events[negative_mask].astype(np.float64, copy=False)
    if len(positive) < spec.minimum_positive_events:
      raise CompensationError(
        f"positive control {control.positive_population_id!r} has only "
        f"{len(positive)} events (minimum {spec.minimum_positive_events})",
        code="calculation_insufficient_positive_events",
      )
    if len(negative) < spec.minimum_negative_events:
      raise CompensationError(
        f"negative control {control.negative_population_id!r} has only "
        f"{len(negative)} events (minimum {spec.minimum_negative_events})",
        code="calculation_insufficient_negative_events",
      )
    indices = [channel_ids.index(channel_id) for channel_id in detector_ids]
    negative_median = np.median(negative[:, indices], axis=0)
    background_subtracted = positive[:, indices] - negative_median
    reference_index = detector_ids.index(control.detector_channel_id)
    reference = background_subtracted[:, reference_index]
    keep = _outlier_mask(reference, spec.outlier_policy)
    outlier_count = int((~keep).sum())
    if int(keep.sum()) < spec.minimum_positive_events:
      raise CompensationError(
        f"outlier filtering leaves too few positive events for "
        f"{control.detector_channel_id!r}",
        code="calculation_insufficient_positive_events",
      )
    cleaned = background_subtracted[keep]
    reference = cleaned[:, reference_index]
    reference_median = float(np.median(reference))
    if not np.isfinite(reference_median) or reference_median <= 0:
      raise CompensationError(
        f"reference signal for {control.detector_channel_id!r} is not positive",
        code="calculation_invalid_reference_signal",
      )
    if spec.regression_method == "median":
      coefficients = np.median(cleaned, axis=0) / reference_median
      predicted = np.outer(reference, coefficients)
    else:
      denominator = float(np.dot(reference, reference))
      if not np.isfinite(denominator) or denominator <= 0:
        raise CompensationError(
          f"reference signal for {control.detector_channel_id!r} is degenerate",
          code="calculation_invalid_reference_signal",
        )
      coefficients = (reference @ cleaned) / denominator
      predicted = np.outer(reference, coefficients)
    if not np.all(np.isfinite(coefficients)):
      raise CompensationError(
        "calculated spillover coefficients are non-finite",
        code="calculation_nonfinite_coefficients",
      )
    coefficients[reference_index] = 1.0
    # Matrix convention: rows are receiving detectors, columns are the
    # single-stain source detector. This is the convention apply_compensation
    # inverts for column-vector event data.
    matrix_array[:, control_index] = coefficients
    residual_rms = float(np.sqrt(np.mean((cleaned - predicted) ** 2)))
    channel_diags.append(CompensationCalculationChannelDiagnostic(
      detector_channel_id=control.detector_channel_id,
      positive_event_count=len(positive),
      negative_event_count=len(negative),
      median_positive=float(np.median(positive[:, indices[reference_index]])),
      median_negative=float(negative_median[reference_index]),
      median_background_subtracted=reference_median,
      spillover_row=tuple(float(value) for value in coefficients),
      outlier_count=outlier_count,
      residual_rms=residual_rms,
    ))

  # Check invertibility.
  try:
    cond = float(np.linalg.cond(matrix_array))
  except np.linalg.LinAlgError as exc:
    raise CompensationError(
      "calculated spillover matrix is singular and cannot be inverted",
      code="calculation_singular_matrix",
    ) from exc

  if not np.isfinite(cond) or cond >= COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD:
    raise CompensationError(
      f"calculated spillover matrix is numerically singular (condition={cond:.2e})",
      code="calculation_singular_matrix",
    )

  if cond >= COMPENSATION_CONDITION_WARNING_THRESHOLD:
    overall_warnings.append(
      f"calculated matrix is ill-conditioned (condition={cond:.2e})"
    )

  # Create the resulting matrix spec.
  now = datetime.now(UTC).isoformat()
  matrix_spec = CompensationMatrixSpec(
    id=f"calculated-{spec.id}",
    name=f"Calculated: {spec.name}",
    source="calculated",
    channels=detector_ids,
    matrix=tuple(tuple(float(v) for v in row) for row in matrix_array),
    created_by=spec.created_by,
    created_at=now,
    notes=(
      f"Auto-calculated from {spec.id}. Method={spec.regression_method}, "
      f"outlier={spec.outlier_policy}."
    ),
    provenance=CompensationProvenanceSpec(
      source_sample_id=None,
      source_metadata_key=None,
      control_sample_ids=tuple(dict.fromkeys(
        control.sample_id for control in spec.controls
      )),
      control_population_ids=tuple(dict.fromkeys(
        [f"{c.sample_id}:{c.positive_population_id}" for c in spec.controls] +
        [f"{c.sample_id}:{c.negative_population_id}" for c in spec.controls]
      )),
      algorithm=f"traditional_{spec.regression_method}_background_subtracted",
      algorithm_version="1.0.0",
      software_version="1.5.0",
      derived_from_matrix_id=None,
      manual_edits=(),
    ),
  )

  return CompensationCalculationResult(
    matrix_spec=matrix_spec,
    channel_diagnostics=tuple(channel_diags),
    condition_number=cond,
    overall_warnings=tuple(overall_warnings),
  )
