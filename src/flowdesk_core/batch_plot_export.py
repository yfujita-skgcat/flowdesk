"""Headless planning and execution for reproducible per-sample plot export."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flowdesk_core.annotations import resolve_sample_title
from flowdesk_core.models import AnnotationSpec, BatchPlotExportSpec


class BatchPlotExportError(ValueError):
  """Raised when a batch definition cannot be executed safely."""


def batch_plot_export_spec_from_mapping(value: Mapping[str, Any]) -> BatchPlotExportSpec:
  """Parse persisted JSON while normalizing list fields to typed tuples."""
  data = dict(value)
  data["sample_ids"] = tuple(data.get("sample_ids", ()))
  data["formats"] = tuple(data.get("formats", ("svg",)))
  return BatchPlotExportSpec(**data)


@dataclass(frozen=True)
class BatchPlotExportItem:
  sample_id: str
  sample_title: str
  output_paths: tuple[str, ...]
  status: str = "planned"
  diagnostic: str | None = None


@dataclass(frozen=True)
class BatchPlotExportReport:
  export_id: str
  status: str
  items: tuple[BatchPlotExportItem, ...]
  manifest_path: str | None = None


def plan_batch_plot_export(
  spec: BatchPlotExportSpec,
  samples: Sequence[Mapping[str, Any]],
  output_dir: str | Path,
  *,
  group_members: Mapping[str, Sequence[str]] | None = None,
  annotations: Sequence[Any] = (),
) -> tuple[BatchPlotExportItem, ...]:
  """Resolve targets and deterministic filenames without reading events."""
  sample_by_id = {str(sample.get("id", "")): sample for sample in samples}
  if len(sample_by_id) != len(samples):
    raise BatchPlotExportError("sample IDs must be unique for batch plot export")
  if spec.target == "all":
    target_ids = tuple(sample_by_id)
  elif spec.target == "explicit":
    target_ids = tuple(spec.sample_ids)
  else:
    target_ids = tuple((group_members or {}).get(spec.group_id or "", ()))
  unknown = [sample_id for sample_id in target_ids if sample_id not in sample_by_id]
  if unknown:
    raise BatchPlotExportError(f"batch target references unknown samples: {unknown!r}")
  output_root = Path(output_dir)
  typed_annotations = _typed_annotations(annotations)
  used: set[Path] = set()
  items: list[BatchPlotExportItem] = []
  for index, sample_id in enumerate(target_ids):
    sample = sample_by_id[sample_id]
    title = resolve_sample_title(
      sample_id,
      str(sample.get("name", "")),
      str(sample.get("path", "")),
      typed_annotations,
    )
    stem = _filename_stem(spec, sample, sample_id, title, index)
    paths: list[str] = []
    diagnostic: str | None = None
    for fmt in spec.formats:
      path = output_root / f"{stem}.{fmt}"
      if path in used:
        if spec.collision_policy == "fail":
          diagnostic = f"output collision: {path}"
          continue
        if spec.collision_policy == "suffix":
          path = _unique_suffix(path, used)
      used.add(path)
      paths.append(str(path))
    items.append(BatchPlotExportItem(
      sample_id, title, tuple(paths), "failed" if diagnostic else "planned", diagnostic
    ))
  return tuple(items)


def run_batch_plot_export(
  spec: BatchPlotExportSpec,
  samples: Sequence[Mapping[str, Any]],
  output_dir: str | Path,
  render: Callable[[Mapping[str, Any], Path, BatchPlotExportSpec], None],
  *,
  group_members: Mapping[str, Sequence[str]] | None = None,
  annotations: Sequence[Any] = (),
) -> BatchPlotExportReport:
  """Render each planned sample and persist per-file provenance plus a manifest."""
  items = plan_batch_plot_export(
    spec, samples, output_dir, group_members=group_members, annotations=annotations
  )
  output_root = Path(output_dir)
  output_root.mkdir(parents=True, exist_ok=True)
  completed: list[BatchPlotExportItem] = []
  for item in items:
    if item.status == "failed":
      completed.append(item)
      continue
    sample = next(sample for sample in samples if str(sample.get("id")) == item.sample_id)
    paths: list[str] = []
    diagnostic: str | None = None
    try:
      for path_text in item.output_paths:
        path = Path(path_text)
        if path.exists() and spec.collision_policy == "fail":
          raise BatchPlotExportError(f"output already exists: {path}")
        render(sample, path, spec)
        if not path.exists() or path.stat().st_size == 0:
          raise BatchPlotExportError(f"renderer produced no output: {path}")
        paths.append(str(path))
        sidecar = path.with_suffix(path.suffix + ".json")
        sidecar.write_text(json.dumps({
          "export_id": spec.id,
          "sample_id": item.sample_id,
          "sample_title": item.sample_title,
          "plot_view_id": spec.plot_view_id,
          "output": str(path),
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
      diagnostic = str(exc)
    completed.append(BatchPlotExportItem(
      item.sample_id, item.sample_title, tuple(paths),
      "success" if diagnostic is None else "failed", diagnostic,
    ))
  failures = [item for item in completed if item.status == "failed"]
  if failures and len(failures) == len(completed):
    status = "failed"
  elif failures:
    status = "partial_success"
  else:
    status = "success"
  manifest = output_root / f"{_safe_slug(spec.id)}.batch.json"
  manifest.write_text(json.dumps({
    "export_id": spec.id,
    "status": status,
    "items": [asdict(item) for item in completed],
  }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
  return BatchPlotExportReport(spec.id, status, tuple(completed), str(manifest))


def _filename_stem(
  spec: BatchPlotExportSpec,
  sample: Mapping[str, Any],
  sample_id: str,
  title: str,
  index: int,
) -> str:
  values = {
    "sample_id": sample_id,
    "sample_title": title,
    "sample_name": str(sample.get("name", sample_id)),
    "plot_id": spec.plot_view_id,
    "index": str(index),
  }
  try:
    rendered = spec.filename_template.format(**values)
  except (KeyError, ValueError) as exc:
    raise BatchPlotExportError(f"invalid filename template: {exc}") from exc
  return _safe_slug(rendered) or _safe_slug(f"{title}_{sample_id}")


def _safe_slug(value: str) -> str:
  value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
  return value.strip("._")


def _typed_annotations(values: Sequence[Any]) -> tuple[AnnotationSpec, ...]:
  result: list[AnnotationSpec] = []
  for value in values:
    if isinstance(value, AnnotationSpec):
      result.append(value)
    elif isinstance(value, Mapping):
      result.append(AnnotationSpec(
        str(value["sample_id"]), str(value["keyword"]), value.get("value"), value["source"]
      ))
    else:
      raise BatchPlotExportError("annotations must be AnnotationSpec or mappings")
  return tuple(result)


def _unique_suffix(path: Path, used: set[Path]) -> Path:
  index = 2
  candidate = path
  while candidate in used:
    candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
    index += 1
  return candidate
