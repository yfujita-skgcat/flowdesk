from __future__ import annotations

import pytest

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
