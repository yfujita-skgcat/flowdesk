"""Deterministic, non-destructive annotation table operations."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from pathlib import Path

from flowdesk_core.models import AnnotationSource, AnnotationSpec, AnnotationValue

SAMPLE_TITLE_KEYWORD = "sample_title"


def resolve_sample_title(
  sample_id: str,
  sample_name: str | None = None,
  path: str | None = None,
  annotations: Iterable[AnnotationSpec] = (),
) -> str:
  """Resolve a display-only title without changing sample identity or metadata.

  Workspace ``sample_title`` annotations take precedence.  Empty values are
  intentionally treated as an unset title so generated fallbacks are not
  persisted back into a project.
  """
  values: list[AnnotationValue] = []
  for annotation in annotations:
    if (
      annotation.sample_id == sample_id
      and annotation.keyword == SAMPLE_TITLE_KEYWORD
      and annotation.source == "workspace"
    ):
      values.append(annotation.value)
  if values:
    value = values[-1]
    if isinstance(value, str) and value.strip():
      return value.strip()
  for candidate in (sample_name, Path(path).stem if path else None, sample_id):
    if candidate and str(candidate).strip():
      return str(candidate).strip()
  return sample_id


def set_sample_title(
  annotations: Sequence[AnnotationSpec],
  sample_id: str,
  title: str | None,
) -> tuple[AnnotationSpec, ...]:
  """Return annotations with one workspace title for ``sample_id``.

  Clearing a title removes only the workspace title annotation and leaves FCS
  and imported values untouched.
  """
  result = [
    annotation for annotation in annotations
    if not (
      annotation.sample_id == sample_id
      and annotation.keyword == SAMPLE_TITLE_KEYWORD
      and annotation.source == "workspace"
    )
  ]
  normalized = "" if title is None else title.strip()
  if normalized:
    result.append(
      AnnotationSpec(sample_id, SAMPLE_TITLE_KEYWORD, normalized, "workspace")
    )
  return tuple(result)


def annotation_columns(annotations: Iterable[AnnotationSpec]) -> tuple[str, ...]:
  """Return stable keyword column order by first appearance."""
  seen: set[str] = set()
  columns: list[str] = []
  for annotation in annotations:
    if annotation.keyword not in seen:
      seen.add(annotation.keyword)
      columns.append(annotation.keyword)
  return tuple(columns)


def annotation_table(
  sample_ids: Sequence[str],
  annotations: Iterable[AnnotationSpec],
) -> tuple[dict[str, AnnotationValue], ...]:
  """Build rows in sample order; absent values are represented as ``None``."""
  values: dict[tuple[str, str], AnnotationValue] = {}
  value_ranks: dict[tuple[str, str], int] = {}
  ranks = {"fcs": 0, "imported": 1, "workspace": 2}
  for annotation in annotations:
    key = (annotation.sample_id, annotation.keyword)
    rank = ranks[annotation.source]
    if rank >= value_ranks.get(key, -1):
      values[key] = annotation.value
      value_ranks[key] = rank
  columns = annotation_columns(annotations)
  return tuple(
    {
      "sample_id": sample_id,
      **{keyword: values.get((sample_id, keyword)) for keyword in columns},
    }
    for sample_id in sample_ids
  )


def replace_annotation_values(
  annotations: Sequence[AnnotationSpec],
  keyword: str,
  old_value: AnnotationValue,
  new_value: AnnotationValue,
  *,
  source: AnnotationSource = "workspace",
) -> tuple[AnnotationSpec, ...]:
  """Replace matching values by adding a workspace-level annotation."""
  result = list(annotations)
  for annotation in annotations:
    if annotation.keyword == keyword and annotation.value == old_value:
      result.append(AnnotationSpec(annotation.sample_id, keyword, new_value, source))
  return tuple(result)


def fill_annotation_series(
  sample_ids: Sequence[str],
  keyword: str,
  start: int | float,
  step: int | float = 1,
  *,
  source: AnnotationSource = "workspace",
) -> tuple[AnnotationSpec, ...]:
  """Create a deterministic numeric series in the supplied sample order."""
  return tuple(
    AnnotationSpec(sample_id, keyword, start + index * step, source)
    for index, sample_id in enumerate(sample_ids)
  )


def parse_annotation_csv(
  text: str,
  *,
  sample_id_column: str = "sample_id",
  source: AnnotationSource = "imported",
) -> tuple[AnnotationSpec, ...]:
  """Parse CSV annotation columns without touching source FCS metadata."""
  reader = csv.DictReader(io.StringIO(text))
  if not reader.fieldnames or sample_id_column not in reader.fieldnames:
    raise ValueError(f"CSV must contain {sample_id_column!r} column")
  result: list[AnnotationSpec] = []
  for row_index, row in enumerate(reader, start=2):
    sample_id = (row.get(sample_id_column) or "").strip()
    if not sample_id:
      raise ValueError(f"CSV row {row_index} has an empty sample ID")
    for keyword, raw_value in row.items():
      if keyword == sample_id_column or raw_value in (None, ""):
        continue
      result.append(
        AnnotationSpec(sample_id, keyword, _parse_scalar(raw_value), source)
      )
  return tuple(result)


def _parse_scalar(value: str) -> AnnotationValue:
  lowered = value.strip().lower()
  if lowered == "true":
    return True
  if lowered == "false":
    return False
  try:
    return int(value)
  except ValueError:
    try:
      return float(value)
    except ValueError:
      return value
