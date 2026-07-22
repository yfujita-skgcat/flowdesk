"""Tests for population statistics and population tree helpers."""

import numpy as np
import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import StatisticResult, StatisticSpec
from flowdesk_core.populations import (
  build_population_tree,
  compute_total_events,
  find_root_populations,
  get_population_by_id,
  get_population_count,
)
from flowdesk_core.statistics import (
  PopulationStatsError,
  compute_cv,
  compute_geometric_mean,
  compute_histogram,
  compute_mad,
  compute_mean,
  compute_median,
  compute_percentile,
  compute_statistic,
  compute_stddev,
  make_population_result,
  population_result_to_export_records,
  population_results_to_export_records,
)
from flowdesk_storage.manifest import ManifestValidationError, validate_manifest

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


# ---------------------------------------------------------------------------
# StatisticSpec and StatisticResult model tests
# ---------------------------------------------------------------------------
class TestStatisticSpec:
  def test_construct_valid_count(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Count live",
      population_id="live",
      metric="count",
    )
    assert spec.id == "stat1"
    assert spec.metric == "count"
    assert spec.source_stage == "compensated"

  def test_construct_valid_percentile(self) -> None:
    spec = StatisticSpec(
      id="stat_p50",
      name="Median FL1",
      population_id="live",
      parameter_id="FL1-A",
      metric="percentile",
      settings={"q": 50},
    )
    assert spec.metric == "percentile"
    assert spec.settings["q"] == 50

  def test_reject_empty_id(self) -> None:
    with pytest.raises(ValueError, match="statistic ID must be non-empty"):
      StatisticSpec(
        id="",
        name="bad",
        population_id="live",
      )

  def test_reject_empty_population_id(self) -> None:
    with pytest.raises(ValueError, match="population_id must be non-empty"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="",
      )

  def test_reject_invalid_metric(self) -> None:
    with pytest.raises(ValueError, match="invalid statistic metric"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        metric="invalid_metric",  # type: ignore[arg-type]
      )

  def test_reject_invalid_source_stage(self) -> None:
    with pytest.raises(ValueError, match="invalid statistic source_stage"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        source_stage="invalid",  # type: ignore[arg-type]
      )

  def test_reject_invalid_value_policy(self) -> None:
    with pytest.raises(ValueError, match="invalid statistic value_policy"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        value_policy="display_bins",  # type: ignore[arg-type]
      )

  def test_reject_percentile_without_q(self) -> None:
    with pytest.raises(ValueError, match="percentile metric requires"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        parameter_id="FL1-A",
        metric="percentile",
      )

  def test_reject_percentile_q_out_of_range(self) -> None:
    with pytest.raises(ValueError, match="percentile 'q' setting must be in"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        parameter_id="FL1-A",
        metric="percentile",
        settings={"q": 101},
      )

  def test_reject_percentile_q_negative(self) -> None:
    with pytest.raises(ValueError, match="percentile 'q' setting must be in"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        parameter_id="FL1-A",
        metric="percentile",
        settings={"q": -1},
      )

  def test_reject_percentile_q_non_numeric(self) -> None:
    with pytest.raises(ValueError, match="percentile 'q' setting must be a number"):
      StatisticSpec(
        id="stat1",
        name="bad",
        population_id="live",
        parameter_id="FL1-A",
        metric="percentile",
        settings={"q": "fifty"},
      )

  def test_serialize_and_reconstruct(self) -> None:
    spec = StatisticSpec(
      id="stat_gm",
      name="Geo mean FL1",
      population_id="live",
      parameter_id="FL1-A",
      metric="geometric_mean",
      source_stage="transformed",
      transform_id="logicle-fl1",
      value_policy="full_events",
      settings={},
      format=".3e",
      notes="geometric mean for log-normal data",
    )
    d = {
      "id": spec.id,
      "name": spec.name,
      "population_id": spec.population_id,
      "parameter_id": spec.parameter_id,
      "metric": spec.metric,
      "source_stage": spec.source_stage,
      "transform_id": spec.transform_id,
      "value_policy": spec.value_policy,
      "settings": spec.settings,
      "format": spec.format,
      "notes": spec.notes,
    }
    spec2 = StatisticSpec(**d)
    assert spec2.id == spec.id
    assert spec2.metric == spec.metric
    assert spec2.source_stage == spec.source_stage
    assert spec2.value_policy == spec.value_policy
    assert spec2.format == spec.format
    assert spec2.notes == spec.notes

  def test_transformed_statistic_requires_explicit_transform_id(self) -> None:
    with pytest.raises(ValueError, match="requires an explicit transform_id"):
      StatisticSpec(
        id="transformed",
        name="Transformed",
        population_id="all_events",
        parameter_id="FL1-A",
        metric="mean",
        source_stage="transformed",
      )


