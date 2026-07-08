"""Tests for the CLI commands."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from flowdesk_cli.inspect_fcs import inspect_fcs_command
from flowdesk_cli.run_project import run_project_command

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


def test_run_project_with_output(tmp_path: Path) -> None:
  proj_dir = _create_minimal_project(tmp_path)
  out_file = tmp_path / "results.tsv"
  exit_code = run_project_command(str(proj_dir), output=str(out_file))
  assert exit_code == 0
  assert out_file.exists()

  with out_file.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[0] == [
    "sample_id",
    "population_id",
    "event_count",
    "frequency_of_parent",
    "frequency_of_total",
  ]
  assert len(rows) >= 2  # header + at least one data row


def test_run_project_output_nan_policy(tmp_path: Path) -> None:
  """Verify that None frequencies are exported as 'NaN' by default."""
  proj_dir = _create_minimal_project(
    tmp_path,
    population_results=[
      {
        "sample_id": "s1",
        "population_id": "root",
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

  # The root population has frequency_of_parent = None -> "NaN"
  assert rows[1][3] == "NaN"
  assert rows[1][4] == "1.0"


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
