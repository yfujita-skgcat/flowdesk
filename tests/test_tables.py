from __future__ import annotations

import pytest

from flowdesk_core.models import AnnotationSpec, StatisticResult
from flowdesk_core.table_runner import run_table_definition
from flowdesk_core.tables import (
  TableCell,
  TableColumnSpec,
  TableDefinitionSpec,
  TableResult,
  TableResultRow,
  table_definition_from_mapping,
)
from flowdesk_storage.manifest import ManifestValidationError, validate_manifest


def test_table_definition_round_trip_preserves_typed_contract() -> None:
  definition = TableDefinitionSpec(
    id="table-1",
    name="QC table",
    row_iterator="explicit_samples",
    sample_ids=("s2", "s1"),
    columns=(
      TableColumnSpec(id="sample", name="Sample", source="keyword", keyword="$FIL"),
      TableColumnSpec(id="events", name="Events", source="statistic", statistic_id="count"),
      TableColumnSpec(id="constant", name="Batch", source="constant", constant="A"),
    ),
    sort_column_id="events",
    sort_descending=True,
  )
  restored = table_definition_from_mapping(definition.to_mapping())
  assert restored == definition


def test_table_definition_rejects_invalid_source_and_sort() -> None:
  with pytest.raises(ValueError, match="source"):
    TableColumnSpec(id="x", name="X", source="unknown")  # type: ignore[arg-type]
  with pytest.raises(ValueError, match="sort column"):
    TableDefinitionSpec(
      id="table", name="Table",
      columns=(TableColumnSpec(id="x", name="X", source="constant", constant=1),),
      sort_column_id="missing",
    )


def test_table_result_distinguishes_undefined_and_error_cells() -> None:
  result = TableResult(
    definition_id="table",
    rows=(TableResultRow(
      row_key="s1",
      values=(
        TableCell(3),
        TableCell(None, status="undefined", reason="missing_keyword"),
        TableCell(None, status="error", reason="formula_cycle"),
      ),
    ),),
  )
  mapping = result.to_mapping()
  assert mapping["rows"][0]["values"][1]["status"] == "undefined"
  assert mapping["rows"][0]["values"][2]["status"] == "error"


def test_manifest_validates_optional_table_definitions() -> None:
  manifest = {
    "project_id": "project",
    "project_version": "0.1",
    "pipeline_version": "0.1",
    "samples": [],
    "table_definitions": [
      TableDefinitionSpec(
        id="table", name="Table",
        columns=(TableColumnSpec(id="x", name="X", source="constant", constant=1),),
      ).to_mapping(),
    ],
  }
  validate_manifest(manifest)
  manifest["table_definitions"][0]["columns"][0]["source"] = "unsafe"
  with pytest.raises(ManifestValidationError, match="table_definitions"):
    validate_manifest(manifest)


def test_table_runner_resolves_keyword_and_statistic_columns_in_sample_order() -> None:
  definition = TableDefinitionSpec(
    id="table", name="Table", row_iterator="explicit_samples",
    sample_ids=("s2", "s1"),
    columns=(
      TableColumnSpec(id="keyword", name="Condition", source="keyword", keyword="condition"),
      TableColumnSpec(id="stat", name="Count", source="statistic", statistic_id="count"),
    ),
  )
  result = run_table_definition(
    definition,
    ("s1", "s2"),
    annotations=(
      AnnotationSpec("s1", "condition", "old", "fcs"),
      AnnotationSpec("s1", "condition", "new", "workspace"),
    ),
    statistic_results=(
      StatisticResult("s1", "count", "all_events", "count", value=12),
      StatisticResult("s2", "count", "all_events", "count", value=8),
    ),
  )
  assert [row.row_key for row in result.rows] == ["s2", "s1"]
  assert result.rows[0].values[0].status == "undefined"
  assert result.rows[0].values[1].value == 8
  assert result.rows[1].values[0].value == "new"
  assert result.rows[1].values[1].value == 12


def test_table_runner_reports_missing_and_ambiguous_sources_without_shifting_columns() -> None:
  definition = TableDefinitionSpec(
    id="table", name="Table", row_iterator="explicit_samples", sample_ids=("missing",),
    columns=(
      TableColumnSpec(id="keyword", name="Keyword", source="keyword", keyword="x"),
      TableColumnSpec(id="stat", name="Stat", source="statistic", statistic_id="count"),
    ),
  )
  result = run_table_definition(
    definition, ("missing",),
    statistic_results=(
      StatisticResult("missing", "count", "p1", "count", value=1),
      StatisticResult("missing", "count", "p2", "count", value=2),
    ),
  )
  assert [cell.reason for cell in result.rows[0].values] == [
    "missing_keyword", "ambiguous_statistic",
  ]


def test_table_runner_uses_resolved_group_members_in_declared_order() -> None:
  definition = TableDefinitionSpec(
    id="table", name="Group table", row_iterator="group", group_id="g1",
    columns=(TableColumnSpec(id="x", name="X", source="constant", constant=1),),
  )
  result = run_table_definition(
    definition, ("s1", "s2", "s3"), group_members={"g1": ("s3", "s1")},
  )
  assert [row.row_key for row in result.rows] == ["s3", "s1"]


def test_group_table_requires_resolved_members() -> None:
  definition = TableDefinitionSpec(
    id="table", name="Group table", row_iterator="group", group_id="missing",
    columns=(TableColumnSpec(id="x", name="X", source="constant", constant=1),),
  )
  with pytest.raises(ValueError, match="not resolved"):
    run_table_definition(definition, (), group_members={})
