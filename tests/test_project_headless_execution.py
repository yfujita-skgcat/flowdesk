import json
from pathlib import Path

import numpy as np

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.models import ChannelSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.sample import SampleData
from flowdesk_storage.project import load_project, save_project


def test_pipeline_runner_imports_without_gui_dependency() -> None:
  import flowdesk_core.pipeline_runner as pipeline_runner

  assert pipeline_runner.PipelineRunner is not None


def test_migrated_project_round_trip_runs_headlessly(tmp_path: Path) -> None:
  fixture = Path(__file__).parent / "fixtures" / "project_v0_1_channel_names.json"
  legacy_bundle = tmp_path / "legacy.flowdesk"
  legacy_bundle.mkdir()
  (legacy_bundle / "manifest.json").write_text(
    fixture.read_text(encoding="utf-8"),
    encoding="utf-8",
  )

  migrated = load_project(legacy_bundle)
  saved_bundle = tmp_path / "saved.flowdesk"
  save_project(saved_bundle, migrated)
  reloaded = load_project(saved_bundle)
  channel_specs = tuple(
    ChannelSpec(
      id=channel["id"],
      name=channel["name"],
      metadata=dict(channel.get("metadata", {})),
    )
    for channel in reloaded["samples"][0]["channels"]
  )
  sample = SampleData(
    sample_id="s1",
    events=np.array(
      [[1.0, 15.0], [2.0, 25.0], [9.0, 15.0], [1.0, 40.0]],
      dtype=np.float64,
    ),
    channels=channel_specs,
  )

  report = PipelineRunner(reloaded).run_samples(
    ExecutionContext(execution_profile_id="default"),
    (sample,),
  )

  result = next(
    result
    for result in report.population_results
    if result.population_id == "cd3_gate"
  )
  assert result.event_count == 2
  assert json.loads(
    (saved_bundle / "manifest.json").read_text(encoding="utf-8")
  )["unknown_project_extension"] == {"keep": "unchanged"}


def test_legacy_logicle_migration_preserves_headless_gate_membership(
  tmp_path: Path,
) -> None:
  legacy = {
    "project_id": "legacy_logicle",
    "project_version": "1.2.0",
    "pipeline_version": "0.1",
    "samples": [{
      "id": "s1",
      "channels": [{"id": "signal", "name": "Signal", "metadata": {}}],
    }],
    "execution_profiles": [{
      "id": "default",
      "gating_strategy_id": "strategy",
    }],
    "transforms": [{
      "id": "legacy_scale",
      "name": "Legacy scale",
      "transform_type": "logicle_like",
      "parameter": "signal",
      "settings": {"w": 0.25, "td": 1e6, "tn": 1e4},
    }],
    "gating_strategies_data": {
      "strategy": {
        "id": "strategy",
        "name": "Strategy",
        "gates": [{
          "id": "legacy_range",
          "name": "Legacy range",
          "gate_type": "range",
          "parent_population_id": "all_events",
          "x_parameter": "signal",
          "thresholds": {"min": 40000.0, "max": 50000.0},
        }],
      },
    },
  }
  bundle = tmp_path / "legacy-logicle.flowdesk"
  bundle.mkdir()
  (bundle / "manifest.json").write_text(
    json.dumps(legacy),
    encoding="utf-8",
  )

  migrated = load_project(bundle)
  sample = SampleData(
    "s1",
    np.array([[-10.0], [0.0], [10.0], [1000.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  report = PipelineRunner(migrated).run_samples(
    ExecutionContext(execution_profile_id="default"),
    (sample,),
  )

  assert migrated["transforms"][0]["transform_type"] == (
    "legacy_logicle_approximation"
  )
  membership = next(
    item.mask
    for item in report.population_membership
    if item.population_id == "legacy_range"
  )
  assert membership.tolist() == [False, False, True, False]


def test_legacy_statistic_missing_nonfinite_policy_gets_compatibility_mode() -> None:
  from flowdesk_storage.migrations import migrate_manifest_with_report

  report = migrate_manifest_with_report({
    "project_id": "legacy-stats",
    "project_version": "1.5.0",
    "pipeline_version": "0.1",
    "samples": [],
    "statistics": [{
      "id": "mean", "name": "Mean", "population_id": "all_events",
      "parameter_id": "signal", "metric": "mean", "source_stage": "raw",
    }],
  })
  statistic = report.migrated["statistics"][0]
  assert statistic["non_finite_policy"] == "exclude_invalid"
  assert any(
    item["code"] == "legacy_statistic_nonfinite_compatibility"
    for item in report.diagnostics
  )
