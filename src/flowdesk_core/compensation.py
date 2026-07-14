"""Compensation matrix validation and application.

Compensation transforms raw fluorescence events by applying the inverse of a
spillover matrix. Raw events are never mutated; a new array is always returned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import (
  CompensationBindingSpec,
  CompensationCalculationControlSpec,
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


def _remove_outliers_iqr(
  values: NDArray[np.float64],
) -> tuple[NDArray[np.float64], int]:
  """Return values with IQR-based outliers removed and the outlier count."""
  q1 = float(np.percentile(values, 25))
  q3 = float(np.percentile(values, 75))
  iqr = q3 - q1
  if iqr <= 0:
    return values, 0
  lower = q1 - 1.5 * iqr
  upper = q3 + 1.5 * iqr
  mask = (values >= lower) & (values <= upper)
  outlier_count = int((~mask).sum())
  return values[mask], outlier_count


def _remove_outliers_zscore(
  values: NDArray[np.float64],
  threshold: float = 3.0,
) -> tuple[NDArray[np.float64], int]:
  """Return values with z-score outliers removed and the outlier count."""
  mean = float(np.mean(values))
  std = float(np.std(values, ddof=1))
  if std <= 0:
    return values, 0
  z = np.abs((values - mean) / std)
  mask = z <= threshold
  outlier_count = int((~mask).sum())
  return values[mask], outlier_count


def _remove_outliers(
  values: NDArray[np.float64],
  policy: str,
) -> tuple[NDArray[np.float64], int]:
  """Apply the requested outlier policy and return cleaned values."""
  if policy == "iqr":
    return _remove_outliers_iqr(values)
  elif policy == "zscore":
    return _remove_outliers_zscore(values)
  else:
    return values, 0


def _compute_spillover_coefficient(
  positive_medians: NDArray[np.float64],
  reference_median: float,
) -> NDArray[np.float64]:
  """Compute spillover coefficients: fraction of reference signal in each detector."""
  if reference_median <= 0:
    return np.zeros(len(positive_medians), dtype=np.float64)
  return positive_medians / reference_median


def _build_spillover_matrix(
  spec: CompensationCalculationSpec,
  population_medians: Mapping[str, NDArray[np.float64]],
  all_channel_ids: Sequence[str],
  detector_ids: list[str],
) -> tuple[NDArray[np.float64], list[CompensationCalculationChannelDiagnostic]]:
  """Build the spillover matrix from per-population median fluorescence.

  Args:
    spec: Calculation specification with detector × control assignments.
    population_medians: Mapping from population ID to median fluorescence
      vector aligned with ``all_channel_ids``.
    all_channel_ids: All channel IDs aligned with median vectors.
    detector_ids: Ordered detector channel IDs (subset of all_channel_ids).

  Returns:
    The spillover matrix (detector_rows × detector_columns) and per-detector
    diagnostics.
  """
  channel_index = {ch: i for i, ch in enumerate(all_channel_ids)}
  n = len(spec.controls)
  matrix = np.zeros((n, n), dtype=np.float64)
  diagnostics: list[CompensationCalculationChannelDiagnostic] = []

  for row_idx, control in enumerate(spec.controls):
    det_id = control.detector_channel_id
    if det_id not in channel_index:
      raise CompensationError(
        f"detector channel {det_id!r} not found in data channels",
        code="calculation_channel_missing",
      )

    pos_med = population_medians[control.positive_population_id]
    neg_med = population_medians[control.negative_population_id]
    background = neg_med.copy()
    background_sub = pos_med - background

    # Select only detector channels for the spillover row.
    detector_medians = np.array([
      float(background_sub[channel_index[d]]) for d in detector_ids
    ])
    reference_median = float(background_sub[channel_index[det_id]])

    spillover_row = _compute_spillover_coefficient(
      detector_medians,
      reference_median,
    )
    matrix[row_idx] = spillover_row

    warnings: list[str] = []
    if reference_median < 10.0:
      warnings.append(f"very low reference median for {det_id!r}: {reference_median:.2f}")

    diagnostics.append(CompensationCalculationChannelDiagnostic(
      detector_channel_id=det_id,
      positive_event_count=0,  # filled by caller
      negative_event_count=0,
      median_positive=float(pos_med[channel_index[det_id]]),
      median_negative=float(neg_med[channel_index[det_id]]),
      median_background_subtracted=reference_median,
      spillover_row=tuple(float(v) for v in spillover_row),
      warnings=tuple(warnings),
    ))

  return matrix, diagnostics


def calculate_spillover_matrix(
  spec: CompensationCalculationSpec,
  events: NDArray[np.float64],
  channel_ids: Sequence[str],
  population_masks: Mapping[str, NDArray[np.bool_]],
) -> CompensationCalculationResult:
  """Calculate a spillover matrix from single-stain control data.

  For each detector channel, the positive and negative control populations
  are used to determine background-subtracted median fluorescence across
  all detectors. The spillover coefficient for each detector pair is the
  ratio of background-subtracted median to the reference detector median.

  Args:
    spec: Calculation configuration with detector × population assignments.
    events: Raw (pre-compensation) event array of shape (n_events, n_channels).
    channel_ids: Ordered channel IDs aligned with ``events`` columns.
    population_masks: Mapping from population ID to a boolean mask identifying
      events belonging to that population.

  Returns:
    ``CompensationCalculationResult`` containing the new ``CompensationMatrixSpec``
    and per-detector diagnostics.

  Raises:
    CompensationError: If a referenced population is missing, has too few
      events, or the resulting matrix is not invertible.
  """
  if events.ndim != 2:
    raise CompensationError("events must be a 2-D array")
  if events.shape[1] != len(channel_ids):
    raise CompensationError("events columns must match channel_ids length")

  # Validate all population masks exist.
  required_pops = set()
  for control in spec.controls:
    required_pops.add(control.positive_population_id)
    required_pops.add(control.negative_population_id)
  missing_pops = required_pops - set(population_masks)
  if missing_pops:
    raise CompensationError(
      f"population masks missing: {', '.join(sorted(missing_pops))}",
      code="calculation_population_missing",
    )

  # Validate detector channels exist in data.
  channel_index = {ch: i for i, ch in enumerate(channel_ids)}
  for control in spec.controls:
    if control.detector_channel_id not in channel_index:
      raise CompensationError(
        f"detector channel {control.detector_channel_id!r} not found in data",
        code="calculation_channel_missing",
      )

  # Compute per-population median fluorescence with outlier removal.
  population_medians: dict[str, NDArray[np.float64]] = {}
  population_event_counts: dict[str, int] = {}
  outlier_counts: dict[str, int] = {}

  for pop_id in required_pops:
    mask = population_masks[pop_id]
    pop_events = events[mask]
    count = int(mask.sum())
    population_event_counts[pop_id] = count

    pop_values = pop_events.astype(np.float64)
    cleaned, n_outliers = _remove_outliers(
      pop_values[:, channel_index[list(channel_ids)[0]]] if len(channel_ids) > 0
      else pop_values[:, 0],
      spec.outlier_policy,
    )
    outlier_counts[pop_id] = n_outliers

    # Compute median per channel after outlier removal on each channel independently.
    medians = np.zeros(len(channel_ids), dtype=np.float64)
    total_outliers = 0
    for ch_idx in range(len(channel_ids)):
      ch_values = pop_values[:, ch_idx]
      ch_cleaned, ch_outliers = _remove_outliers(ch_values, spec.outlier_policy)
      total_outliers += ch_outliers
      medians[ch_idx] = float(np.median(ch_cleaned)) if len(ch_cleaned) > 0 else 0.0
    outlier_counts[pop_id] = total_outliers

    population_medians[pop_id] = medians

  # Check minimum event counts.
  overall_warnings: list[str] = []
  for control in spec.controls:
    pos_count = population_event_counts[control.positive_population_id]
    neg_count = population_event_counts[control.negative_population_id]
    if pos_count < spec.minimum_positive_events:
      overall_warnings.append(
        f"positive control {control.positive_population_id!r} has only "
        f"{pos_count} events (minimum {spec.minimum_positive_events})"
      )
    if neg_count < spec.minimum_negative_events:
      overall_warnings.append(
        f"negative control {control.negative_population_id!r} has only "
        f"{neg_count} events (minimum {spec.minimum_negative_events})"
      )

  # Build spillover matrix.
  detector_ids = [c.detector_channel_id for c in spec.controls]
  detector_channel_ids = tuple(detector_ids)
  try:
    matrix_array, channel_diags = _build_spillover_matrix(
      spec, population_medians, channel_ids, detector_ids,
    )
  except CompensationError:
    raise

  # Ensure diagonal is 1.0.
  for i in range(len(detector_ids)):
    matrix_array[i, i] = 1.0

  # Check invertibility.
  try:
    cond = float(np.linalg.cond(matrix_array))
  except np.linalg.LinAlgError:
    raise CompensationError(
      "calculated spillover matrix is singular and cannot be inverted",
      code="calculation_singular_matrix",
    )

  if not np.isfinite(cond) or cond >= COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD:
    raise CompensationError(
      f"calculated spillover matrix is numerically singular (condition={cond:.2e})",
      code="calculation_singular_matrix",
    )

  if cond >= COMPENSATION_CONDITION_WARNING_THRESHOLD:
    overall_warnings.append(
      f"calculated matrix is ill-conditioned (condition={cond:.2e})"
    )

  # Update diagnostics with actual event counts.
  updated_diags: list[CompensationCalculationChannelDiagnostic] = []
  for diag in channel_diags:
    pos_count = population_event_counts[
      next(c.positive_population_id for c in spec.controls
           if c.detector_channel_id == diag.detector_channel_id)
    ]
    neg_count = population_event_counts[
      next(c.negative_population_id for c in spec.controls
           if c.detector_channel_id == diag.detector_channel_id)
    ]
    updated_diags.append(CompensationCalculationChannelDiagnostic(
      detector_channel_id=diag.detector_channel_id,
      positive_event_count=pos_count,
      negative_event_count=neg_count,
      median_positive=diag.median_positive,
      median_negative=diag.median_negative,
      median_background_subtracted=diag.median_background_subtracted,
      spillover_row=diag.spillover_row,
      outlier_count=outlier_counts.get(
        next(c.positive_population_id for c in spec.controls
             if c.detector_channel_id == diag.detector_channel_id),
        0,
      ),
      warnings=diag.warnings,
    ))

  # Create the resulting matrix spec.
  now = datetime.now(timezone.utc).isoformat()
  matrix_spec = CompensationMatrixSpec(
    id=f"calculated-{spec.id}",
    name=f"Calculated: {spec.name}",
    source="calculated",
    channels=detector_channel_ids,
    matrix=tuple(tuple(float(v) for v in row) for row in matrix_array),
    created_by=spec.created_by,
    created_at=now,
    notes=f"Auto-calculated from {spec.id}. Method={spec.regression_method}, outlier={spec.outlier_policy}.",
    provenance=CompensationProvenanceSpec(
      source_sample_id=None,
      source_metadata_key=None,
      control_sample_ids=tuple(),
      control_population_ids=tuple(dict.fromkeys(
        list(c.positive_population_id for c in spec.controls) +
        list(c.negative_population_id for c in spec.controls)
      )),
      algorithm="spillover_median",
      algorithm_version="1.0.0",
      software_version="1.5.0",
      derived_from_matrix_id=None,
      manual_edits=(),
    ),
  )

  return CompensationCalculationResult(
    matrix_spec=matrix_spec,
    channel_diagnostics=tuple(updated_diags),
    condition_number=cond,
    overall_warnings=tuple(overall_warnings),
  )
