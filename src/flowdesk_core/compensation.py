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
from flowdesk_core.models import CompensationMatrixSpec


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


COMPENSATION_CONDITION_WARNING_THRESHOLD = 1e8
COMPENSATION_NUMERICAL_SINGULARITY_THRESHOLD = 1.0 / np.finfo(np.float64).eps


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


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
