"""Renderer-neutral plot export preparation and a dependency-free SVG adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import struct
import zlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any

from flowdesk_core.models import BatchPlotExportSpec, PlotPresentationSpec, PlotType
from flowdesk_core.plot_presentation import (
  OverlaySourceResolution,
  PresentationDiagnostic,
  ResolvedPresentation,
  resolve_presentation_layers,
  resolve_presentation_title,
  validate_presentation,
)
from flowdesk_core.plot_scene import PlotScene
from flowdesk_core.vector_scatter import VectorScatterLayer, compact_scatter_batches


class PlotExportError(ValueError):
  """Raised when a plot cannot be exported without losing visible content."""


REFERENCE_DPI = 96


@dataclass(frozen=True)
class ExportCanvasSpec:
  """Resolved logical and raster dimensions for one export request."""

  logical_width: int
  logical_height: int
  dpi: int
  raster_resolution_mode: str
  raster_scale: float
  raster_width: int
  raster_height: int
  physical_width_in: float
  physical_height_in: float

  def to_mapping(self) -> dict[str, Any]:
    return asdict(self)


def resolve_export_canvas(
  options: BatchPlotExportSpec | None = None,
  *,
  width: int = 800,
  height: int = 600,
) -> ExportCanvasSpec:
  """Resolve canvas dimensions once for all format adapters."""
  width = width if options is None else options.width
  height = height if options is None else options.height
  dpi = REFERENCE_DPI if options is None else options.dpi
  mode = "legacy_pixel_dimensions" if options is None else options.raster_resolution_mode
  if options is not None and options.aspect_1_to_1:
    width = height = min(width, height)
  if mode == "dpi_scaled":
    scale = dpi / REFERENCE_DPI
    raster_width = max(1, round(width * scale))
    raster_height = max(1, round(height * scale))
  else:
    scale = 1.0
    raster_width = width
    raster_height = height
  return ExportCanvasSpec(
    logical_width=width,
    logical_height=height,
    dpi=dpi,
    raster_resolution_mode=mode,
    raster_scale=scale,
    raster_width=raster_width,
    raster_height=raster_height,
    physical_width_in=width / REFERENCE_DPI,
    physical_height_in=height / REFERENCE_DPI,
  )


@dataclass(frozen=True)
class PreparedPlotExport:
  plot_id: str
  plot_type: PlotType
  source_order: tuple[str, ...]
  metadata: dict[str, Any]
  resolved_presentation: ResolvedPresentation
  gate_overlays: tuple[dict[str, Any], ...] = ()
  scene: PlotScene = PlotScene()


def _diagnostic_mapping(value: PresentationDiagnostic) -> dict[str, Any]:
  return asdict(value)


def prepare_plot_export(
  plot_id: str,
  plot_type: PlotType,
  sources: tuple[dict[str, Any], ...] | list[dict[str, Any]],
  resolutions: tuple[OverlaySourceResolution, ...],
  *,
  view_presentation: dict[str, Any] | None = None,
  project_default: dict[str, Any] | None = None,
  global_preference: dict[str, Any] | None = None,
  gate_overlays: tuple[dict[str, Any], ...] = (),
  scene: dict[str, Any] | None = None,
) -> PreparedPlotExport:
  """Resolve ordered sources and reject invalid visible layers atomically."""
  if not plot_id:
    raise PlotExportError("plot ID must be non-empty")
  source_by_id = {str(source.get("source_id")): source for source in sources}
  resolution_by_id = {item.source_id: item for item in resolutions}
  diagnostics: list[dict[str, Any]] = []
  visible_order: list[str] = []
  for source in sorted(
    sources,
    key=lambda item: (int(item.get("order", 0)), str(item.get("source_id", ""))),
  ):
    source_id = str(source.get("source_id", ""))
    resolution = resolution_by_id.get(source_id)
    if resolution is None:
      diagnostic = {
        "code": "plot_export_missing_resolution",
        "message": "source has no compatibility resolution",
        "source_id": source_id,
      }
      diagnostics.append(diagnostic)
      if source.get("visible", True):
        raise PlotExportError(f"visible source {source_id!r} has no resolution")
      continue
    diagnostics.extend(_diagnostic_mapping(item) for item in resolution.diagnostics)
    if resolution.status != "compatible" and not resolution.diagnostics:
      diagnostics.append({
        "code": f"plot_export_{resolution.status}_source",
        "message": f"source compatibility status is {resolution.status}",
        "source_id": source_id,
      })
    if not source.get("visible", True):
      continue
    if resolution.status != "compatible":
      raise PlotExportError(
        f"visible source {source_id!r} is {resolution.status}; export refused"
      )
    visible_order.append(source_id)
  resolved = resolve_presentation_layers(
    view_presentation,
    project_default,
    global_preference,
    source_ids=tuple(visible_order),
  )
  resolved_dict = asdict(resolved.presentation)
  source_labels = tuple(
    str(source_by_id[source_id].get("display_name", source_id))
    for source_id in visible_order
  )
  style_by_id = {style.source_id: style for style in resolved.presentation.source_styles}
  scene_value = dict(scene or {})
  scene_value.setdefault(
    "title_lines",
    resolve_presentation_title(resolved.presentation, source_labels).splitlines(),
  )
  scene_value.setdefault("source_order", list(visible_order))
  scene_value.setdefault("x_axis_label", resolved.presentation.x_axis_display_label or "")
  scene_value.setdefault("y_axis_label", resolved.presentation.y_axis_display_label or "")
  scene_value.setdefault("gates", [dict(gate) for gate in gate_overlays])
  scene_value.setdefault(
    "title_colors",
    [
      (style.color if (style := style_by_id.get(source_id)) is not None else None)
      or "#000000"
      for source_id in visible_order
    ],
  )
  scene_model = PlotScene.from_mapping(scene_value)
  validate_presentation(plot_type, resolved.presentation)
  metadata = {
    "plot_id": plot_id,
    "definition_version": 1,
    "plot_type": plot_type,
    "ordered_source_ids": list(visible_order),
    "sources": [
      {
        "source_id": source_id,
        "sample_id": source_by_id[source_id].get("sample_id"),
        "population_id": source_by_id[source_id].get("population_id"),
        "display_name": source_by_id[source_id].get("display_name", source_id),
        "x_parameter_id": source_by_id[source_id].get("x_parameter_id"),
        "y_parameter_id": source_by_id[source_id].get("y_parameter_id"),
        "x_transform_id": source_by_id[source_id].get("x_transform_id"),
        "y_transform_id": source_by_id[source_id].get("y_transform_id"),
        "visible": bool(source_by_id[source_id].get("visible", True)),
      }
      for source_id in visible_order
    ],
    "presentation": resolved_dict,
    "style_provenance": dict(resolved.provenance),
    "font_requests": {
      name: asdict(getattr(resolved.presentation, name))
      for name in ("title_font", "axis_label_font", "tick_font", "legend_font")
    },
    "font_fallback_diagnostics": [{
      "code": "font_backend_actual_face_unavailable",
      "severity": "info",
      "message": "The renderer backend determines the actual fallback face.",
    }],
    "gate_overlays": [dict(gate) for gate in gate_overlays],
    "scene": scene_model.to_mapping(),
    "scene_hash": scene_model.scene_hash(),
    "plot_area": {"left": 60, "top": 50, "right": 20, "bottom": 60},
    "diagnostics": diagnostics,
    "scientific_note": (
      "Presentation settings and display sampling do not alter scientific results."
    ),
  }
  return PreparedPlotExport(
    plot_id, plot_type, tuple(visible_order), metadata, resolved,
    tuple(dict(gate) for gate in gate_overlays), scene_model,
  )


def write_plot_svg(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
  event_colors: Mapping[str, tuple[str, ...]] | None = None,
  *,
  options: BatchPlotExportSpec | None = None,
) -> None:
  """Write a small deterministic SVG using the prepared source order."""
  selected = presentation or prepared.resolved_presentation.presentation
  layers = layers or {}
  if any(source_id not in layers for source_id in prepared.source_order):
    missing = [source_id for source_id in prepared.source_order if source_id not in layers]
    raise PlotExportError(f"missing prepared layer data: {', '.join(missing)}")
  if not prepared.source_order:
    raise PlotExportError("cannot export a plot with no visible source")
  width, height = _dimensions(800, 600, options)
  left, top, plot_width, plot_height = _raster_layout(
    width, height, prepared, selected, options,
  )
  elements = [
    f'<rect width="100%" height="100%" fill="{escape(selected.background_color)}"/>',
  ]
  if options is None or options.include_ticks:
    elements.extend(_svg_axes(left, top, plot_width, plot_height))
  if options is None or options.include_title:
    elements.append(
      f'<text x="{width / 2:g}" y="32" text-anchor="middle" '
      f'font-size="{selected.title_font.size}">{escape(selected.title)}</text>'
    )
  if options is None or options.include_axis_labels:
    elements.extend([
      f'<text x="{left + plot_width / 2:g}" y="{height - 20:g}" text-anchor="middle">'
      f"{escape(selected.x_axis_display_label or '')}</text>",
      f'<text x="15" y="{top + plot_height / 2:g}" text-anchor="middle" '
      f'transform="rotate(-90 15 {top + plot_height / 2:g})">'
      f"{escape(selected.y_axis_display_label or '')}</text>",
    ])
  style_by_id = {style.source_id: style for style in selected.source_styles}
  source_labels = {
    source_id: next(
      (
        source.get("display_name", source_id)
        for source in prepared.metadata["sources"]
        if source["source_id"] == source_id
      ),
      source_id,
    )
    for source_id in prepared.source_order
  }
  full_vector = options is None or options.vector_scatter_mode == "full_vector"
  compact_vector = (
    options is not None
    and options.vector_scatter_mode == "compact_vector"
    and not event_colors
  )
  hybrid_raster = options is not None and options.vector_scatter_mode == "hybrid_raster"
  hybrid_info: dict[str, Any] | None = None
  if hybrid_raster:
    hybrid_info = _hybrid_scatter_raster(
      prepared, selected, layers, plot_width=plot_width, plot_height=plot_height,
      dpi=options.hybrid_scatter_dpi, event_colors=event_colors,
    )
    elements.append(
      f'<image x="{left:g}" y="{top:g}" width="{plot_width:g}" height="{plot_height:g}" '
      f'preserveAspectRatio="none" data-scatter-dpi="{hybrid_info["dpi"]}" '
      f'href="data:image/png;base64,{base64.b64encode(hybrid_info["png"]).decode("ascii")}"/>'
    )
  marker_ids: dict[str, str] = {}
  if full_vector:
    defs: list[str] = ['<defs><clipPath id="plot-clip">'
                       f'<rect x="{left:g}" y="{top:g}" width="{plot_width:g}" '
                       f'height="{plot_height:g}"/></clipPath>']
    for index, source_id in enumerate(prepared.source_order):
      style = style_by_id.get(source_id)
      color = "#000000" if style is None or style.color is None else style.color
      alpha = 1.0 if style is None else style.alpha
      marker_size = 3.0 if style is None else style.marker_size
      marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
      marker_id = f"scatter-marker-{index}"
      marker_ids[source_id] = marker_id
      radius = marker_size / 2
      shape = _svg_marker_shape(marker_shape, radius, color, alpha)
      defs.append(f'<g id="{marker_id}">{shape}</g>')
    defs.append("</defs>")
    elements.insert(0, "".join(defs))
    elements.append('<g clip-path="url(#plot-clip)">')
  compact_batches = ()
  if compact_vector:
    compact_batches = compact_scatter_batches(
      _vector_layers(prepared, selected, layers),
      plot_width=plot_width,
      plot_height=plot_height,
    )
  for index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color = "#000000" if style is None or style.color is None else style.color
    alpha = 1.0 if style is None else style.alpha
    marker_size = 3.0 if style is None else style.marker_size
    marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
    x_values, y_values = layers[source_id]
    if not compact_vector and not hybrid_raster:
      colors = None if event_colors is None else event_colors.get(source_id)
      for point_index, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=False)):
        x = left + float(x_value) * plot_width
        y = top + (1.0 - float(y_value)) * plot_height
        point_color = color if colors is None or point_index >= len(colors) else colors[point_index]
        if full_vector and point_color == color:
          elements.append(f'<use href="#{marker_ids[source_id]}" x="{x:g}" y="{y:g}"/>')
        else:
          marker = _svg_marker_shape(marker_shape, marker_size / 2, point_color, alpha)
          elements.append(marker.replace(
            "/>", f' transform="translate({x:g} {y:g})"/>'
          ))
    if compact_vector:
      for batch in compact_batches:
        if batch.source_id != source_id:
          continue
        radius = batch.marker_size / 2
        path_data = " ".join(
          _svg_marker_path(batch.marker_shape, radius,
                           left + point[0] * plot_width,
                           top + (1.0 - point[1]) * plot_height)
          for point in batch.points
        )
        elements.append(
          f'<path d="{path_data}" fill="{escape(batch.color)}" '
          f'fill-opacity="{batch.alpha:g}"/>'
        )
    label = style.legend_label if style and style.legend_label else source_labels[source_id]
    if options is None or options.include_legend:
      elements.append(
        f'<text x="{width - 180:g}" y="{55 + index * 20}" fill="{escape(color)}">'
        f"{escape(str(label))}</text>"
      )
  if full_vector:
    elements.append("</g>")
  if options is None or options.include_gates:
    elements.extend(_svg_gates(_scene_gates(prepared), left, top, plot_width, plot_height))
  svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
    + "".join(elements) + "</svg>\n"
  )
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(svg, encoding="utf-8")
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options, hybrid_info), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_png(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
  event_colors: Mapping[str, tuple[str, ...]] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
) -> None:
  """Write an antialiased PNG from the prepared renderer-neutral scene."""
  if width < 1 or height < 1:
    raise PlotExportError("PNG dimensions must be positive")
  canvas = resolve_export_canvas(options, width=width, height=height)
  width, height = canvas.raster_width, canvas.raster_height
  selected = presentation or prepared.resolved_presentation.presentation
  layers = layers or {}
  if not prepared.source_order:
    raise PlotExportError("cannot export a plot with no visible source")
  if any(source_id not in layers for source_id in prepared.source_order):
    raise PlotExportError("missing prepared layer data")
  try:
    from PIL import Image, ImageDraw
  except ImportError as exc:
    raise PlotExportError("PNG export requires the Pillow package") from exc
  scale = 2
  device_scale = scale * canvas.raster_scale
  image = Image.new(
    "RGBA", (width * scale, height * scale), _rgb(selected.background_color) + (255,)
  )
  draw = ImageDraw.Draw(image)
  left, top, plot_width, plot_height = _raster_layout(
    canvas.logical_width, canvas.logical_height, prepared, selected, options,
  )
  left = round(left * device_scale)
  top = round(top * device_scale)
  plot_width = round(plot_width * device_scale)
  plot_height = round(plot_height * device_scale)
  if options is None or options.include_ticks:
    _draw_raster_axes(
      draw, prepared, selected, left, top, plot_width, plot_height, device_scale
    )
  style_by_id = {style.source_id: style for style in selected.source_styles}
  for source_id in prepared.source_order:
    style = style_by_id.get(source_id)
    color_text = "#000000" if style is None or style.color is None else style.color
    alpha = 1.0 if style is None else style.alpha
    marker_size = 3.0 if style is None else style.marker_size
    radius = max(1, round(marker_size * device_scale / 2))
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    colors = None if event_colors is None else event_colors.get(source_id)
    for index, (x_value, y_value) in enumerate(zip(*layers[source_id], strict=False)):
      color = _rgb(color_text if colors is None or index >= len(colors) else colors[index])
      x = round(left + float(x_value) * plot_width)
      y = round(top + (1.0 - float(y_value)) * plot_height)
      layer_draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=color + (round(255 * alpha),),
      )
    image.alpha_composite(layer)
  draw = ImageDraw.Draw(image)
  if options is None or options.include_gates:
    _draw_raster_gates(
      draw, _scene_gates(prepared), left, top, plot_width, plot_height, device_scale
    )
  _draw_raster_text(
    draw, prepared, selected, width * scale, height * scale,
    left, top, plot_width, plot_height, options, device_scale,
  )
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  image.convert("RGB").resize(
    (width, height), Image.Resampling.LANCZOS
  ).save(out_path, format="PNG", dpi=(canvas.dpi, canvas.dpi))
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_pdf(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
  event_colors: Mapping[str, tuple[str, ...]] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
) -> None:
  """Write a minimal vector PDF using the same prepared layers and styles."""
  if width < 1 or height < 1 or not prepared.source_order:
    raise PlotExportError("PDF dimensions and visible sources are required")
  width, height = _dimensions(width, height, options)
  selected = presentation or prepared.resolved_presentation.presentation
  layers = layers or {}
  if any(source_id not in layers for source_id in prepared.source_order):
    raise PlotExportError("missing prepared layer data")
  background = _rgb(selected.background_color)
  left, top, plot_width, plot_height = _raster_layout(
    width, height, prepared, selected, options,
  )
  commands = [
    f"{background[0] / 255:g} {background[1] / 255:g} {background[2] / 255:g} rg",
    f"0 0 {width} {height} re f",
  ]
  style_by_id = {style.source_id: style for style in selected.source_styles}
  full_vector = options is None or options.vector_scatter_mode == "full_vector"
  compact_vector = options is not None and options.vector_scatter_mode == "compact_vector"
  hybrid_raster = options is not None and options.vector_scatter_mode == "hybrid_raster"
  hybrid_info: dict[str, Any] | None = None
  if hybrid_raster:
    hybrid_info = _hybrid_scatter_raster(
      prepared, selected, layers, plot_width=plot_width, plot_height=plot_height,
      dpi=options.hybrid_scatter_dpi, event_colors=event_colors,
    )
  form_specs: list[tuple[tuple[int, int, int], float, str, float]] = []
  marker_refs: dict[tuple[str, str], int] = {}
  if full_vector:
    for source_id in prepared.source_order:
      style = style_by_id.get(source_id)
      default_color = "#4c78a8" if style is None or style.color is None else style.color
      alpha = 1.0 if style is None else style.alpha
      marker_size = 2.0 if style is None else style.marker_size
      marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
      colors = None if event_colors is None else event_colors.get(source_id)
      point_count = len(layers[source_id][0])
      for index in range(point_count):
        color_text = default_color if colors is None or index >= len(colors) else colors[index]
        key = (source_id, color_text)
        if key not in marker_refs:
          marker_refs[key] = len(form_specs)
          form_specs.append((_rgb(color_text), alpha, marker_shape, marker_size))
    commands.append("q")
    commands.append(f"{left:g} {height - top - plot_height:g} {plot_width:g} {plot_height:g} re W n")
  preserve_event_colors = compact_vector and bool(event_colors)
  compact_batches = compact_scatter_batches(
    _vector_layers(prepared, selected, layers),
    plot_width=plot_width,
    plot_height=plot_height,
  ) if compact_vector and not preserve_event_colors else ()
  compact_alpha_values = (
    tuple(dict.fromkeys(
      1.0 if style_by_id.get(source_id) is None else style_by_id[source_id].alpha
      for source_id in prepared.source_order
    ))
    if preserve_event_colors
    else tuple(dict.fromkeys(batch.alpha for batch in compact_batches))
  )
  if compact_vector:
    commands.append("q")
    commands.append(f"{left:g} {height - top - plot_height:g} {plot_width:g} {plot_height:g} re W n")
    alpha_index = {alpha: index for index, alpha in enumerate(compact_alpha_values)}
    if preserve_event_colors:
      # Do not regroup different per-event colors: doing so can reorder
      # translucent overlaps and change the visual density.
      for source_id in prepared.source_order:
        style = style_by_id.get(source_id)
        alpha = 1.0 if style is None else style.alpha
        marker_size = 3.0 if style is None else style.marker_size
        marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
        default_color = "#000000" if style is None or style.color is None else style.color
        colors = event_colors.get(source_id) if event_colors is not None else None
        for index, point in enumerate(zip(*layers[source_id], strict=False)):
          color_text = default_color if colors is None or index >= len(colors) else colors[index]
          color = _rgb(color_text)
          commands.extend((f"/C{alpha_index[alpha]} gs",
                           f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} rg"))
          commands.append(_pdf_compound_path(
            ((float(point[0]), float(point[1])),), marker_shape, marker_size,
            left, top, plot_width, plot_height, height,
          ) + " f")
    else:
      for batch in compact_batches:
        color = _rgb(batch.color)
        commands.extend((f"/C{alpha_index[batch.alpha]} gs",
                         f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} rg"))
        commands.append(_pdf_compound_path(
          batch.points, batch.marker_shape, batch.marker_size,
          left, top, plot_width, plot_height, height,
        ) + " f")
    commands.append("Q")
  elif hybrid_raster:
    # PDF decoders map the first image row to the visual top edge. The
    # hybrid raster already stores rows in the PNG top-to-bottom order.
    commands.extend(("q", f"{plot_width:g} 0 0 {plot_height:g} {left:g} {height - top - plot_height:g} cm",
                     "/ImScatter Do", "Q"))
  elif not full_vector:
    for source_id in prepared.source_order:
      style = style_by_id.get(source_id)
      color = _rgb("#4c78a8" if style is None or style.color is None else style.color)
      commands.append(f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} rg")
      for x_value, y_value in zip(*layers[source_id], strict=False):
        x, y = _pdf_normalized_point(
          float(x_value), float(y_value), left, top, plot_width, plot_height, height,
        )
        commands.append(f"{x:g} {y:g} 2 2 re f")
  elif full_vector:
    for source_id in prepared.source_order:
      style = style_by_id.get(source_id)
      default_color = "#4c78a8" if style is None or style.color is None else style.color
      colors = None if event_colors is None else event_colors.get(source_id)
      for index, (x_value, y_value) in enumerate(zip(*layers[source_id], strict=False)):
        x, y = _pdf_normalized_point(
          float(x_value), float(y_value), left, top, plot_width, plot_height, height,
        )
        size = (2.0 if style is None else style.marker_size) / 2.0
        color_text = default_color if colors is None or index >= len(colors) else colors[index]
        commands.extend(("q", f"{size:g} 0 0 {size:g} {x:g} {y:g} cm", f"/M{marker_refs[(source_id, color_text)]} Do", "Q"))
    commands.append("Q")
  # Place the opaque PDF image before the axes.  This also avoids Poppler
  # losing pre-image strokes when decoding an image soft mask.
  if options is None or options.include_ticks:
    commands.extend(_pdf_scene_axes(
      prepared, selected, left, top, plot_width, plot_height, height,
    ))
  if options is None or options.include_gates:
    commands.extend(_pdf_gates(_scene_gates(prepared), left, top, plot_width, plot_height, height))
  commands.extend(_pdf_scene_text(
    prepared, selected, left, top, plot_width, plot_height, width, height, options,
  ))
  # Text drawing commands may contain WinAnsi characters such as the
  # multiplication sign used in scientific tick labels ("2 × 10⁶").
  # PDF syntax remains ASCII, while its text operands are Latin-1/WinAnsi.
  stream = ("\n".join(commands) + "\n").encode("latin-1")
  form_start = 7
  xobjects = " ".join(
    f"/M{index} {form_start + index * 2} 0 R" for index in range(len(form_specs))
  )
  extgstate_start = form_start + len(form_specs) * 2
  extgstates = " ".join(
    f"/C{index} {extgstate_start + index} 0 R"
    for index in range(len(compact_alpha_values))
  )
  resources = "/Resources << /Font << /F1 5 0 R /F2 6 0 R >>"
  if xobjects:
    resources += f" /XObject << {xobjects} >>"
  if extgstates:
    resources += f" /ExtGState << {extgstates} >>"
  image_start = extgstate_start + len(compact_alpha_values)
  if hybrid_info is not None:
    resources += f" /XObject << /ImScatter {image_start} 0 R >>"
  resources += " >>"
  objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    (
      f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
      f"{resources} /Contents 4 0 R >>"
    ).encode("ascii"),
    b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
    + stream + b"endstream",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
  ]
  for color, alpha, marker_shape, _marker_size in form_specs:
    marker_stream = _pdf_marker_stream(marker_shape, color)
    form_index = len(objects) + 1
    alpha_index = form_index + 1
    objects.append(
      (
        f"<< /Type /XObject /Subtype /Form /FormType 1 /BBox [-1 -1 1 1] "
        f"/Resources << /ExtGState << /GS0 {alpha_index} 0 R >> >> "
        f"/Length {len(marker_stream)} >>\nstream\n"
      ).encode("ascii") + marker_stream + b"\nendstream"
    )
    objects.append(
      f"<< /Type /ExtGState /ca {alpha:g} /CA {alpha:g} >>".encode("ascii")
    )
  for alpha in compact_alpha_values:
    objects.append(f"<< /Type /ExtGState /ca {alpha:g} /CA {alpha:g} >>".encode("ascii"))
  if hybrid_info is not None:
    mask_start = image_start + 1
    # PDF Flate streams are raw component rows unless a PNG predictor is
    # declared. Do not prefix each row with PNG filter bytes here.
    compressed_rgb = zlib.compress(hybrid_info["rgb"], 6)
    compressed_alpha = zlib.compress(hybrid_info["alpha"], 6)
    objects.append(
      (
        f"<< /Type /XObject /Subtype /Image /Width {hybrid_info['width']} "
        f"/Height {hybrid_info['height']} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        f"/Filter /FlateDecode /SMask {mask_start} 0 R /Length {len(compressed_rgb)} >>\nstream\n"
      ).encode("ascii") + compressed_rgb + b"\nendstream"
    )
    objects.append(
      (
        f"<< /Type /XObject /Subtype /Image /Width {hybrid_info['width']} "
        f"/Height {hybrid_info['height']} /ColorSpace /DeviceGray /BitsPerComponent 8 "
        f"/Filter /FlateDecode /Length {len(compressed_alpha)} >>\nstream\n"
      ).encode("ascii") + compressed_alpha + b"\nendstream"
    )
  pdf = bytearray(b"%PDF-1.4\n")
  offsets = [0]
  for index, obj in enumerate(objects, start=1):
    offsets.append(len(pdf))
    pdf.extend(f"{index} 0 obj\n".encode("ascii"))
    pdf.extend(obj)
    pdf.extend(b"\nendobj\n")
  xref = len(pdf)
  pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
  pdf.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]))
  pdf.extend(
    (
      f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
      f"startxref\n{xref}\n%%EOF\n"
    ).encode("ascii")
  )
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_bytes(bytes(pdf))
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options, hybrid_info), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_jpg(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
  event_colors: Mapping[str, tuple[str, ...]] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
) -> None:
  """Write JPEG through Pillow without making Qt part of the core renderer."""
  try:
    from PIL import Image
  except ImportError as exc:
    raise PlotExportError("JPEG export requires the Pillow package") from exc
  width, height = _dimensions(width, height, options)
  png_path = Path(path).with_suffix(".png.tmp")
  write_plot_png(png_path, prepared, presentation, layers, width=width, height=height,
                 options=options, event_colors=event_colors)
  try:
    with Image.open(png_path) as image:
      image.convert("RGB").save(path, format="JPEG", dpi=(options.dpi, options.dpi)
                                 if options else None)
  finally:
    png_path.unlink(missing_ok=True)
    png_path.with_suffix(png_path.suffix + ".json").unlink(missing_ok=True)
  Path(path).with_suffix(Path(path).suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def _dimensions(width: int, height: int, options: BatchPlotExportSpec | None) -> tuple[int, int]:
  if width < 1 or height < 1:
    raise PlotExportError("plot dimensions must be positive")
  if options is None:
    return width, height
  canvas = resolve_export_canvas(options)
  return canvas.logical_width, canvas.logical_height


def _export_metadata(
  prepared: PreparedPlotExport,
  options: BatchPlotExportSpec | None,
  vector_scatter: dict[str, Any] | None = None,
) -> dict[str, Any]:
  metadata = dict(prepared.metadata)
  metadata["export_canvas"] = resolve_export_canvas(options).to_mapping()
  if options is not None:
    metadata["export_options"] = asdict(options)
    metadata["vector_scatter"] = {
      "requested_mode": options.vector_scatter_mode,
      "resolved_mode": options.vector_scatter_mode,
      "hybrid_scatter_dpi": options.hybrid_scatter_dpi,
    }
  if vector_scatter is not None:
    metadata["vector_scatter"].update({
      "algorithm_version": vector_scatter["algorithm_version"],
      "raster_width": vector_scatter["width"],
      "raster_height": vector_scatter["height"],
      "scatter_image_dpi": vector_scatter["dpi"],
      "rendered_event_count": vector_scatter["rendered_event_count"],
      "point_plan_hash": vector_scatter["point_plan_hash"],
      "encoding": "png_rgba_lossless",
    })
  return metadata


def _svg_axes(left: int, top: int, width: int, height: int) -> list[str]:
  elements = [
    f'<path d="M {left} {top} V {top + height} H {left + width}" '
    'fill="none" stroke="#808080" stroke-width="1"/>',
  ]
  for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
    x = left + fraction * width
    y = top + (1.0 - fraction) * height
    elements.append(f'<path d="M {x:g} {top + height} v 5 M {left - 5} {y:g} h 5" '
                    'stroke="#808080" stroke-width="1"/>')
  return elements


def _svg_marker_shape(shape: str, radius: float, color: str, alpha: float) -> str:
  """Return one reusable marker footprint centered at the SVG origin."""
  fill = f'fill="{escape(color)}" fill-opacity="{alpha:g}"'
  if shape == "square":
    return f'<rect x="{-radius:g}" y="{-radius:g}" width="{2 * radius:g}" height="{2 * radius:g}" {fill}/>'
  if shape == "triangle":
    return (
      f'<path d="M 0 {-radius:g} L {radius:g} {radius:g} L {-radius:g} {radius:g} Z" {fill}/>'
    )
  if shape in {"cross", "plus"}:
    stroke = f'stroke="{escape(color)}" stroke-opacity="{alpha:g}" stroke-width="{max(1.0, radius / 2):g}"'
    if shape == "cross":
      return f'<path d="M {-radius:g} {-radius:g} L {radius:g} {radius:g} M {radius:g} {-radius:g} L {-radius:g} {radius:g}" fill="none" {stroke}/>'
    return f'<path d="M {-radius:g} 0 H {radius:g} M 0 {-radius:g} V {radius:g}" fill="none" {stroke}/>'
  return f'<circle cx="0" cy="0" r="{radius:g}" {fill}/>'


def _svg_marker_path(shape: str, radius: float, x: float, y: float) -> str:
  """Return one translated marker subpath for a compact compound path."""
  if shape == "square":
    return f"M {x - radius:g} {y - radius:g} h {2 * radius:g} v {2 * radius:g} h {-2 * radius:g} Z"
  if shape == "triangle":
    return f"M {x:g} {y - radius:g} L {x + radius:g} {y + radius:g} L {x - radius:g} {y + radius:g} Z"
  # Cross and plus are stroked markers; use a small filled square footprint
  # in compact mode so all markers in one compound path share one fill.
  if shape in {"cross", "plus"}:
    half = max(radius / 3, 0.5)
    return f"M {x - half:g} {y - half:g} h {2 * half:g} v {2 * half:g} h {-2 * half:g} Z"
  k = radius * 0.55228475
  return (
    f"M {x:g} {y - radius:g} C {x + k:g} {y - radius:g} {x + radius:g} {y - k:g} {x + radius:g} {y:g} "
    f"C {x + radius:g} {y + k:g} {x + k:g} {y + radius:g} {x:g} {y + radius:g} "
    f"C {x - k:g} {y + radius:g} {x - radius:g} {y + k:g} {x - radius:g} {y:g} "
    f"C {x - radius:g} {y - k:g} {x - k:g} {y - radius:g} {x:g} {y - radius:g} Z"
  )


def _vector_layers(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]],
) -> tuple[VectorScatterLayer, ...]:
  style_by_id = {style.source_id: style for style in selected.source_styles}
  result: list[VectorScatterLayer] = []
  for z_index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color = "#000000" if style is None or style.color is None else style.color
    points = tuple(
      (float(x), float(y))
      for x, y in zip(*layers[source_id], strict=False)
    )
    result.append(VectorScatterLayer(
      source_id=source_id,
      points=points,
      color=color,
      alpha=1.0 if style is None else style.alpha,
      marker_shape="circle" if style is None or style.marker_shape is None else style.marker_shape,
      marker_size=3.0 if style is None else style.marker_size,
      z_index=z_index,
    ))
  return tuple(result)


def _svg_gates(gates: tuple[dict[str, Any], ...], left: int, top: int,
               width: int, height: int) -> list[str]:
  elements: list[str] = []
  for gate in gates:
    points = _gate_points(gate)
    if len(points) < 2:
      continue
    path = " ".join(
      ("M" if index == 0 else "L")
      + f" {left + x * width:g} {top + (1 - y) * height:g}"
      for index, (x, y) in enumerate(points)
    ) + " Z"
    color = escape(str(gate.get("color", "#ffffff")))
    elements.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
  return elements


def _gate_points(gate: dict[str, Any]) -> tuple[tuple[float, float], ...]:
  raw = gate.get("points") or gate.get("coordinates") or ()
  result: list[tuple[float, float]] = []
  for point in raw:
    if isinstance(point, (list, tuple)) and len(point) >= 2:
      result.append((float(point[0]), float(point[1])))
  return tuple(result)


def _draw_png_axes(pixels: bytearray, width: int, height: int, left: int, top: int,
                   plot_width: int, plot_height: int) -> None:
  color = (128, 128, 128)
  _draw_png_line(pixels, width, height, left, top, left, top + plot_height, color)
  _draw_png_line(pixels, width, height, left, top + plot_height,
                 left + plot_width, top + plot_height, color)


def _draw_png_gates(pixels: bytearray, width: int, height: int,
                    gates: tuple[dict[str, Any], ...], left: int, top: int,
                    plot_width: int, plot_height: int) -> None:
  for gate in gates:
    points = _gate_points(gate)
    if len(points) < 2:
      continue
    color = _rgb(str(gate.get("color", "#ffffff")))
    for first, second in zip(points, (*points[1:], points[0]), strict=False):
      _draw_png_line(
        pixels, width, height,
        int(left + first[0] * plot_width), int(top + (1 - first[1]) * plot_height),
        int(left + second[0] * plot_width), int(top + (1 - second[1]) * plot_height),
        color,
      )


def _draw_png_line(pixels: bytearray, width: int, height: int,
                   x1: int, y1: int, x2: int, y2: int,
                   color: tuple[int, int, int]) -> None:
  steps = max(abs(x2 - x1), abs(y2 - y1), 1)
  for step in range(steps + 1):
    fraction = step / steps
    x = round(x1 + (x2 - x1) * fraction)
    y = round(y1 + (y2 - y1) * fraction)
    if 0 <= x < width and 0 <= y < height:
      offset = (y * width + x) * 3
      pixels[offset:offset + 3] = bytes(color)


def _raster_layout(
  width: int,
  height: int,
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  options: BatchPlotExportSpec | None,
) -> tuple[int, int, int, int]:
  """Reserve text margins before rendering the normalized data rectangle."""
  title_lines = _scene_lines(prepared)
  title_height = (
    max(38, round(selected.title_font.size * 1.8)) * max(1, len(title_lines)) + 10
    if (options is None or options.include_title) and title_lines else 18
  )
  left = max(74, round(selected.tick_font.size * 5.2))
  bottom = max(48, round(selected.tick_font.size * 3.4))
  right = 22
  plot_width = max(1, width - left - right)
  plot_height = max(1, height - title_height - bottom)
  return (
    round(left), round(title_height), round(plot_width), round(plot_height)
  )


def _scene_lines(prepared: PreparedPlotExport) -> list[str]:
  raw = prepared.scene.title_lines
  return [str(value) for value in raw if str(value)]


def _scene_mapping(prepared: PreparedPlotExport) -> dict[str, Any]:
  """Return the typed scene for renderer adapters.

  Renderers must not reconstruct scene state from raw metadata; the metadata
  copy is only for sidecars and provenance.
  """
  return prepared.scene.to_mapping()


def _scene_gates(prepared: PreparedPlotExport) -> tuple[dict[str, Any], ...]:
  """Return gate geometry from the canonical scene, never sidecar metadata."""
  return prepared.scene.gates


def _font(size: float, *, bold: bool = False) -> Any:
  """Return a portable Pillow font without making font availability fatal."""
  from PIL import ImageFont

  name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
  try:
    return ImageFont.truetype(name, max(1, round(size)))
  except OSError:
    return ImageFont.load_default()


def _draw_raster_axes(
  draw: Any,
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  left: int,
  top: int,
  plot_width: int,
  plot_height: int,
  scale: int,
) -> None:
  color = _foreground_rgba(selected.background_color)
  width = max(1, round(selected.axis_line_width * scale))
  bottom = top + plot_height
  if selected.show_grid:
    grid_color = (216, 216, 216, 255)
    scene = _scene_mapping(prepared)
    for axis, origin, extent, horizontal in (
      ("x_ticks", left, plot_width, True),
      ("y_ticks", bottom, plot_height, False),
    ):
      ticks = scene.get(axis, ()) if isinstance(scene, dict) else ()
      for tick in ticks:
        if not isinstance(tick, dict):
          continue
        position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
        if horizontal:
          x = round(origin + position * extent)
          draw.line((x, top, x, bottom), fill=grid_color, width=max(1, round(scale / 2)))
        else:
          y = round(origin - position * extent)
          draw.line(
            (left, y, left + plot_width, y),
            fill=grid_color,
            width=max(1, round(scale / 2)),
          )
  draw.rectangle(
    (left, top, left + plot_width, bottom), outline=color, width=width
  )
  scene = _scene_mapping(prepared)
  for axis, origin, extent, horizontal in (
    ("x_ticks", left, plot_width, True),
    ("y_ticks", bottom, plot_height, False),
  ):
    ticks = scene.get(axis, ()) if isinstance(scene, dict) else ()
    for tick in ticks:
      if not isinstance(tick, dict):
        continue
      position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
      major = bool(tick.get("major", True))
      length = round((6 if major else 3) * scale)
      if horizontal:
        x = round(origin + position * extent)
        draw.line((x, bottom, x, bottom + length), fill=color, width=width)
      else:
        y = round(origin - position * extent)
        draw.line((left - length, y, left, y), fill=color, width=width)


def _draw_raster_gates(
  draw: Any,
  gates: tuple[dict[str, Any], ...],
  left: int,
  top: int,
  plot_width: int,
  plot_height: int,
  scale: int,
) -> None:
  for gate in gates:
    points = _gate_points(gate)
    if len(points) < 2:
      continue
    mapped = [
      (round(left + x * plot_width), round(top + (1 - y) * plot_height))
      for x, y in points
    ]
    mapped.append(mapped[0])
    draw.line(
      mapped,
      fill=_rgb(str(gate.get("color", "#ffffff"))) + (255,),
      width=max(1, round(float(gate.get("width", 1.5)) * scale)),
      joint="curve",
    )


def _draw_raster_text(
  draw: Any,
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  width: int,
  height: int,
  left: int,
  top: int,
  plot_width: int,
  plot_height: int,
  options: BatchPlotExportSpec | None,
  scale: int,
) -> None:
  scene = _scene_mapping(prepared)
  title_lines = _scene_lines(prepared)
  title_colors = scene.get("title_colors", ()) if isinstance(scene, dict) else ()
  if options is None or options.include_title:
    title_font = _font(selected.title_font.size * scale, bold=selected.title_font.weight == "bold")
    line_height = round(selected.title_font.size * 1.45 * scale)
    for index, line in enumerate(title_lines):
      color = str(title_colors[index]) if index < len(title_colors) else "#b8c7ff"
      _draw_centered(draw, width // 2, 20 * scale + index * line_height, line,
                     title_font, _rgb(color) + (255,))
  foreground = _foreground_rgba(selected.background_color)
  tick_font = _font(selected.tick_font.size * scale, bold=selected.tick_font.weight == "bold")
  if options is None or options.include_ticks:
    for axis, origin, extent, horizontal in (
      ("x_ticks", left, plot_width, True),
      ("y_ticks", top + plot_height, plot_height, False),
    ):
      ticks = scene.get(axis, ()) if isinstance(scene, dict) else ()
      for tick in ticks:
        if not isinstance(tick, dict) or not tick.get("major", True):
          continue
        label = _display_tick_label(str(tick.get("label", "")))
        if not label:
          continue
        position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
        if horizontal:
          _draw_centered(draw, round(origin + position * extent), top + plot_height + 9 * scale,
                         label, tick_font, foreground)
        else:
          bbox = draw.textbbox((0, 0), label, font=tick_font)
          x = left - 9 * scale - (bbox[2] - bbox[0])
          y = round(origin - position * extent) - (bbox[3] - bbox[1]) // 2
          draw.text((x, y), label, font=tick_font, fill=foreground)
  if options is None or options.include_axis_labels:
    axis_font = _font(selected.axis_label_font.size * scale,
                      bold=selected.axis_label_font.weight == "bold")
    _draw_centered(draw, left + plot_width // 2, height - 27 * scale,
                   selected.x_axis_display_label or "", axis_font, foreground)
    label = selected.y_axis_display_label or ""
    if label:
      _draw_vertical(
        draw, 18 * scale, top + plot_height // 2, label, axis_font,
        foreground,
      )


def _draw_centered(draw: Any, x: int, y: int, text: str, font: Any, fill: Any) -> None:
  bbox = draw.textbbox((0, 0), text, font=font)
  draw.text((x - (bbox[2] - bbox[0]) // 2, y), text, font=font, fill=fill)


def _foreground_rgba(background_color: str) -> tuple[int, int, int, int]:
  """Return a legible monochrome foreground for the selected plot background."""
  red, green, blue = _rgb(background_color)
  luminance = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
  return (0, 0, 0, 255) if luminance >= 128 else (232, 232, 232, 255)


def _draw_vertical(draw: Any, x: int, y: int, text: str, font: Any, fill: Any) -> None:
  """Draw one label rotated 90 degrees counterclockwise around its center."""
  rotated = _vertical_text_image(text, font, fill)
  draw._image.alpha_composite(
    rotated, (round(x - rotated.width // 2), round(y - rotated.height // 2))
  )


def _vertical_text_image(text: str, font: Any, fill: Any) -> Any:
  """Render a padded vertical-label image without losing font bbox offsets."""
  from PIL import Image, ImageDraw

  probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
  bbox = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
  text_width = bbox[2] - bbox[0]
  text_height = bbox[3] - bbox[1]
  padding = 4
  label = Image.new(
    "RGBA", (text_width + 2 * padding, text_height + 2 * padding), (0, 0, 0, 0),
  )
  # Pillow's bbox commonly has a positive top offset.  Drawing at ``padding``
  # alone puts the glyph below this buffer and cuts its lower part.
  ImageDraw.Draw(label).text(
    (padding - bbox[0], padding - bbox[1]), text, font=font, fill=fill,
  )
  return label.rotate(90, expand=True)


def _display_tick_label(label: str) -> str:
  """Match the GUI's compact scientific labels without importing Qt."""
  match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))e([+-]?\d+)", label.strip(), re.I)
  if match is None:
    return label
  mantissa, exponent = match.groups()
  superscript = str(int(exponent)).translate(str.maketrans(
    "0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
  ))
  if float(mantissa) == 1.0:
    return f"10{superscript}"
  return f"{mantissa} × 10{superscript}"