class TestStatisticResult:
  def test_construct_ok(self) -> None:
    result = StatisticResult(
      sample_id="s1",
      statistic_id="stat1",
      population_id="live",
      metric="count",
      value=100,
      status="ok",
    )
    assert result.value == 100
    assert result.status == "ok"

  def test_construct_undefined(self) -> None:
    result = StatisticResult(
      sample_id="s1",
      statistic_id="stat1",
      population_id="live",
      metric="mean",
      value=None,
      status="undefined",
      undefined_reason="all_nan",
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"


# ---------------------------------------------------------------------------
# compute_statistic dispatcher tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
  ("metric", "settings", "values", "expected"),
  (
    ("mean", {}, (1.0, 2.0, 3.0), 2.0),
    ("median", {}, (1.0, 2.0, 3.0), 2.0),
    ("stddev", {}, (1.0, 2.0, 3.0), float(np.sqrt(2.0 / 3.0))),
    ("mad", {}, (1.0, 2.0, 3.0), 1.0),
    ("percentile", {"q": 50}, (1.0, 2.0, 3.0), 2.0),
    ("geometric_mean", {}, (1.0, 4.0), 2.0),
    ("cv", {}, (1.0, 2.0, 3.0), float(np.sqrt(2.0 / 3.0) / 2.0)),
  ),
)
def test_value_statistics_known_values(
  metric: str,
  settings: dict[str, float],
  values: tuple[float, ...],
  expected: float,
) -> None:
  """Each persisted numeric metric has a hand-computed reference value."""
  result = compute_statistic(
    spec=StatisticSpec(
      id=f"known-{metric}",
      name=f"Known {metric}",
      population_id="live",
      parameter_id="FL1-A",
      metric=metric,  # type: ignore[arg-type]
      settings=settings,
    ),
    sample_id="s1",
    event_count=len(values),
    parent_count=len(values),
    total_count=len(values),
    values=np.array(values, dtype=np.float64),
  )

  assert result.status == "ok"
  assert result.undefined_reason is None
  assert result.value == pytest.approx(expected)


@pytest.mark.parametrize(
  ("metric", "settings"),
  (
    ("mean", {}),
    ("median", {}),
    ("stddev", {}),
    ("mad", {}),
    ("percentile", {"q": 50}),
    ("geometric_mean", {}),
    ("cv", {}),
  ),
)
def test_value_statistics_empty_and_all_nan(
  metric: str,
  settings: dict[str, float],
) -> None:
  """Empty populations and all-NaN values retain distinct statuses."""
  spec = StatisticSpec(
    id=f"edge-{metric}",
    name=f"Edge {metric}",
    population_id="live",
    parameter_id="FL1-A",
    metric=metric,  # type: ignore[arg-type]
    settings=settings,
  )
  empty_result = compute_statistic(
    spec=spec,
    sample_id="s1",
    event_count=0,
    parent_count=0,
    total_count=0,
    values=np.array([], dtype=np.float64),
  )
  all_nan_result = compute_statistic(
    spec=spec,
    sample_id="s1",
    event_count=2,
    parent_count=2,
    total_count=2,
    values=np.array([np.nan, np.nan], dtype=np.float64),
  )

  assert empty_result.value is None
  assert empty_result.status == "empty"
  assert empty_result.undefined_reason == "empty_population"
  assert all_nan_result.value is None
  assert all_nan_result.status == "undefined"
  assert all_nan_result.undefined_reason == "all_nan"


@pytest.mark.parametrize(
  ("metric", "settings"),
  (
    ("mean", {}),
    ("median", {}),
    ("stddev", {}),
    ("mad", {}),
    ("percentile", {"q": 50}),
    ("geometric_mean", {}),
    ("cv", {}),
  ),
)
def test_value_statistics_reject_nonfinite_input(
  metric: str,
  settings: dict[str, float],
) -> None:
  """Inf must never become an apparently valid statistic result."""
  result = compute_statistic(
    spec=StatisticSpec(
      id=f"nonfinite-{metric}",
      name=f"Nonfinite {metric}",
      population_id="live",
      metric=metric,  # type: ignore[arg-type]
      settings=settings,
    ),
    sample_id="s1",
    event_count=3,
    parent_count=3,
    total_count=3,
    values=np.array([1.0, np.nan, np.inf], dtype=np.float64),
  )

  assert result.value is None
  assert result.status == "undefined"
  assert result.undefined_reason == "nonfinite_values"


