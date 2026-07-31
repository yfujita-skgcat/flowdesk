"""Qt/pyqtgraph export adapter shared with the live plot widget."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.models import BatchPlotExportSpec, TransformSpec
from flowdesk_core.plot_export import (
  prepare_plot_export,
  write_plot_jpg,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.transforms import apply_transform


def render_batch_plot_qt(
  path: str | Path,
  *,
  raw_layers: Mapping[str, tuple[NDArray[np.float64], NDArray[np.float64]]],
  event_colors: Mapping[str, NDArray[np.str_]] | None = None,
  source_ids: tuple[str, ...],
  source_styles: Mapping[str, Mapping[str, Any]],
  presentation: Mapping[str, Any],
  x_parameter: str,
  y_parameter: str,
  title_lines: tuple[str, ...],
  title_colors: tuple[str, ...],
  x_transform: Mapping[str, Any] | None,
  y_transform: Mapping[str, Any] | None,
  x_range: tuple[float, float],
  y_range: tuple[float, float],
  gates: tuple[Mapping[str, Any], ...],
  width: int,
  height: int,
  options: BatchPlotExportSpec,
  plot_area: tuple[float, float, float, float] | None = None,
  scene_metadata: Mapping[str, Any] | None = None,
  export_metadata: Mapping[str, Any] | None = None,
) -> None:
  """Render a prepared GUI export through the canonical core adapters.

  This compatibility entry point is retained for callers that historically
  supplied Qt-shaped arguments, but it must not construct a temporary
  ``PlotWidget``.  The live GUI and batch/CLI exports share the same
  renderer-neutral scene; PNG/JPEG/SVG/PDF are then emitted by the core
  format adapters.  Analysis transforms are applied once to the supplied
  processed arrays before normalization, and gate coordinates are already in
  the declared transformed coordinate system.
  """
  x_spec = _transform_spec(x_transform)
  y_spec = _transform_spec(y_transform)
  sources = tuple({
    "source_id": source_id, "sample_id": source_id,
    "population_id": "all_events", "display_name": source_id,
    "visible": True, "order": index,
  } for index, source_id in enumerate(source_ids))
  if not sources:
    raise ValueError("at least one source is required")
  resolved_presentation = dict(presentation)
  resolved_presentation["title"] = "\n".join(title_lines)
  resolved_presentation["source_styles"] = [
    {"source_id": source_id, **dict(source_styles.get(source_id, {}))}
    for source_id in source_ids
  ]
  if len(source_ids) == 1 and not source_styles.get(source_ids[0], {}).get("color"):
    resolved_presentation["source_styles"][0].update({
      "color": str(resolved_presentation.get("single_color", "#000000")),
      "marker_size": float(resolved_presentation.get("single_dot_size", 1.5)),
    })
  scene = {
    "x_parameter": x_parameter, "y_parameter": y_parameter,
    "x_transform_id": x_spec.id if x_spec else None,
    "y_transform_id": y_spec.id if y_spec else None,
    "view_range": [list(x_range), list(y_range)],
    "plot_area": list(plot_area or (60.0, 50.0, 20.0, 60.0)),
    "title_lines": list(title_lines), "title_colors": list(title_colors),
    "x_axis_label": str(presentation.get("x_axis_display_label", "")),
    "y_axis_label": str(presentation.get("y_axis_display_label", "")),
    "source_order": list(source_ids),
    "gates": [dict(gate) for gate in gates],
  }
  if scene_metadata:
    for key in ("x_ticks", "y_ticks", "view_range", "z_order", "clip_to_plot_area"):
      if key in scene_metadata:
        scene[key] = scene_metadata[key]
  resolutions = tuple(
    OverlaySourceResolution(source_id, "compatible", index)
    for index, source_id in enumerate(source_ids)
  )
  prepared = prepare_plot_export(
    "qt-export", "scatter", sources, resolutions,
    view_presentation=resolved_presentation, scene=scene,
    gate_overlays=tuple(dict(gate) for gate in gates),
  )
  normalized_layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {}
  x_span = float(x_range[1] - x_range[0])
  y_span = float(y_range[1] - y_range[0])
  if x_span <= 0 or y_span <= 0:
    raise ValueError("export ranges must be increasing")
  for source_id in source_ids:
    x_values, y_values = raw_layers[source_id]
    if x_spec is not None:
      x_values = apply_transform(x_spec, x_values)
    if y_spec is not None:
      y_values = apply_transform(y_spec, y_values)
    normalized_layers[source_id] = (
      tuple((np.asarray(x_values, dtype=np.float64) - x_range[0]) / x_span),
      tuple((np.asarray(y_values, dtype=np.float64) - y_range[0]) / y_span),
    )
  suffix = Path(path).suffix.lower()
  if suffix == ".png":
    write_plot_png(path, prepared, layers=normalized_layers,
                   event_colors=event_colors, options=options,
                   width=options.width, height=options.height)
  elif suffix in {".jpg", ".jpeg"}:
    write_plot_jpg(path, prepared, layers=normalized_layers,
                   event_colors=event_colors, options=options,
                   width=options.width, height=options.height)
  elif suffix in {".svg", ".pdf"}:
    writer = write_plot_svg if suffix == ".svg" else write_plot_pdf
    writer(path, prepared, layers=normalized_layers,
           event_colors=event_colors, options=options,
           width=options.width, height=options.height)
  else:
    raise ValueError(f"plot renderer does not support {suffix!r}")
  if export_metadata:
    sidecar = Path(path).with_suffix(Path(path).suffix + ".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata.update(dict(export_metadata))
    metadata["display_state"] = {
      "mode": "scatter", "input_event_count": sum(len(raw_layers[s][0]) for s in source_ids),
      "displayed_event_count": sum(len(normalized_layers[s][0]) for s in source_ids),
    }
    sidecar.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _transform_spec(value: Mapping[str, Any] | None) -> TransformSpec | None:
  if not value:
    return None
  return TransformSpec(
    id=str(value["id"]), name=str(value.get("name", value["id"])),
    transform_type=str(value["transform_type"]),
    parameter=str(value["parameter"]),
    settings=dict(value.get("settings", {})), role="analysis",
    notes=str(value.get("notes", "")),
  )
