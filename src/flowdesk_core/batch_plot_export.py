"""Headless planning and execution for reproducible per-sample plot export."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flowdesk_core.annotations import resolve_sample_title
from flowdesk_core.execution_control import (
  ExecutionCancelled,
  ExecutionControl,
  ProgressEvent,
)
from flowdesk_core.models import AnnotationSpec, BatchPlotExportSpec
from flowdesk_core.plot_export import resolve_export_canvas


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
  # Definitions written before lightweight vector scatter support retain the
  # historical one-object-per-event SVG/PDF representation.
  data.setdefault("vector_scatter_mode", "full_vector")
  data.setdefault("hybrid_scatter_dpi", 600)
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
  preflight: dict[str, Any] | None = None,
  prepare: Callable[[], None] | None = None,
  execution_control: ExecutionControl | None = None,
) -> BatchPlotExportReport:
  """Render planned outputs sequentially with optional preparation/progress control.

  ``prepare`` owns shared source loading, display preparation, shared-range
  resolution, and renderer preflight.  It runs once before the first output,
  leaving ``render`` to build one already-prepared output.  Final files and
  sidecars are published only through same-directory atomic replacement.
  """
  items = plan_batch_plot_export(
    spec, samples, output_dir, group_members=group_members, annotations=annotations,
    overlay_sample_ids=overlay_sample_ids,
  )
  output_root = Path(output_dir)
  output_root.mkdir(parents=True, exist_ok=True)
  sample_by_id = {str(sample.get("id")): sample for sample in samples}
  total_units = sum(len(item.output_paths) for item in items if item.status != "failed")
  operation_id = (
    execution_control.begin_operation("batch_plot_export")
    if execution_control is not None else "batch_plot_export"
  )
  completed_units = 0

  def progress(
    phase: str,
    *,
    sample_id: str | None = None,
    output_path: str | None = None,
    message: str | None = None,
  ) -> None:
    if execution_control is None:
      return
    execution_control.emit_progress(ProgressEvent(
      operation_id=operation_id,
      operation="batch_plot_export",
      phase=phase,
      completed_units=completed_units,
      total_units=total_units,
      sample_id=sample_id,
      output_path=output_path,
      message=message,
    ))

  progress("planning")
  preparation_error: str | None = None
  cancelled = False
  try:
    if execution_control is not None:
      execution_control.cancellation_token.raise_if_cancelled()
    if prepare is not None:
      progress("preparing_sources")
      prepare()
      if execution_control is not None:
        execution_control.cancellation_token.raise_if_cancelled()
  except ExecutionCancelled:
    cancelled = True
  except Exception as exc:
    preparation_error = str(exc)

  completed: list[BatchPlotExportItem] = []
  cancellation_recorded = False
  for item_index, item in enumerate(items):
    if item.status == "failed":
      completed.append(item)
      continue
    if (
      execution_control is not None
      and execution_control.cancellation_token.is_cancelled()
    ):
      cancelled = True
    if cancelled:
      has_published_output = any(existing.status == "success" for existing in completed)
      status = (
        "cancelled"
        if not cancellation_recorded and not has_published_output
        else "not_started"
      )
      completed.append(_replace_item_status(item, status))
      cancellation_recorded = True
      continue
    if preparation_error is not None:
      completed.append(_replace_item_status(item, "failed", preparation_error))
      continue
    sample = sample_by_id[item.sample_id]
    paths: list[str] = []
    diagnostic: str | None = None
    try:
      for path_text in item.output_paths:
        if execution_control is not None:
          execution_control.cancellation_token.raise_if_cancelled()
        path = Path(path_text)
        if path.exists() and spec.collision_policy == "fail":
          raise BatchPlotExportError(f"output already exists: {path}")
        staged_path = _staged_output_path(path)
        staged_sidecar = staged_path.with_suffix(staged_path.suffix + ".json")
        try:
          render(sample, staged_path, spec)
          if not staged_path.exists() or staged_path.stat().st_size == 0:
            raise BatchPlotExportError(f"renderer produced no output: {path}")
          _write_sidecar(
            staged_path, item, spec,
            final_output_path=path,
          )
          progress("writing_sidecars", sample_id=item.sample_id, output_path=str(path))
          staged_path.replace(path)
          staged_sidecar.replace(path.with_suffix(path.suffix + ".json"))
        except Exception:
          staged_path.unlink(missing_ok=True)
          staged_sidecar.unlink(missing_ok=True)
          raise
        paths.append(str(path))
        completed_units += 1
        progress("rendering", sample_id=item.sample_id, output_path=str(path))
      completed.append(BatchPlotExportItem(
        item.sample_id, item.sample_title, tuple(paths), "success", None,
        item.source_sample_ids, item.well_ids, item.well_sources,
      ))
    except ExecutionCancelled:
      cancelled = True
      cancellation_recorded = True
      completed.append(BatchPlotExportItem(
        item.sample_id, item.sample_title, tuple(paths),
        "cancelled" if not paths else "success", None,
        item.source_sample_ids, item.well_ids, item.well_sources,
      ))
    except Exception as exc:
      diagnostic = str(exc)
      completed.append(BatchPlotExportItem(
        item.sample_id, item.sample_title, tuple(paths), "failed", diagnostic,
        item.source_sample_ids, item.well_ids, item.well_sources,
      ))
    if cancelled:
      for remainder in items[item_index + 1:]:
        if remainder.status == "failed":
          completed.append(remainder)
        else:
          completed.append(_replace_item_status(remainder, "not_started"))
      break
  failures = [item for item in completed if item.status == "failed"]
  successes = [item for item in completed if item.status == "success"]
  if cancelled:
    status = "partial_cancelled" if successes else "cancelled"
  elif failures and len(failures) == len(completed):
    status = "failed"
  elif failures:
    status = "partial_success"
  else:
    status = "success"
  manifest = output_root / f"{_safe_slug(spec.id)}.batch.json"
  progress("finalizing_manifest")
  _write_json_atomically(manifest, {
    "export_id": spec.id,
    "export_options": asdict(spec),
    "export_canvas": resolve_export_canvas(spec).to_mapping(),
    "vector_scatter_preflight": (preflight or {}).get("value"),
    "status": status,
    "items": [asdict(item) for item in completed],
  })
  return BatchPlotExportReport(spec.id, status, tuple(completed), str(manifest))


def _replace_item_status(
  item: BatchPlotExportItem, status: str, diagnostic: str | None = None,
) -> BatchPlotExportItem:
  return BatchPlotExportItem(
    item.sample_id, item.sample_title, item.output_paths, status,
    item.diagnostic if diagnostic is None else diagnostic,
    item.source_sample_ids, item.well_ids, item.well_sources,
  )


def _staged_output_path(path: Path) -> Path:
  """Return a same-directory temporary path preserving the renderer suffix."""
  return path.with_name(f".{path.stem}.flowdesk-{uuid.uuid4().hex}{path.suffix}")


def _write_sidecar(
  staged_path: Path,
  item: BatchPlotExportItem,
  spec: BatchPlotExportSpec,
  *,
  final_output_path: Path,
) -> None:
  """Merge renderer metadata and write the staged provenance sidecar."""
  staged_sidecar = staged_path.with_suffix(staged_path.suffix + ".json")
  renderer_metadata: dict[str, Any] = {}
  if staged_sidecar.exists():
    try:
      loaded = json.loads(staged_sidecar.read_text(encoding="utf-8"))
      if isinstance(loaded, dict):
        renderer_metadata = loaded
    except (OSError, json.JSONDecodeError):
      renderer_metadata = {}
  renderer_metadata.update({
    "export_id": spec.id,
    "sample_id": item.sample_id,
    "sample_title": item.sample_title,
    "source_sample_ids": item.source_sample_ids,
    "well_ids": item.well_ids,
    "well_sources": item.well_sources,
    "export_options": asdict(spec),
    "plot_view_id": spec.plot_view_id,
    "output": str(final_output_path),
  })
  staged_sidecar.write_text(
    json.dumps(renderer_metadata, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def _write_json_atomically(path: Path, value: Mapping[str, Any]) -> None:
  staged_path = _staged_output_path(path)
  try:
    staged_path.write_text(
      json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    staged_path.replace(path)
  except Exception:
    staged_path.unlink(missing_ok=True)
    raise


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
