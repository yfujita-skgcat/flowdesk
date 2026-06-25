"""Compensation matrix helpers."""

from __future__ import annotations

from flowdesk_core.models import CompensationMatrixSpec


def validate_compensation_matrix(spec: CompensationMatrixSpec) -> None:
  """Validate matrix shape and channel alignment."""

  size = len(spec.channels)
  if len(spec.matrix) != size or any(len(row) != size for row in spec.matrix):
    raise ValueError("compensation matrix must be square and match channels")
