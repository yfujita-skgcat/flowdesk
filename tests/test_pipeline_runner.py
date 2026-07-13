"""Tests for the pipeline runner."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.models import ChannelSpec, GateSpec, GatingStrategySpec
from flowdesk_core.pipeline_runner import (
  PipelineError,
  PipelineRunner,
  run_project_pipeline,
)
from flowdesk_core.sample import SampleData
from flowdesk_core.statistics import population_results_to_export_records

# ---------------------------------------------------------------------------
# Helper: minimal project fixture
# ---------------------------------------------------------------------------

def _make_project(
  *,
  project_id: str = "test_project",
  pipeline_version: str = "0.1",
  execution_profiles: list[dict] | None = None,
  samples: list[dict] | None = None,
  compensation_matrices: list[dict] | None = None,
  derived_parameters: list[dict] | None = None,
  transforms: list[dict] | None = None,
  gating_strategies_data: dict[str, object] | None = None,
  population_results: list[dict] | None = None,
  default_compensation_matrix_id: str | None = None,
) -> dict:
  return {
    "project_id": project_id,
    "pipeline_version": pipeline_version,
    "execution_profiles": execution_profiles or [
      {"id": "default", "name": "Default", "gating_strategy_id": None}
    ],
    "samples": samples or [],
    "compensation_matrices": compensation_matrices or [],
    "derived_parameters": derived_parameters or [],
    "transforms": transforms or [],
    "gating_strategies_data": gating_strategies_data or {},
    "population_results": population_results or [],
    "default_compensation_matrix_id": default_compensation_matrix_id,
  }


def _make_event_data(
  n_events: int = 100,
  channels: list[str] | None = None,
) -> tuple[dict[str, np.ndarray], list[str]]:
  """Create synthetic event data."""
  if channels is None:
    channels = ["FSC-H", "SSC-H", "FL1-A", "FL2-A"]
  data = np.random.rand(n_events, len(channels)).astype(np.float64) * 1000.0
  return {
    "s1": data,
  }, channels


# ---------------------------------------------------------------------------
# Existing test (must still pass)
# ---------------------------------------------------------------------------

def test_project_object_can_call_pipeline_runner() -> None:
  project = {
    "project_id": "example",
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default analysis"}],
    "population_results": [
      {
        "sample_id": "s1",
        "population_id": "all_events",
        "event_count": 10,
        "frequency_of_parent": None,
        "frequency_of_total": 1.0,
      }
    ],
  }

  report = run_project_pipeline(project, execution_profile_id="default")

  assert report.execution_profile_id == "default"
  assert report.population_results[0].event_count == 10


# ---------------------------------------------------------------------------
# Execution profile resolution
# ---------------------------------------------------------------------------

def test_unknown_execution_profile_raises() -> None:
  project = _make_project(
    execution_profiles=[{"id": "default", "name": "Default"}]
  )
  with pytest.raises(PipelineError, match="unknown execution profile"):
    run_project_pipeline(project, execution_profile_id="nonexistent")


def test_unknown_profile_shows_available() -> None:
  project = _make_project(
    execution_profiles=[
      {"id": "default", "name": "Default"},
      {"id": "quick", "name": "Quick"},
    ]
  )
  with pytest.raises(PipelineError, match="nonexistent") as exc_info:
    run_project_pipeline(project, execution_profile_id="nonexistent")
  assert "default" in str(exc_info.value)


def test_pipeline_error_is_flowdesk_error() -> None:
  assert issubclass(PipelineError, FlowdeskError)


# ---------------------------------------------------------------------------
# Full pipeline with synthetic events
# ---------------------------------------------------------------------------

def test_full_pipeline_basic() -> None:
  event_data, channels = _make_event_data(n_events=50)
  project = _make_project(
    samples=[{"id": "s1", "name": "Sample 1", "path": "/tmp/s1.fcs"}],
  )

  report = run_project_pipeline(
    project,
    execution_profile_id="default",
    event_data=event_data,
    channel_names=channels,
  )

  assert report.status == "success"
  assert len(report.population_results) >= 1
  assert report.project_id == "test_project"
  assert report.pipeline_version == "0.1"


def test_full_pipeline_population_count() -> None:
  event_data, channels = _make_event_data(n_events=200)
  project = _make_project(
    samples=[{"id": "s1", "name": "Sample 1"}],
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  root = report.population_results[0]
  assert root.event_count == 200
  assert root.frequency_of_total == 1.0


def test_full_pipeline_no_data() -> None:
  project = _make_project()
  report = run_project_pipeline(project)
  assert report.status == "placeholder_complete"


def test_full_pipeline_missing_sample_data() -> None:
  project = _make_project(
    samples=[{"id": "s1", "name": "Sample 1"}, {"id": "s2", "name": "Sample 2"}],
  )
  # Only provide data for s1.
  data_s1 = np.random.rand(50, 2).astype(np.float64)
  report = run_project_pipeline(
    project,
    event_data={"s1": data_s1},
    channel_names=["A", "B"],
  )
  assert "warning: no event data for sample 's2'" in " ".join(report.messages)


# ---------------------------------------------------------------------------
# Compensation step
# ---------------------------------------------------------------------------

def test_pipeline_with_compensation() -> None:
  event_data, channels = _make_event_data(n_events=30)
  # Identity compensation matrix (2 channels).
  project = _make_project(
    samples=[{"id": "s1"}],
    compensation_matrices=[
      {
        "id": "comp1",
        "name": "Identity",
        "source": "user_defined",
        "channels": ("FL1-A", "FL2-A"),
        "matrix": ((1.0, 0.0), (0.0, 1.0)),
      }
    ],
    default_compensation_matrix_id="comp1",
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  assert report.status == "success"
  assert "compensation=done" in " ".join(report.messages)


# ---------------------------------------------------------------------------
# Derived parameters step
# ---------------------------------------------------------------------------

def test_pipeline_with_derived_parameters() -> None:
  event_data, channels = _make_event_data(n_events=20)
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[
      {
        "id": "ratio",
        "name": "FL1_over_FL2",
        "expression": "FL1-A / FL2-A",
        "source_stage": "compensated",
        "input_parameters": ["FL1-A", "FL2-A"],
      }
    ],
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  assert report.status == "success"
  assert "derived_params=done" in " ".join(report.messages)


def test_derived_failure_policy_fail_run_stops_pipeline(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  def failing_evaluator(*_args, **_kwargs):
    raise TypeError("synthetic vector evaluation failure")

  monkeypatch.setattr(
    "flowdesk_core.pipeline_runner.evaluate_array_expression",
    failing_evaluator,
  )
  sample = SampleData(
    "s1",
    np.ones((3, 1), dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "ratio",
      "name": "Ratio",
      "expression": "signal",
      "invalid_value_policy": "fail_run",
    }],
  )

  with pytest.raises(
    PipelineError, match="derived_parameter_evaluation_failed"
  ):
    PipelineRunner(project).run_samples(ExecutionContext(), (sample,))


def test_derived_failure_policy_fail_sample_continues_other_samples(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  from flowdesk_core.derived_parameters import ExpressionError

  def sample_specific_evaluator(_expression, variables, **_kwargs):
    if "other" in variables:
      raise ExpressionError("synthetic sample-specific failure")
    return np.full(len(variables["signal"]), 2.0, dtype=np.float64)

  monkeypatch.setattr(
    "flowdesk_core.pipeline_runner.evaluate_array_expression",
    sample_specific_evaluator,
  )
  valid = SampleData(
    "valid",
    np.array([[2.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  invalid = SampleData(
    "invalid",
    np.array([[3.0]], dtype=np.float64),
    (ChannelSpec(id="other", name="Other"),),
  )
  project = _make_project(
    samples=[{"id": "valid"}, {"id": "invalid"}],
    derived_parameters=[{
      "id": "copy",
      "name": "Copy",
      "expression": "signal",
      "invalid_value_policy": "fail_sample",
    }],
  )

  report = PipelineRunner(project).run_samples(
    ExecutionContext(), (valid, invalid)
  )

  assert report.status == "partial_success"
  assert {result.sample_id for result in report.population_results} == {"valid"}
  assert len(report.diagnostics) == 1
  diagnostic = report.diagnostics[0]
  assert diagnostic.code == "derived_parameter_evaluation_failed"
  assert diagnostic.sample_id == "invalid"
  assert diagnostic.parameter_id == "copy"
  assert diagnostic.severity == "error"
  assert diagnostic.details["policy"] == "fail_sample"


def test_derived_failure_policy_emit_nan_records_full_diagnostic(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  def failing_evaluator(*_args, **_kwargs):
    raise TypeError("synthetic vector evaluation failure")

  monkeypatch.setattr(
    "flowdesk_core.pipeline_runner.evaluate_array_expression",
    failing_evaluator,
  )
  sample = SampleData(
    "s1",
    np.ones((4, 1), dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "ratio",
      "name": "Ratio",
      "expression": "signal",
      "invalid_value_policy": "emit_nan_with_warning",
    }],
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  assert report.status == "success"
  assert len(report.diagnostics) == 1
  diagnostic = report.diagnostics[0]
  assert diagnostic.code == "derived_parameter_evaluation_failed"
  assert diagnostic.sample_id == "s1"
  assert diagnostic.parameter_id == "ratio"
  assert diagnostic.exception_type == "TypeError"
  assert diagnostic.affected_event_count == 4
  assert diagnostic.details == {
    "expression": "signal",
    "policy": "emit_nan_with_warning",
  }


def test_unknown_derived_input_is_rejected_before_failure_policy() -> None:
  sample = SampleData(
    "s1",
    np.ones((2, 1), dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "ratio",
      "name": "Ratio",
      "expression": "missing / signal",
      "invalid_value_policy": "emit_nan_with_warning",
    }],
  )

  with pytest.raises(PipelineError, match="unknown_derived_input"):
    PipelineRunner(project).run_samples(ExecutionContext(), (sample,))


def test_dependency_cycle_is_rejected_before_sample_processing(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  sample = SampleData(
    "s1",
    np.ones((1, 1), dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[
      {"id": "first", "name": "First", "expression": "second + 1"},
      {"id": "second", "name": "Second", "expression": "first + 1"},
    ],
  )
  monkeypatch.setattr(
    PipelineRunner,
    "_step_compensation",
    lambda *_args: pytest.fail("sample processing started before graph validation"),
  )

  with pytest.raises(PipelineError, match="derived_dependency_cycle"):
    PipelineRunner(project).run_samples(ExecutionContext(), (sample,))


def test_runner_evaluates_dependent_definitions_in_topological_order(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  evaluation_order: list[str] = []

  def vector_evaluator(expression, variables, **_kwargs):
    evaluation_order.append(expression)
    if expression == "signal + 1":
      return variables["signal"] + 1
    return variables["first"] + 1

  monkeypatch.setattr(
    "flowdesk_core.pipeline_runner.evaluate_array_expression", vector_evaluator
  )
  sample = SampleData(
    "s1",
    np.array([[1.0], [2.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  strategy = GatingStrategySpec(
    id="derived_chain",
    name="Derived chain",
    gates=(GateSpec(
      id="high_second",
      name="High second",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter="second",
      thresholds={"min": 3.5},
    ),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[
      {"id": "second", "name": "Second", "expression": "first + 1"},
      {"id": "first", "name": "First", "expression": "signal + 1"},
    ],
    execution_profiles=[
      {"id": "default", "gating_strategy_id": strategy.id}
    ],
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  assert evaluation_order == ["signal + 1", "first + 1"]
  count = next(
    result.event_count
    for result in report.population_results
    if result.population_id == "high_second"
  )
  assert count == 1


# ---------------------------------------------------------------------------
# Transforms step
# ---------------------------------------------------------------------------

def test_pipeline_with_transforms() -> None:
  event_data, channels = _make_event_data(n_events=20)
  project = _make_project(
    samples=[{"id": "s1"}],
    transforms=[
      {
        "id": "log_fl1",
        "name": "Log FL1-A",
        "transform_type": "log",
        "parameter": "FL1-A",
        "settings": {"base": 10, "invalid_value_policy": "to_nan"},
      }
    ],
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  assert report.status == "success"
  assert "transforms=done" in " ".join(report.messages)


# ---------------------------------------------------------------------------
# Gating step
# ---------------------------------------------------------------------------

def test_pipeline_with_gating_strategy() -> None:
  from flowdesk_core.models import GateSpec, GatingStrategySpec

  event_data, channels = _make_event_data(n_events=100)
  strategy = GatingStrategySpec(
    id="test_gating",
    name="Test Gating",
    gates=(
      GateSpec(
        id="live_gate",
        name="Live cells",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="FSC-H",
        y_parameter="SSC-H",
        thresholds={"x_min": 0.0, "x_max": 500.0, "y_min": 0.0, "y_max": 500.0},
      ),
    ),
  )

  project = _make_project(
    samples=[{"id": "s1"}],
    execution_profiles=[
      {
        "id": "default",
        "name": "Default",
        "gating_strategy_id": "test_gating",
      }
    ],
    gating_strategies_data={"test_gating": strategy},
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  assert report.status == "success"
  assert len(report.population_results) >= 2  # root + live_gate


# ---------------------------------------------------------------------------
# Sample selector
# ---------------------------------------------------------------------------

def test_sample_selector_all() -> None:
  event_data, channels = _make_event_data(n_events=50)
  project = _make_project(
    samples=[{"id": "s1"}],
    execution_profiles=[
      {"id": "default", "name": "Default", "sample_selector": "all"}
    ],
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )
  assert report.status == "success"


def test_sample_selector_specific() -> None:
  data_s1 = np.random.rand(30, 3).astype(np.float64)
  data_s2 = np.random.rand(40, 3).astype(np.float64)
  project = _make_project(
    samples=[{"id": "s1"}, {"id": "s2"}],
    execution_profiles=[
      {"id": "default", "name": "Default", "sample_selector": "s1"}
    ],
  )

  report = run_project_pipeline(
    project,
    event_data={"s1": data_s1, "s2": data_s2},
    channel_names=["A", "B", "C"],
  )
  # Only s1 should be processed.
  sample_ids = {r.sample_id for r in report.population_results}
  assert sample_ids == {"s1"}


# ---------------------------------------------------------------------------
# Execution report content
# ---------------------------------------------------------------------------

def test_report_has_pipeline_version() -> None:
  event_data, channels = _make_event_data(n_events=10)
  project = _make_project(pipeline_version="0.2")

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )
  assert report.pipeline_version == "0.2"


def test_report_has_profile_id() -> None:
  event_data, channels = _make_event_data(n_events=10)
  project = _make_project(
    execution_profiles=[
      {"id": "quick", "name": "Quick profile"}
    ],
  )

  report = run_project_pipeline(
    project,
    execution_profile_id="quick",
    event_data=event_data,
    channel_names=channels,
  )
  assert report.execution_profile_id == "quick"


def test_report_summary() -> None:
  event_data, channels = _make_event_data(n_events=10)
  project = _make_project(samples=[{"id": "s1"}])

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )
  assert "test_project" in report.summary
  assert "success" in report.summary


def test_report_input_files_recorded() -> None:
  event_data, channels = _make_event_data(n_events=10)
  project = _make_project(
    samples=[{"id": "s1", "name": "Sample 1", "path": "/tmp/nonexistent.fcs"}],
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )
  assert len(report.input_files) >= 1
  assert report.input_files[0]["sample_id"] == "s1"


# ---------------------------------------------------------------------------
# Export records from pipeline results
# ---------------------------------------------------------------------------

def test_export_records_from_pipeline() -> None:
  event_data, channels = _make_event_data(n_events=100)
  project = _make_project(samples=[{"id": "s1"}])

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  records = population_results_to_export_records(
    list(report.population_results)
  )
  assert len(records) >= 3  # at least root population x 3 metrics


# ---------------------------------------------------------------------------
# Phase 2: PopulationMembership in ExecutionReport
# ---------------------------------------------------------------------------


def test_pipeline_membership_present_in_report() -> None:
  """ExecutionReport contains population_membership when event data is supplied."""
  event_data, channels = _make_event_data(n_events=50)
  project = _make_project(samples=[{"id": "s1"}])

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  assert len(report.population_membership) >= 1
  # Root membership for s1
  root_mem = report.population_membership[0]
  assert root_mem.sample_id == "s1"
  assert root_mem.population_id == "all_events"
  assert root_mem.event_count == 50
  assert root_mem.mask.shape == (50,)
  assert root_mem.mask.dtype == np.bool_
  assert root_mem.mask.all()


def test_pipeline_membership_masks_are_readonly() -> None:
  """Membership masks in ExecutionReport are read-only."""
  event_data, channels = _make_event_data(n_events=30)
  project = _make_project(samples=[{"id": "s1"}])

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  for mem in report.population_membership:
    assert not mem.mask.flags["WRITEABLE"]
    with pytest.raises(ValueError, match="read-only"):
      mem.mask[0] = False


def test_pipeline_membership_event_count_consistency() -> None:
  """PopulationResult.event_count matches PopulationMembership.mask.sum()."""
  event_data, channels = _make_event_data(n_events=100)
  project = _make_project(samples=[{"id": "s1"}])

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  for result in report.population_results:
    matching_memberships = [
      m for m in report.population_membership
      if m.sample_id == result.sample_id
      and m.population_id == result.population_id
    ]
    assert len(matching_memberships) == 1
    assert result.event_count == matching_memberships[0].event_count
    assert result.event_count == int(matching_memberships[0].mask.sum())


def test_pipeline_membership_multiple_samples_no_mixing() -> None:
  """Membership masks for different samples do not mix sample IDs."""
  data_s1 = np.random.rand(30, 3).astype(np.float64)
  data_s2 = np.random.rand(40, 3).astype(np.float64)
  project = _make_project(
    samples=[{"id": "s1"}, {"id": "s2"}],
  )

  report = run_project_pipeline(
    project,
    event_data={"s1": data_s1, "s2": data_s2},
    channel_names=["A", "B", "C"],
  )

  s1_memberships = [m for m in report.population_membership if m.sample_id == "s1"]
  s2_memberships = [m for m in report.population_membership if m.sample_id == "s2"]

  assert len(s1_memberships) >= 1
  assert len(s2_memberships) >= 1

  # s1 root mask length matches s1 event count
  assert s1_memberships[0].mask.shape[0] == 30
  assert s2_memberships[0].mask.shape[0] == 40

  # No s1 membership has s2 sample_id and vice versa
  for m in s1_memberships:
    assert m.sample_id == "s1"
  for m in s2_memberships:
    assert m.sample_id == "s2"


def test_pipeline_membership_with_gating_strategy() -> None:
  """Membership masks are produced when a gating strategy is configured."""
  from flowdesk_core.models import GateSpec, GatingStrategySpec

  event_data, channels = _make_event_data(n_events=100)
  strategy = GatingStrategySpec(
    id="test_gating",
    name="Test Gating",
    gates=(
      GateSpec(
        id="live_gate",
        name="Live cells",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="FSC-H",
        y_parameter="SSC-H",
        thresholds={
          "x_min": 0.0, "x_max": 500.0,
          "y_min": 0.0, "y_max": 500.0,
        },
      ),
    ),
  )

  project = _make_project(
    samples=[{"id": "s1"}],
    execution_profiles=[
      {
        "id": "default",
        "name": "Default",
        "gating_strategy_id": "test_gating",
      }
    ],
    gating_strategies_data={"test_gating": strategy},
  )

  report = run_project_pipeline(
    project,
    event_data=event_data,
    channel_names=channels,
  )

  # Should have root + live_gate membership
  pop_ids = {m.population_id for m in report.population_membership}
  assert "all_events" in pop_ids
  assert "live_gate" in pop_ids

  # Verify consistency: event_count from result matches membership
  live_result = next(
      r for r in report.population_results
      if r.population_id == "live_gate"
  )
  live_membership = next(
      m for m in report.population_membership
      if m.population_id == "live_gate"
  )
  assert live_result.event_count == live_membership.event_count


def test_pipeline_membership_placeholder_mode_empty() -> None:
  """Placeholder mode (no event data) produces empty membership."""
  project = _make_project()
  report = run_project_pipeline(project)
  assert len(report.population_membership) == 0


# ---------------------------------------------------------------------------
# Sample-specific stable channel identity API
# ---------------------------------------------------------------------------


def test_run_samples_gate_count_is_stable_across_channel_permutation() -> None:
  fsc = ChannelSpec(id="fsc_area", name="FSC-A")
  cd3 = ChannelSpec(id="cd3_area", name="B530-A", short_name="CD3")
  canonical_events = np.array(
    [[1.0, 15.0], [2.0, 25.0], [9.0, 15.0], [1.0, 40.0]],
    dtype=np.float64,
  )
  first = SampleData("s1", canonical_events, (fsc, cd3))
  second = SampleData("s2", canonical_events[:, [1, 0]], (cd3, fsc))
  original_first = first.events.tobytes()
  original_second = second.events.tobytes()
  strategy = GatingStrategySpec(
    id="stable_identity",
    name="Stable identity",
    gates=(
      GateSpec(
        id="cd3_positive",
        name="CD3 positive",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="fsc_area",
        y_parameter="cd3_area",
        thresholds={
          "x_min": 0.0,
          "x_max": 5.0,
          "y_min": 10.0,
          "y_max": 30.0,
        },
      ),
    ),
  )
  project = _make_project(
    samples=[{"id": "s1"}, {"id": "s2"}],
    execution_profiles=[
      {
        "id": "default",
        "sample_selector": "all",
        "gating_strategy_id": strategy.id,
      }
    ],
    compensation_matrices=[
      {
        "id": "identity_compensation",
        "name": "Identity compensation",
        "source": "user_defined",
        "channels": ("fsc_area", "cd3_area"),
        "matrix": ((1.0, 0.0), (0.0, 1.0)),
      }
    ],
    default_compensation_matrix_id="identity_compensation",
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(
    ExecutionContext(execution_profile_id="default"),
    (first, second),
  )

  counts = {
    result.sample_id: result.event_count
    for result in report.population_results
    if result.population_id == "cd3_positive"
  }
  masks = {
    membership.sample_id: membership.mask
    for membership in report.population_membership
    if membership.population_id == "cd3_positive"
  }
  assert counts == {"s1": 2, "s2": 2}
  np.testing.assert_array_equal(masks["s1"], masks["s2"])
  assert first.events.tobytes() == original_first
  assert second.events.tobytes() == original_second


def test_run_samples_passes_derived_channel_identity_to_gating() -> None:
  source_events = np.array([[2.0, 1.0]], dtype=np.float64)
  source_before = source_events.copy()
  sample = SampleData(
    "s1",
    source_events,
    (
      ChannelSpec(id="signal", name="Signal-A"),
      ChannelSpec(id="denominator", name="Reference-A"),
    ),
  )
  strategy = GatingStrategySpec(
    id="derived_gate_strategy",
    name="Derived gate strategy",
    gates=(
      GateSpec(
        id="ratio_near_two",
        name="Ratio near two",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="ratio",
        y_parameter="denominator",
        thresholds={
          "x_min": 3.5,
          "x_max": 4.5,
          "y_min": 0.0,
          "y_max": 10.0,
        },
      ),
    ),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[
          {
            "id": "ratio",
            "name": "Signal ratio",
            "expression": "signal / denominator",
            "input_parameters": ["signal", "denominator"],
      }
    ],
    transforms=[
      {
        "id": "scale_ratio",
        "name": "Scale ratio",
        "transform_type": "linear",
        "parameter": "ratio",
        "settings": {"scale": 2.0, "offset": 0.0},
      }
    ],
    execution_profiles=[
      {"id": "default", "gating_strategy_id": strategy.id}
    ],
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(
    ExecutionContext(execution_profile_id="default"),
    (sample,),
  )

  result = next(
    result
    for result in report.population_results
    if result.population_id == "ratio_near_two"
  )
  assert result.event_count == 1
  np.testing.assert_array_equal(source_events, source_before)
  np.testing.assert_array_equal(sample.events, source_before)
