"""Qt-independent persisted table definitions and typed result rows.

This module intentionally contains no table execution or GUI code.  Later
increments can add a runner that resolves these stable definitions from the
authoritative pipeline report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

TableRowIterator = Literal["samples", "explicit_samples"]
TableColumnSource = Literal[
  "keyword", "statistic", "platform_result", "formula", "constant"
]
TableCellStatus = Literal["ok", "undefined", "error"]


def _non_empty(value: Any, label: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"table {label} must be a non-empty string")
  return value


def _unique_strings(values: Sequence[Any], label: str) -> tuple[str, ...]:
  result = tuple(_non_empty(value, label) for value in values)
  if len(set(result)) != len(result):
    raise ValueError(f"table {label} must not contain duplicates")
  return result


@dataclass(frozen=True)
class TableColumnSpec:
  """A typed table column definition; formatting never changes its value."""

  id: str
  name: str
  source: TableColumnSource
  keyword: str | None = None
  statistic_id: str | None = None
  platform_result: str | None = None
  formula: str | None = None
  constant: int | float | str | bool | None = None
  hidden: bool = False
  number_format: str | None = None

  def __post_init__(self) -> None:
    _non_empty(self.id, "column id")
    _non_empty(self.name, "column name")
    if self.source not in {
      "keyword", "statistic", "platform_result", "formula", "constant",
    }:
      raise ValueError(f"invalid table column source: {self.source!r}")
    required = {
      "keyword": self.keyword,
      "statistic": self.statistic_id,
      "platform_result": self.platform_result,
      "formula": self.formula,
    }
    selected = required.get(self.source)
    if self.source != "constant" and (not isinstance(selected, str) or not selected.strip()):
      raise ValueError(f"table column source {self.source!r} requires a value")
    if self.source == "constant" and any(value is not None for value in required.values()):
      raise ValueError("constant table column must not define another source value")
    if not isinstance(self.hidden, bool):
      raise ValueError("table column hidden must be a boolean")

  def to_mapping(self) -> dict[str, Any]:
    return {
      "id": self.id,
      "name": self.name,
      "source": self.source,
      "keyword": self.keyword,
      "statistic_id": self.statistic_id,
      "platform_result": self.platform_result,
      "formula": self.formula,
      "constant": self.constant,
      "hidden": self.hidden,
      "number_format": self.number_format,
    }


@dataclass(frozen=True)
class TableDefinitionSpec:
  """Persisted table layout and row-selection contract."""

  id: str
  name: str
  row_iterator: TableRowIterator = "samples"
  sample_ids: tuple[str, ...] = field(default_factory=tuple)
  columns: tuple[TableColumnSpec, ...] = field(default_factory=tuple)
  filter_expression: str | None = None
  sort_column_id: str | None = None
  sort_descending: bool = False

  def __post_init__(self) -> None:
    _non_empty(self.id, "definition id")
    _non_empty(self.name, "definition name")
    if self.row_iterator not in {"samples", "explicit_samples"}:
      raise ValueError(f"invalid table row iterator: {self.row_iterator!r}")
    sample_ids = _unique_strings(self.sample_ids, "sample IDs")
    if self.row_iterator == "explicit_samples" and not sample_ids:
      raise ValueError("explicit_samples table iterator requires sample IDs")
    if not self.columns:
      raise ValueError("table definition requires at least one column")
    column_ids = _unique_strings(tuple(column.id for column in self.columns), "column IDs")
    if self.sort_column_id is not None and self.sort_column_id not in column_ids:
      raise ValueError("table sort column must reference a defined column")
    if not isinstance(self.sort_descending, bool):
      raise ValueError("table sort_descending must be a boolean")
    object.__setattr__(self, "sample_ids", sample_ids)

  def to_mapping(self) -> dict[str, Any]:
    return {
      "id": self.id,
      "name": self.name,
      "row_iterator": self.row_iterator,
      "sample_ids": list(self.sample_ids),
      "columns": [column.to_mapping() for column in self.columns],
      "filter_expression": self.filter_expression,
      "sort_column_id": self.sort_column_id,
      "sort_descending": self.sort_descending,
    }


@dataclass(frozen=True)
class TableCell:
  """A typed result cell; undefined and error are not conflated with null."""

  value: int | float | str | bool | None
  status: TableCellStatus = "ok"
  reason: str | None = None

  def __post_init__(self) -> None:
    if self.status not in {"ok", "undefined", "error"}:
      raise ValueError(f"invalid table cell status: {self.status!r}")
    if self.status == "ok" and self.reason is not None:
      raise ValueError("successful table cell must not have a reason")
    if self.status != "ok" and not self.reason:
      raise ValueError("undefined/error table cell requires a reason")

  def to_mapping(self) -> dict[str, Any]:
    return {"value": self.value, "status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class TableResultRow:
  """One deterministic row produced by a future table runner."""

  row_key: str
  values: tuple[TableCell, ...]

  def __post_init__(self) -> None:
    _non_empty(self.row_key, "row key")

  def to_mapping(self) -> dict[str, Any]:
    return {"row_key": self.row_key, "values": [cell.to_mapping() for cell in self.values]}


@dataclass(frozen=True)
class TableResult:
  """Serializable result container kept separate from display formatting."""

  definition_id: str
  rows: tuple[TableResultRow, ...] = field(default_factory=tuple)

  def __post_init__(self) -> None:
    _non_empty(self.definition_id, "result definition ID")

  def to_mapping(self) -> dict[str, Any]:
    return {
      "definition_id": self.definition_id,
      "rows": [row.to_mapping() for row in self.rows],
    }


def table_column_from_mapping(value: Mapping[str, Any]) -> TableColumnSpec:
  """Parse one persisted table column without executing any expression."""
  return TableColumnSpec(
    id=str(value.get("id", "")),
    name=str(value.get("name", "")),
    source=value.get("source", "constant"),
    keyword=value.get("keyword"),
    statistic_id=value.get("statistic_id"),
    platform_result=value.get("platform_result"),
    formula=value.get("formula"),
    constant=value.get("constant"),
    hidden=value.get("hidden", False),
    number_format=value.get("number_format"),
  )


def table_definition_from_mapping(value: Mapping[str, Any]) -> TableDefinitionSpec:
  """Parse a persisted table definition with strict typed validation."""
  columns = value.get("columns", ())
  if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)):
    raise ValueError("table definition columns must be an array")
  return TableDefinitionSpec(
    id=str(value.get("id", "")),
    name=str(value.get("name", "")),
    row_iterator=value.get("row_iterator", "samples"),
    sample_ids=tuple(value.get("sample_ids", ())),
    columns=tuple(table_column_from_mapping(column) for column in columns),
    filter_expression=value.get("filter_expression"),
    sort_column_id=value.get("sort_column_id"),
    sort_descending=value.get("sort_descending", False),
  )

