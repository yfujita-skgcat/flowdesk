"""Headless execution for the first Table Editor increment."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from flowdesk_core.models import AnnotationSpec, StatisticResult
from flowdesk_core.tables import (
  TableCell,
  TableColumnSpec,
  TableDefinitionSpec,
  TableResult,
  TableResultRow,
)


def run_table_definition(
  definition: TableDefinitionSpec,
  sample_ids: Sequence[str],
  annotations: Iterable[AnnotationSpec] = (),
  statistic_results: Iterable[StatisticResult] = (),
) -> TableResult:
  """Resolve keyword/statistic columns for explicit sample rows.

  This runner consumes already-authoritative pipeline values.  It never reads
  Qt cells, display samples, or raw FCS data, and it returns one cell per
  definition column even when a source is missing or ambiguous.
  """
  available_ids = tuple(str(value) for value in sample_ids)
  rows = (
    available_ids
    if definition.row_iterator == "samples"
    else definition.sample_ids
  )
  annotation_values = _annotation_values(annotations)
  statistic_values = _statistic_values(statistic_results)
  result_rows = tuple(
    TableResultRow(
      row_key=sample_id,
      values=tuple(
        _resolve_cell(
          column, sample_id, sample_id in available_ids,
          annotation_values, statistic_values,
        )
        for column in definition.columns
      ),
    )
    for sample_id in rows
  )
  return TableResult(definition_id=definition.id, rows=result_rows)


def _annotation_values(
  annotations: Iterable[AnnotationSpec],
) -> dict[tuple[str, str], Any]:
  ranks = {"fcs": 0, "imported": 1, "workspace": 2}
  values: dict[tuple[str, str], tuple[int, Any]] = {}
  for annotation in annotations:
    key = (annotation.sample_id, annotation.keyword)
    rank = ranks[annotation.source]
    if rank >= values.get(key, (-1, None))[0]:
      values[key] = (rank, annotation.value)
  return {key: value for key, (_rank, value) in values.items()}


def _statistic_values(
  results: Iterable[StatisticResult],
) -> dict[tuple[str, str], tuple[StatisticResult, ...]]:
  grouped: dict[tuple[str, str], list[StatisticResult]] = {}
  for result in results:
    grouped.setdefault((result.sample_id, result.statistic_id), []).append(result)
  return {key: tuple(value) for key, value in grouped.items()}


def _resolve_cell(
  column: TableColumnSpec,
  sample_id: str,
  sample_exists: bool,
  annotations: dict[tuple[str, str], Any],
  statistics: dict[tuple[str, str], tuple[StatisticResult, ...]],
) -> TableCell:
  if not sample_exists:
    return TableCell(None, status="undefined", reason="missing_sample")
  if column.source == "constant":
    return TableCell(column.constant)
  if column.source == "keyword":
    key = (sample_id, str(column.keyword))
    if key not in annotations:
      return TableCell(None, status="undefined", reason="missing_keyword")
    return TableCell(annotations[key])
  if column.source == "statistic":
    values = statistics.get((sample_id, str(column.statistic_id)), ())
    if not values:
      return TableCell(None, status="undefined", reason="missing_statistic")
    if len(values) > 1:
      return TableCell(None, status="error", reason="ambiguous_statistic")
    statistic = values[0]
    if statistic.status == "ok":
      return TableCell(statistic.value)
    if statistic.status in {"empty", "undefined"}:
      return TableCell(
        None, status="undefined",
        reason=statistic.undefined_reason or statistic.status,
      )
    return TableCell(None, status="error", reason="statistic_error")
  return TableCell(None, status="error", reason="unsupported_column_source")