def test_nonfinite_policy_strict_and_explicit_exclusion_report_qc() -> None:
  values = np.array([2.0, np.nan, 6.0], dtype=np.float64)
  strict = compute_statistic(
    spec=StatisticSpec(
      id="strict", name="Strict", population_id="live", metric="mean",
      non_finite_policy="strict",
    ),
    sample_id="s1", event_count=3, parent_count=3, total_count=3, values=values,
    non_finite_policy="strict",
  )
  assert strict.status == "undefined"
  assert strict.undefined_reason == "nonfinite_values"
  assert strict.n_total == 3
  assert strict.n_valid == 2
  assert strict.n_invalid == 1
  assert strict.invalid_fraction == pytest.approx(1 / 3)

  excluded = compute_statistic(
    spec=StatisticSpec(
      id="excluded", name="Excluded", population_id="live", metric="mean",
      non_finite_policy="exclude_invalid",
    ),
    sample_id="s1", event_count=3, parent_count=3, total_count=3, values=values,
    non_finite_policy="exclude_invalid",
  )
  assert excluded.status == "ok"
  assert excluded.value == pytest.approx(4.0)



class TestComputeStatisticCount:
  def test_count_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Count",
      population_id="live",
      metric="count",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=50,
      parent_count=100,
      total_count=200,
      values=None,
    )
    assert result.value == 50
    assert result.status == "ok"

  def test_count_empty_population(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Count",
      population_id="live",
      metric="count",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=0,
      parent_count=100,
      total_count=200,
      values=None,
    )
    assert result.value == 0
    assert result.status == "empty"
    assert result.undefined_reason == "empty_population"


class TestComputeStatisticFrequency:
  def test_frequency_of_parent(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq parent",
      population_id="live",
      metric="frequency_of_parent",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=25,
      parent_count=100,
      total_count=200,
      values=None,
    )
    assert result.value == 0.25
    assert result.status == "ok"

  def test_frequency_of_parent_none_parent(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq parent",
      population_id="live",
      metric="frequency_of_parent",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=25,
      parent_count=None,
      total_count=200,
      values=None,
    )
    assert result.value is None
    assert result.status == "ok"

  def test_frequency_of_parent_zero_parent(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq parent",
      population_id="live",
      metric="frequency_of_parent",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=25,
      parent_count=0,
      total_count=200,
      values=None,
    )
    assert result.value is None
    assert result.status == "ok"

  def test_frequency_of_total(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq total",
      population_id="live",
      metric="frequency_of_total",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=50,
      parent_count=100,
      total_count=200,
      values=None,
    )
    assert result.value == 0.25
    assert result.status == "ok"

  def test_frequency_of_total_none_total(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq total",
      population_id="live",
      metric="frequency_of_total",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=50,
      parent_count=100,
      total_count=None,
      values=None,
    )
    assert result.value is None
    assert result.status == "ok"

  def test_frequency_empty_population(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Freq",
      population_id="live",
      metric="frequency_of_parent",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=0,
      parent_count=100,
      total_count=200,
      values=None,
    )
    assert result.value is None
    assert result.status == "empty"
    assert result.undefined_reason == "empty_population"


