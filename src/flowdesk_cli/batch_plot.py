"""CLI adapter for persisted, per-sample batch plot export."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  run_batch_plot_export,
)
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.models import BatchPlotExportSpec, PlotType, PlotViewSpec, TransformSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.plot_export import (
  prepare_plot_export,
  write_plot_jpg,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.processed_display import ProcessedDisplayRequest
from flowdesk_core.transforms import apply_transform
from flowdesk_storage.project import load_project, resolve_sample_paths


def batch_plot_command(project_path: str, export_id: str, output_dir: str) -> int:
  try:
    project = load_project(project_path)
    raw = next(
      item for item in project.get("batch_plot_exports", [])
      if str(item.get("id")) == export_id
    )
    spec = batch_plot_export_spec_from_mapping(raw)
    samples = resolve_sample_paths(project, Path(project_path))
    annotations = project.get("annotations", [])
    runner = PipelineRunner(project)
    transform_by_id = {
      str(item.get("id")): item for item in project.get("transforms", [])
      if isinstance(item, Mapping) and item.get("id")
    }
    view = next(
      (item for item in project.get("plot_views", [])
       if str(item.get("id")) == spec.plot_view_id),
      {"id": spec.plot_view_id, "plot_type": "scatter"},
    )
    prepared_layers: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    shared_bounds: tuple[float, float, float, float] | None = None

    def extract_layer(sample: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
      _info, sample_data = read_fcs_sample(sample["path"], str(sample["id"]))
      names = [channel.id for channel in sample_data.channels]
      if len(names) < 2:
        raise ValueError("plot requires at least two channels")
      x_id = str(view.get("x_parameter") or names[0])
      y_id = str(view.get("y_parameter") or names[1])
      view_spec = PlotViewSpec(
        id=spec.plot_view_id,
        population_id=str(view.get("population_id", "all_events")),
        x_parameter=x_id,
        y_parameter=y_id,
        plot_type=cast(PlotType, str(view.get("plot_type", "scatter"))),
        rendering_downsample=cast(dict[str, Any], view.get("rendering_downsample", {})),
      )
      processed = runner.prepare_display_sample(ProcessedDisplayRequest(
        revision=0,
        sample=sample_data,
        population_id=view_spec.population_id,
        x_parameter_id=x_id,
        y_parameter_id=y_id,
        x_transform_id=view.get("x_transform_id"),
        y_transform_id=view.get("y_transform_id"),
        display_max_points=int(view_spec.rendering_downsample.get("max_points", 20_000)),
      ))
      x_values = processed.events[processed.display_mask, processed.channel_index(x_id)]
      y_values = processed.events[processed.display_mask, processed.channel_index(y_id)]
      x_transform_id = view.get("x_transform_id")
      y_transform_id = view.get("y_transform_id")
      if x_transform_id:
        x_values = apply_transform(
          _transform_spec(transform_by_id, str(x_transform_id)), x_values
        )
      if y_transform_id:
        y_values = apply_transform(
          _transform_spec(transform_by_id, str(y_transform_id)), y_values
        )
      finite = np.isfinite(x_values) & np.isfinite(y_values)
      return x_values[finite], y_values[finite], {
        "x_id": x_id, "y_id": y_id, "view_spec": view_spec,
      }

    def render(
      sample: Mapping[str, Any], path: Path, _spec: BatchPlotExportSpec
    ) -> None:
      nonlocal shared_bounds
      sample_id = str(sample["id"])
      if not prepared_layers:
        for candidate in samples:
          x_values, y_values, _ = extract_layer(candidate)
          prepared_layers[str(candidate["id"])] = (x_values, y_values)
        if spec.layout_policy == "shared_ranges":
          all_x = np.concatenate([value[0] for value in prepared_layers.values()])
          all_y = np.concatenate([value[1] for value in prepared_layers.values()])
          shared_bounds = (
            float(np.min(all_x)), float(np.max(all_x)),
            float(np.min(all_y)), float(np.max(all_y)),
          )
      x_values, y_values = prepared_layers[sample_id]
      metadata = extract_layer(sample)[2]
      x_id, y_id = metadata["x_id"], metadata["y_id"]
      x_values = _normalize(x_values, shared_bounds[:2] if shared_bounds else None)
      y_values = _normalize(y_values, (shared_bounds[2], shared_bounds[3])
                            if shared_bounds else None)
      sample_id = str(sample["id"])
      source = {
        "source_id": sample_id, "sample_id": sample_id,
        "population_id": str(view.get("population_id", "all_events")),
        "display_name": str(sample.get("name", sample_id)),
        "x_parameter_id": x_id, "y_parameter_id": y_id, "visible": True,
      }
      prepared = prepare_plot_export(
        spec.plot_view_id, cast(PlotType, str(view.get("plot_type", "scatter"))),
        (source,), (OverlaySourceResolution(sample_id, "compatible"),),
        view_presentation=cast(dict[str, Any] | None, view.get("presentation")),
      )
      layers = {sample_id: (tuple(x_values), tuple(y_values))}
      if path.suffix.lower() == ".png":
        write_plot_png(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec)
      elif path.suffix.lower() in {".jpg", ".jpeg"}:
        write_plot_jpg(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec)
      elif path.suffix.lower() == ".svg":
        write_plot_svg(path, prepared, layers=layers, options=spec)
      elif path.suffix.lower() == ".pdf":
        write_plot_pdf(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec)
      else:
        raise ValueError(f"CLI renderer does not support {path.suffix!r}")

    batch_report = run_batch_plot_export(
      spec, samples, output_dir, render, annotations=annotations,
    )
    print(f"Batch plot export {batch_report.status}: {len(batch_report.items)} samples")
    return 0 if batch_report.status == "success" else 1
  except (BatchPlotExportError, FileNotFoundError, KeyError, ValueError) as exc:
    print(f"Error: batch plot export failed: {exc}")
    return 1


def _normalize(
  values: np.ndarray,
  bounds: tuple[float, float] | None = None,
) -> np.ndarray:
  if values.size == 0:
    raise ValueError("plot has no finite events")
  low, high = bounds or (float(np.min(values)), float(np.max(values)))
  if high == low:
    return np.full(values.shape, 0.5, dtype=np.float64)
  return (values - low) / (high - low)


def _transform_spec(
  transform_by_id: Mapping[str, Mapping[str, Any]], transform_id: str,
) -> TransformSpec:
  """Build a typed transform for canonical headless plot coordinates."""
  definition = transform_by_id.get(transform_id)
  if definition is None:
    raise ValueError(f"plot transform is missing: {transform_id!r}")
  return TransformSpec(
    id=str(definition["id"]),
    name=str(definition.get("name", definition["id"])),
    transform_type=cast(Any, str(definition["transform_type"])),
    parameter=str(definition["parameter"]),
    settings=dict(definition.get("settings", {})),
    role="analysis",
    notes=str(definition.get("notes", "")),
  )
