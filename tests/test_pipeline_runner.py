"""Tests for the pipeline runner."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.pipeline_runner import (
  PipelineError,
  run_project_pipeline,
)
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
