"""CLI adapter for persisted, per-sample batch plot export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  run_batch_plot_export,
)
from flowdesk_core.display_data import prepare_display_data
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.models import PlotViewSpec
from flowdesk_core.pipeline_runner import run_project_pipeline
from flowdesk_core.plot_export import prepare_plot_export, write_plot_png, write_plot_svg
from flowdesk_core.plot_presentation import OverlaySourceResolution
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
    typed_samples = tuple(
      read_fcs_sample(sample["path"], str(sample["id"]))[1]
      for sample in samples
    )
    report = run_project_pipeline(
      project, output_dir=None, execution_profile_id="default", samples=typed_samples,
    )
    view = next(
      (item for item in project.get("plot_views", [])
       if str(item.get("id")) == spec.plot_view_id),
      {"id": spec.plot_view_id, "plot_type": "scatter"},
    )

    def render(sample: dict[str, Any], path: Path, _spec) -> None:
      info, sample_data = read_fcs_sample(sample["path"], str(sample["id"]))
      names = [channel.id for channel in info.channels]
      if len(names) < 2:
        raise ValueError("plot requires at least two channels")
      x_id = str(view.get("x_parameter") or names[0])
      y_id = str(view.get("y_parameter") or names[1])
      view_spec = PlotViewSpec(
        id=spec.plot_view_id,
        population_id=str(view.get("population_id", "all_events")),
        x_parameter=x_id,
        y_parameter=y_id,
        plot_type=str(view.get("plot_type", "scatter")),
        rendering_downsample=dict(view.get("rendering_downsample", {})),
      )
      display = prepare_display_data(
        view_spec, sample_data.events, names, report, sample_id=str(sample["id"])
      )
      x_values, y_values = _normalize(display.x), _normalize(display.y)
      sample_id = str(sample["id"])
      source = {
        "source_id": sample_id, "sample_id": sample_id,
        "population_id": str(view.get("population_id", "all_events")),
        "display_name": str(sample.get("name", sample_id)),
        "x_parameter_id": x_id, "y_parameter_id": y_id, "visible": True,
      }
      prepared = prepare_plot_export(
        spec.plot_view_id, str(view.get("plot_type", "scatter")),
        (source,), (OverlaySourceResolution(sample_id, "compatible"),),
        view_presentation=view.get("presentation"),
      )
      layers = {sample_id: (tuple(x_values), tuple(y_values))}
      if path.suffix.lower() == ".png":
        write_plot_png(path, prepared, layers=layers, width=spec.width, height=spec.height)
      elif path.suffix.lower() == ".svg":
        write_plot_svg(path, prepared, layers=layers)
      else:
        raise ValueError(f"CLI renderer does not support {path.suffix!r}")

    report = run_batch_plot_export(
      spec, samples, output_dir, render, annotations=annotations,
    )
    print(f"Batch plot export {report.status}: {len(report.items)} samples")
    return 0 if report.status == "success" else 1
  except (BatchPlotExportError, FileNotFoundError, KeyError, ValueError) as exc:
    print(f"Error: batch plot export failed: {exc}")
    return 1


def _normalize(values: np.ndarray) -> np.ndarray:
  if values.size == 0:
    raise ValueError("plot has no finite events")
  low, high = float(np.min(values)), float(np.max(values))
  if high == low:
    return np.full(values.shape, 0.5, dtype=np.float64)
  return (values - low) / (high - low)
