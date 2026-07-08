"""Tests for population statistics and population tree helpers."""

import numpy as np
import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.populations import (
  build_population_tree,
  compute_total_events,
  find_root_populations,
  get_population_by_id,
  get_population_count,
)
from flowdesk_core.statistics import (
  PopulationStatsError,
  compute_histogram,
  compute_mad,
  compute_mean,
  compute_median,
  compute_percentile,
  compute_stddev,
  make_population_result,
  population_result_to_export_records,
  population_results_to_export_records,
)

# ---------------------------------------------------------------------------
# make_population_result
# ---------------------------------------------------------------------------

def test_population_result_frequencies() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="live",
    event_count=25,
    parent_count=50,
    total_count=100,
  )

  assert result.event_count == 25
  assert result.frequency_of_parent == 0.5
  assert result.frequency_of_total == 0.25


def test_population_result_zero_parent() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="empty_child",
    event_count=0,
    parent_count=0,
    total_count=100,
  )

  assert result.event_count == 0
  assert result.frequency_of_parent is None
  assert result.frequency_of_total == 0.0


def test_population_result_zero_total() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="orphan",
    event_count=10,
    parent_count=50,
    total_count=0,
  )

  assert result.event_count == 10
  assert result.frequency_of_parent == 0.2
  assert result.frequency_of_total is None


def test_population_result_none_parent() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="root",
    event_count=1000,
    parent_count=None,
    total_count=1000,
  )

  assert result.event_count == 1000
  assert result.frequency_of_parent is None
  assert result.frequency_of_total == 1.0


def test_population_result_all_none() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="standalone",
    event_count=42,
    parent_count=None,
    total_count=None,
  )

  assert result.event_count == 42
  assert result.frequency_of_parent is None
  assert result.frequency_of_total is None


# ---------------------------------------------------------------------------
# Moment statistics
# ---------------------------------------------------------------------------

def test_mean_basic() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
  assert compute_mean(vals) == 3.0


def test_mean_with_nan() -> None:
  vals = np.array([1.0, 2.0, np.nan, 4.0, 5.0], dtype=np.float64)
  assert compute_mean(vals) == 3.0


def test_mean_empty() -> None:
  vals = np.array([], dtype=np.float64)
  assert np.isnan(compute_mean(vals))


def test_median_basic() -> None:
  vals = np.array([3.0, 1.0, 2.0, 4.0, 5.0], dtype=np.float64)
  assert compute_median(vals) == 3.0


def test_median_with_nan() -> None:
  vals = np.array([3.0, 1.0, np.nan, 4.0, 5.0], dtype=np.float64)
  # After removing nan: [1, 3, 4, 5] → median is 3.5
  assert compute_median(vals) == 3.5


def test_median_even_count() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
  assert compute_median(vals) == 2.5


def test_median_empty() -> None:
  vals = np.array([], dtype=np.float64)
  assert np.isnan(compute_median(vals))


def test_mad_basic() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
  assert compute_mad(vals) == 1.0


def test_mad_with_nan() -> None:
  vals = np.array([1.0, 2.0, np.nan, 4.0, 5.0], dtype=np.float64)
  # After removing nan: [1, 2, 4, 5] → median=3 → MAD=median(|x-3|)=1.5
  assert compute_mad(vals) == 1.5


def test_mad_empty() -> None:
  vals = np.array([], dtype=np.float64)
  assert np.isnan(compute_mad(vals))


def test_stddev_basic() -> None:
  vals = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], dtype=np.float64)
  assert abs(compute_stddev(vals) - 2.0) < 1e-10


def test_stddev_with_nan() -> None:
  vals = np.array([2.0, 4.0, np.nan, 4.0, 5.0], dtype=np.float64)
  assert not np.isnan(compute_stddev(vals))


def test_stddev_empty() -> None:
  vals = np.array([], dtype=np.float64)
  assert np.isnan(compute_stddev(vals))


def test_percentile_50() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
  assert compute_percentile(vals, 50) == 3.0


def test_percentile_0() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
  assert compute_percentile(vals, 0) == 1.0


def test_percentile_100() -> None:
  vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
  assert compute_percentile(vals, 100) == 5.0


def test_percentile_empty() -> None:
  vals = np.array([], dtype=np.float64)
  assert np.isnan(compute_percentile(vals, 50))


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

