"""Tests for the Qt-independent B3.3 result overlay state."""

from __future__ import annotations

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_core.preview import PreviewReport
from flowdesk_qt.results_state import (
  ResultRowKey,
  RuntimeResultState,
)


def _report(*results: PopulationResult) -> ExecutionReport:
  return ExecutionReport(
    project_id="project",
    execution_profile_id="default",
    pipeline_version="test",
    status="success",
    population_results=results,
  )


def _preview(
  revision: int,
  *results: PopulationResult,
  statistics: tuple[StatisticResult, ...] = (),
) -> PreviewReport:
  return PreviewReport(
    revision=revision,
    project_id="project",
    execution_profile_id="default",
    sample_id="sample-1",
    strategy_id="strategy",
    required_population_id="child",
    source_event_count=10,
    status="success",
    population_results=results,
    statistic_results=statistics,
  )


def _state() -> RuntimeResultState:
  return RuntimeResultState(
    _report(
      PopulationResult("sample-1", "all_events", 10, None, 1.0),
      PopulationResult("sample-1", "parent", 6, 0.6, 0.6),
      PopulationResult("sample-1", "child", 3, 0.5, 0.3),
      PopulationResult("sample-1", "sibling", 2, 0.3333, 0.2),
      PopulationResult("sample-2", "all_events", 8, None, 1.0),
      PopulationResult("sample-2", "parent", 4, 0.5, 0.5),
      PopulationResult("sample-2", "child", 2, 0.5, 0.25),
      PopulationResult("sample-2", "sibling", 1, 0.25, 0.125),
    ),
    authoritative_revision=1,
    sample_ids=("sample-1", "sample-2"),
    population_ids=("all_events", "parent", "child", "sibling"),
    statistic_definitions=(("child-mean", "child"),),
  )


def test_gate_invalidation_retains_values_and_marks_active_and_other_samples() -> None:
  state = _state()

  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("parent", "child"),
  )

  active_child = state.row(ResultRowKey.population("sample-1", "child"))
  other_child = state.row(ResultRowKey.population("sample-2", "child"))
  sibling = state.row(ResultRowKey.population("sample-1", "sibling"))
  assert active_child.result.event_count == 3
  assert active_child.freshness == "recalculating"
  assert active_child.revision == 1
  assert other_child.result.event_count == 2
  assert other_child.freshness == "stale"
  assert sibling.freshness == "current"
  assert state.batch_stale


def test_invalidation_marks_statistics_by_affected_population() -> None:
  state = _state()
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("child",),
  )

  active_stat = state.row(ResultRowKey.statistic("sample-1", "child-mean"))
  other_stat = state.row(ResultRowKey.statistic("sample-2", "child-mean"))
  assert active_stat.freshness == "recalculating"
  assert other_stat.freshness == "stale"


def test_same_revision_preview_is_atomic_and_does_not_change_baseline() -> None:
  state = _state()
  baseline = state.authoritative_report
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("parent", "child"),
  )
  accepted = state.accept_preview(
    _preview(
      2,
      PopulationResult("sample-1", "all_events", 10, None, 1.0),
      PopulationResult("sample-1", "parent", 5, 0.5, 0.5),
      PopulationResult("sample-1", "child", 1, 0.2, 0.1),
    )
  )

  assert accepted
  assert state.authoritative_report is baseline
  assert state.row(ResultRowKey.population("sample-1", "parent")).result.event_count == 5
  child = state.row(ResultRowKey.population("sample-1", "child"))
  assert child.result.event_count == 1
  assert child.revision == 2
  assert child.source == "active_sample_preview"
  assert child.freshness == "current"
  assert state.row(ResultRowKey.population("sample-2", "child")).freshness == "stale"


def test_obsolete_preview_changes_no_row() -> None:
  state = _state()
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("child",),
  )
  before = state.row(ResultRowKey.population("sample-1", "child"))

  assert not state.accept_preview(
    _preview(
      1,
      PopulationResult("sample-1", "child", 0, 0.0, 0.0),
    )
  )
  after = state.row(ResultRowKey.population("sample-1", "child"))
  assert after == before


def test_new_population_has_no_fabricated_old_value() -> None:
  state = RuntimeResultState(
    _report(PopulationResult("sample-1", "all_events", 10, None, 1.0)),
    authoritative_revision=1,
    sample_ids=("sample-1",),
    population_ids=("all_events", "new-gate"),
  )
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("new-gate",),
  )
  row = state.row(ResultRowKey.population("sample-1", "new-gate"))
  assert row.result is None
  assert row.freshness == "recalculating"


def test_preview_statistic_overlay_is_current_without_changing_batch_baseline() -> None:
  state = _state()
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("child",),
  )
  state.accept_preview(
    _preview(
      2,
      PopulationResult("sample-1", "child", 1, 1.0, 0.1),
      statistics=(
        StatisticResult(
          "sample-1", "child-mean", "child", "mean", 12.5,
        ),
      ),
    )
  )
  row = state.row(ResultRowKey.statistic("sample-1", "child-mean"))
  assert row.result.value == 12.5
  assert row.freshness == "current"
  assert row.source == "active_sample_preview"
  assert state.authoritative_report.statistic_results == ()


def test_multi_population_statistic_keys_do_not_collide() -> None:
  report = ExecutionReport(
    project_id="project",
    execution_profile_id="default",
    pipeline_version="test",
    status="success",
    population_results=(
      PopulationResult("sample-1", "all_events", 10, None, 1.0),
      PopulationResult("sample-1", "child", 4, 0.4, 0.4),
    ),
    statistic_results=(
      StatisticResult("sample-1", "mean-fl1", "all_events", "mean", 10.0),
      StatisticResult("sample-1", "mean-fl1", "child", "mean", 20.0),
    ),
  )
  state = RuntimeResultState(
    report,
    authoritative_revision=1,
    sample_ids=("sample-1",),
    population_ids=("all_events", "child"),
    statistic_definitions=(
      ("mean-fl1", "all_events"),
      ("mean-fl1", "child"),
    ),
  )

  all_events = state.row(
    ResultRowKey.statistic("sample-1", "mean-fl1", "all_events")
  )
  child = state.row(
    ResultRowKey.statistic("sample-1", "mean-fl1", "child")
  )
  assert all_events.result.value == 10.0
  assert child.result.value == 20.0
  assert len([row for row in state.rows() if row.key.kind == "statistic"]) == 2


def test_disabled_statistic_row_is_distinct_from_missing() -> None:
  state = RuntimeResultState(
    _report(PopulationResult("sample-1", "all_events", 10, None, 1.0)),
    authoritative_revision=1,
    sample_ids=("sample-1",),
    population_ids=("all_events",),
    statistic_definitions=(("disabled-mean", "all_events", False),),
  )
  row = state.row(
    ResultRowKey.statistic("sample-1", "disabled-mean", "all_events")
  )
  assert row.result is None
  assert row.freshness == "disabled"
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("all_events",),
  )
  assert state.row(
    ResultRowKey.statistic("sample-1", "disabled-mean", "all_events")
  ).freshness == "disabled"