def _pdf_scene_axes(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  left: int,
  top: int,
  width: int,
  plot_height: int,
  page_height: int,
) -> list[str]:
  """Draw the same scene tick/grid geometry as the raster export."""
  bottom = top + plot_height
  pdf_bottom = page_height - bottom
  pdf_top = page_height - top
  foreground = _foreground_rgba(selected.background_color)
  red, green, blue = (value / 255 for value in foreground[:3])
  commands: list[str] = []
  scene = _scene_mapping(prepared)
  if selected.show_grid:
    for axis, horizontal in (("x_ticks", True), ("y_ticks", False)):
      for tick in scene.get(axis, ()):
        if not isinstance(tick, dict):
          continue
        position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
        is_major = bool(tick.get("major", True))
        commands.append(
          "0.72 0.72 0.72 RG 0.75 w" if is_major else "0.88 0.88 0.88 RG 0.35 w"
        )
        if horizontal:
          x = left + position * width
          commands.append(f"{x:g} {pdf_bottom:g} m {x:g} {pdf_top:g} l S")
        else:
          y = page_height - (bottom - position * plot_height)
          commands.append(f"{left:g} {y:g} m {left + width:g} {y:g} l S")
  commands.append(f"{red:g} {green:g} {blue:g} RG {selected.axis_line_width:g} w")
  commands.append(f"{left:g} {pdf_bottom:g} {width:g} {plot_height:g} re S")
  for axis, horizontal in (("x_ticks", True), ("y_ticks", False)):
    for tick in scene.get(axis, ()):
      if not isinstance(tick, dict):
        continue
      position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
      length = 6 if tick.get("major", True) else 3
      if horizontal:
        x = left + position * width
        commands.append(f"{x:g} {pdf_bottom:g} m {x:g} {pdf_bottom - length:g} l S")
      else:
        y = page_height - (bottom - position * plot_height)
        commands.append(f"{left:g} {y:g} m {left - length:g} {y:g} l S")
  return commands


