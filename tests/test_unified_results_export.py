"""Tests for unified Results export and population full paths."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.export import (
  build_results_wide_rows,
  results_long_to_text,
  results_wide_to_text,
  write_results_long,
  write_results_wide,
)
from flowdesk_core.gating_strategy import GatingStrategyError
from flowdesk_core.models import GateSpec, PopulationResult, StatisticResult
from flowdesk_core.populations import build_population_paths


def _project() -> dict:
  gates = [
    GateSpec("live", "Live", "range", "all_events", x_parameter="FSC-A"),
    GateSpec("gfp_pos", "GFP+", "range", "live", x_parameter="FSC-A"),
    GateSpec("gfp_neg", "GFP-", "range", "live", x_parameter="FSC-A"),
    GateSpec("cd44", "CD44+", "range", "gfp_neg", x_parameter="FSC-A"),
  ]
  return {
    "project_id": "p",
    "project_version": "1.0.0",
    "pipeline_version": "0.1",
    "samples": [{"id": "s1", "name": "Sample one", "path": "/tmp/s1.fcs"}],
    "annotations": [],
    "execution_profiles": [{
      "id": "default", "gating_strategy_id": "strategy",
      "sample_selector": "all",
    }],
    "gating_strategies_data": {"strategy": {
      "id": "strategy", "name": "Strategy", "root_population_id": "all_events",
      "gates": [gate.__dict__ for gate in gates],
    }},
    "statistics": [{"id": "mean", "name": "FSC-A Mean"}],
  }


def _report() -> ExecutionReport:
  return ExecutionReport(
    project_id="p", execution_profile_id="default", pipeline_version="0.1",
    status="success",
    population_results=(
      PopulationResult("s1", "all_events", 100, None, 1.0),
      PopulationResult("s1", "live", 50, 0.5, 0.5),
      PopulationResult("s1", "gfp_pos", 10, 0.2, 0.1),
      PopulationResult("s1", "gfp_neg", 40, 0.8, 0.4),
      PopulationResult("s1", "cd44", 20, 0.5, 0.2),
    ),
    statistic_results=(
      StatisticResult(
        "s1", "mean", "gfp_pos", "mean", 594405.6,
        statistic_name="FSC-A Mean",
      ),
    ),
  )


def test_population_paths_use_ids_and_saved_preorder() -> None:
  project = _project()
  gates = tuple(GateSpec(**gate) for gate in project["gating_strategies_data"]["strategy"]["gates"])
  assert build_population_paths(gates) == {
    "all_events": "All Events",
    "live": "All Events/Live",
    "gfp_pos": "All Events/Live/GFP+",
    "gfp_neg": "All Events/Live/GFP-",
    "cd44": "All Events/Live/GFP-/CD44+",
  }
  rows = build_results_wide_rows(_report(), project)
  assert [row.population_id for row in rows] == [
    "all_events", "live", "gfp_pos", "gfp_neg", "cd44",
  ]


def test_population_path_rejects_cycle() -> None:
  gates = (
    GateSpec("a", "A", "range", "b", x_parameter="FSC-A"),
    GateSpec("b", "B", "range", "a", x_parameter="FSC-A"),
  )
  with pytest.raises(GatingStrategyError, match="cycle"):
    build_population_paths(gates)


def test_unified_wide_export_combines_metrics_and_statistics(tmp_path: Path) -> None:
  path = tmp_path / "results.tsv"
  write_results_wide(_report(), _project(), path)
  with path.open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
  assert rows[0]["Population"] == "All Events"
  assert rows[0]["% Parent"] == ""
  assert rows[0]["% Total"] == "100.0"
  assert rows[2]["Population"] == "All Events/Live/GFP+"
  assert rows[2]["% Parent"] == "20.0"
  assert rows[2]["FSC-A Mean"] == "594405.6"


def test_unified_long_export_contains_both_result_types(tmp_path: Path) -> None:
  path = tmp_path / "results.tsv"
  write_results_long(_report(), _project(), path, include_internal_ids=True)
  with path.open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
  assert {row["Result Type"] for row in rows} == {"population", "statistic"}
  statistic = next(row for row in rows if row["Result Type"] == "statistic")
  assert statistic["Population"] == "All Events/Live/GFP+"
  assert statistic["Population ID"] == "gfp_pos"


def test_results_text_helpers_match_delimited_writer(tmp_path: Path) -> None:
  project = _project()
  report = _report()
  wide_path = tmp_path / "wide.tsv"
  long_path = tmp_path / "long.tsv"
  write_results_wide(report, project, wide_path)
  write_results_long(report, project, long_path)
  assert results_wide_to_text(report, project).replace("\r\n", "\n") == wide_path.read_text()
  assert results_long_to_text(report, project).replace("\r\n", "\n") == long_path.read_text()


def test_export_resolves_strategy_per_sample() -> None:
  project = _project()
  project["samples"].append({"id": "s2", "name": "Sample two", "path": "/tmp/s2.fcs"})
  project["gating_strategies_data"]["other"] = {
    "id": "other", "name": "Other", "gates": [{
      "id": "dead", "name": "Dead", "gate_type": "range",
      "parent_population_id": "all_events", "x_parameter": "FSC-A",
    }],
  }
  project["sample_groups"] = [
    {"id": "g1", "name": "G1", "sample_ids": ["s1"]},
    {"id": "g2", "name": "G2", "sample_ids": ["s2"]},
  ]
  project["group_strategy_bindings"] = [
    {"id": "b1", "group_id": "g1", "gating_strategy_id": "strategy"},
    {"id": "b2", "group_id": "g2", "gating_strategy_id": "other"},
  ]
  report = ExecutionReport(
    project_id="p", execution_profile_id="default", pipeline_version="0.1",
    status="success",
    population_results=(
      PopulationResult("s1", "all_events", 1, None, 1.0),
      PopulationResult("s1", "live", 1, 1.0, 1.0),
      PopulationResult("s2", "all_events", 1, None, 1.0),
      PopulationResult("s2", "dead", 1, 1.0, 1.0),
    ),
  )
  rows = build_results_wide_rows(report, project)
  assert [(row.sample_id, row.population_path) for row in rows] == [
    ("s1", "All Events"), ("s1", "All Events/Live"),
    ("s2", "All Events"), ("s2", "All Events/Dead"),
  ]


def test_duplicate_statistic_display_names_get_stable_headers(tmp_path: Path) -> None:
  project = _project()
  project["statistics"] = [
    {"id": "mean_raw", "name": "Mean"},
    {"id": "mean_comp", "name": "Mean"},
  ]
  report = _report()
  report = ExecutionReport(
    project_id=report.project_id,
    execution_profile_id=report.execution_profile_id,
    pipeline_version=report.pipeline_version,
    status=report.status,
    population_results=report.population_results,
    statistic_results=(
      StatisticResult("s1", "mean_raw", "live", "mean", 1.0, statistic_name="Mean"),
      StatisticResult("s1", "mean_comp", "live", "mean", 2.0, statistic_name="Mean"),
    ),
  )
  path = tmp_path / "duplicate.tsv"
  write_results_wide(report, project, path)
  with path.open(encoding="utf-8") as handle:
    header = next(csv.reader(handle, delimiter="\t"))
  assert "Mean" in header
  assert "Mean [mean_comp]" in header