class TestComputeStatisticMean:
  def test_mean_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Mean FL1",
      population_id="live",
      metric="mean",
    )
    vals = np.array([2.0, 4.0, 6.0, 8.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=4,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value == 5.0
    assert result.status == "ok"

  def test_mean_with_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Mean FL1",
      population_id="live",
      metric="mean",
    )
    vals = np.array([2.0, np.nan, 6.0, 8.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=4,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    # NaN-aware mean: (2+6+8)/3 = 5.333...
    assert abs(result.value - 5.333333333333333) < 1e-10
    assert result.status == "ok"

  def test_mean_all_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Mean FL1",
      population_id="live",
      metric="mean",
    )
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"

  def test_mean_no_values(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Mean FL1",
      population_id="live",
      metric="mean",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=5,
      parent_count=10,
      total_count=10,
      values=None,
    )
    assert result.value is None
    assert result.status == "empty"
    assert result.undefined_reason == "empty_population"


class TestComputeStatisticMedian:
  def test_median_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Median FL1",
      population_id="live",
      metric="median",
    )
    vals = np.array([1.0, 3.0, 5.0, 7.0, 9.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=5,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value == 5.0
    assert result.status == "ok"

  def test_median_all_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Median FL1",
      population_id="live",
      metric="median",
    )
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"


class TestComputeStatisticStddev:
  def test_stddev_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Stddev FL1",
      population_id="live",
      metric="stddev",
    )
    vals = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=8,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert abs(result.value - 2.0) < 1e-10
    assert result.status == "ok"

  def test_stddev_all_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Stddev FL1",
      population_id="live",
      metric="stddev",
    )
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"


class TestComputeStatisticMAD:
  def test_mad_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="MAD FL1",
      population_id="live",
      metric="mad",
    )
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=5,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value == 1.0
    assert result.status == "ok"

  def test_mad_all_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="MAD FL1",
      population_id="live",
      metric="mad",
    )
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"


class TestComputeStatisticPercentile:
  def test_percentile_50(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="P50 FL1",
      population_id="live",
      metric="percentile",
      settings={"q": 50},
    )
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=5,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value == 3.0
    assert result.status == "ok"

  def test_percentile_all_nan(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="P50 FL1",
      population_id="live",
      metric="percentile",
      settings={"q": 50},
    )
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nan"


# ---------------------------------------------------------------------------
# Geometric mean tests
# ---------------------------------------------------------------------------

