"""Deterministic display-only event-density color assignment."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

_PALETTE = np.asarray((
  "#1f3cff", "#00c8ff", "#00bd45", "#ffe600", "#ed1c24",
), dtype="<U7")


def density_event_colors(
  x_values: NDArray[np.float64],
  y_values: NDArray[np.float64],
  *,
  bins: int = 128,
) -> NDArray[np.str_]:
  """Return one blue-to-red density color per finite display event.

  This is a presentation helper only. Callers retain event order and must not
  use this display aggregation for gate membership or statistics.
  """
  x = np.asarray(x_values, dtype=np.float64)
  y = np.asarray(y_values, dtype=np.float64)
  if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
    raise ValueError("density colors require equally sized one-dimensional coordinates")
  if bins < 2:
    raise ValueError("density color bins must be at least 2")
  colors = np.full(len(x), _PALETTE[0], dtype="<U7")
  finite = np.isfinite(x) & np.isfinite(y)
  if not np.any(finite):
    return colors
  x_finite = x[finite]
  y_finite = y[finite]
  x_min, x_max = float(np.min(x_finite)), float(np.max(x_finite))
  y_min, y_max = float(np.min(y_finite)), float(np.max(y_finite))
  if x_min == x_max or y_min == y_max:
    colors[finite] = _PALETTE[-1]
    return colors
  x_bin = np.minimum(((x_finite - x_min) / (x_max - x_min) * bins).astype(int), bins - 1)
  y_bin = np.minimum(((y_finite - y_min) / (y_max - y_min) * bins).astype(int), bins - 1)
  occupancy = np.zeros((bins, bins), dtype=np.int32)
  np.add.at(occupancy, (x_bin, y_bin), 1)
  counts = occupancy[x_bin, y_bin]
  maximum = int(np.max(counts))
  level = np.zeros_like(counts)
  if maximum > 1:
    level = np.floor(
      np.log(counts) / np.log(maximum) * (len(_PALETTE) - 1)
    ).astype(int)
  colors[finite] = _PALETTE[np.clip(level, 0, len(_PALETTE) - 1)]
  return colors