def _pdf_scene_text(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  left: int,
  top: int,
  width: int,
  plot_height: int,
  page_width: int,
  page_height: int,
  options: BatchPlotExportSpec | None,
) -> list[str]:
  """Emit ASCII-safe PDF text for titles, major ticks, and axis labels."""
  scene = _scene_mapping(prepared)
  commands: list[str] = []
  if options is None or options.include_title:
    title_lines = _scene_lines(prepared)
    colors = scene.get("title_colors", ())
    for index, line in enumerate(title_lines):
      color = str(colors[index]) if index < len(colors) else "#4c78a8"
      red, green, blue = (value / 255 for value in _rgb(color))
      size = selected.title_font.size
      text = _pdf_text(line)
      x = (page_width - len(text) * size * 0.55) / 2
      # PDF text coordinates use the baseline; Pillow's raster renderer
      # receives the top-left text coordinate.
      y = page_height - 20 - size * 0.85 - index * size * 1.45
      commands.append(f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg {x:g} {y:g} Td ({text}) Tj ET")
  foreground = _foreground_rgba(selected.background_color)
  red, green, blue = (value / 255 for value in foreground[:3])
  if options is None or options.include_ticks:
    for axis, horizontal in (("x_ticks", True), ("y_ticks", False)):
      for tick in scene.get(axis, ()):
        if not isinstance(tick, dict) or not tick.get("major", True):
          continue
        label = str(tick.get("label", ""))
        if not label:
          continue
        position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
        size = selected.tick_font.size
        if horizontal:
          x = left + position * width - _pdf_tick_label_width(label, size) / 2
          y = page_height - (top + plot_height + 9 + size)
        else:
          x = left - 10 - _pdf_tick_label_width(label, size)
          y = page_height - (top + plot_height - position * plot_height) - size * 0.35
        commands.extend(_pdf_tick_label_commands(label, x, y, size, red, green, blue))
  if options is None or options.include_axis_labels:
    size = selected.axis_label_font.size
    x_label = _pdf_text(selected.x_axis_display_label or "")
    if x_label:
      x = left + width / 2 - len(x_label) * size * 0.28
      commands.append(f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg {x:g} 11 Td ({x_label}) Tj ET")
    y_label = _pdf_text(selected.y_axis_display_label or "")
    if y_label:
      y = page_height - (top + plot_height / 2 + len(y_label) * size * 0.28)
      commands.append(f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg 0 1 -1 0 20 {y:g} Tm ({y_label}) Tj ET")
  return commands


def _pdf_text(value: str) -> str:
  return value.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_tick_label_width(label: str, size: float) -> float:
  """Estimate the width used by the Type1 PDF tick-label fallback."""
  match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))e([+-]?\d+)", label.strip(), re.I)
  if match is None:
    return len(label) * size * 0.55
  mantissa, exponent = match.groups()
  prefix = "" if float(mantissa) == 1.0 else f"{mantissa} × "
  return (len(prefix) + 2) * size * 0.55 + len(str(int(exponent))) * size * 0.36


def _pdf_tick_label_commands(
  label: str,
  x: float,
  y: float,
  size: float,
  red: float,
  green: float,
  blue: float,
) -> list[str]:
  """Draw scientific ticks with a raised exponent using portable Type1 fonts."""
  match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))e([+-]?\d+)", label.strip(), re.I)
  if match is None:
    text = _pdf_text(label)
    return [f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg {x:g} {y:g} Td ({text}) Tj ET"]
  mantissa, exponent = match.groups()
  prefix = "" if float(mantissa) == 1.0 else f"{mantissa} × "
  normal = _pdf_text(f"{prefix}10")
  exponent_text = _pdf_text(str(int(exponent)))
  exponent_x = x + len(prefix + "10") * size * 0.55
  exponent_y = y + size * 0.35
  exponent_size = size * 0.65
  return [
    f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg {x:g} {y:g} Td ({normal}) Tj ET",
    f"BT /F2 {exponent_size:g} Tf {red:g} {green:g} {blue:g} rg {exponent_x:g} {exponent_y:g} Td ({exponent_text}) Tj ET",
  ]


def _pdf_marker_stream(shape: str, color: tuple[int, int, int]) -> bytes:
  """Build a normalized reusable Form XObject marker centered at (0, 0)."""
  red, green, blue = (value / 255 for value in color)
  # Each Form XObject owns GS0, whose alpha is resolved with the marker's
  # source style. Activate it before painting so full-vector dots use the
  # same source opacity as PNG, compact vector, and hybrid raster output.
  prefix = f"/GS0 gs\n{red:g} {green:g} {blue:g} rg\n"
  if shape == "square":
    body = "-1 -1 2 2 re f\n"
  elif shape == "triangle":
    body = "0 1 m 1 -1 l -1 -1 l h f\n"
  elif shape == "cross":
    body = "0.35 w -1 -1 m 1 1 l S 1 -1 m -1 1 l S\n"
  elif shape == "plus":
    body = "0.35 w -1 0 m 1 0 l S 0 -1 m 0 1 l S\n"
  else:
    # A four-segment cubic approximation of a unit circle.
    body = (
      "0 1 m 0.5523 1 1 0.5523 1 0 c "
      "1 -0.5523 0.5523 -1 0 -1 c "
      "-0.5523 -1 -1 -0.5523 -1 0 c "
      "-1 0.5523 -0.5523 1 0 1 c f\n"
    )
  return (prefix + body).encode("ascii")


def _pdf_compound_path(
  points: tuple[tuple[float, float], ...],
  shape: str,
  marker_size: float,
  left: float,
  top: float,
  plot_width: float,
  plot_height: float,
  page_height: float,
) -> str:
  """Create one compound path containing non-overlapping marker subpaths."""
  radius = marker_size / 2
  commands: list[str] = []
  for x_value, y_value in points:
    x, y = _pdf_normalized_point(
      x_value, y_value, left, top, plot_width, plot_height, page_height,
    )
    if shape == "square":
      commands.append(f"{x - radius:g} {y - radius:g} {2 * radius:g} {2 * radius:g} re")
    elif shape == "triangle":
      commands.append(f"{x:g} {y - radius:g} m {x + radius:g} {y + radius:g} l {x - radius:g} {y + radius:g} l h")
    else:
      # Circle and line-like markers use a filled circular footprint in the
      # compact path; full_vector retains their exact stroke geometry.
      k = radius * 0.55228475
      commands.append(
        f"{x:g} {y - radius:g} m {x + k:g} {y - radius:g} {x + radius:g} {y - k:g} {x + radius:g} {y:g} c "
        f"{x + radius:g} {y + k:g} {x + k:g} {y + radius:g} {x:g} {y + radius:g} c "
        f"{x - k:g} {y + radius:g} {x - radius:g} {y + k:g} {x - radius:g} {y:g} c "
        f"{x - radius:g} {y - k:g} {x - k:g} {y - radius:g} {x:g} {y - radius:g} c h"
      )
  return " ".join(commands)


def _pdf_normalized_point(
  x_value: float,
  y_value: float,
  left: float,
  top: float,
  plot_width: float,
  plot_height: float,
  page_height: float,
) -> tuple[float, float]:
  """Map PlotScene's top-origin normalized point to PDF page coordinates."""
  return (
    left + x_value * plot_width,
    page_height - (top + (1.0 - y_value) * plot_height),
  )


def _pdf_gates(gates: tuple[dict[str, Any], ...], left: int, top: int,
               width: int, plot_height: int, height: int) -> list[str]:
  commands: list[str] = []
  for gate in gates:
    points = _gate_points(gate)
    if len(points) < 2:
      continue
    color = _rgb(str(gate.get("color", "#ffffff")))
    commands.append(f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} RG 2 w")
    transformed = [
      _pdf_normalized_point(x, y, left, top, width, plot_height, height)
      for x, y in points
    ]
    commands.append(f"{transformed[0][0]:g} {transformed[0][1]:g} m")
    commands.extend(f"{x:g} {y:g} l" for x, y in transformed[1:])
    commands.append("h S")
  return commands


def _rgb(value: str) -> tuple[int, int, int]:
  if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
    raise PlotExportError(f"invalid RGB color {value!r}")
  try:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]
  except ValueError as exc:
    raise PlotExportError(f"invalid RGB color {value!r}") from exc


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
  return (
    struct.pack(">I", len(payload)) + kind + payload
    + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
  )