class TestComputeGeometricMean:
  def test_basic(self) -> None:
    vals = np.array([1.0, 2.0, 4.0, 8.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "ok"
    assert reason is None
    assert abs(val - 2.82842712474619) < 1e-6

  def test_with_nan(self) -> None:
    vals = np.array([1.0, np.nan, 4.0, 16.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "ok"
    assert abs(val - 4.0) < 1e-10

  def test_all_nan(self) -> None:
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "undefined"
    assert reason == "all_nan"

  def test_empty(self) -> None:
    vals = np.array([], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "undefined"
    assert reason == "all_nan"

  def test_all_nonpositive(self) -> None:
    vals = np.array([-1.0, -2.0, 0.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "undefined"
    assert reason == "all_nonpositive_geometric_mean"

  def test_mixed_positive_and_negative(self) -> None:
    vals = np.array([1.0, -2.0, 4.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "ok"
    assert reason is None
    assert abs(val - 2.0) < 1e-10

  def test_with_zeros_and_positives(self) -> None:
    vals = np.array([0.0, 1.0, 4.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert status == "ok"
    assert abs(val - 2.0) < 1e-10

  def test_inf_handling(self) -> None:
    vals = np.array([1.0, 2.0, np.inf, 8.0], dtype=np.float64)
    val, status, reason = compute_geometric_mean(vals)
    assert np.isnan(val)
    assert status == "undefined"
    assert reason == "nonfinite_values"


# ---------------------------------------------------------------------------
# Coefficient of variation tests
# ---------------------------------------------------------------------------

class TestComputeCV:
  def test_basic(self) -> None:
    vals = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    val, status, reason = compute_cv(vals)
    assert status == "ok"
    assert reason is None
    expected_std = float(np.std(vals))
    expected_mean = float(np.mean(vals))
    assert abs(val - expected_std / abs(expected_mean)) < 1e-10

  def test_all_nan(self) -> None:
    vals = np.array([np.nan, np.nan], dtype=np.float64)
    val, status, reason = compute_cv(vals)
    assert status == "undefined"
    assert reason == "all_nan"

  def test_empty(self) -> None:
    vals = np.array([], dtype=np.float64)
    val, status, reason = compute_cv(vals)
    assert status == "undefined"
    assert reason == "all_nan"

  def test_zero_mean(self) -> None:
    vals = np.array([-1.0, 1.0], dtype=np.float64)
    val, status, reason = compute_cv(vals)
    assert status == "undefined"
    assert reason == "zero_mean_for_cv"

  def test_with_inf(self) -> None:
    vals = np.array([1.0, 2.0, np.inf, 4.0], dtype=np.float64)
    val, status, reason = compute_cv(vals)
    assert np.isnan(val)
    assert status == "undefined"
    assert reason == "nonfinite_values"


# ---------------------------------------------------------------------------
# Dispatcher: geometric_mean and cv
# ---------------------------------------------------------------------------

class TestComputeStatisticGeometricMean:
  def test_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Geo mean FL1",
      population_id="live",
      metric="geometric_mean",
    )
    vals = np.array([1.0, 2.0, 4.0, 8.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=4,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert abs(result.value - 2.82842712474619) < 1e-6
    assert result.status == "ok"

  def test_all_nonpositive(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Geo mean FL1",
      population_id="live",
      metric="geometric_mean",
    )
    vals = np.array([-1.0, -2.0, 0.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=3,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "all_nonpositive_geometric_mean"

  def test_empty_population(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="Geo mean FL1",
      population_id="live",
      metric="geometric_mean",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=0,
      parent_count=10,
      total_count=10,
      values=np.array([1.0], dtype=np.float64),
    )
    assert result.value is None
    assert result.status == "empty"
    assert result.undefined_reason == "empty_population"


class TestComputeStatisticCV:
  def test_basic(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="CV FL1",
      population_id="live",
      metric="cv",
    )
    vals = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=3,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.status == "ok"
    assert result.value is not None

  def test_zero_mean(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="CV FL1",
      population_id="live",
      metric="cv",
    )
    vals = np.array([-1.0, 1.0], dtype=np.float64)
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=2,
      parent_count=10,
      total_count=10,
      values=vals,
    )
    assert result.value is None
    assert result.status == "undefined"
    assert result.undefined_reason == "zero_mean_for_cv"

  def test_empty_population(self) -> None:
    spec = StatisticSpec(
      id="stat1",
      name="CV FL1",
      population_id="live",
      metric="cv",
    )
    result = compute_statistic(
      spec=spec,
      sample_id="s1",
      event_count=0,
      parent_count=10,
      total_count=10,
      values=np.array([1.0], dtype=np.float64),
    )
    assert result.value is None
    assert result.status == "empty"
    assert result.undefined_reason == "empty_population"


# ---------------------------------------------------------------------------
# Manifest validation for statistics
# ---------------------------------------------------------------------------
class TestManifestStatisticsValidation:
  def _minimal_manifest(self, statistics=None):
    return {
      "project_id": "test",
      "project_version": "1.5.0",
      "pipeline_version": "1.0",
      "samples": [],
      "statistics": statistics or [],
    }

  def test_valid_statistics_pass(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1",
        "name": "Count live",
        "population_id": "live",
        "metric": "count",
        "source_stage": "compensated",
      },
      {
        "id": "stat2",
        "name": "Mean FL1",
        "population_id": "live",
        "parameter_id": "FL1-A",
        "metric": "mean",
        "source_stage": "compensated",
      },
      {
        "id": "stat3",
        "name": "P50 FL1",
        "population_id": "live",
        "parameter_id": "FL1-A",
        "metric": "percentile",
        "source_stage": "compensated",
        "settings": {"q": 50},
      },
    ])
    validate_manifest(manifest)

  def test_valid_statistics_all_metrics(self) -> None:
    metrics = [
      "count", "frequency_of_parent", "frequency_of_total",
      "mean", "median", "geometric_mean", "stddev", "cv", "mad",
    ]
    stats = []
    for m in metrics:
      stat = {
        "id": f"stat_{m}",
        "name": f"Stat {m}",
        "population_id": "live",
        "metric": m,
        "source_stage": "compensated",
      }
      if m not in {"count", "frequency_of_parent", "frequency_of_total"}:
        stat["parameter_id"] = "FL1-A"
      stats.append(stat)
    stats.append({
      "id": "stat_percentile",
      "name": "P25",
      "population_id": "live",
      "parameter_id": "FL1-A",
      "metric": "percentile",
      "source_stage": "compensated",
      "settings": {"q": 25},
    })
    manifest = self._minimal_manifest(statistics=stats)
    validate_manifest(manifest)

  def test_duplicate_statistic_id_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1", "name": "A", "population_id": "live",
        "metric": "count", "source_stage": "compensated",
      },
      {
        "id": "stat1", "name": "B", "population_id": "live",
        "metric": "mean", "source_stage": "compensated",
      },
    ])
    with pytest.raises(ManifestValidationError, match="duplicate statistic ID"):
      validate_manifest(manifest)

  def test_invalid_metric_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1", "name": "A", "population_id": "live",
        "metric": "invalid_metric", "source_stage": "compensated",
      },
    ])
    with pytest.raises(ManifestValidationError, match="invalid metric"):
      validate_manifest(manifest)

  def test_invalid_source_stage_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1", "name": "A", "population_id": "live",
        "metric": "count", "source_stage": "invalid",
      },
    ])
    with pytest.raises(ManifestValidationError, match="invalid source_stage"):
      validate_manifest(manifest)

  def test_empty_population_id_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1", "name": "A", "population_id": "",
        "metric": "count", "source_stage": "compensated",
      },
    ])
    with pytest.raises(ManifestValidationError, match="population_id must be a non-empty string"):
      validate_manifest(manifest)

  def test_percentile_missing_q_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
          "id": "stat1", "name": "A", "population_id": "live",
          "parameter_id": "FL1-A",
          "metric": "percentile", "source_stage": "compensated",
      },
    ])
    with pytest.raises(ManifestValidationError, match="percentile metric requires"):
      validate_manifest(manifest)

  def test_percentile_q_out_of_range_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
          "id": "stat1", "name": "A", "population_id": "live",
          "parameter_id": "FL1-A",
          "metric": "percentile", "source_stage": "compensated",
        "settings": {"q": 101},
      },
    ])
    with pytest.raises(ManifestValidationError, match="percentile 'q' must be in"):
      validate_manifest(manifest)

  def test_percentile_q_negative_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
          "id": "stat1", "name": "A", "population_id": "live",
          "parameter_id": "FL1-A",
          "metric": "percentile", "source_stage": "compensated",
        "settings": {"q": -5},
      },
    ])
    with pytest.raises(ManifestValidationError, match="percentile 'q' must be in"):
      validate_manifest(manifest)

  def test_percentile_q_infinite_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
          "id": "stat1", "name": "A", "population_id": "live",
          "parameter_id": "FL1-A",
          "metric": "percentile", "source_stage": "compensated",
        "settings": {"q": float("inf")},
      },
    ])
    with pytest.raises(ManifestValidationError, match="percentile 'q' must be finite"):
      validate_manifest(manifest)

  def test_statistics_not_array_fails(self) -> None:
    manifest = self._minimal_manifest(statistics="not_array")
    with pytest.raises(ManifestValidationError, match="statistics must be an array"):
      validate_manifest(manifest)

  def test_statistics_not_object_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=["not_an_object"])
    with pytest.raises(ManifestValidationError, match="statistics\\[0\\] must be an object"):
      validate_manifest(manifest)

  def test_statistics_empty_array_passes(self) -> None:
    manifest = self._minimal_manifest(statistics=[])
    validate_manifest(manifest)

  def test_statistics_missing_from_manifest_passes(self) -> None:
    manifest = {
      "project_id": "test",
      "project_version": "1.5.0",
      "pipeline_version": "1.0",
      "samples": [],
    }
    validate_manifest(manifest)

  def test_statistics_with_optional_fields(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1",
        "name": "Mean FL1",
        "population_id": "live",
        "parameter_id": "FL1-A",
        "metric": "mean",
        "source_stage": "compensated",
        "settings": {},
        "format": ".3f",
        "notes": "display format for publication",
      },
    ])
    validate_manifest(manifest)

  def test_statistics_null_format(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1",
        "name": "Mean FL1",
        "population_id": "live",
        "parameter_id": "FL1-A",
        "metric": "mean",
        "source_stage": "compensated",
        "format": None,
      },
    ])
    validate_manifest(manifest)

  def test_invalid_value_policy_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1",
        "name": "Mean FL1",
        "population_id": "live",
        "parameter_id": "FL1-A",
        "metric": "mean",
        "source_stage": "compensated",
        "value_policy": "display_bins",
      },
    ])
    with pytest.raises(ManifestValidationError, match="invalid value_policy"):
      validate_manifest(manifest)

  def test_value_metric_without_parameter_id_fails(self) -> None:
    manifest = self._minimal_manifest(statistics=[
      {
        "id": "stat1",
        "name": "Mean FL1",
        "population_id": "live",
        "metric": "mean",
        "source_stage": "compensated",
      },
    ])
    with pytest.raises(ManifestValidationError, match="requires parameter_id"):
      validate_manifest(manifest)
