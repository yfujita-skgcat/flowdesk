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
