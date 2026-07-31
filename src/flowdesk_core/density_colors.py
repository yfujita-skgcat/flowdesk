"""Deterministic, display-only smooth event-density colors."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class DensityColorConfig:
  """Versioned numerical choices for the display-only density estimator."""

  algorithm_version: str = "smooth-density.v2"
  cells_per_logical_pixel: float = 2.0
  minimum_cells: int = 128
  maximum_cells: int = 512
  gaussian_sigma_pixels: float = 1.25
  normalization_low_percentile: float = 1.0
  normalization_high_percentile: float = 100.0
  # Keep small plots on the fast single-call path while bounding the input
  # temporary used by np.histogram2d for very large populations.
  histogram_chunk_size: int | None = 250_000

  def __post_init__(self) -> None:
    if self.cells_per_logical_pixel <= 0:
      raise ValueError("cells_per_logical_pixel must be positive")
    if not 2 <= self.minimum_cells <= self.maximum_cells:
      raise ValueError("density cell limits must satisfy 2 <= minimum <= maximum")
    if self.gaussian_sigma_pixels <= 0:
      raise ValueError("gaussian_sigma_pixels must be positive")
    if not 0 <= self.normalization_low_percentile < self.normalization_high_percentile <= 100:
      raise ValueError("density normalization percentiles must be ordered percentages")
    if self.histogram_chunk_size is not None and self.histogram_chunk_size < 1:
      raise ValueError("histogram_chunk_size must be positive when provided")


@dataclass(frozen=True)
class DensityColorMetadata:
  bounds: tuple[float, float, float, float]
  grid_shape: tuple[int, int]
  sigma_cells: tuple[float, float]
  normalization_log_density: tuple[float, float]
  valid_input_count: int
  algorithm_version: str


@dataclass(frozen=True)
class DensityColorResult:
  colors: NDArray[np.str_]
  normalized_density: NDArray[np.float64]
  metadata: DensityColorMetadata


_PALETTE_STOPS = np.asarray((
  (31, 60, 255), (0, 200, 255), (0, 189, 69), (255, 230, 0), (237, 28, 36),
), dtype=np.float64)
_DEFAULT_CONFIG = DensityColorConfig()
_ESTIMATOR_LOCK = RLock()


def estimate_density_colors(
  input_x: NDArray[np.float64],
  input_y: NDArray[np.float64],
  query_x: NDArray[np.float64],
  query_y: NDArray[np.float64],
  *,
  bounds: tuple[float, float, float, float],
  logical_size: tuple[int, int],
  config: DensityColorConfig = _DEFAULT_CONFIG,
) -> DensityColorResult:
  """Estimate a smooth field from full input and color separate display points."""
  # NumPy histogram/convolution implementations used below are not guaranteed
  # to be re-entrant across all supported BLAS/OpenMP combinations.  Density
  # requests are latest-wins display work, so serializing this short numerical
  # kernel avoids overlapping stale workers while keeping it off the GUI thread.
  with _ESTIMATOR_LOCK:
    return _estimate_density_colors(
      input_x, input_y, query_x, query_y,
      bounds=bounds, logical_size=logical_size, config=config,
    )


def _estimate_density_colors(
  input_x: NDArray[np.float64],
  input_y: NDArray[np.float64],
  query_x: NDArray[np.float64],
  query_y: NDArray[np.float64],
  *,
  bounds: tuple[float, float, float, float],
  logical_size: tuple[int, int],
  config: DensityColorConfig,
) -> DensityColorResult:
  """Unlocked implementation for the public density estimator."""
  x, y = _coordinates(input_x, input_y, "input")
  qx, qy = _coordinates(query_x, query_y, "query")
  x_min, x_max, y_min, y_max = bounds
  width, height = logical_size
  if not x_min < x_max or not y_min < y_max:
    raise ValueError("density bounds must have increasing finite limits")
  if width <= 0 or height <= 0:
    raise ValueError("logical density plot size must be positive")
  if not all(np.isfinite(bounds)):
    raise ValueError("density bounds must be finite")
  shape = _grid_shape(width, height, config)
  finite = np.isfinite(x) & np.isfinite(y)
  visible = finite & (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)
  histogram = _histogram2d(
    y[visible], x[visible], shape=shape,
    bounds=(x_min, x_max, y_min, y_max),
    chunk_size=config.histogram_chunk_size,
  )
  sigma = (
    config.gaussian_sigma_pixels * shape[0] / height,
    config.gaussian_sigma_pixels * shape[1] / width,
  )
  smoothed = _gaussian_smooth(histogram, sigma)
  positive = np.log1p(smoothed[smoothed > 0])
  if len(positive):
    low, high = np.percentile(positive, (
      config.normalization_low_percentile, config.normalization_high_percentile,
    ))
  else:
    low = high = 0.0
  sampled = _bilinear(smoothed, qx, qy, bounds)
  normalized = np.zeros(len(qx), dtype=np.float64)
  query_visible = (
    np.isfinite(qx) & np.isfinite(qy) & (qx >= x_min) & (qx <= x_max)
    & (qy >= y_min) & (qy <= y_max)
  )
  if high > low:
    normalized[query_visible] = np.clip(
      (np.log1p(sampled[query_visible]) - low) / (high - low), 0.0, 1.0,
    )
  elif len(positive):
    normalized[query_visible] = 1.0
  return DensityColorResult(
    _palette(normalized), normalized,
    DensityColorMetadata(
      bounds, shape, sigma, (float(low), float(high)),
      int(np.count_nonzero(visible)), config.algorithm_version,
    ),
  )


def density_event_colors(
  x_values: NDArray[np.float64], y_values: NDArray[np.float64], *, bins: int = 128,
) -> NDArray[np.str_]:
  """Compatibility wrapper for callers without a viewport/display size."""
  x, y = _coordinates(x_values, y_values, "event")
  finite = np.isfinite(x) & np.isfinite(y)
  if not np.any(finite):
    return np.full(len(x), "#1f3cff", dtype="<U7")
  x_min, x_max = np.min(x[finite]), np.max(x[finite])
  y_min, y_max = np.min(y[finite]), np.max(y[finite])
  if x_min == x_max or y_min == y_max:
    return np.full(len(x), "#ed1c24", dtype="<U7")
  config = DensityColorConfig(minimum_cells=bins, maximum_cells=bins)
  return estimate_density_colors(
    x, y, x, y, bounds=(float(x_min), float(x_max), float(y_min), float(y_max)),
    logical_size=(bins * 2, bins * 2), config=config,
  ).colors


def _coordinates(
  x_values: NDArray[np.float64], y_values: NDArray[np.float64], name: str,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
  x = np.asarray(x_values, dtype=np.float64)
  y = np.asarray(y_values, dtype=np.float64)
  if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
    raise ValueError(f"density {name} coordinates must be equally sized one-dimensional arrays")
  return x, y


def _grid_shape(width: int, height: int, config: DensityColorConfig) -> tuple[int, int]:
  return (
    min(config.maximum_cells, max(
      config.minimum_cells, round(height / config.cells_per_logical_pixel),
    )),
    min(config.maximum_cells, max(
      config.minimum_cells, round(width / config.cells_per_logical_pixel),
    )),
  )


def _histogram2d(
  y_values: NDArray[np.float64],
  x_values: NDArray[np.float64],
  *,
  shape: tuple[int, int],
  bounds: tuple[float, float, float, float],
  chunk_size: int | None,
) -> NDArray[np.float64]:
  """Build a deterministic histogram, optionally in bounded-memory chunks.

  ``np.histogram2d`` returns floating counts even though every bin contains an
  integer number of events.  Each chunk is rounded back to exact integer counts
  before accumulation, so chunking cannot change the global field.  Smoothing,
  percentile normalization, and query interpolation happen only after the full
  histogram has been assembled; this is not arbitrary per-event colour work.
  """
  if chunk_size is None or len(x_values) <= chunk_size:
    histogram, _, _ = np.histogram2d(
      y_values, x_values, bins=shape,
      range=((bounds[2], bounds[3]), (bounds[0], bounds[1])),
    )
    return histogram
  histogram = np.zeros(shape, dtype=np.int64)
  for start in range(0, len(x_values), chunk_size):
    stop = min(start + chunk_size, len(x_values))
    chunk, _, _ = np.histogram2d(
      y_values[start:stop], x_values[start:stop], bins=shape,
      range=((bounds[2], bounds[3]), (bounds[0], bounds[1])),
    )
    histogram += np.rint(chunk).astype(np.int64)
  return histogram.astype(np.float64)


def _gaussian_smooth(
  values: NDArray[np.float64], sigma: tuple[float, float],
) -> NDArray[np.float64]:
  result = values.astype(np.float64, copy=True)
  for axis, value in enumerate(sigma):
    radius = max(1, int(np.ceil(3 * value)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / value) ** 2)
    kernel /= kernel.sum()
    padding = [(0, 0), (0, 0)]
    padding[axis] = (radius, radius)
    padded = np.pad(result, padding, mode="edge")
    # ``apply_along_axis`` invokes a Python callback for every grid row/column.
    # The density grid is bounded but this callback still dominates repeated
    # interactive requests on some Python/NumPy builds.  A sliding view keeps
    # the same edge-padded, valid convolution while reducing the whole pass to
    # one vectorized contraction.  The final axis is the kernel window for both
    # axis choices in NumPy's ``sliding_window_view`` API.
    windows = np.lib.stride_tricks.sliding_window_view(
      padded, kernel.size, axis=axis,
    )
    result = np.tensordot(windows, kernel, axes=([-1], [0]))
  return result


def _bilinear(
  field: NDArray[np.float64], x: NDArray[np.float64], y: NDArray[np.float64],
  bounds: tuple[float, float, float, float],
) -> NDArray[np.float64]:
  x_min, x_max, y_min, y_max = bounds
  columns = (x - x_min) / (x_max - x_min) * (field.shape[1] - 1)
  rows = (y - y_min) / (y_max - y_min) * (field.shape[0] - 1)
  columns = np.clip(columns, 0, field.shape[1] - 1)
  rows = np.clip(rows, 0, field.shape[0] - 1)
  x0, y0 = columns.astype(int), rows.astype(int)
  x1, y1 = np.minimum(x0 + 1, field.shape[1] - 1), np.minimum(y0 + 1, field.shape[0] - 1)
  dx, dy = columns - x0, rows - y0
  return ((1 - dx) * (1 - dy) * field[y0, x0] + dx * (1 - dy) * field[y0, x1]
          + (1 - dx) * dy * field[y1, x0] + dx * dy * field[y1, x1])


def _palette(values: NDArray[np.float64]) -> NDArray[np.str_]:
  scaled = np.clip(values, 0.0, 1.0) * (len(_PALETTE_STOPS) - 1)
  low = scaled.astype(int)
  high = np.minimum(low + 1, len(_PALETTE_STOPS) - 1)
  fraction = (scaled - low)[:, None]
  rgb = np.rint(
    _PALETTE_STOPS[low] * (1 - fraction) + _PALETTE_STOPS[high] * fraction
  ).astype(np.uint8)
  return np.asarray([f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in rgb], dtype="<U7")
