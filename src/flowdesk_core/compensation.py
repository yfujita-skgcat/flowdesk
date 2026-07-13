"""Compensation matrix validation and application.

Compensation transforms raw fluorescence events by applying the inverse of a
spillover matrix. Raw events are never mutated; a new array is always returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import CompensationBindingSpec, CompensationMatrixSpec


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
