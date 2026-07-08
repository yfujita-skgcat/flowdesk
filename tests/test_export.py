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
)
from flowdesk_core.models import ExportRecord, PopulationResult

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
