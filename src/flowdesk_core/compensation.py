"""Compensation matrix validation and application.

Compensation transforms raw fluorescence events by applying the inverse of a
spillover matrix. Raw events are never mutated; a new array is always returned.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import CompensationMatrixSpec


class CompensationError(FlowdeskError):
  """Raised when compensation data or matrix is invalid."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_compensation_matrix(spec: CompensationMatrixSpec) -> None:
  """Validate matrix shape, channel alignment, and invertibility.

  Raises:
    CompensationError: If the matrix is not square, its dimension does not
      match the channel list, channel names are duplicated, values are
      non-finite, or the matrix is singular.
  """

  size = len(spec.channels)
  if len(spec.matrix) != size or any(len(row) != size for row in spec.matrix):
    raise CompensationError(
      "compensation matrix must be square and match channels"
    )

  if len(set(spec.channels)) != size:
    raise CompensationError(
      "compensation channels must be unique"
    )

  arr = np.array(spec.matrix, dtype=np.float64)

  if not np.all(np.isfinite(arr)):
    raise CompensationError(
      "compensation matrix must contain finite values only"
    )

  # Check invertibility (singular matrix cannot be used for compensation).
  try:
    np.linalg.inv(arr)
  except np.linalg.LinAlgError as exc:
    raise CompensationError(
      "compensation matrix is singular and cannot be inverted"
    ) from exc


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

  validate_compensation_matrix(spec)

  if events.ndim != 2:
    raise CompensationError("events must be a 2-D array")

  if events.shape[1] != len(channel_names):
    raise CompensationError(
      "events columns count must match channel_names length"
    )

  compensated = events.copy()

  # Build a lookup from channel name to column index.
  name_to_idx: dict[str, int] = {
    name: idx for idx, name in enumerate(channel_names)
  }

  # Verify all compensation channels exist in the data.
  missing = [ch for ch in spec.channels if ch not in name_to_idx]
  if missing:
    raise CompensationError(
      f"compensation channels not found in data: {', '.join(missing)}"
    )

  # Map compensation matrix rows/cols to column indices in the event table.
  # The order of spec.channels defines the matrix row/column order.
  col_indices = [name_to_idx[ch] for ch in spec.channels]

  spillover = np.array(spec.matrix, dtype=np.float64)
  inverse = np.linalg.inv(spillover)

  # compensated_fluorescence = inverse @ raw_fluorescence^T, then transpose back
  raw_block = compensated[:, col_indices]  # (n_events, n_fl)
  comp_block = inverse @ raw_block.T       # (n_fl, n_events)
  compensated[:, col_indices] = comp_block.T  # (n_events, n_fl)

  return compensated
