"""Tests for the export module."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.export import (
  ExportError,
  _format_value,
  _nan_placeholder,
  write_export_records,
  write_population_results,
  write_population_results_csv,
  write_population_results_wide,
  write_statistic_results,
)
from flowdesk_core.models import ExportRecord, PopulationResult, StatisticResult

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_export_error_is_flowdesk_error() -> None:
  assert issubclass(ExportError, FlowdeskError)


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------


def test_format_value_int() -> None:
  assert _format_value(42, "string_nan") == "42"


def test_format_value_float() -> None:
  assert _format_value(3.14, "string_nan") == "3.14"


def test_format_value_none_string_nan() -> None:
  assert _format_value(None, "string_nan") == "NaN"


def test_format_value_none_empty() -> None:
  assert _format_value(None, "empty") == ""


def test_format_value_none_zero() -> None:
  assert _format_value(None, "zero") == "0"


def test_format_value_float_nan() -> None:
  assert _format_value(float("nan"), "string_nan") == "NaN"
  assert _format_value(float("nan"), "empty") == ""
  assert _format_value(float("nan"), "zero") == "0"


def test_format_value_string_passthrough() -> None:
  assert _format_value("hello", "string_nan") == "hello"


def test_nan_placeholder_string_nan() -> None:
  assert _nan_placeholder("string_nan") == "NaN"


def test_nan_placeholder_empty() -> None:
  assert _nan_placeholder("empty") == ""


def test_nan_placeholder_zero() -> None:
  assert _nan_placeholder("zero") == "0"


# ---------------------------------------------------------------------------
# ExportRecord -> delimited file
# ---------------------------------------------------------------------------


def test_write_export_records_headers(tmp_path: Path) -> None:
  records = [
    ExportRecord(
      sample_id="s1",
      population_id="all_events",
      metric="event_count",
      value=100,
    ),
  ]
  out = tmp_path / "out.tsv"
  write_export_records(records, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[0] == ["sample_id", "population_id", "metric", "value"]
  assert rows[1][2] == "event_count"


def test_write_export_records_values(tmp_path: Path) -> None:
  records = [
    ExportRecord("s1", "pop1", "event_count", 50),
    ExportRecord("s1", "pop1", "frequency_of_parent", 0.5),
    ExportRecord("s1", "pop1", "frequency_of_total", 0.25),
  ]
  out = tmp_path / "out.tsv"
  write_export_records(records, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert len(rows) == 4  # header + 3 data rows
  assert rows[1][3] == "50"
  assert rows[2][3] == "0.5"
  assert rows[3][3] == "0.25"


def test_write_export_records_csv_delimiter(tmp_path: Path) -> None:
  records = [ExportRecord("s1", "pop1", "event_count", 30)]
  out = tmp_path / "out.csv"
  write_export_records(records, out, delimiter=",")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter=",")
    rows = list(reader)

  assert len(rows) == 2
  assert rows[0] == ["sample_id", "population_id", "metric", "value"]


def test_write_export_records_nan_policy_empty(tmp_path: Path) -> None:
  records = [ExportRecord("s1", "pop1", "frequency_of_parent", None)]
  out = tmp_path / "out.tsv"
  write_export_records(records, out, nan_policy="empty")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[1][3] == ""


def test_write_export_records_nan_policy_zero(tmp_path: Path) -> None:
  records = [ExportRecord("s1", "pop1", "frequency_of_parent", None)]
  out = tmp_path / "out.tsv"
  write_export_records(records, out, nan_policy="zero")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[1][3] == "0"


# ---------------------------------------------------------------------------
# PopulationResult -> delimited file (long format)
# ---------------------------------------------------------------------------


def test_write_population_results_creates_three_rows(tmp_path: Path) -> None:
  results = [
    PopulationResult(
      sample_id="s1",
      population_id="all_events",
      event_count=200,
      frequency_of_parent=None,
      frequency_of_total=1.0,
    ),
  ]
  out = tmp_path / "out.tsv"
  write_population_results(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  # header + 3 metrics
  assert len(rows) == 4
  assert rows[0] == ["sample_id", "population_id", "metric", "value"]


def test_write_population_results_values(tmp_path: Path) -> None:
  results = [
    PopulationResult(
      sample_id="s1",
      population_id="pop_a",
      event_count=100,
      frequency_of_parent=0.5,
      frequency_of_total=0.25,
    ),
  ]
  out = tmp_path / "out.tsv"
  write_population_results(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  metrics = [row[2] for row in rows[1:]]
  assert "event_count" in metrics
  assert "frequency_of_parent" in metrics
  assert "frequency_of_total" in metrics


# ---------------------------------------------------------------------------
# Wide-format export
# ---------------------------------------------------------------------------


def test_write_population_results_wide(tmp_path: Path) -> None:
  results = [
    PopulationResult("s1", "all_events", 500, None, 1.0),
    PopulationResult("s1", "live", 400, 0.8, 0.8),
  ]
  out = tmp_path / "wide.tsv"
  write_population_results_wide(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[0] == [
    "sample_id",
    "population_id",
    "event_count",
    "frequency_of_parent",
    "frequency_of_total",
  ]
  assert len(rows) == 3  # header + 2 populations
  assert rows[1][1] == "all_events"
  assert rows[2][1] == "live"


def test_write_population_results_wide_nan_handling(tmp_path: Path) -> None:
  results = [PopulationResult("s1", "pop", 100, None, None)]
  out = tmp_path / "wide.tsv"
  write_population_results_wide(results, out, nan_policy="string_nan")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[1][3] == "NaN"
  assert rows[1][4] == "NaN"


# ---------------------------------------------------------------------------
# CSV convenience wrapper
# ---------------------------------------------------------------------------


def test_write_population_results_csv(tmp_path: Path) -> None:
  results = [
    PopulationResult("s1", "all_events", 300, None, 1.0),
  ]
  out = tmp_path / "out.csv"
  write_population_results_csv(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter=",")
    rows = list(reader)

  assert len(rows) == 2
  assert rows[0] == [
    "sample_id",
    "population_id",
    "event_count",
    "frequency_of_parent",
    "frequency_of_total",
  ]


# ---------------------------------------------------------------------------
# ExportError on bad path
# ---------------------------------------------------------------------------


def test_export_error_on_unwritable_path(tmp_path: Path) -> None:
  results = [PopulationResult("s1", "all_events", 10, None, 1.0)]
  bad_dir = tmp_path / "does_not_exist"
  with pytest.raises(ExportError):
    write_population_results_wide(results, bad_dir / "out.tsv")


def test_export_records_error_on_unwritable_path(tmp_path: Path) -> None:
  records = [ExportRecord("s1", "pop", "event_count", 5)]
  bad_dir = tmp_path / "does_not_exist"
  with pytest.raises(ExportError):
    write_export_records(records, bad_dir / "out.tsv")


# ---------------------------------------------------------------------------
# StatisticResult -> delimited file
# ---------------------------------------------------------------------------


def test_write_statistic_results_headers(tmp_path: Path) -> None:
  results = [
    StatisticResult(
      sample_id="s1",
      statistic_id="stat1",
      population_id="live",
      metric="count",
      value=100,
      status="ok",
      statistic_name="All events count",
    ),
  ]
  out = tmp_path / "out.tsv"
  write_statistic_results(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[0] == [
    "sample_id",
    "statistic_id",
    "display_name",
    "population_id",
    "metric",
    "value",
    "unit",
    "status",
    "undefined_reason",
  ]
  assert rows[1][0] == "s1"
  assert rows[1][1] == "stat1"
  assert rows[1][2] == "All events count"


def test_write_statistic_results_values(tmp_path: Path) -> None:
  results = [
    StatisticResult(
      "s1", "stat1", "live", "count", 100, None, "ok", None,
      "Count live",
    ),
    StatisticResult(
      "s1", "stat2", "live", "mean", 3.14, "AU", "ok", None,
      "Mean FL1",
    ),
    StatisticResult(
      "s1", "stat3", "dead", "median", None, None, "empty",
      "empty_population", "Median dead",
    ),
  ]
  out = tmp_path / "out.tsv"
  write_statistic_results(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert len(rows) == 4  # header + 3 data rows
  assert rows[1][2] == "Count live"
  assert rows[2][2] == "Mean FL1"
  assert rows[1][5] == "100"
  assert rows[2][5] == "3.14"
  assert rows[2][6] == "AU"
  assert rows[3][5] == "NaN"
  assert rows[3][7] == "empty"
  assert rows[3][8] == "empty_population"


def test_write_statistic_results_csv_delimiter(tmp_path: Path) -> None:
  results = [
    StatisticResult("s1", "stat1", "pop", "count", 50, None, "ok", None),
  ]
  out = tmp_path / "out.csv"
  write_statistic_results(results, out, delimiter=",")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter=",")
    rows = list(reader)

  assert len(rows) == 2
  assert rows[0][0] == "sample_id"


def test_write_statistic_results_nan_policy_empty(tmp_path: Path) -> None:
  results = [
    StatisticResult("s1", "stat1", "pop", "mean", None, None, "empty", "empty_population"),
  ]
  out = tmp_path / "out.tsv"
  write_statistic_results(results, out, nan_policy="empty")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[1][5] == ""


def test_write_statistic_results_nan_policy_zero(tmp_path: Path) -> None:
  results = [
    StatisticResult("s1", "stat1", "pop", "mean", None, None, "empty", "empty_population"),
  ]
  out = tmp_path / "out.tsv"
  write_statistic_results(results, out, nan_policy="zero")

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert rows[1][5] == "0"


def test_write_statistic_results_empty_list(tmp_path: Path) -> None:
  out = tmp_path / "out.tsv"
  write_statistic_results([], out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.reader(fh, delimiter="\t")
    rows = list(reader)

  assert len(rows) == 1  # header only


def test_write_statistic_results_error_on_unwritable_path(tmp_path: Path) -> None:
  results = [
    StatisticResult("s1", "stat1", "pop", "count", 5, None, "ok", None),
  ]
  bad_dir = tmp_path / "does_not_exist"
  with pytest.raises(ExportError):
    write_statistic_results(results, bad_dir / "out.tsv")


# ---------------------------------------------------------------------------
# GUI values vs CLI export vs Python API consistency
# ---------------------------------------------------------------------------


def test_statistic_export_values_match_api(tmp_path: Path) -> None:
  """Verify that exported statistic values match the original StatisticResult values.

  This test exercises the full export pipeline:
  1. Create StatisticResult objects with known values.
  2. Export to TSV.
  3. Re-read the file and verify values match the original API output.
  """
  results = [
    StatisticResult("s1", "stat_count", "all_events", "count", 100, None, "ok", None),
    StatisticResult("s1", "stat_mean", "live", "mean", 5.5, "AU", "ok", None),
    StatisticResult("s1", "stat_median", "live", "median", 4.0, None, "ok", None),
    StatisticResult("s1", "stat_pct", "live", "percentile", 3.2, None, "ok", None),
    StatisticResult("s1", "stat_empty", "dead", "count", 0, None, "empty", "empty_population"),
  ]

  out = tmp_path / "stats.tsv"
  write_statistic_results(results, out)

  with out.open(encoding="utf-8") as fh:
    reader = csv.DictReader(fh, delimiter="\t")
    rows = list(reader)

  assert len(rows) == 5

  # Verify each row matches the original StatisticResult
  row_map = {row["statistic_id"]: row for row in rows}

  # Count: value should be exactly "100"
  assert row_map["stat_count"]["value"] == "100"
  assert row_map["stat_count"]["status"] == "ok"
  assert row_map["stat_count"]["sample_id"] == "s1"
  assert row_map["stat_count"]["population_id"] == "all_events"

  # Mean: value and unit
  assert row_map["stat_mean"]["value"] == "5.5"
  assert row_map["stat_mean"]["unit"] == "AU"
  assert row_map["stat_mean"]["status"] == "ok"

  # Empty population: count=0 is a valid numeric value, not NaN
  assert row_map["stat_empty"]["value"] == "0"
  assert row_map["stat_empty"]["status"] == "empty"
  assert row_map["stat_empty"]["undefined_reason"] == "empty_population"


def test_statistic_export_cli_matches_core_api(
  tmp_path: Path,
  monkeypatch,
) -> None:
  """Verify CLI --statistics-output matches core write_statistic_results output.

  This test creates a project with statistics, runs it via CLI and core API,
  and compares the two exports.
  """
  import numpy as np

  from flowdesk_cli.run_project import run_project_command
  from flowdesk_core.execution_context import ExecutionContext
  from flowdesk_core.models import ChannelSpec
  from flowdesk_core.pipeline_runner import PipelineRunner
  from flowdesk_core.sample import SampleData
  from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
  from flowdesk_storage.project import save_project

  # Create synthetic sample data
  events = np.array([
    [1.0, 10.0],
    [2.0, 20.0],
    [3.0, 30.0],
    [4.0, 40.0],
    [5.0, 50.0],
  ], dtype=np.float64)
  channels = (
    ChannelSpec(id="FSC", name="FSC"),
    ChannelSpec(id="SSC", name="SSC"),
  )
  sample_data = SampleData("sample1", events, channels)

  # Create project with statistics
  project = {
    "project_version": CURRENT_PROJECT_VERSION,
    "project_id": "test-proj",
    "pipeline_version": "0.1",
    "project_name": "Test Project",
    "samples": [
      {
        "id": "sample1",
        "path": "sample.fcs",
        "channels": [
          {"id": "FSC", "name": "FSC", "metadata": {}},
          {"id": "SSC", "name": "SSC", "metadata": {}},
        ],
      },
    ],
    "gating_strategies_data": {
      "default_strategy": {
        "id": "default_strategy",
        "name": "Default Strategy",
        "description": "",
        "gates": [
          {
            "id": "positive",
            "name": "Positive",
            "gate_type": "range",
            "parent_population_id": "all_events",
            "x_parameter": "FSC",
            "thresholds": {"min": 1.5},
          },
        ],
        "is_default": True,
      },
    },
    "transforms": [],
    "statistics": [
      {
        "id": "stat_count",
        "name": "All Count",
        "population_id": "all_events",
        "metric": "count",
        "source_stage": "compensated",
      },
      {
        "id": "stat_mean",
        "name": "SSC Mean",
        "population_id": "all_events",
        "parameter_id": "SSC",
        "metric": "mean",
        "source_stage": "compensated",
      },
      {
        "id": "stat_pos_count",
        "name": "Positive Count",
        "population_id": "positive",
        "metric": "count",
        "source_stage": "compensated",
      },
    ],
    "execution_profiles": [
      {
        "id": "default",
        "name": "Default",
        "description": "",
        "is_default": True,
        "gate_strategy_id": "default_strategy",
        "include_display_only": False,
      },
    ],
    "gating_profile_id": "default",
  }

  project_path = tmp_path / "test.flowdesk"
  save_project(project_path, project)

  # Monkeypatch read_fcs_sample for CLI (injected via run_project module)
  monkeypatch.setattr(
    "flowdesk_cli.run_project.read_fcs_sample",
    lambda *_args: (None, sample_data),
  )

  # Core API export
  core_stats_path = tmp_path / "core-stats.tsv"
  runner = PipelineRunner(project)
  core_report = runner.run_samples(ExecutionContext(), (sample_data,))
  write_statistic_results(list(core_report.statistic_results), core_stats_path)

  # CLI export
  cli_stats_path = tmp_path / "cli-stats.tsv"
  exit_code = run_project_command(
    str(project_path),
    statistics_output=str(cli_stats_path),
  )
  assert exit_code == 0

  # Compare: read both files and verify values match
  with core_stats_path.open(encoding="utf-8") as fh:
    core_rows = list(csv.DictReader(fh, delimiter="\t"))
  with cli_stats_path.open(encoding="utf-8") as fh:
    cli_rows = list(csv.DictReader(fh, delimiter="\t"))

  assert len(core_rows) == len(cli_rows)

  core_map = {r["statistic_id"]: r for r in core_rows}
  cli_map = {r["statistic_id"]: r for r in cli_rows}

  for stat_id in core_map:
    assert stat_id in cli_map, f"Missing statistic {stat_id} in CLI export"
    core_r = core_map[stat_id]
    cli_r = cli_map[stat_id]
    assert core_r["value"] == cli_r["value"], (
      f"Value mismatch for {stat_id}: core={core_r['value']}, cli={cli_r['value']}"
    )
    assert core_r["status"] == cli_r["status"], (
      f"Status mismatch for {stat_id}: core={core_r['status']}, cli={cli_r['status']}"
    )
    assert core_r["metric"] == cli_r["metric"], (
      f"Metric mismatch for {stat_id}: core={core_r['metric']}, cli={cli_r['metric']}"
    )
