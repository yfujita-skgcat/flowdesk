"""Headless execution for the first Table Editor increment."""

from __future__ import annotations

import ast
import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real
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
  group_members: Mapping[str, Sequence[str]] | None = None,
) -> TableResult:
  """Resolve keyword/statistic columns for explicit sample rows.

  This runner consumes already-authoritative pipeline values.  It never reads
  Qt cells, display samples, or raw FCS data, and it returns one cell per
  definition column even when a source is missing or ambiguous.
  """
  available_ids = tuple(str(value) for value in sample_ids)
  if definition.row_iterator == "samples":
    rows = available_ids
  elif definition.row_iterator == "explicit_samples":
    rows = definition.sample_ids
  else:
    if group_members is None or definition.group_id not in group_members:
      raise ValueError(f"table group {definition.group_id!r} is not resolved")
    rows = tuple(str(value) for value in group_members[definition.group_id])
  annotation_values = _annotation_values(annotations)
  statistic_values = _statistic_values(statistic_results)
  column_order = _column_evaluation_order(definition.columns)
  result_rows = tuple(
    _resolve_row(
      definition, sample_id, sample_id in available_ids,
      annotation_values, statistic_values, column_order,
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


def _column_evaluation_order(
  columns: Sequence[TableColumnSpec],
) -> tuple[str, ...]:
  """Return a deterministic dependency order and reject unsafe/cyclic formulas."""
  by_id = {column.id: column for column in columns}
  dependencies: dict[str, tuple[str, ...]] = {}
  for column in columns:
    if column.source != "formula":
      dependencies[column.id] = ()
      continue
    try:
      tree = ast.parse(str(column.formula), mode="eval")
    except SyntaxError as exc:
      raise ValueError(f"invalid formula for column {column.id!r}: {exc.msg}") from exc
    names = tuple(dict.fromkeys(node.id for node in ast.walk(tree) if isinstance(node, ast.Name)))
    unknown = tuple(name for name in names if name not in by_id)
    if unknown:
      raise ValueError(f"formula column {column.id!r} references unknown columns {unknown!r}")
    dependencies[column.id] = names
  visiting: set[str] = set()
  visited: set[str] = set()
  order: list[str] = []

  def visit(column_id: str) -> None:
    if column_id in visiting:
      raise ValueError("table formula dependency cycle")
    if column_id in visited:
      return
    visiting.add(column_id)
    for dependency in dependencies[column_id]:
      visit(dependency)
    visiting.remove(column_id)
    visited.add(column_id)
    order.append(column_id)

  for column in columns:
    visit(column.id)
  return tuple(order)


def _resolve_row(
  definition: TableDefinitionSpec,
  sample_id: str,
  sample_exists: bool,
  annotations: dict[tuple[str, str], Any],
  statistics: dict[tuple[str, str], tuple[StatisticResult, ...]],
  column_order: Sequence[str],
) -> TableResultRow:
  by_id = {column.id: column for column in definition.columns}
  cells: dict[str, TableCell] = {}
  for column_id in column_order:
    column = by_id[column_id]
    if column.source != "formula":
      cells[column_id] = _resolve_cell(
        column, sample_id, sample_exists, annotations, statistics,
      )
      continue
    dependencies = {
      name: cells[name]
      for name in _formula_names(str(column.formula))
    }
    if any(cell.status != "ok" for cell in dependencies.values()):
      status = (
        "undefined"
        if any(cell.status == "undefined" for cell in dependencies.values())
        else "error"
      )
      cells[column_id] = TableCell(
        None, status=status, reason="formula_dependency_undefined"
        if status == "undefined" else "formula_dependency_error",
      )
      continue
    try:
      value = _evaluate_formula(str(column.formula), {
        name: cell.value for name, cell in dependencies.items()
      })
      cells[column_id] = TableCell(value)
    except (ArithmeticError, TypeError, ValueError, SyntaxError):
      cells[column_id] = TableCell(None, status="error", reason="formula_error")
  return TableResultRow(
    row_key=sample_id,
    values=tuple(cells[column.id] for column in definition.columns),
  )


def _formula_names(expression: str) -> tuple[str, ...]:
  tree = ast.parse(expression, mode="eval")
  return tuple(dict.fromkeys(node.id for node in ast.walk(tree) if isinstance(node, ast.Name)))


def _evaluate_formula(expression: str, values: Mapping[str, Any]) -> int | float:
  tree = ast.parse(expression, mode="eval")

  def evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
      return evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
      and not isinstance(node.value, bool):
      return node.value
    if isinstance(node, ast.Name):
      value = values[node.id]
      if not isinstance(value, Real) or isinstance(value, bool):
        raise TypeError("formula operands must be numeric")
      return value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
      operand = evaluate(node.operand)
      return +operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp) and isinstance(
      node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
    ):
      left, right = evaluate(node.left), evaluate(node.right)
      if isinstance(node.op, ast.Add):
        return left + right
      if isinstance(node.op, ast.Sub):
        return left - right
      if isinstance(node.op, ast.Mult):
        return left * right
      if isinstance(node.op, ast.Div):
        return left / right
      if isinstance(node.op, ast.Mod):
        return left % right
      return left ** right
    raise ValueError("formula contains an unsupported expression")

  result = evaluate(tree)
  if not math.isfinite(float(result)):
    raise ValueError("formula result must be finite")
  return result
