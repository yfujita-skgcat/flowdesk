from __future__ import annotations

import numpy as np

from flowdesk_core.density_colors import DensityColorConfig, estimate_density_colors


def test_smooth_density_is_deterministic_continuous_and_warmer_at_cluster_centre() -> None:
  rng = np.random.default_rng(42)
  x = np.concatenate((rng.normal(0.0, 0.08, 6000), rng.uniform(-1, 1, 300)))
  y = np.concatenate((rng.normal(0.0, 0.08, 6000), rng.uniform(-1, 1, 300)))
  query_x = np.linspace(-0.35, 0.35, 100)
  query_y = np.zeros(100)
  result = estimate_density_colors(
    x, y, query_x, query_y, bounds=(-1, 1, -1, 1), logical_size=(600, 400),
  )

  assert result.normalized_density[50] > result.normalized_density[0]
  assert len(set(result.colors)) >= 32
  assert np.max(np.abs(np.diff(result.normalized_density))) < 0.2
  repeat = estimate_density_colors(
    x, y, query_x, query_y, bounds=(-1, 1, -1, 1), logical_size=(600, 400),
  )
  assert np.array_equal(result.colors, repeat.colors)
  assert result.metadata.grid_shape == (200, 300)
  assert result.metadata.algorithm_version == "smooth-density.v1"


def test_density_estimator_clips_viewport_and_rejects_invalid_contract() -> None:
  result = estimate_density_colors(
    np.array([0.0, 0.1, 20.0, np.nan]), np.array([0.0, 0.1, 20.0, 0.0]),
    np.array([0.0, 0.1]), np.array([0.0, 0.1]), bounds=(-1, 1, -1, 1), logical_size=(320, 160),
  )
  assert result.metadata.valid_input_count == 2
  assert result.metadata.grid_shape == (128, 160)
  with np.testing.assert_raises_regex(ValueError, "increasing"):
    estimate_density_colors(
      np.array([1.0]), np.array([1.0]), np.array([1.0]), np.array([1.0]),
      bounds=(1, 1, 0, 1), logical_size=(1, 1),
    )
  with np.testing.assert_raises_regex(ValueError, "ordered"):
    DensityColorConfig(normalization_low_percentile=99.0, normalization_high_percentile=1.0)
