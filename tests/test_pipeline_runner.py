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
  compensation_bindings: list[dict] | None = None,
  compensation_calculations: list[dict] | None = None,
  derived_parameters: list[dict] | None = None,
  transforms: list[dict] | None = None,
  gating_strategies_data: dict[str, object] | None = None,
  population_results: list[dict] | None = None,
  default_compensation_matrix_id: str | None = None,
  statistics: list[dict] | None = None,
) -> dict:
  return {
    "project_id": project_id,
    "pipeline_version": pipeline_version,
    "execution_profiles": execution_profiles or [
      {"id": "default", "name": "Default", "gating_strategy_id": None}
    ],
    "samples": samples or [],
    "compensation_matrices": compensation_matrices or [],
    "compensation_bindings": compensation_bindings or [],
    "compensation_calculations": compensation_calculations or [],
    "derived_parameters": derived_parameters or [],
    "transforms": transforms or [],
    "gating_strategies_data": gating_strategies_data or {},
    "statistics": statistics or [],
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


def test_two_samples_use_different_bound_compensation_matrices() -> None:
  channels = (
    ChannelSpec(id="signal", name="Signal", detector="D1"),
    ChannelSpec(id="reference", name="Reference", detector="D2"),
  )
  raw = np.array([[15.0, 10.0]], dtype=np.float64)
  first = SampleData("s1", raw, channels)
  second = SampleData("s2", raw, channels)
  strategy = GatingStrategySpec(
    id="compensated_gate",
    name="Compensated gate",
    gates=(GateSpec(
      id="signal_15",
      name="Signal near 15",
      gate_type="range",
      x_parameter="signal",
      thresholds={"min": 14.0, "max": 16.0},
    ),),
  )
  project = _make_project(
    samples=[{"id": "s1"}, {"id": "s2"}],
    execution_profiles=[{
      "id": "default",
      "sample_selector": "all",
      "gating_strategy_id": strategy.id,
    }],
    compensation_matrices=[
      {
        "id": "identity",
        "name": "Identity",
        "source": "user_defined",
        "channels": ("signal", "reference"),
        "matrix": ((1.0, 0.0), (0.0, 1.0)),
      },
      {
        "id": "spill",
        "name": "Spill",
        "source": "user_defined",
        "channels": ("signal", "reference"),
        "matrix": ((1.0, 0.5), (0.0, 1.0)),
      },
    ],
    compensation_bindings=[
      {"id": "s1-comp", "matrix_id": "identity", "scope": "sample", "target_id": "s1"},
      {"id": "s2-comp", "matrix_id": "spill", "scope": "sample", "target_id": "s2"},
    ],
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (first, second))

  counts = {
    result.sample_id: result.event_count
    for result in report.population_results
    if result.population_id == "signal_15"
  }
  assert counts == {"s1": 1, "s2": 0}
  applied = [
    diagnostic for diagnostic in report.diagnostics
    if diagnostic.code == "compensation_matrix_applied"
  ]
  assert [(value.sample_id, value.details["matrix_id"]) for value in applied] == [
    ("s1", "identity"), ("s2", "spill")
  ]
  assert applied[0].details["binding_id"] == "s1-comp"
  assert applied[0].details["channel_order"] == ["signal", "reference"]
  np.testing.assert_array_equal(first.events, raw)
  np.testing.assert_array_equal(second.events, raw)


def test_condition_warning_is_recorded_with_applied_matrix() -> None:
  sample = SampleData(
    "s1",
    np.array([[1.0, 1e-10]], dtype=np.float64),
    (
      ChannelSpec(id="a", name="A", detector="D1"),
      ChannelSpec(id="b", name="B", detector="D2"),
    ),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    compensation_matrices=[{
      "id": "ill",
      "name": "Ill conditioned",
      "source": "imported",
      "channels": ("a", "b"),
      "matrix": ((1.0, 0.0), (0.0, 1e-10)),
    }],
    default_compensation_matrix_id="ill",
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  diagnostics = {diagnostic.code: diagnostic for diagnostic in report.diagnostics}
  assert diagnostics["compensation_matrix_applied"].details["matrix_id"] == "ill"
  warning = diagnostics["compensation_condition_warning"]
  assert warning.sample_id == "s1"
  assert warning.details["condition_number"] == pytest.approx(1e10)
  assert warning.details["binding_scope"] == "project_default"


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


def test_unknown_derived_input_is_rejected_before_failure_policy(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
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
  monkeypatch.setattr(
    PipelineRunner,
    "_step_compensation",
    lambda *_args: pytest.fail(
      "sample processing started for an unknown derived input"
    ),
  )

  with pytest.raises(PipelineError, match="unknown_derived_input"):
    PipelineRunner(project).run_samples(ExecutionContext(), (sample,))


@pytest.mark.parametrize(
  ("expression", "events", "expected_gate_count"),
  [
    (
      "signal / reference",
      np.array([[2.0, 1.0], [4.0, 0.0], [6.0, 3.0]], dtype=np.float64),
      2,
    ),
    (
      "sqrt(signal)",
      np.array([[-1.0, 1.0], [0.0, 1.0], [4.0, 1.0]], dtype=np.float64),
      1,
    ),
    (
      "signal + 1",
      np.array([[np.nan, 1.0], [np.nan, 2.0], [np.nan, 3.0]], dtype=np.float64),
      0,
    ),
  ],
  ids=("division-by-zero", "function-domain", "all-nan-input"),
)
def test_numeric_invalid_derived_values_are_excluded_from_downstream_gate(
  expression: str,
  events: np.ndarray,
  expected_gate_count: int,
) -> None:
  source_before = events.copy()
  sample = SampleData(
    "s1",
    events,
    (
      ChannelSpec(id="signal", name="Signal"),
      ChannelSpec(id="reference", name="Reference"),
    ),
  )
  strategy = GatingStrategySpec(
    id="numeric_invalid_values",
    name="Numeric invalid values",
    gates=(GateSpec(
      id="finite_result",
      name="Finite result",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter="result",
      thresholds={"min": 1.5, "max": 2.5},
    ),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "result_definition",
      "output_channel_id": "result",
      "name": "Result",
      "expression": expression,
      "invalid_value_policy": "fail_run",
    }],
    execution_profiles=[
      {"id": "default", "gating_strategy_id": strategy.id}
    ],
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  counts = {
    result.population_id: result.event_count
    for result in report.population_results
  }
  assert counts["all_events"] == len(events)
  assert counts["finite_result"] == expected_gate_count
  assert report.diagnostics == ()
  np.testing.assert_array_equal(sample.events, source_before)


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


def test_project_transform_referenced_by_gate_is_applied_exactly_once() -> None:
  strategy = GatingStrategySpec(
    id="single_application",
    name="Single application",
    gates=(GateSpec(
      id="scaled_range",
      name="Scaled range",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter="signal",
      x_transform_id="scale_signal",
      thresholds={"min": 3.5, "max": 4.5},
    ),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    transforms=[{
      "id": "scale_signal",
      "name": "Scale signal",
      "transform_type": "linear",
      "parameter": "signal",
      "settings": {"scale": 2.0, "offset": 0.0},
      "role": "analysis",
    }],
    execution_profiles=[{
      "id": "default",
      "gating_strategy_id": strategy.id,
    }],
    gating_strategies_data={strategy.id: strategy},
  )
  sample = SampleData(
    "s1",
    np.array([[1.0], [2.0], [3.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  result = next(
    item for item in report.population_results
    if item.population_id == "scaled_range"
  )
  assert result.event_count == 1


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


def test_raw_and_compensated_derived_sources_use_explicit_stage_views() -> None:
  source_events = np.array([[15.0, 10.0]], dtype=np.float64)
  sample = SampleData(
    "s1",
    source_events,
    (
      ChannelSpec(id="signal", name="Signal"),
      ChannelSpec(id="reference", name="Reference"),
    ),
  )
  strategy = GatingStrategySpec(
    id="source_views",
    name="Source views",
    gates=(GateSpec(
      id="expected_values",
      name="Expected values",
      gate_type="rectangle",
      parent_population_id="all_events",
      x_parameter="raw_signal",
      y_parameter="compensated_signal",
      thresholds={
        "x_min": 29.0,
        "x_max": 31.0,
        "y_min": 9.0,
        "y_max": 11.0,
      },
    ),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    compensation_matrices=[{
      "id": "spill",
      "name": "Spill",
      "source": "user_defined",
      "channels": ("signal", "reference"),
      "matrix": ((1.0, 0.5), (0.0, 1.0)),
    }],
    default_compensation_matrix_id="spill",
    derived_parameters=[
      {
        "id": "raw_definition",
        "output_channel_id": "raw_signal",
        "name": "Raw signal",
        "expression": "signal",
        "source_stage": "raw",
      },
      {
        "id": "compensated_definition",
        "output_channel_id": "compensated_signal",
        "name": "Compensated signal",
        "expression": "signal",
        "source_stage": "compensated",
      },
    ],
    transforms=[{
      "id": "scale_raw_derived",
      "name": "Scale raw-derived signal",
      "transform_type": "linear",
      "parameter": "raw_signal",
      "settings": {"scale": 2.0, "offset": 0.0},
    }],
    execution_profiles=[
      {"id": "default", "gating_strategy_id": strategy.id}
    ],
    gating_strategies_data={strategy.id: strategy},
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  result = next(
    result
    for result in report.population_results
    if result.population_id == "expected_values"
  )
  assert result.event_count == 1
  np.testing.assert_array_equal(sample.events, source_events)


def test_legacy_transformed_derived_source_is_rejected_before_processing(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  sample = SampleData(
    "s1",
    np.ones((1, 1), dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "legacy",
      "output_channel_id": "legacy_output",
      "name": "Legacy",
      "expression": "signal",
      "source_stage": "transformed",
      "legacy_source_stage_policy": "reject",
    }],
  )
  monkeypatch.setattr(
    PipelineRunner,
    "_step_compensation",
    lambda *_args: pytest.fail("processing started for rejected legacy source"),
  )

  with pytest.raises(PipelineError, match="legacy_transformed_source_rejected"):
    PipelineRunner(project).run_samples(ExecutionContext(), (sample,))


def test_derived_preview_uses_bounded_core_pipeline_and_stable_output_id() -> None:
  sample = SampleData(
    "s1",
    np.array([[2.0, 1.0], [6.0, 3.0], [12.0, 4.0]], dtype=np.float64),
    (
      ChannelSpec(id="signal", name="Signal"),
      ChannelSpec(id="reference", name="Reference"),
    ),
  )
  project = _make_project(
    samples=[{"id": "s1"}],
    derived_parameters=[{
      "id": "ratio_definition",
      "output_channel_id": "ratio",
      "name": "Ratio",
      "expression": "signal / reference",
      "unit": "ratio",
      "source_stage": "raw",
      "input_parameters": ["signal", "reference"],
      "invalid_value_policy": "fail_run",
    }],
  )

  preview = PipelineRunner(project).preview_derived_parameter(
    sample, "ratio", max_events=2
  )

  np.testing.assert_array_equal(preview.values, [2.0, 2.0])
  assert preview.channel.id == "ratio"
  assert preview.channel.unit == "ratio"
  assert preview.source_event_count == 3
  assert preview.preview_event_count == 2
  assert not preview.values.flags.writeable


# ---------------------------------------------------------------------------
# Compensation calculation integration
# ---------------------------------------------------------------------------


def _make_single_stain_events(
  rng: np.random.Generator,
  n_per_pop: int = 500,
  fl1_median: float = 10000.0,
  fl2_median: float = 8000.0,
  spill_fl1_to_fl2: float = 0.2,
  spill_fl2_to_fl1: float = 0.1,
  background: float = 100.0,
) -> np.ndarray:
  """Create synthetic single-stain control events.

  Three contiguous populations in row order:
  FL1-positive, FL2-positive, negative.
  """
  total = n_per_pop * 3
  events = np.zeros((total, 2), dtype=np.float64)

  # FL1-positive.
  idx = 0
  events[idx:idx + n_per_pop, 0] = rng.normal(
    fl1_median, fl1_median * 0.05, n_per_pop,
  )
  events[idx:idx + n_per_pop, 1] = rng.normal(
    background + spill_fl1_to_fl2 * fl1_median,
    background * 0.2,
    n_per_pop,
  )
  idx += n_per_pop

  # FL2-positive.
  events[idx:idx + n_per_pop, 0] = rng.normal(
    background + spill_fl2_to_fl1 * fl2_median,
    background * 0.2,
    n_per_pop,
  )
  events[idx:idx + n_per_pop, 1] = rng.normal(
    fl2_median, fl2_median * 0.05, n_per_pop,
  )
  idx += n_per_pop

  # Negative.
  events[idx:idx + n_per_pop, 0] = rng.normal(
    background, background * 0.1, n_per_pop,
  )
  events[idx:idx + n_per_pop, 1] = rng.normal(
    background, background * 0.1, n_per_pop,
  )

  return events


def _make_control_gating_strategy(
  n_total: int,
  n_per_pop: int,
  fl1_threshold: float,
  fl2_threshold: float,
) -> GatingStrategySpec:
  """Build a gating strategy that separates the three synthetic populations.

  Assumes row order: FL1-positive [0:n), FL2-positive [n:2n), negative [2n:3n).
  Gates use row-index-based ranges that match the synthetic data layout.
  """
  return GatingStrategySpec(
    id="control_gating",
    name="Control gating",
    gates=(
      # FL1-positive: high FL1-A, low FL2-A.
      GateSpec(
        id="pos_FL1",
        name="FL1 positive",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="FL1-A",
        y_parameter="FL2-A",
        thresholds={
          "x_min": fl1_threshold * 0.5,
          "x_max": fl1_threshold * 2.0,
          "y_min": 0.0,
          "y_max": fl2_threshold * 0.3,
        },
      ),
      # FL2-positive: low FL1-A, high FL2-A.
      GateSpec(
        id="pos_FL2",
        name="FL2 positive",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="FL1-A",
        y_parameter="FL2-A",
        thresholds={
          "x_min": 0.0,
          "x_max": fl1_threshold * 0.3,
          "y_min": fl2_threshold * 0.5,
          "y_max": fl2_threshold * 2.0,
        },
      ),
      # Negative: low on both.
      GateSpec(
        id="neg",
        name="Negative",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="FL1-A",
        y_parameter="FL2-A",
        thresholds={
          "x_min": 0.0,
          "x_max": fl1_threshold * 0.3,
          "y_min": 0.0,
          "y_max": fl2_threshold * 0.3,
        },
      ),
    ),
  )


def test_compensation_calculation_integration() -> None:
  """Dynamic compensation matrix is calculated from control sample and applied."""
  rng = np.random.default_rng(42)
  n_per_pop = 500
  fl1_med = 10000.0
  fl2_med = 8000.0

  control_events = _make_single_stain_events(
    rng, n_per_pop=n_per_pop,
    fl1_median=fl1_med, fl2_median=fl2_med,
  )

  strategy = _make_control_gating_strategy(
    n_total=n_per_pop * 3,
    n_per_pop=n_per_pop,
    fl1_threshold=fl1_med,
    fl2_threshold=fl2_med,
  )

  # Main sample data (separate from control).
  main_events = rng.random((50, 2)).astype(np.float64) * 1000

  project = _make_project(
    samples=[
      {"id": "control", "name": "Single-stain control"},
      {"id": "main", "name": "Main sample"},
    ],
    execution_profiles=[{
      "id": "default",
      "name": "Default",
      "gating_strategy_id": strategy.id,
    }],
    compensation_calculations=[{
      "id": "calc1",
      "name": "2-color spillover",
      "controls": [
        {
          "sample_id": "control",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "pos_FL1",
          "negative_population_id": "neg",
        },
        {
          "sample_id": "control",
          "detector_channel_id": "FL2-A",
          "positive_population_id": "pos_FL2",
          "negative_population_id": "neg",
        },
      ],
    }],
    gating_strategies_data={"control_gating": strategy},
  )

  report = run_project_pipeline(
    project,
    execution_profile_id="default",
    event_data={"control": control_events, "main": main_events},
    channel_names=["FL1-A", "FL2-A"],
  )

  assert report.status == "success"
  assert "compensation_calculation=done" in " ".join(report.messages)

  # Verify that a compensation_calculated diagnostic was emitted.
  calc_diagnostics = [
    d for d in report.diagnostics
    if d.code == "compensation_calculated"
  ]
  assert len(calc_diagnostics) >= 1
  assert calc_diagnostics[0].details["calculation_id"] == "calc1"


def test_compensation_calculation_control_sample_missing_stops_pipeline() -> None:
  """A missing explicit control sample must not silently skip calculation."""
  project = _make_project(
    samples=[{"id": "main"}],
    execution_profiles=[{
      "id": "default",
      "name": "Default",
    }],
    compensation_calculations=[{
      "id": "calc1",
      "name": "2-color spillover",
      "controls": [
        {
          "sample_id": "control",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "pos_FL1",
          "negative_population_id": "neg",
        },
      ],
    }],
  )

  rng = np.random.default_rng(42)
  with pytest.raises(PipelineError, match="calculation_control_sample_missing"):
    run_project_pipeline(
      project,
      execution_profile_id="default",
      event_data={"main": rng.random((10, 2)).astype(np.float64)},
      channel_names=["FL1-A", "FL2-A"],
    )


def test_persisted_calculated_matrix_is_used_without_recalculating_controls() -> None:
  """A saved calculated result remains reproducible when controls are absent."""
  project = _make_project(
    samples=[{"id": "main"}],
    execution_profiles=[{
      "id": "default",
      "name": "Default",
      "gating_strategy_id": None,
    }],
    compensation_matrices=[{
      "id": "calculated-calc1",
      "name": "Saved calculated matrix",
      "source": "calculated",
      "channels": ("FL1-A", "FL2-A"),
      "matrix": ((1.0, 0.0), (0.0, 1.0)),
      "provenance": {
        "control_sample_ids": ["control"],
        "control_population_ids": ["control:positive", "control:negative"],
        "algorithm": "traditional_linear_background_subtracted",
        "algorithm_version": "1.0.0",
        "software_version": "1.5.0",
        "manual_edits": [],
      },
    }],
    default_compensation_matrix_id="calculated-calc1",
    compensation_calculations=[{
      "id": "calc1",
      "name": "Unavailable controls must not trigger recalculation",
      "controls": [{
        "sample_id": "control",
        "detector_channel_id": "FL1-A",
        "positive_population_id": "positive",
        "negative_population_id": "negative",
      }],
    }],
  )

  report = run_project_pipeline(
    project,
    execution_profile_id="default",
    event_data={"main": np.array([[100.0, 50.0]], dtype=np.float64)},
    channel_names=["FL1-A", "FL2-A"],
  )

  assert report.status == "success"
  assert not any(
    diagnostic.code == "compensation_calculated"
    for diagnostic in report.diagnostics
  )


def test_compensation_calculation_identical_positive_negative_is_rejected() -> None:
  """An all-events positive/negative pair is not a valid control."""
  rng = np.random.default_rng(42)
  control_events = rng.random((50, 2)).astype(np.float64) * 1000
  main_events = rng.random((20, 2)).astype(np.float64) * 1000

  project = _make_project(
    samples=[
      {"id": "control"},
      {"id": "main"},
    ],
    execution_profiles=[{
      "id": "default",
      "name": "Default",
      "gating_strategy_id": None,
    }],
    compensation_calculations=[{
      "id": "calc1",
      "name": "Identity calc",
      "minimum_positive_events": 1,
      "minimum_negative_events": 1,
      "controls": [
        {
          "sample_id": "control",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "all_events",
          "negative_population_id": "all_events",
        },
        {
          "sample_id": "control",
          "detector_channel_id": "FL2-A",
          "positive_population_id": "all_events",
          "negative_population_id": "all_events",
        },
      ],
    }],
  )

  with pytest.raises(PipelineError, match="calculation_invalid_reference_signal"):
    run_project_pipeline(
      project,
      execution_profile_id="default",
      event_data={"control": control_events, "main": main_events},
      channel_names=["FL1-A", "FL2-A"],
    )


def test_dynamic_compensation_matrix_overrides_static() -> None:
  """A dynamically calculated matrix with the same ID overrides a static one."""
  rng = np.random.default_rng(42)
  fl1_med = 10000.0
  fl2_med = 8000.0
  n_per_pop = 500

  control_events = _make_single_stain_events(
    rng, n_per_pop=n_per_pop,
    fl1_median=fl1_med, fl2_median=fl2_med,
  )
  main_events = rng.random((50, 2)).astype(np.float64) * 1000

  strategy = _make_control_gating_strategy(
    n_total=n_per_pop * 3,
    n_per_pop=n_per_pop,
    fl1_threshold=fl1_med,
    fl2_threshold=fl2_med,
  )

  project = _make_project(
    samples=[
      {"id": "control"},
      {"id": "main"},
    ],
    execution_profiles=[{
      "id": "default",
      "name": "Default",
      "gating_strategy_id": strategy.id,
    }],
    # Static matrix with the same ID the calculation will produce.
    compensation_matrices=[{
      "id": "calculated-calc1",
      "name": "Static placeholder",
      "source": "user_defined",
      "channels": ("FL1-A", "FL2-A"),
      "matrix": ((1.0, 0.0), (0.0, 1.0)),
    }],
    default_compensation_matrix_id="calculated-calc1",
    compensation_calculations=[{
      "id": "calc1",
      "name": "2-color spillover",
      "controls": [
        {
          "sample_id": "control",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "pos_FL1",
          "negative_population_id": "neg",
        },
        {
          "sample_id": "control",
          "detector_channel_id": "FL2-A",
          "positive_population_id": "pos_FL2",
          "negative_population_id": "neg",
        },
      ],
    }],
    gating_strategies_data={"control_gating": strategy},
  )

  report = run_project_pipeline(
    project,
    execution_profile_id="default",
    event_data={"control": control_events, "main": main_events},
    channel_names=["FL1-A", "FL2-A"],
  )

  assert report.status == "success"

  # The calculated matrix ID is "calculated-{calc_id}" = "calculated-calc1".
  # It should override the static matrix with the same ID.
  calc_diagnostics = [
    d for d in report.diagnostics
    if d.code == "compensation_calculated"
  ]
  assert len(calc_diagnostics) >= 1
  matrix_id = calc_diagnostics[0].details["matrix_id"]
  assert matrix_id == "calculated-calc1"

  # Verify the applied matrix is the dynamically calculated one.
  applied = [
    d for d in report.diagnostics
    if d.code == "compensation_matrix_applied"
    and d.sample_id == "main"
  ]
  assert len(applied) >= 1
  assert applied[0].details["matrix_id"] == "calculated-calc1"


# ---------------------------------------------------------------------------
# Statistics pipeline integration
# ---------------------------------------------------------------------------

def test_pipeline_statistics_in_report() -> None:
  """Statistics defined in the project manifest appear in ExecutionReport."""
  stats = [
    {
      "id": "stat_count",
      "name": "Count live",
      "population_id": "all_events",
      "metric": "count",
      "source_stage": "compensated",
    },
    {
      "id": "stat_mean",
      "name": "Mean FL1",
      "population_id": "all_events",
      "parameter_id": "FSC-H",
      "metric": "mean",
      "source_stage": "compensated",
    },
  ]
  project = _make_project(
    project_id="stat_test",
    execution_profiles=[
      {"id": "default", "name": "Default", "gating_strategy_id": None},
    ],
    samples=[{"id": "s1", "group_id": "test", "channels": [
      {"id": "FSC-H", "name": "FSC-H"},
      {"id": "SSC-H", "name": "SSC-H"},
    ]}],
    statistics=stats,
  )

  events = np.array([
    [1.0, 2.0],
    [3.0, 4.0],
    [5.0, 6.0],
  ], dtype=np.float64)
  channels = tuple(
    ChannelSpec(id=cid, name=cid)
    for cid in ["FSC-H", "SSC-H"]
  )
  sample = SampleData(sample_id="s1", events=events, channels=channels)

  ctx = ExecutionContext(execution_profile_id="default")
  runner = PipelineRunner(project)
  report = runner.run_samples(ctx, [sample])

  assert report.status == "success"
  assert len(report.statistic_results) == 2

  by_id = {r.statistic_id: r for r in report.statistic_results}

  count_r = by_id["stat_count"]
  assert count_r.value == 3
  assert count_r.status == "ok"

  mean_r = by_id["stat_mean"]
  assert mean_r.value == pytest.approx(3.0)
  assert mean_r.status == "ok"


def test_pipeline_statistics_empty() -> None:
  """No statistics in manifest produces empty statistic_results."""
  project = _make_project(
    project_id="no_stat",
    execution_profiles=[
      {"id": "default", "name": "Default", "gating_strategy_id": None},
    ],
    samples=[{"id": "s1", "group_id": "test", "channels": [
      {"id": "FSC-H", "name": "FSC-H"},
    ]}],
  )

  events = np.array([[1.0]], dtype=np.float64)
  channels = (ChannelSpec(id="FSC-H", name="FSC-H"),)
  sample = SampleData(sample_id="s1", events=events, channels=channels)

  ctx = ExecutionContext(execution_profile_id="default")
  runner = PipelineRunner(project)
  report = runner.run_samples(ctx, [sample])

  assert report.statistic_results == ()


def test_pipeline_statistics_with_gating_strategy() -> None:
  """Statistics are computed per-gated population."""
  # Create a gating strategy with a threshold gate on FSC-H.
  strategy = GatingStrategySpec(
    id="strat1",
    name="Strategy",
    gates=(
      GateSpec(
        id="g1",
        name="Live",
        gate_type="range",
        parent_population_id="all_events",
        x_parameter="FSC-H",
        thresholds={"min": 2.0, "max": 100.0},
      ),
      GateSpec(
        id="g2",
        name="High live",
        gate_type="range",
        parent_population_id="g1",
        x_parameter="FSC-H",
        thresholds={"min": 4.0, "max": 100.0},
      ),
    ),
    root_population_id="all_events",
  )

  stats = [
    {
      "id": "stat_count_all",
      "name": "Count all",
      "population_id": "all_events",
      "metric": "count",
      "source_stage": "compensated",
    },
    {
      "id": "stat_count_live",
      "name": "Count live",
      "population_id": "g1",
      "metric": "count",
      "source_stage": "compensated",
    },
    {
      "id": "stat_mean_live",
      "name": "Mean FL1 live",
      "population_id": "g1",
      "parameter_id": "FSC-H",
      "metric": "mean",
      "source_stage": "compensated",
    },
    {
      "id": "stat_frequency_high_live_parent",
      "name": "High live frequency of parent",
      "population_id": "g2",
      "metric": "frequency_of_parent",
      "source_stage": "compensated",
    },
    {
      "id": "stat_frequency_high_live_total",
      "name": "High live frequency of total",
      "population_id": "g2",
      "metric": "frequency_of_total",
      "source_stage": "compensated",
    },
  ]
  project = _make_project(
    project_id="stat_gate_test",
    execution_profiles=[
      {"id": "default", "name": "Default", "gating_strategy_id": "strat1"},
    ],
    samples=[{"id": "s1", "group_id": "test", "channels": [
      {"id": "FSC-H", "name": "FSC-H"},
      {"id": "SSC-H", "name": "SSC-H"},
    ]}],
    gating_strategies_data={"strat1": strategy},
    statistics=stats,
  )

  events = np.array([
    [1.0, 2.0],   # FSC-H < 2 -> not in g1
    [3.0, 4.0],   # FSC-H >= 2 -> in g1
    [5.0, 6.0],   # FSC-H >= 2 -> in g1
  ], dtype=np.float64)
  channels = tuple(
    ChannelSpec(id=cid, name=cid)
    for cid in ["FSC-H", "SSC-H"]
  )
  sample = SampleData(sample_id="s1", events=events, channels=channels)

  ctx = ExecutionContext(execution_profile_id="default")
  runner = PipelineRunner(project)
  report = runner.run_samples(ctx, [sample])

  assert report.status == "success"
  by_id = {r.statistic_id: r for r in report.statistic_results}

  count_all = by_id["stat_count_all"]
  assert count_all.value == 3
  assert count_all.status == "ok"

  count_live = by_id["stat_count_live"]
  assert count_live.value == 2
  assert count_live.status == "ok"

  mean_live = by_id["stat_mean_live"]
  assert mean_live.value == pytest.approx(4.0)  # mean of [3.0, 5.0]
  assert mean_live.status == "ok"

  assert by_id["stat_frequency_high_live_parent"].value == pytest.approx(0.5)
  assert by_id["stat_frequency_high_live_total"].value == pytest.approx(1 / 3)


def test_pipeline_statistics_respect_persisted_source_stage() -> None:
  """A full-event gate mask is applied to each requested value space."""
  strategy = GatingStrategySpec(
    id="source-stage-strategy",
    name="Source stage strategy",
    gates=(
      GateSpec(
        id="high",
        name="High transformed signal",
        gate_type="range",
        parent_population_id="all_events",
        x_parameter="signal",
        thresholds={"min": 50.0, "max": 100.0},
      ),
    ),
    root_population_id="all_events",
  )
  project = _make_project(
    project_id="statistics-source-stage",
    execution_profiles=[{
      "id": "default",
      "name": "Default",
      "gating_strategy_id": strategy.id,
    }],
    samples=[{"id": "s1", "channels": [{"id": "signal", "name": "signal"}]}],
    compensation_matrices=[{
      "id": "divide-by-two",
      "name": "Divide by two",
      "source": "user_defined",
      "channels": ("signal",),
      "matrix": ((2.0,),),
    }],
    default_compensation_matrix_id="divide-by-two",
    transforms=[{
      "id": "scale-ten",
      "name": "Scale ten",
      "transform_type": "linear",
      "parameter": "signal",
      "role": "analysis",
      "settings": {"scale": 10.0, "offset": 0.0},
    }],
    gating_strategies_data={strategy.id: strategy},
    statistics=[
      {
        "id": "raw",
        "name": "Raw mean",
        "population_id": "high",
        "parameter_id": "signal",
        "metric": "mean",
        "source_stage": "raw",
      },
      {
        "id": "compensated",
        "name": "Compensated mean",
        "population_id": "high",
        "parameter_id": "signal",
        "metric": "mean",
        "source_stage": "compensated",
      },
      {
        "id": "transformed",
        "name": "Transformed mean",
        "population_id": "high",
        "parameter_id": "signal",
        "metric": "mean",
        "source_stage": "transformed",
      },
    ],
  )
  sample = SampleData(
    sample_id="s1",
    events=np.array([[8.0], [12.0]], dtype=np.float64),
    channels=(ChannelSpec(id="signal", name="signal", unit="a.u."),),
  )

  report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))

  values = {result.statistic_id: result.value for result in report.statistic_results}
  assert values == {"raw": 12.0, "compensated": 6.0, "transformed": 60.0}
  metadata = {
    result.statistic_id: (result.statistic_name, result.unit)
    for result in report.statistic_results
  }
  assert metadata == {
    "raw": ("Raw mean", "a.u."),
    "compensated": ("Compensated mean", "a.u."),
    "transformed": ("Transformed mean", "a.u."),
  }


def test_pipeline_statistics_invalid_spec_raises() -> None:
  """Invalid statistic definition raises PipelineError."""
  project = _make_project(
    project_id="bad_stat",
    execution_profiles=[
      {"id": "default", "name": "Default", "gating_strategy_id": None},
    ],
    samples=[{"id": "s1", "group_id": "test", "channels": [
      {"id": "FSC-H", "name": "FSC-H"},
    ]}],
    statistics=[
      {"id": "stat1", "name": "Bad", "population_id": "", "metric": "count"},
    ],
  )

  events = np.array([[1.0]], dtype=np.float64)
  channels = (ChannelSpec(id="FSC-H", name="FSC-H"),)
  sample = SampleData(sample_id="s1", events=events, channels=channels)

  ctx = ExecutionContext(execution_profile_id="default")
  runner = PipelineRunner(project)
  with pytest.raises(PipelineError, match="invalid_statistic_definition"):
    runner.run_samples(ctx, [sample])
