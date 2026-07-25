"""Qt/pyqtgraph export adapter shared with the live plot widget."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.models import BatchPlotExportSpec, GateSpec, TransformSpec
from flowdesk_core.overlays import Overlay2DLayer
from flowdesk_core.transforms import apply_transform
from flowdesk_qt.plot_style import PlotStyleSettings
from flowdesk_qt.plot_widget import PlotWidget


def render_batch_plot_qt(
  path: str | Path,
  *,
  raw_layers: Mapping[str, tuple[NDArray[np.float64], NDArray[np.float64]]],
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
  export_metadata: Mapping[str, Any] | None = None,
) -> None:
  """Render a batch plot through the same pyqtgraph widget as the GUI.

  The event arrays are canonical processed display inputs.  Analysis
  transforms are applied by ``PlotWidget`` exactly as in the live GUI; gate
  coordinates are already stored in their declared transformed coordinate
  system and are therefore not transformed again.
  """
  os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
  from PySide6.QtWidgets import QApplication

  app = QApplication.instance()
  owns_app = app is None
  if app is None:
    app = QApplication(["flowdesk-batch-export"])
  widget = PlotWidget()
  widget.resize(max(1, width), max(1, height))
  x_spec = _transform_spec(x_transform)
  y_spec = _transform_spec(y_transform)
  widget.set_axis_transform_specs(x_spec, y_spec)
  style = _style_from_presentation(presentation, source_styles, source_ids)
  widget.set_style(style)

  active_id = source_ids[0]
  active_x, active_y = raw_layers[active_id]
  active_style = source_styles.get(active_id, {})
  widget.set_style(PlotStyleSettings(
    **{
      **style.__dict__,
      "dot_color": str(active_style.get("color", style.dot_color)),
      "dot_opacity": float(active_style.get("alpha", style.dot_opacity)),
      "dot_size": float(active_style.get("marker_size", style.dot_size)),
    }
  ))
  widget.set_export_metadata(None if export_metadata is None else dict(export_metadata))
  widget.plot_events(
    active_x, active_y,
    x_label=str(presentation.get("x_axis_display_label", "")),
    y_label=str(presentation.get("y_axis_display_label", "")),
  )
  overlay_layers: list[Overlay2DLayer] = []
  for source_id in source_ids[1:]:
    x_values, y_values = raw_layers[source_id]
    if x_spec is not None:
      x_values = apply_transform(x_spec, x_values)
    if y_spec is not None:
      y_values = apply_transform(y_spec, y_values)
    overlay_layers.append(Overlay2DLayer(
      source_id, x_values, y_values, dict(source_styles.get(source_id, {})),
    ))
  if overlay_layers:
    widget.plot_overlay_layers(overlay_layers)

  widget.set_presentation(
    dict(presentation),
    title_override="\n".join(title_lines),
    title_colors=title_colors,
  )
  widget.set_manual_view_range(x_range, y_range)
  for index, raw_gate in enumerate(gates):
    gate = _gate_spec(raw_gate)
    if gate is None:
      continue
    if gate.x_parameter not in {None, x_parameter}:
      continue
    if gate.y_parameter not in {None, y_parameter}:
      continue
    if gate.x_transform_id != (x_spec.id if x_spec else None):
      continue
    if gate.y_transform_id != (y_spec.id if y_spec else None):
      continue
    color = str(raw_gate.get("color", style.gate_outline_color))
    widget.add_gate_overlay(gate, index, color)

  app.processEvents()
  export_options = {
    "include_title": options.include_title,
    "include_axis_labels": options.include_axis_labels,
    "include_ticks": options.include_ticks,
    "include_gates": options.include_gates,
    "include_status_banner": options.include_status_banner,
  }
  suffix = Path(path).suffix.lower()
  if suffix == ".png":
    widget.export_png(
      path,
      width=width,
      height=height,
      aspect_1_to_1=options.aspect_1_to_1,
      export_options=export_options,
    )
  elif suffix in {".jpg", ".jpeg"}:
    widget.export_jpg(
      path,
      width=width,
      height=height,
      aspect_1_to_1=options.aspect_1_to_1,
      export_options=export_options,
    )
  elif suffix in {".svg", ".pdf"}:
    widget.export_vector(
      path,
      "SVG" if suffix == ".svg" else "PDF",
      width=width,
      height=height,
      aspect_1_to_1=options.aspect_1_to_1,
      export_options=export_options,
    )
  else:
    raise ValueError(f"Qt plot renderer does not support {suffix!r}")
  widget.close()
  if owns_app:
    app.processEvents()


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


def _gate_spec(value: Mapping[str, Any]) -> GateSpec | None:
  try:
    coordinates = tuple(tuple(float(item) for item in point[:2]) for point in value.get("coordinates", ()))
    thresholds = dict(value.get("thresholds", {}))
    return GateSpec(
      id=str(value["id"]), name=str(value.get("name", value["id"])),
      gate_type=str(value["gate_type"]),
      parent_population_id=value.get("parent_population_id"),
      x_parameter=value.get("x_parameter"), y_parameter=value.get("y_parameter"),
      x_transform_id=value.get("x_transform_id"), y_transform_id=value.get("y_transform_id"),
      compensation_id=value.get("compensation_id"), coordinates=coordinates,
      thresholds=thresholds, notes=str(value.get("notes", "")),
    )
  except (KeyError, TypeError, ValueError):
    return None


def _style_from_presentation(
  presentation: Mapping[str, Any],
  source_styles: Mapping[str, Mapping[str, Any]],
  source_ids: tuple[str, ...],
) -> PlotStyleSettings:
  tick_font = presentation.get("tick_font", {})
  return PlotStyleSettings(
    background_color=str(presentation.get("background_color", "#ffffff")),
    dot_color=str(source_styles.get(source_ids[0], {}).get("color", "#000000")),
    dot_size=float(source_styles.get(source_ids[0], {}).get("marker_size", 1.5)),
    dot_opacity=float(source_styles.get(source_ids[0], {}).get("alpha", 0.6)),
    gate_outline_color=str(presentation.get("gate_outline_color", "#e00000")),
    gate_fill_color=str(presentation.get("gate_outline_color", "#e00000")),
    gate_fill_opacity=0.0,
    axis_line_width=float(presentation.get("axis_line_width", 2.0)),
    tick_font_family=str(tick_font.get("family", "DejaVu Sans")),
    tick_font_size=float(tick_font.get("size", 10.0)),
    tick_font_weight=str(tick_font.get("weight", "bold")),
    show_grid=bool(presentation.get("show_grid", True)),
  )