def _hybrid_scatter_raster(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]],
  event_colors: Mapping[str, tuple[str, ...]] | None = None,
  *,
  plot_width: float,
  plot_height: float,
  dpi: int,
) -> dict[str, Any]:
  """Render only scatter markers into a transparent lossless RGBA raster."""
  if dpi < 72 or dpi > 2400:
    raise PlotExportError("hybrid scatter dpi must be between 72 and 2400")
  raster_scale = dpi / 96.0
  raster_width = max(1, round(plot_width * raster_scale))
  raster_height = max(1, round(plot_height * raster_scale))
  pixels = bytearray(raster_width * raster_height * 4)
  style_by_id = {style.source_id: style for style in selected.source_styles}
  point_records: list[dict[str, Any]] = []

  def blend(index: int, color: tuple[int, int, int], alpha: float) -> None:
    src_a = max(0.0, min(1.0, alpha))
    if src_a <= 0:
      return
    dst_a = pixels[index + 3] / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0:
      return
    for offset, channel in enumerate(color):
      value = (channel * src_a + pixels[index + offset] * dst_a * (1.0 - src_a)) / out_a
      pixels[index + offset] = max(0, min(255, round(value)))
    pixels[index + 3] = max(0, min(255, round(out_a * 255)))

  for z_index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color_text = "#000000" if style is None or style.color is None else style.color
    alpha = 1.0 if style is None else style.alpha
    shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
    marker_size = 3.0 if style is None else style.marker_size
    radius = marker_size * raster_scale / 2.0
    x_values, y_values = layers[source_id]
    colors = None if event_colors is None else event_colors.get(source_id)
    for index, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=False)):
      point_color_text = (
        color_text if colors is None or index >= len(colors) else colors[index]
      )
      point_color = _rgb(point_color_text)
      x = float(x_value) * (raster_width - 1)
      y = (1.0 - float(y_value)) * (raster_height - 1)
      point_records.append({
        "source_id": source_id, "x": float(x_value), "y": float(y_value),
        "color": point_color_text, "alpha": alpha, "marker_shape": shape,
        "marker_size": marker_size, "z_index": z_index,
      })
      min_x = max(0, math.floor(x - radius - 1))
      max_x = min(raster_width - 1, math.ceil(x + radius + 1))
      min_y = max(0, math.floor(y - radius - 1))
      max_y = min(raster_height - 1, math.ceil(y + radius + 1))
      for pixel_y in range(min_y, max_y + 1):
        for pixel_x in range(min_x, max_x + 1):
          dx = pixel_x + 0.5 - x
          dy = pixel_y + 0.5 - y
          inside = (
            dx * dx + dy * dy <= radius * radius
            if shape == "circle"
            else abs(dx) <= radius and abs(dy) <= radius
          )
          if inside:
            blend((pixel_y * raster_width + pixel_x) * 4, point_color, alpha)

  raw_rows = b"".join(
    b"\x00" + bytes(pixels[row * raster_width * 4:(row + 1) * raster_width * 4])
    for row in range(raster_height)
  )
  png = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", raster_width, raster_height, 8, 6, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(raw_rows, 6))
    + _png_chunk(b"IEND", b"")
  )
  canonical = json.dumps(
    {
      "mode": "hybrid_raster", "algorithm_version": "hybrid_scatter_raster.v1",
      "dpi": dpi, "width": raster_width, "height": raster_height,
      "source_order": list(prepared.source_order), "points": point_records,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
  ).encode("utf-8")
  return {
    "png": png, "rgb": bytes(value for index, value in enumerate(pixels) if index % 4 != 3),
    "alpha": bytes(pixels[index] for index in range(3, len(pixels), 4)),
    "width": raster_width, "height": raster_height, "dpi": dpi,
    "rendered_event_count": len(point_records),
    "point_plan_hash": hashlib.sha256(canonical).hexdigest(),
    "algorithm_version": "hybrid_scatter_raster.v1",
  }
