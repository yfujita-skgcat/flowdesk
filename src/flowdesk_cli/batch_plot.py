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
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.plot_export import prepare_plot_export, write_plot_svg
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
      x_index, y_index = names.index(x_id), names.index(y_id)
      x, y = sample_data.events[:, x_index], sample_data.events[:, y_index]
      finite = np.isfinite(x) & np.isfinite(y)
      x_values, y_values = _normalize(x[finite]), _normalize(y[finite])
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
      write_plot_svg(
        path, prepared,
        layers={sample_id: (tuple(x_values), tuple(y_values))},
      )

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
