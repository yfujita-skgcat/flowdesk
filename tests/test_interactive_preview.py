"""Core contract tests for revision-tagged current-sample previews."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.models import ChannelSpec, GateSpec, GatingStrategySpec
from flowdesk_core.pipeline_runner import PipelineError, PipelineRunner
from flowdesk_core.preview import PreviewRequest, PreviewRevisionState
from flowdesk_core.processed_display import ProcessedDisplayRequest
from flowdesk_core.sample import SampleData


def _project(strategy: GatingStrategySpec) -> dict:
  return {
    "project_id": "preview-contract",
    "pipeline_version": "0.1",
    "execution_profiles": [
      {
        "id": "default",
        "name": "Default",
        "sample_selector": "all",
        "gating_strategy_id": strategy.id,
      }
    ],
    "samples": [{"id": "sample-1", "name": "Sample 1"}],
    "compensation_matrices": [
      {
        "id": "identity",
        "name": "Identity",
        "source": "user_defined",
        "channels": ("x", "y"),
        "matrix": ((1.0, 0.0), (0.0, 1.0)),
      }
    ],
    "compensation_bindings": [],
    "compensation_calculations": [],
    "derived_parameters": [
      {
        "id": "sum",
        "name": "X plus Y",
        "expression": "x + y",
        "input_parameters": ["x", "y"],
      }
    ],
    "transforms": [
      {
        "id": "scale-x",
        "name": "Scale X",
        "transform_type": "linear",
        "parameter": "x",
        "settings": {"scale": 2.0, "offset": 0.0},
      }
    ],
    "default_compensation_matrix_id": "identity",
    "gating_strategies_data": {strategy.id: strategy},
    "statistics": [
      {
        "id": "selected-count",
        "name": "Selected count",
        "population_id": "selected",
        "metric": "count",
        "source_stage": "compensated",
      },
      {
        "id": "selected-mean",
        "name": "Selected mean X",
        "population_id": "selected",
        "parameter_id": "x",
        "metric": "mean",
        "source_stage": "transformed",
        "transform_id": "scale-x",
      },
    ],
    "population_results": [],
    "gate_overrides": [],
    "sample_groups": [],
  }


def _strategy() -> GatingStrategySpec:
  return GatingStrategySpec(
    id="preview-strategy",
    name="Preview strategy",
    gates=(
      GateSpec(
        id="selected",
        name="Selected",
        gate_type="rectangle",
        parent_population_id="all_events",
        x_parameter="x",
        y_parameter="sum",
        x_transform_id="scale-x",
        thresholds={
          "x_min": 1000.0,
          "x_max": 1998.0,
          "y_min": 999.0,
          "y_max": 999.0,
        },
      ),
    ),
  )


def _sample() -> SampleData:
  values = np.arange(1000, dtype=np.float64)
  return SampleData(
    sample_id="sample-1",
    events=np.column_stack((values, values[::-1])),
    channels=(ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )


def test_preview_matches_full_batch_for_full_resolution_sample() -> None:
  sample = _sample()
  runner = PipelineRunner(_project(_strategy()))

  batch = runner.run_samples(ExecutionContext(), (sample,))
  preview = runner.preview_sample(PreviewRequest(
    revision=17,
    sample=sample,
    strategy_id="preview-strategy",
    required_population_id="selected",
    changed_gate_id="selected",
  ))

  assert preview.revision == 17
  assert preview.source_event_count == sample.event_count == 1000
  assert preview.status == batch.status == "success"
  assert preview.population_results == batch.population_results
  assert preview.statistic_results == batch.statistic_results
  assert len(preview.population_membership) == len(batch.population_membership)
  for actual, expected in zip(
    preview.population_membership,
    batch.population_membership,
    strict=True,
  ):
    assert actual.sample_id == expected.sample_id
    assert actual.population_id == expected.population_id
    assert actual.event_count == expected.event_count
    np.testing.assert_array_equal(actual.mask, expected.mask)
    assert not actual.mask.flags.writeable

  selected = next(
    result for result in preview.population_results
    if result.population_id == "selected"
  )
  assert selected.event_count == 500
  assert selected.frequency_of_parent == pytest.approx(0.5)
  assert selected.frequency_of_total == pytest.approx(0.5)
  statistics = {
    result.statistic_id: result.value for result in preview.statistic_results
  }
  assert statistics["selected-count"] == 500
  assert statistics["selected-mean"] == pytest.approx(1499.0)

  count_only = runner.preview_sample(PreviewRequest(
    revision=18,
    sample=sample,
    required_population_id="selected",
    requested_statistic_ids=("selected-count",),
  ))
  assert [value.statistic_id for value in count_only.statistic_results] == [
    "selected-count"
  ]


def test_preview_request_and_report_are_frozen() -> None:
  request = PreviewRequest(revision=1, sample=_sample())
  report = PipelineRunner(_project(_strategy())).preview_sample(request)

  with pytest.raises(FrozenInstanceError):
    request.revision = 2  # type: ignore[misc]
  with pytest.raises(FrozenInstanceError):
    report.status = "changed"  # type: ignore[misc]


def test_runner_snapshots_nested_gate_definitions_for_preview() -> None:
  strategy = _strategy()
  project = _project(strategy)
  runner = PipelineRunner(project)
  strategy.gates[0].thresholds["x_min"] = 1800.0

  preview = runner.preview_sample(PreviewRequest(
    revision=3,
    sample=_sample(),
    required_population_id="selected",
  ))

  selected = next(
    result for result in preview.population_results
    if result.population_id == "selected"
  )
  assert selected.event_count == 500


def test_preview_rejects_mismatched_strategy_or_population() -> None:
  runner = PipelineRunner(_project(_strategy()))
  sample = _sample()

  with pytest.raises(PipelineError, match="strategy does not match"):
    runner.preview_sample(PreviewRequest(
      revision=1,
      sample=sample,
      strategy_id="obsolete-strategy",
    ))
  with pytest.raises(PipelineError, match="required population"):
    runner.preview_sample(PreviewRequest(
      revision=1,
      sample=sample,
      required_population_id="missing-population",
    ))


def test_processed_display_uses_compensated_derived_events_and_full_membership() -> None:
  sample = _sample()
  runner = PipelineRunner(_project(_strategy()))

  display = runner.prepare_display_sample(ProcessedDisplayRequest(
    revision=24,
    sample=sample,
    population_id="selected",
    x_parameter_id="x",
    y_parameter_id="sum",
    x_transform_id="scale-x",
  ))

  assert display.revision == 24
  assert display.sample_id == sample.sample_id
  assert [channel.id for channel in display.channels] == ["x", "y", "sum"]
  np.testing.assert_array_equal(
    display.events[:, display.channel_index("sum")], 999.0
  )
  assert int(display.display_mask.sum()) == 500
  assert not display.events.flags.writeable
  assert not display.display_mask.flags.writeable
  selected = next(
    membership for membership in display.preview_report.population_membership
    if membership.population_id == "selected"
  )
  np.testing.assert_array_equal(display.display_mask, selected.mask)


def test_processed_display_rejects_missing_parameter_and_population() -> None:
  runner = PipelineRunner(_project(_strategy()))
  sample = _sample()

  with pytest.raises(PipelineError, match="display_parameter_missing"):
    runner.prepare_display_sample(ProcessedDisplayRequest(
      revision=1,
      sample=sample,
      population_id="all_events",
      x_parameter_id="missing",
    ))
  with pytest.raises(PipelineError, match="required population"):
    runner.prepare_display_sample(ProcessedDisplayRequest(
      revision=1,
      sample=sample,
      population_id="missing-population",
      x_parameter_id="x",
    ))


def test_display_layer_skips_authoritative_preview_for_all_events() -> None:
  sample = _sample()
  runner = PipelineRunner(_project(_strategy()))
  request = ProcessedDisplayRequest(
    revision=1,
    sample=sample,
    population_id="all_events",
    x_parameter_id="x",
    y_parameter_id="y",
  )

  layer = runner.prepare_display_layer(request)
  full = runner.prepare_display_sample(request)

  assert layer.preview_report is None
  np.testing.assert_array_equal(layer.events, full.events)
  np.testing.assert_array_equal(layer.display_mask, full.display_mask)
  assert layer.diagnostics
  assert layer.diagnostics[0] == full.diagnostics[0]


def test_revision_state_invalidates_descendants_and_falls_back_to_ancestor() -> None:
  state = PreviewRevisionState()
  assert state.accept_authoritative(0)
  state.invalidate({"A", "B", "C"})

  parents = {"A": "all_events", "B": "A", "C": "B"}
  available = {"all_events", "A", "B", "C"}
  assert state.analysis_revision == 1
  assert state.preview_status == "stale"
  assert not state.result_is_current("B", 0)
  assert state.nearest_valid_population(
    "C", parents, available, result_revision=1
  ) is None

  # The root result is still valid for the new revision and is the safe
  # fallback while descendants are recalculated.
  state.accept_preview(1, {"all_events"})
  assert state.nearest_valid_population(
    "C", parents, available, result_revision=1
  ) == "all_events"

  state.accept_preview(1, {"A", "B", "C"})
  assert state.nearest_valid_population(
    "C", parents, available, result_revision=1
  ) == "C"


def test_revision_state_rejects_obsolete_results() -> None:
  state = PreviewRevisionState()
  state.invalidate({"gate"})
  assert not state.accept_preview(0, {"gate"})
  assert not state.accept_authoritative(0)
  assert state.authoritative_result_revision is None
  assert state.preview_result_revision is None
  assert state.preview_status == "stale"
