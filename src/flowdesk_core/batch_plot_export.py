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


@dataclass(frozen=True)
class WellResolution:
  """A normalized well identifier and how it was obtained."""

  value: str | None
  source: str | None


def batch_plot_export_spec_from_mapping(value: Mapping[str, Any]) -> BatchPlotExportSpec:
  """Parse persisted JSON while normalizing list fields to typed tuples."""
  data = dict(value)
  data["sample_ids"] = tuple(data.get("sample_ids", ()))
  data["formats"] = tuple(data.get("formats", ("png",)))
  return BatchPlotExportSpec(**data)


@dataclass(frozen=True)
class BatchPlotExportItem:
  sample_id: str
  sample_title: str
  output_paths: tuple[str, ...]
  status: str = "planned"
  diagnostic: str | None = None
  source_sample_ids: tuple[str, ...] = ()
  well_ids: tuple[str, ...] = ()
  well_sources: tuple[str, ...] = ()


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
  overlay_sample_ids: Mapping[str, Sequence[str]] | None = None,
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
    source_ids = _source_ids(sample_id, overlay_sample_ids)
    unknown_sources = [source_id for source_id in source_ids if source_id not in sample_by_id]
    if unknown_sources:
      raise BatchPlotExportError(
        f"overlay references unknown samples: {unknown_sources!r}"
      )
    source_samples = [sample_by_id[source_id] for source_id in source_ids]
    wells = tuple(
      resolution for source_sample in source_samples
      if (resolution := resolve_sample_well(source_sample)).value is not None
    )
    stem = _filename_stem(
      spec, sample, sample_id, title, index,
      source_sample_ids=source_ids, well_resolutions=wells,
    )
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
      sample_id, title, tuple(paths), "failed" if diagnostic else "planned", diagnostic,
      source_ids, tuple(item.value for item in wells if item.value is not None),
      tuple(item.source for item in wells if item.source),
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
  overlay_sample_ids: Mapping[str, Sequence[str]] | None = None,
) -> BatchPlotExportReport:
  """Render each planned sample and persist per-file provenance plus a manifest."""
  items = plan_batch_plot_export(
    spec, samples, output_dir, group_members=group_members, annotations=annotations,
    overlay_sample_ids=overlay_sample_ids,
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
          "source_sample_ids": item.source_sample_ids,
          "well_ids": item.well_ids,
          "well_sources": item.well_sources,
          "export_options": asdict(spec),
          "plot_view_id": spec.plot_view_id,
          "output": str(path),
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
      diagnostic = str(exc)
    completed.append(BatchPlotExportItem(
      item.sample_id, item.sample_title, tuple(paths),
      "success" if diagnostic is None else "failed", diagnostic,
      item.source_sample_ids, item.well_ids, item.well_sources,
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
    "export_options": asdict(spec),
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
  *,
  source_sample_ids: Sequence[str] = (),
  well_resolutions: Sequence[WellResolution] = (),
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
  rendered = _safe_slug(rendered) or _safe_slug(f"{title}_{sample_id}")
  well_ids = tuple(dict.fromkeys(item.value for item in well_resolutions if item.value))
  if well_ids:
    return _safe_slug("_".join((*well_ids, rendered)))
  if len(source_sample_ids) > 1:
    return _safe_slug("_".join((*source_sample_ids, rendered)))
  return rendered


def resolve_sample_well(sample: Mapping[str, Any]) -> WellResolution:
  """Resolve a stable well ID without depending on the host operating system."""
  for key in ("well", "well_id"):
    resolved = _normalize_well(sample.get(key))
    if resolved:
      return WellResolution(resolved, f"sample.{key}")
  metadata = sample.get("metadata")
  if isinstance(metadata, Mapping):
    for key in ("well", "well_id"):
      resolved = _normalize_well(metadata.get(key))
      if resolved:
        return WellResolution(resolved, f"metadata.{key}")
  path = str(sample.get("path", ""))
  filename = path.replace("\\", "/").rsplit("/", 1)[-1]
  tokens = tuple(dict.fromkeys(
    _normalize_well(match) for match in _WELL_TOKEN_RE.findall(filename)
  ))
  tokens = tuple(token for token in tokens if token)
  if len(tokens) == 1:
    return WellResolution(tokens[0], "filename_token")
  if len(tokens) > 1:
    return WellResolution(None, "ambiguous_filename_tokens")
  return WellResolution(None, None)


_WELL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Pa-p](?:0?[1-9]|[1-9][0-9]))(?![A-Za-z0-9])")


def _normalize_well(value: Any) -> str | None:
  if not isinstance(value, str):
    return None
  match = re.fullmatch(r"([A-Pa-p]{1,3})0*([1-9][0-9]{0,2})", value.strip())
  if not match:
    return None
  return f"{match.group(1).upper()}{int(match.group(2))}"


def _source_ids(
  sample_id: str,
  overlay_sample_ids: Mapping[str, Sequence[str]] | None,
) -> tuple[str, ...]:
  values = (sample_id, *((overlay_sample_ids or {}).get(sample_id, ())))
  return tuple(dict.fromkeys(str(value) for value in values))


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
