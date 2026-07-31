from __future__ import annotations

import numpy as np

from flowdesk_core.density_colors import (
  DensityColorConfig,
  density_event_colors,
  estimate_density_colors,
)


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
  assert result.metadata.algorithm_version == "smooth-density.v2"
  assert result.metadata.requested_histogram_workers == 1
  assert result.metadata.effective_histogram_workers == 1


def test_density_normalization_does_not_clip_a_large_high_density_region() -> None:
  rng = np.random.default_rng(7)
  x = rng.normal(0.0, 0.08, 20_000)
  y = rng.normal(0.0, 0.08, 20_000)
  result = estimate_density_colors(
    x, y, x[:5000], y[:5000],
    bounds=(-1, 1, -1, 1), logical_size=(800, 600),
  )
  warm = result.normalized_density[result.normalized_density > 0.75]
  assert len(np.unique(np.round(warm, 3))) > 20
  assert np.count_nonzero(result.normalized_density == 1.0) < len(warm) * 0.1


def test_chunked_histogram_matches_unchunked_density_result() -> None:
  rng = np.random.default_rng(123)
  x = np.concatenate((rng.normal(0.0, 0.2, 12_345), np.array([-1.0, 1.0, np.nan])))
  y = np.concatenate((rng.normal(0.0, 0.15, 12_345), np.array([-1.0, 1.0, np.nan])))
  query_x = np.linspace(-1.0, 1.0, 257)
  query_y = np.sin(query_x)
  common = dict(
    bounds=(-1.0, 1.0, -1.0, 1.0), logical_size=(640, 480),
    config=DensityColorConfig(histogram_chunk_size=None),
  )
  unchunked = estimate_density_colors(x, y, query_x, query_y, **common)
  chunked = estimate_density_colors(
    x, y, query_x, query_y,
    bounds=common["bounds"], logical_size=common["logical_size"],
    config=DensityColorConfig(histogram_chunk_size=257),
  )
  assert np.array_equal(unchunked.colors, chunked.colors)
  assert np.array_equal(unchunked.normalized_density, chunked.normalized_density)
  assert chunked.metadata.valid_input_count == unchunked.metadata.valid_input_count
  parallel = estimate_density_colors(
    x, y, query_x, query_y,
    bounds=common["bounds"], logical_size=common["logical_size"],
    config=DensityColorConfig(histogram_chunk_size=257, histogram_workers=2),
  )
  assert np.array_equal(unchunked.colors, parallel.colors)
  assert np.array_equal(unchunked.normalized_density, parallel.normalized_density)
  assert parallel.metadata.requested_histogram_workers == 2
  assert parallel.metadata.effective_histogram_workers == 2
  budget_limited = estimate_density_colors(
    x, y, query_x, query_y,
    bounds=common["bounds"], logical_size=common["logical_size"],
    config=DensityColorConfig(
      histogram_chunk_size=257, histogram_workers=4, histogram_memory_budget_bytes=1,
    ),
  )
  assert np.array_equal(unchunked.colors, budget_limited.colors)
  assert np.array_equal(unchunked.normalized_density, budget_limited.normalized_density)
  assert budget_limited.metadata.effective_histogram_workers == 1


def test_density_chunk_size_rejects_non_positive_values() -> None:
  with np.testing.assert_raises_regex(ValueError, "histogram_chunk_size"):
    DensityColorConfig(histogram_chunk_size=0)
  with np.testing.assert_raises_regex(ValueError, "histogram_workers"):
    DensityColorConfig(histogram_workers=0)
  with np.testing.assert_raises_regex(ValueError, "histogram_memory_budget_bytes"):
    DensityColorConfig(histogram_memory_budget_bytes=0)


def test_density_cancel_check_stops_before_expensive_stages() -> None:
  checks = 0

  def cancel() -> None:
    nonlocal checks
    checks += 1
    if checks >= 2:
      raise RuntimeError("cancelled")

  with np.testing.assert_raises_regex(RuntimeError, "cancelled"):
    estimate_density_colors(
      np.linspace(0.0, 1.0, 1000), np.linspace(0.0, 1.0, 1000),
      np.array([0.5]), np.array([0.5]),
      bounds=(0.0, 1.0, 0.0, 1.0), logical_size=(320, 240),
      config=DensityColorConfig(histogram_chunk_size=100),
      cancel_check=cancel,
    )
  assert checks == 2


def test_density_palette_preserves_canonical_hex_colors() -> None:
  colors = density_event_colors(np.array([1.0, 1.0]), np.array([2.0, 2.0]))
  assert np.array_equal(colors, np.array(["#ed1c24", "#ed1c24"], dtype="<U7"))


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
