"""Tests for the CLI commands."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import flowdesk_cli.main as cli_main
from flowdesk_cli.inspect_fcs import inspect_fcs_command
from flowdesk_cli.run_project import run_project_command
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import ChannelSpec
from flowdesk_core.sample import SampleData
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import save_project

# ---------------------------------------------------------------------------
# Helper: create a minimal .flowdesk project bundle
# ---------------------------------------------------------------------------


def _create_minimal_project(
  tmp_path: Path,
  project_id: str = "test_proj",
  pipeline_version: str = "0.1",
  population_results: list[dict] | None = None,
) -> Path:
  """Create a minimal valid project bundle directory."""
  proj_dir = tmp_path / f"{project_id}.flowdesk"
  proj_dir.mkdir()
  (proj_dir / "cache").mkdir()
  (proj_dir / "exports").mkdir()
  (proj_dir / "gates").mkdir()

  manifest = {
    "project_id": project_id,
    "project_version": "1.0.0",
    "pipeline_version": pipeline_version,
    "samples": [],
    "execution_profiles": [
      {"id": "default", "name": "Default"}
    ],
    "population_results": population_results or [
      {
        "sample_id": "s1",
        "population_id": "all_events",
        "event_count": 42,
        "frequency_of_parent": None,
        "frequency_of_total": 1.0,
      }
    ],
  }

  with (proj_dir / "manifest.json").open("w", encoding="utf-8") as fh:
    json.dump(manifest, fh)

  return proj_dir


# ---------------------------------------------------------------------------
# run_project_command tests
# ---------------------------------------------------------------------------


def test_run_project_success(tmp_path: Path) -> None:
  proj_dir = _create_minimal_project(tmp_path)
  exit_code = run_project_command(str(proj_dir))
  assert exit_code == 0


def test_run_project_not_found() -> None:
  exit_code = run_project_command("/nonexistent/path.to/flowdesk")
  assert exit_code == 1


def test_run_project_reports_cooperative_cancellation(
  tmp_path: Path, capsys
) -> None:
  project = _create_minimal_project(tmp_path)
  control = ExecutionControl()
  control.cancellation_token.cancel()

  assert run_project_command(str(project), execution_control=control) == 130
  assert "Cancelled: execution cancelled" in capsys.readouterr().err


def test_run_project_passes_runtime_execution_options_to_core(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  capsys: pytest.CaptureFixture[str],
) -> None:
  project = _create_minimal_project(tmp_path)
  received: list[ExecutionControl | None] = []

  def fake_pipeline(*_args, execution_control=None, **_kwargs) -> ExecutionReport:
    received.append(execution_control)
    return ExecutionReport(
      project_id="test_proj",
      execution_profile_id="default",
      pipeline_version="0.1",
      status="success",
      execution_provenance={
        "backend": "thread", "effective_max_workers": 2,
        "requested_max_workers": 4,
      },
    )

  monkeypatch.setattr("flowdesk_cli.run_project.run_project_pipeline", fake_pipeline)
  assert run_project_command(
    str(project),
    execution_options=ExecutionOptions(
      backend="thread", max_workers=4, memory_budget_bytes=32 * 1024 * 1024,
    ),
  ) == 0

  assert received[0] is not None
  assert received[0].options == ExecutionOptions(
    backend="thread", max_workers=4, memory_budget_bytes=32 * 1024 * 1024,
  )
  assert "Execution: backend=thread workers=2/4" in capsys.readouterr().out


def test_run_cli_parses_explicit_thread_runtime_options(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  received: dict[str, object] = {}

  def fake_run(project: str, **kwargs: object) -> int:
    received["project"] = project
    received.update(kwargs)
    return 0

  monkeypatch.setattr(cli_main, "run_project_command", fake_run)
  monkeypatch.setattr(sys, "argv", [
    "flowdesk", "run", "example.flowdesk", "--execution-backend", "thread",
    "--max-workers", "3", "--memory-budget-mib", "128",
  ])

  assert cli_main.main() == 0
  assert received["project"] == "example.flowdesk"
  assert received["execution_options"] == ExecutionOptions(
    backend="thread", max_workers=3, memory_budget_bytes=128 * 1024 * 1024,
  )


def test_run_cli_rejects_nonpositive_worker_limit(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(sys, "argv", [
    "flowdesk", "run", "example.flowdesk", "--max-workers", "0",
  ])

  with pytest.raises(SystemExit):
    cli_main.main()


def test_run_project_with_output(tmp_path: Path) -> None:
  proj_dir = _create_minimal_project(tmp_path)
  out_file = tmp_path / "results.tsv"
  exit_code = run_project_command(str(proj_dir), output=str(out_file))
  assert exit_code == 0
  assert out_file.exists()

  with out_file.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[0] == ["Sample", "Population", "Events", "% Parent", "% Total"]
  assert len(rows) >= 2  # header + at least one data row


def test_run_project_output_missing_frequency_is_blank(tmp_path: Path) -> None:
  """Verify that missing frequencies are blank in unified export."""
  proj_dir = _create_minimal_project(
    tmp_path,
    population_results=[
      {
        "sample_id": "s1",
        "population_id": "all_events",
        "event_count": 100,
        "frequency_of_parent": None,
        "frequency_of_total": 1.0,
      }
    ],
  )
  out_file = tmp_path / "results.tsv"
  exit_code = run_project_command(str(proj_dir), output=str(out_file))
  assert exit_code == 0

  with out_file.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  # The root population has no parent frequency and total percentage is 100.
  assert rows[1][3] == ""
  assert rows[1][4] == "100.0"


def test_run_project_invalid_manifest(tmp_path: Path) -> None:
  """A project missing required fields should return non-zero exit code."""
  proj_dir = tmp_path / "bad.flowdesk"
  proj_dir.mkdir()
  (proj_dir / "cache").mkdir()
  (proj_dir / "exports").mkdir()
  (proj_dir / "gates").mkdir()

  # Missing required fields: project_id, pipeline_version, samples
  bad_manifest = {"execution_profiles": [{"id": "default"}]}
  with (proj_dir / "manifest.json").open("w", encoding="utf-8") as fh:
    json.dump(bad_manifest, fh)

  exit_code = run_project_command(str(proj_dir))
  assert exit_code == 1


def test_run_project_prints_persisted_derived_diagnostic_as_json(
  tmp_path: Path,
  monkeypatch,
  capsys,
) -> None:
  project_dir = tmp_path / "derived-diagnostic.flowdesk"
  manifest = {
    "project_id": "derived_diagnostic",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "samples": [{
      "id": "s1",
      "path": "sample.fcs",
      "channels": [
        {"id": "signal", "name": "Signal", "metadata": {}},
        {"id": "missing", "name": "Missing", "metadata": {}},
      ],
    }],
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "derived_parameters": [{
      "id": "missing_definition",
      "output_channel_id": "derived_missing",
      "name": "Missing input",
      "expression": "missing",
      "source_stage": "raw",
      "input_parameters": ["missing"],
      "unit": None,
      "invalid_value_policy": "emit_nan_with_warning",
    }],
  }
  save_project(project_dir, manifest)
  sample = SampleData(
    "s1",
    np.array([[1.0], [2.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )
  monkeypatch.setattr(
    "flowdesk_cli.run_project.read_fcs_sample",
    lambda *_args: (None, sample),
  )

  exit_code = run_project_command(str(project_dir))

  captured = capsys.readouterr()
  assert exit_code == 0
  diagnostic_line = next(
    line for line in captured.err.splitlines()
    if line.startswith("Diagnostic: ")
  )
  diagnostic = json.loads(diagnostic_line.removeprefix("Diagnostic: "))
  assert diagnostic == {
    "affected_event_count": 2,
    "code": "derived_parameter_evaluation_failed",
    "details": {
      "expression": "missing",
      "policy": "emit_nan_with_warning",
    },
    "exception_type": "ExpressionError",
    "message": (
      "derived parameter 'missing_definition' failed for sample 's1': "
      "unknown parameter: missing"
    ),
    "parameter_id": "missing_definition",
    "sample_id": "s1",
    "severity": "warning",
    "stage": "derived_parameters",
  }


def test_cli_and_core_export_match_for_nonfinite_derived_statistics(
  tmp_path: Path,
  monkeypatch,
  capsys,
) -> None:
  """The CLI must preserve derived QC and statistic policy from the core run."""
  from flowdesk_core.execution_context import ExecutionContext
  from flowdesk_core.export import write_statistic_results
  from flowdesk_core.pipeline_runner import PipelineRunner

  project = {
    "project_id": "nonfinite-e2e",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "samples": [{
      "id": "s1", "path": "sample.fcs",
      "channels": [
        {"id": "signal", "name": "Signal", "metadata": {}},
        {"id": "reference", "name": "Reference", "metadata": {}},
      ],
    }],
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "derived_parameters": [{
      "id": "ratio_definition", "name": "Ratio", "output_channel_id": "ratio",
      "expression": "signal / reference", "source_stage": "raw",
      "input_parameters": ["signal", "reference"],
      "invalid_value_policy": "emit_nan_with_warning",
      "non_finite_policy": "strict",
    }],
    "statistics": [
      {
        "id": "ratio_strict", "name": "Ratio strict", "population_id": "all_events",
        "parameter_id": "ratio", "metric": "mean", "source_stage": "compensated",
        "non_finite_policy": "strict",
      },
      {
        "id": "ratio_excluded", "name": "Ratio excluded", "population_id": "all_events",
        "parameter_id": "ratio", "metric": "mean", "source_stage": "compensated",
        "non_finite_policy": "exclude_invalid",
      },
    ],
  }
  project_path = tmp_path / "nonfinite-e2e.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1",
    np.array([[2.0, 1.0], [4.0, 0.0], [6.0, 3.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"), ChannelSpec(id="reference", name="Reference")),
  )
  original = sample.events.copy()
  monkeypatch.setattr(
    "flowdesk_cli.run_project.read_fcs_sample", lambda *_args: (None, sample)
  )

  core_report = PipelineRunner(project).run_samples(ExecutionContext(), (sample,))
  core_path = tmp_path / "core.tsv"
  write_statistic_results(list(core_report.statistic_results), core_path)
  cli_path = tmp_path / "cli.tsv"
  assert run_project_command(str(project_path), statistics_output=str(cli_path)) == 0

  import csv
  with core_path.open(encoding="utf-8") as handle:
    core_rows = list(csv.DictReader(handle, delimiter="\t"))
  with cli_path.open(encoding="utf-8") as handle:
    cli_rows = list(csv.DictReader(handle, delimiter="\t"))
  assert core_rows == cli_rows
  row_map = {row["statistic_id"]: row for row in cli_rows}
  assert row_map["ratio_strict"]["status"] == "undefined"
  assert row_map["ratio_strict"]["n_invalid"] == "1"
  assert row_map["ratio_excluded"]["value"] == "2.0"
  assert "derived_parameter_nonfinite_values" in capsys.readouterr().err
  np.testing.assert_array_equal(sample.events, original)


# ---------------------------------------------------------------------------
# inspect_fcs_command tests
# ---------------------------------------------------------------------------


def test_inspect_fcs_not_found() -> None:
  exit_code = inspect_fcs_command("/nonexistent/file.fcs")
  assert exit_code == 1


def test_inspect_fcs_success(tmp_path: Path) -> None:
  """Inspect a synthetic FCS file created by flowdesk_core.fcs_io."""
  import numpy as np

  from flowdesk_core.fcs_io import write_fcs_file

  fcs_path = tmp_path / "synthetic.fcs"
  events = np.array(
    [[100.0, 200.0], [300.0, 400.0], [500.0, 600.0]],
    dtype=np.float64,
  )
  write_fcs_file(
    path=str(fcs_path),
    event_data=events,
    channel_names=["FSC-H", "SSC-H"],
  )

  exit_code = inspect_fcs_command(str(fcs_path))
  assert exit_code == 0