def test_histogram_basic() -> None:
  vals = np.array([0.0, 0.5, 1.0, 1.5, 2.0], dtype=np.float64)
  hist = compute_histogram(vals, n_bins=4)

  assert "counts" in hist
  assert "bin_edges" in hist
  assert "bin_centers" in hist
  assert len(hist["counts"]) == 4
  assert len(hist["bin_edges"]) == 5
  assert len(hist["bin_centers"]) == 4


def test_histogram_empty() -> None:
  vals = np.array([], dtype=np.float64)
  hist = compute_histogram(vals, n_bins=10)

  assert len(hist["counts"]) == 10
  assert all(c == 0 for c in hist["counts"])


def test_histogram_all_nan() -> None:
  vals = np.array([np.nan, np.nan], dtype=np.float64)
  hist = compute_histogram(vals, n_bins=5)

  assert all(c == 0 for c in hist["counts"])


def test_histogram_invalid_bins() -> None:
  vals = np.array([1.0, 2.0], dtype=np.float64)
  with pytest.raises(PopulationStatsError):
    compute_histogram(vals, n_bins=0)


def test_histogram_error_hierarchy() -> None:
  assert issubclass(PopulationStatsError, FlowdeskError)


# ---------------------------------------------------------------------------
# Export record conversion
# ---------------------------------------------------------------------------

def test_export_record_single() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="live",
    event_count=25,
    parent_count=50,
    total_count=100,
  )

  records = population_result_to_export_records(result)
  assert len(records) == 3

  metrics = {r.metric for r in records}
  assert "event_count" in metrics
  assert "frequency_of_parent" in metrics
  assert "frequency_of_total" in metrics

  event_count_rec = next(r for r in records if r.metric == "event_count")
  assert event_count_rec.value == 25

  freq_parent_rec = next(r for r in records if r.metric == "frequency_of_parent")
  assert freq_parent_rec.value == 0.5

  freq_total_rec = next(r for r in records if r.metric == "frequency_of_total")
  assert freq_total_rec.value == 0.25


def test_export_record_with_none_frequencies() -> None:
  result = make_population_result(
    sample_id="s1",
    population_id="root",
    event_count=100,
    parent_count=None,
    total_count=None,
  )

  records = population_result_to_export_records(result)
  assert len(records) == 3

  freq_parent_rec = next(r for r in records if r.metric == "frequency_of_parent")
  assert freq_parent_rec.value is None

  freq_total_rec = next(r for r in records if r.metric == "frequency_of_total")
  assert freq_total_rec.value is None


def test_export_records_multiple() -> None:
  results = [
    make_population_result("s1", "root", 100, None, 100),
    make_population_result("s1", "child", 30, 100, 100),
  ]

  records = population_results_to_export_records(results)
  assert len(records) == 6  # 2 results x 3 metrics each


# ---------------------------------------------------------------------------
# Population tree helpers
# ---------------------------------------------------------------------------

def test_find_root_populations() -> None:
  results = [
    make_population_result("s1", "root", 100, None, 100),
    make_population_result("s1", "child", 30, 100, 100),
  ]

  roots = find_root_populations(results)
  assert len(roots) == 1
  assert roots[0].population_id == "root"


def test_find_root_populations_empty() -> None:
  assert find_root_populations([]) == []


def test_build_population_tree() -> None:
  results = [
    make_population_result("s1", "root", 100, None, 100),
    make_population_result("s1", "child1", 50, 100, 100),
    make_population_result("s1", "child2", 25, 100, 100),
  ]

  tree = build_population_tree(results)
  assert "root" in tree
  assert "child1" in tree["root"]
  assert "child2" in tree["root"]
  assert tree["child1"] == []
  assert tree["child2"] == []


def test_build_population_tree_empty() -> None:
  assert build_population_tree([]) == {}


def test_get_population_count() -> None:
  results = [
    make_population_result("s1", "root", 100, None, 100),
    make_population_result("s1", "child", 30, 100, 100),
  ]

  assert get_population_count(results, "root") == 100
  assert get_population_count(results, "child") == 30
  assert get_population_count(results, "unknown") is None


def test_get_population_by_id() -> None:
  results = [
    make_population_result("s1", "root", 100, None, 100),
    make_population_result("s1", "child", 30, 100, 100),
  ]

  root = get_population_by_id(results, "root")
  assert root is not None
  assert root.event_count == 100

  assert get_population_by_id(results, "unknown") is None


def test_compute_total_events() -> None:
  results = [
    make_population_result("s1", "root", 1000, None, 1000),
    make_population_result("s1", "child", 300, 1000, 1000),
  ]

  assert compute_total_events(results) == 1000


def test_compute_total_events_empty() -> None:
  assert compute_total_events([]) == 0
