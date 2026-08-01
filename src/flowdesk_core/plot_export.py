"""Renderer-neutral plot export preparation and a dependency-free SVG adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import struct
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from html import escape
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from flowdesk_core.font_resources import (
  BundledFontError,
  bundled_font_filename,
  load_bundled_font,
)
from flowdesk_core.models import BatchPlotExportSpec, PlotPresentationSpec, PlotType
from flowdesk_core.plot_presentation import (
  OverlaySourceResolution,
  PresentationDiagnostic,
  ResolvedPresentation,
  resolve_presentation_layers,
  resolve_presentation_title,
  validate_presentation,
)
from flowdesk_core.plot_scene import (
  POINTS_TO_PX,
  PlotLayoutSpec,
  PlotScene,
  resolve_plot_layout,
)
from flowdesk_core.vector_scatter import (
  CompactScatterBatch,
  VectorScatterLayer,
  compact_scatter_batches,
)


def _font_px(size: float) -> float:
  """Convert persisted Qt point sizes to renderer canvas pixels."""
  return float(size) * POINTS_TO_PX


class PlotExportError(ValueError):
  """Raised when a plot cannot be exported without losing visible content."""


REFERENCE_DPI = 96
LayerValues = tuple[Sequence[float], Sequence[float]]


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


@dataclass(frozen=True)
class VectorRenderCache:
  """Immutable vector/hybrid scatter payload shared by format writers.

  SVG and PDF use the same normalized layer points and compact batches. The
  optional hybrid raster bytes are also shared so a multi-format export does
  not rasterize the same scatter twice. This cache is presentation-only and
  never participates in analytical results. ``layers`` is retained only for
  full-vector writers when event colours are absent; compact batches and hybrid
  raster payloads already own their needed points.
  """

  layers: tuple[VectorScatterLayer, ...]
  compact_batches: tuple[CompactScatterBatch, ...] = ()
  hybrid_info: Mapping[str, Any] | None = None


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
  source_labels = tuple(
    str(source_by_id[source_id].get("display_name", source_id))
    for source_id in visible_order
  )
  resolved_title = resolve_presentation_title(
    resolved.presentation, source_labels
  )
  if source_labels:
    resolved = replace(
      resolved,
      presentation=replace(resolved.presentation, title=resolved_title),
    )
  resolved_dict = asdict(resolved.presentation)
  style_by_id = {style.source_id: style for style in resolved.presentation.source_styles}
  scene_value = dict(scene or {})
  resolved_title_lines = resolved_title.splitlines()
  # A persisted display_scene can contain a title captured before a Sample
  # Sheet edit. In overlay-sample-title mode the current visible source labels
  # are authoritative for both one-source and multi-source exports.
  if resolved.presentation.title_mode == "overlay_sample_titles":
    scene_value["title_lines"] = resolved_title_lines
  else:
    scene_value.setdefault("title_lines", resolved_title_lines)
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
    "raster_font": {
      "policy": "bundled_scalable",
      "regular": bundled_font_filename(),
      "bold": bundled_font_filename(bold=True),
    },
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
  layers: Mapping[str, LayerValues] | None = None,
  event_colors: Mapping[str, Any] | None = None,
  *,
  options: BatchPlotExportSpec | None = None,
  render_cache: VectorRenderCache | None = None,
  cancel_check: Callable[[], None] | None = None,
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
  layout = _resolved_layout(width, height, prepared, selected, options)
  left, top, plot_width, plot_height = (
    round(value) for value in layout.plot_rect
  )
  foreground = _foreground_rgba(selected.background_color)
  axis_color = f"#{foreground[0]:02x}{foreground[1]:02x}{foreground[2]:02x}"
  elements = [
    f'<rect width="100%" height="100%" fill="{escape(selected.background_color)}"/>',
  ]
  if options is None or options.include_ticks:
    elements.extend(_svg_scene_axes(prepared, selected, layout))
  if options is None or options.include_title:
    title_lines = _title_lines(prepared, selected)
    title_colors = prepared.scene.title_colors
    for index, line in enumerate(title_lines):
      color = title_colors[index] if index < len(title_colors) else "#000000"
      baseline = _title_baseline(layout, index, len(title_lines))
      elements.append(
        f'<text x="{width / 2:g}" y="{baseline:g}" text-anchor="middle" '
        f'fill="{escape(str(color))}" font-family="{escape(selected.title_font.family)}" '
        f'font-size="{_font_px(selected.title_font.size):g}" '
        f'font-weight="{escape(selected.title_font.weight)}">{escape(line)}</text>'
      )
  if options is None or options.include_axis_labels:
    elements.extend([
      f'<text x="{layout.x_axis_label_anchor[0]:g}" y="{layout.x_axis_label_anchor[1]:g}" '
      f'text-anchor="middle" fill="{axis_color}" '
      f'font-size="{_font_px(selected.axis_label_font.size):g}">'
      f"{escape(selected.x_axis_display_label or '')}</text>",
      f'<text x="{layout.y_axis_label_anchor[0]:g}" y="{layout.y_axis_label_anchor[1]:g}" '
      f'text-anchor="middle" fill="{axis_color}" '
      f'transform="rotate(-90 {layout.y_axis_label_anchor[0]:g} '
      f'{layout.y_axis_label_anchor[1]:g})" '
      f'font-size="{_font_px(selected.axis_label_font.size):g}">'
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
  vector_cache = render_cache
  if vector_cache is None and (compact_vector or hybrid_raster):
    vector_cache = prepare_vector_render_cache(
      prepared, selected, layers, options=options, event_colors=event_colors,
      cancel_check=cancel_check,
    )
  hybrid_info: dict[str, Any] | None = None
  if hybrid_raster:
    hybrid_info = dict((vector_cache.hybrid_info if vector_cache else None) or {})
    elements.append(
      f'<image x="{left:g}" y="{top:g}" width="{plot_width:g}" height="{plot_height:g}" '
      f'preserveAspectRatio="none" data-scatter-dpi="{hybrid_info["dpi"]}" '
      f'href="data:image/png;base64,{base64.b64encode(hybrid_info["png"]).decode("ascii")}"/>'
    )
  cached_layers_by_id = (
    {layer.source_id: layer for layer in vector_cache.layers}
    if vector_cache is not None and not event_colors else {}
  )
  marker_ids: dict[str, str] = {}
  if full_vector:
    defs: list[str] = ['<defs><clipPath id="plot-clip">'
                       f'<rect x="{left:g}" y="{top:g}" width="{plot_width:g}" '
                       f'height="{plot_height:g}"/></clipPath>']
    for index, source_id in enumerate(prepared.source_order):
      if cancel_check is not None:
        cancel_check()
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
  compact_batches: tuple[CompactScatterBatch, ...] = ()
  if compact_vector:
    compact_batches = vector_cache.compact_batches if vector_cache else ()
  for index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color = "#000000" if style is None or style.color is None else style.color
    alpha = 1.0 if style is None else style.alpha
    marker_size = 3.0 if style is None else style.marker_size
    marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
    cached_layer = (
      cached_layers_by_id.get(source_id)
      if full_vector and not event_colors else None
    )
    if cached_layer is None:
      points: Iterator[tuple[float, float]] = zip(*layers[source_id], strict=False)
    else:
      points = iter(cached_layer.points)
    if not compact_vector and not hybrid_raster:
      colors = None if event_colors is None else event_colors.get(source_id)
      for point_index, (x_value, y_value) in enumerate(points):
        if cancel_check is not None and point_index % 256 == 0:
          cancel_check()
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
        if cancel_check is not None:
          cancel_check()
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
      # The former implementation used y=55 for every export.  That fixed
      # coordinate collides with the second/third title line in overlays.
      # Keep the legend in the resolved title band so it cannot enter the
      # plot rectangle or overlap title glyphs.
      title_end = (
        layout.title_baselines[-1] + layout.title_line_height * 0.55
        if layout.title_baselines else 0.0
      )
      legend_y = max(title_end + 4.0, layout.title_block[1] + 4.0) + index * 18.0
      elements.append(
        f'<text x="{width - 180:g}" y="{legend_y:g}" fill="{escape(color)}">'
        f"{escape(str(label))}</text>"
      )
    if cancel_check is not None:
      cancel_check()
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
    json.dumps(_export_metadata(prepared, options, hybrid_info, selected), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_png(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: Mapping[str, LayerValues] | None = None,
  event_colors: Mapping[str, Any] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
  cancel_check: Callable[[], None] | None = None,
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
  layout = _resolved_layout(
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
      if cancel_check is not None and index % 256 == 0:
        cancel_check()
      color = _rgb(color_text if colors is None or index >= len(colors) else colors[index])
      x = round(left + float(x_value) * plot_width)
      y = round(top + (1.0 - float(y_value)) * plot_height)
      layer_draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=color + (round(255 * alpha),),
      )
    image.alpha_composite(layer)
    if cancel_check is not None:
      cancel_check()
  draw = ImageDraw.Draw(image)
  if options is None or options.include_gates:
    _draw_raster_gates(
      draw, _scene_gates(prepared), left, top, plot_width, plot_height, device_scale
    )
  _draw_raster_text(
    draw, prepared, selected, width * scale, height * scale,
    left, top, plot_width, plot_height, options, device_scale, layout,
  )
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  image.convert("RGB").resize(
    (width, height), Image.Resampling.LANCZOS
  ).save(out_path, format="PNG", dpi=(canvas.dpi, canvas.dpi))
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options, selected=selected), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_pdf(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: Mapping[str, LayerValues] | None = None,
  event_colors: Mapping[str, Any] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
  render_cache: VectorRenderCache | None = None,
  cancel_check: Callable[[], None] | None = None,
) -> None:
  """Write a minimal vector PDF using the same prepared layers and styles."""
  pdf_started = time.perf_counter()
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
  layout = _resolved_layout(width, height, prepared, selected, options)
  commands = [
    f"{background[0] / 255:g} {background[1] / 255:g} {background[2] / 255:g} rg",
    f"0 0 {width} {height} re f",
  ]
  style_by_id = {style.source_id: style for style in selected.source_styles}
  full_vector = options is None or options.vector_scatter_mode == "full_vector"
  compact_vector = options is not None and options.vector_scatter_mode == "compact_vector"
  hybrid_raster = options is not None and options.vector_scatter_mode == "hybrid_raster"
  vector_cache = render_cache
  cache_started = time.perf_counter()
  if vector_cache is None and (compact_vector or hybrid_raster):
    vector_cache = prepare_vector_render_cache(
      prepared, selected, layers, options=options, event_colors=event_colors,
      cancel_check=cancel_check,
    )
  cache_seconds = time.perf_counter() - cache_started
  hybrid_info: dict[str, Any] | None = None
  if hybrid_raster:
    hybrid_info = dict((vector_cache.hybrid_info if vector_cache else None) or {})
    hybrid_info.setdefault("timings", {})
    hybrid_info["timings"]["pdf_scatter_cache_seconds"] = cache_seconds
  command_started = time.perf_counter()
  cached_layers_by_id = (
    {layer.source_id: layer for layer in vector_cache.layers}
    if vector_cache is not None and not event_colors else {}
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
      cached_layer = cached_layers_by_id.get(source_id)
      point_count = (
        len(cached_layer.points)
        if cached_layer is not None and not event_colors
        else len(layers[source_id][0])
      )
      for index in range(point_count):
        if cancel_check is not None and index % 256 == 0:
          cancel_check()
        color_text = default_color if colors is None or index >= len(colors) else colors[index]
        key = (source_id, color_text)
        if key not in marker_refs:
          marker_refs[key] = len(form_specs)
          form_specs.append((_rgb(color_text), alpha, marker_shape, marker_size))
    commands.append("q")
    commands.append(f"{left:g} {height - top - plot_height:g} {plot_width:g} {plot_height:g} re W n")
  preserve_event_colors = compact_vector and bool(event_colors)
  compact_batches = (
    vector_cache.compact_batches if vector_cache is not None
    and compact_vector and not preserve_event_colors
    else ()
  )
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
          if cancel_check is not None and index % 256 == 0:
            cancel_check()
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
        if cancel_check is not None:
          cancel_check()
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
      if cancel_check is not None:
        cancel_check()
      style = style_by_id.get(source_id)
      color = _rgb("#4c78a8" if style is None or style.color is None else style.color)
      commands.append(f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} rg")
      for index, (x_value, y_value) in enumerate(zip(*layers[source_id], strict=False)):
        if cancel_check is not None and index % 256 == 0:
          cancel_check()
        x, y = _pdf_normalized_point(
          float(x_value), float(y_value), left, top, plot_width, plot_height, height,
        )
        commands.append(f"{x:g} {y:g} 2 2 re f")
  elif full_vector:
    for source_id in prepared.source_order:
      if cancel_check is not None:
        cancel_check()
      style = style_by_id.get(source_id)
      default_color = "#4c78a8" if style is None or style.color is None else style.color
      colors = None if event_colors is None else event_colors.get(source_id)
      cached_layer = cached_layers_by_id.get(source_id)
      points = (
        iter(cached_layer.points)
        if cached_layer is not None and not event_colors
        else zip(*layers[source_id], strict=False)
      )
      for index, (x_value, y_value) in enumerate(points):
        if cancel_check is not None and index % 256 == 0:
          cancel_check()
        x, y = _pdf_normalized_point(
          float(x_value), float(y_value), left, top, plot_width, plot_height, height,
        )
        size = (2.0 if style is None else style.marker_size) / 2.0
        color_text = default_color if colors is None or index >= len(colors) else colors[index]
        commands.extend(("q", f"{size:g} 0 0 {size:g} {x:g} {y:g} cm", f"/M{marker_refs[(source_id, color_text)]} Do", "Q"))
    commands.append("Q")
  if cancel_check is not None:
    cancel_check()
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
    layout,
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
  command_seconds = time.perf_counter() - command_started
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  publish_started = time.perf_counter()
  out_path.write_bytes(bytes(pdf))
  publish_seconds = time.perf_counter() - publish_started
  if hybrid_info is not None:
    hybrid_info.setdefault("timings", {}).update({
      "pdf_command_seconds": command_seconds,
      "pdf_publish_seconds": publish_seconds,
      "pdf_total_seconds": time.perf_counter() - pdf_started,
    })
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options, hybrid_info, selected), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_jpg(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: Mapping[str, LayerValues] | None = None,
  event_colors: Mapping[str, Any] | None = None,
  *,
  width: int = 800,
  height: int = 600,
  options: BatchPlotExportSpec | None = None,
  cancel_check: Callable[[], None] | None = None,
) -> None:
  """Write JPEG through Pillow without making Qt part of the core renderer."""
  selected = presentation or prepared.resolved_presentation.presentation
  try:
    from PIL import Image
  except ImportError as exc:
    raise PlotExportError("JPEG export requires the Pillow package") from exc
  width, height = _dimensions(width, height, options)
  png_path = Path(path).with_suffix(".png.tmp")
  write_plot_png(png_path, prepared, presentation, layers, width=width, height=height,
                 options=options, event_colors=event_colors, cancel_check=cancel_check)
  try:
    with Image.open(png_path) as image:
      image.convert("RGB").save(path, format="JPEG", dpi=(options.dpi, options.dpi)
                                 if options else None)
  finally:
    png_path.unlink(missing_ok=True)
    png_path.with_suffix(png_path.suffix + ".json").unlink(missing_ok=True)
  Path(path).with_suffix(Path(path).suffix + ".json").write_text(
    json.dumps(_export_metadata(prepared, options, selected=selected), indent=2, ensure_ascii=False) + "\n",
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
  selected: PlotPresentationSpec | None = None,
) -> dict[str, Any]:
  metadata = dict(prepared.metadata)
  canvas = resolve_export_canvas(options)
  selected_presentation = selected or prepared.resolved_presentation.presentation
  metadata["export_canvas"] = canvas.to_mapping()
  metadata["renderer_contract_version"] = "plot-layout.v1"
  metadata["plot_layout"] = _resolved_layout(
    canvas.logical_width, canvas.logical_height, prepared,
    selected_presentation, options,
  ).to_mapping()
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
    if isinstance(vector_scatter.get("timings"), Mapping):
      metadata["render_timings"] = dict(vector_scatter["timings"])
  return metadata


def _svg_scene_axes(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  layout: PlotLayoutSpec,
) -> list[str]:
  """Render scene ticks/labels instead of the former fraction-based axes."""
  left, top, width, height = (float(value) for value in layout.plot_rect)
  bottom = top + height
  scene = _scene_mapping(prepared)
  foreground = _foreground_rgba(selected.background_color)
  axis_color = f"#{foreground[0]:02x}{foreground[1]:02x}{foreground[2]:02x}"
  elements = [
    f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="{height:g}" '
    f'fill="none" stroke="{axis_color}" stroke-width="{selected.axis_line_width:g}"/>',
  ]
  for axis, horizontal in (("x_ticks", True), ("y_ticks", False)):
    for tick in scene.get(axis, ()):
      if not isinstance(tick, Mapping):
        continue
      position = min(1.0, max(0.0, float(tick.get("position", 0.0))))
      major = bool(tick.get("major", True))
      if horizontal:
        x = left + position * width
        y = bottom
        grid = f'M {x:g} {top:g} V {bottom:g}'
        tick_path = f'M {x:g} {bottom:g} v {6 if major else 3:g}'
      else:
        x = left
        y = bottom - position * height
        grid = f'M {left:g} {y:g} H {left + width:g}'
        tick_path = f'M {left:g} {y:g} h {-6 if major else -3:g}'
      if selected.show_grid:
        grid_color = "#b8b8b8" if major else "#e0e0e0"
        elements.append(
          f'<path d="{grid}" fill="none" stroke="{grid_color}" '
          f'stroke-width="{1.0 if not major else 1.25:g}"/>'
        )
      elements.append(
        f'<path d="{tick_path}" fill="none" stroke="{axis_color}" '
        f'stroke-width="{selected.axis_line_width:g}"/>'
      )
      if major:
        label = _display_tick_label(str(tick.get("label", "")))
        if not label:
          continue
        if horizontal:
          elements.append(
            f'<text x="{x:g}" y="{layout.x_tick_label_y:g}" '
            f'text-anchor="middle" fill="{axis_color}" '
            f'font-size="{_font_px(selected.tick_font.size):g}">{escape(label)}</text>'
          )
        else:
          elements.append(
            f'<text x="{layout.y_tick_label_x:g}" y="{y + _font_px(selected.tick_font.size) * 0.35:g}" '
            f'text-anchor="end" fill="{axis_color}" '
            f'font-size="{_font_px(selected.tick_font.size):g}">{escape(label)}</text>'
          )
  if selected.x_axis_display_label:
    elements.append(
      f'<text x="{layout.x_axis_label_anchor[0]:g}" y="{layout.x_axis_label_anchor[1]:g}" '
      f'text-anchor="middle" fill="{axis_color}" '
      f'font-size="{_font_px(selected.axis_label_font.size):g}">{escape(selected.x_axis_display_label)}</text>'
    )
  if selected.y_axis_display_label:
    x_anchor, y_center = layout.y_axis_label_anchor
    elements.append(
      f'<text x="{x_anchor:g}" y="{y_center:g}" '
      f'text-anchor="middle" transform="rotate(-90 {x_anchor:g} {y_center:g})" '
      f'fill="{axis_color}" font-size="{_font_px(selected.axis_label_font.size):g}">'
      f'{escape(selected.y_axis_display_label)}</text>'
    )
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
  layers: Mapping[str, LayerValues],
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
    stroke_width = float(gate.get("width", 2.0))
    style = str(gate.get("style", "solid"))
    dash = {
      "dashed": ' stroke-dasharray="6,4"',
      "dotted": ' stroke-dasharray="1,3"',
      "dashdot": ' stroke-dasharray="6,3,1,3"',
    }.get(style, "")
    elements.append(
      f'<path d="{path}" fill="none" stroke="{color}" '
      f'stroke-width="{stroke_width:g}"{dash}/>'
    )
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
  """Resolve the normalized data rectangle from the canonical layout."""
  layout = resolve_plot_layout(
    _scene_with_selected_title(prepared, selected),
    asdict(selected),
    width=width,
    height=height,
    include_title=options is None or options.include_title,
    include_axis_labels=options is None or options.include_axis_labels,
    include_ticks=options is None or options.include_ticks,
  )
  _assert_layout(layout)
  left, top, plot_width, plot_height = layout.plot_rect
  return round(left), round(top), round(plot_width), round(plot_height)


def _resolved_layout(
  width: int,
  height: int,
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  options: BatchPlotExportSpec | None,
) -> PlotLayoutSpec:
  """Return the same layout used by every format adapter."""
  layout = resolve_plot_layout(
    _scene_with_selected_title(prepared, selected),
    asdict(selected),
    width=width,
    height=height,
    include_title=options is None or options.include_title,
    include_axis_labels=options is None or options.include_axis_labels,
    include_ticks=options is None or options.include_ticks,
  )
  _assert_layout(layout)
  return layout


def _assert_layout(layout: PlotLayoutSpec) -> None:
  """Reject layout geometry that could clip or overlap the data rectangle."""
  if layout.title_baselines:
    last_baseline = layout.title_baselines[-1]
    if last_baseline + layout.title_line_height * 0.35 > layout.plot_rect[1] + 1e-6:
      raise PlotExportError("title layout intersects plot rectangle")


def _scene_with_selected_title(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
) -> PlotScene:
  """Use an explicit writer presentation title for direct-export callers."""
  selected_lines = tuple(str(line) for line in selected.title.splitlines() if str(line))
  # In overlay mode the scene title lines are resolved from current visible
  # source metadata. ``selected.title`` must never shadow a Sample Sheet title,
  # regardless of whether one or many sources are visible.
  if (
    selected.title_mode == "overlay_sample_titles"
    and selected is prepared.resolved_presentation.presentation
  ):
    return prepared.scene
  if not selected_lines or selected_lines == prepared.scene.title_lines:
    return prepared.scene
  return replace(prepared.scene, title_lines=selected_lines)


def _title_lines(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
) -> tuple[str, ...]:
  return _scene_with_selected_title(prepared, selected).title_lines


def _title_baseline(
  layout: PlotLayoutSpec, line_index: int, line_count: int,
) -> float:
  """Align shorter per-sample titles to the bottom of a shared title band."""
  offset = max(0, len(layout.title_baselines) - line_count)
  return layout.title_baselines[offset + line_index]


def prepare_vector_render_cache(
  prepared: PreparedPlotExport,
  selected: PlotPresentationSpec,
  layers: Mapping[str, LayerValues],
  *,
  options: BatchPlotExportSpec | None = None,
  event_colors: Mapping[str, Any] | None = None,
  cancel_check: Callable[[], None] | None = None,
) -> VectorRenderCache:
  """Prepare the immutable scatter payload shared by SVG and PDF writers.

  The logical canvas and plot rectangle are resolved from the same arguments
  used by each writer. The returned object may safely be reused for every
  format of one prepared sample/view. It does not cache analytical arrays or
  alter event order, colors, or visibility.
  """
  width, height = _dimensions(800, 600, options)
  _left, _top, plot_width, plot_height = _raster_layout(
    width, height, prepared, selected, options,
  )
  vector_layers: tuple[VectorScatterLayer, ...] = ()
  if options is None or options.vector_scatter_mode == "full_vector":
    vector_layers = _vector_layers(prepared, selected, layers)
  compact_batches: tuple[CompactScatterBatch, ...] = ()
  if (
    options is not None
    and options.vector_scatter_mode == "compact_vector"
    and not event_colors
  ):
    compact_source_layers = _vector_layers(prepared, selected, layers)
    compact_batches = compact_scatter_batches(
      compact_source_layers, plot_width=plot_width, plot_height=plot_height,
    )
  hybrid_info: Mapping[str, Any] | None = None
  if options is not None and options.vector_scatter_mode == "hybrid_raster":
    hybrid_info = _hybrid_scatter_raster(
      prepared, selected, layers, plot_width=plot_width,
      plot_height=plot_height, dpi=options.hybrid_scatter_dpi,
      event_colors=event_colors,
      cancel_check=cancel_check,
    )
  return VectorRenderCache(vector_layers, compact_batches, hybrid_info)


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
  """Return the deterministic bundled scalable Pillow font.

  A fixed-size Pillow bitmap fallback would make high-DPI text much smaller
  than lines and points. Treat missing/corrupt package resources as an export
  failure instead of producing a visually invalid image.
  """
  try:
    return load_bundled_font(max(1, round(size)), bold=bold)
  except (BundledFontError, OSError) as exc:
    raise PlotExportError(f"bundled raster font is unavailable: {exc}") from exc


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
          grid_color = (184, 184, 184, 255) if bool(tick.get("major", True)) else (224, 224, 224, 255)
          draw.line((x, top, x, bottom), fill=grid_color, width=max(1, round(scale * (1.25 if tick.get("major", True) else 0.75))))
        else:
          y = round(origin - position * extent)
          grid_color = (184, 184, 184, 255) if bool(tick.get("major", True)) else (224, 224, 224, 255)
          draw.line(
            (left, y, left + plot_width, y),
            fill=grid_color,
            width=max(1, round(scale * (1.25 if tick.get("major", True) else 0.75))),
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
    line_width = max(1, round(float(gate.get("width", 1.5)) * scale))
    draw.line(
      mapped,
      fill=_rgb(str(gate.get("color", "#ffffff"))) + (255,),
      width=line_width,
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
  layout: PlotLayoutSpec,
) -> None:
  scene = _scene_mapping(prepared)
  title_lines = _title_lines(prepared, selected)
  title_colors = scene.get("title_colors", ()) if isinstance(scene, dict) else ()
  if options is None or options.include_title:
    title_font = _font(_font_px(selected.title_font.size) * scale, bold=selected.title_font.weight == "bold")
    for index, line in enumerate(title_lines):
      color = str(title_colors[index]) if index < len(title_colors) else "#b8c7ff"
      _draw_centered(draw, width // 2, round(_title_baseline(layout, index, len(title_lines)) * scale), line,
                     title_font, _rgb(color) + (255,))
  foreground = _foreground_rgba(selected.background_color)
  tick_font = _font(_font_px(selected.tick_font.size) * scale, bold=selected.tick_font.weight == "bold")
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
          _draw_centered(draw, round(origin + position * extent), round(layout.x_tick_label_y * scale),
                         label, tick_font, foreground)
        else:
          bbox = draw.textbbox((0, 0), label, font=tick_font)
          x = round(layout.y_tick_label_x * scale) - (bbox[2] - bbox[0])
          y = round(origin - position * extent) - (bbox[3] - bbox[1]) // 2
          draw.text((x, y), label, font=tick_font, fill=foreground)
  if options is None or options.include_axis_labels:
    axis_font = _font(_font_px(selected.axis_label_font.size) * scale,
                      bold=selected.axis_label_font.weight == "bold")
    _draw_centered(
      draw, round(layout.x_axis_label_anchor[0] * scale),
      round(layout.x_axis_label_anchor[1] * scale),
                   selected.x_axis_display_label or "", axis_font, foreground)
    label = selected.y_axis_display_label or ""
    if label:
      _draw_vertical(
        draw, round(layout.y_axis_label_anchor[0] * scale),
        round(layout.y_axis_label_anchor[1] * scale), label, axis_font,
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
  layout: PlotLayoutSpec,
) -> list[str]:
  """Emit ASCII-safe PDF text for titles, major ticks, and axis labels."""
  scene = _scene_mapping(prepared)
  commands: list[str] = []
  if options is None or options.include_title:
    title_lines = _title_lines(prepared, selected)
    colors = scene.get("title_colors", ())
    for index, line in enumerate(title_lines):
      color = str(colors[index]) if index < len(colors) else "#4c78a8"
      red, green, blue = (value / 255 for value in _rgb(color))
      size = _font_px(selected.title_font.size)
      text = _pdf_text(line)
      x = (page_width - len(text) * size * 0.55) / 2
      # PDF text coordinates use the baseline; Pillow's raster renderer
      # receives the top-left text coordinate.
      y = page_height - _title_baseline(layout, index, len(title_lines)) - size * 0.15
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
        size = _font_px(selected.tick_font.size)
        if horizontal:
          x = left + position * width - _pdf_tick_label_width(label, size) / 2
          y = page_height - layout.x_tick_label_y
        else:
          x = layout.y_tick_label_x - _pdf_tick_label_width(label, size)
          y = page_height - (top + plot_height - position * plot_height) - size * 0.35
        commands.extend(_pdf_tick_label_commands(label, x, y, size, red, green, blue))
  if options is None or options.include_axis_labels:
    size = _font_px(selected.axis_label_font.size)
    x_label = _pdf_text(selected.x_axis_display_label or "")
    if x_label:
      x = layout.x_axis_label_anchor[0] - len(x_label) * size * 0.28
      y = page_height - layout.x_axis_label_anchor[1]
      commands.append(f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg {x:g} {y:g} Td ({x_label}) Tj ET")
    y_label = _pdf_text(selected.y_axis_display_label or "")
    if y_label:
      x_anchor, y_anchor = layout.y_axis_label_anchor
      y = page_height - y_anchor + len(y_label) * size * 0.28
      commands.append(f"BT /F2 {size:g} Tf {red:g} {green:g} {blue:g} rg 0 1 -1 0 {x_anchor:g} {y:g} Tm ({y_label}) Tj ET")
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
    line_width = float(gate.get("width", 2.0))
    commands.append(
      f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} "
      f"RG {line_width:g} w"
    )
    style = str(gate.get("style", "solid"))
    if style == "dashed":
      commands.append("[6 4] 0 d")
    elif style == "dotted":
      commands.append("[1 3] 0 d")
    elif style == "dashdot":
      commands.append("[6 3 1 3] 0 d")
    else:
      commands.append("[] 0 d")
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
  layers: Mapping[str, LayerValues],
  event_colors: Mapping[str, Any] | None = None,
  *,
  plot_width: float,
  plot_height: float,
  dpi: int,
  cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
  """Render only scatter markers into a transparent lossless RGBA raster."""
  if dpi < 72 or dpi > 2400:
    raise PlotExportError("hybrid scatter dpi must be between 72 and 2400")
  raster_scale = dpi / 96.0
  raster_width = max(1, round(plot_width * raster_scale))
  raster_height = max(1, round(plot_height * raster_scale))
  pixels = bytearray(raster_width * raster_height * 4)
  rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(
    (raster_height, raster_width, 4)
  )
  style_by_id = {style.source_id: style for style in selected.source_styles}
  point_hasher = hashlib.sha256()
  rendered_event_count = 0
  rgb_cache: dict[str, tuple[int, int, int]] = {}
  composite_started = time.perf_counter()

  def blend_opaque_row(
    pixel_y: int,
    min_x: int,
    max_x: int,
    center_x: float,
    center_y: float,
    radius: float,
    shape: str,
    color: tuple[int, int, int],
  ) -> None:
    """Apply an opaque marker row with the same pixel-center predicate."""
    x_positions = np.arange(min_x, max_x + 1, dtype=np.float64)
    dx = x_positions + 0.5 - center_x
    dy = pixel_y + 0.5 - center_y
    inside = (
      dx * dx + dy * dy <= radius * radius
      if shape == "circle"
      else (np.abs(dx) <= radius) & (abs(dy) <= radius)
    )
    positions = np.flatnonzero(inside)
    if len(positions):
      rgba[pixel_y, min_x + positions, :3] = color
      rgba[pixel_y, min_x + positions, 3] = 255

  def blend_alpha_marker(
    min_x: int,
    max_x: int,
    min_y: int,
    max_y: int,
    center_x: float,
    center_y: float,
    radius: float,
    shape: str,
    color: tuple[int, int, int],
    alpha: float,
  ) -> None:
    """Alpha-composite one marker directly into the NumPy RGBA buffer.

    The previous implementation allocated a Pillow mask and tile for every
    event, then called ``Image.alpha_composite``.  That preserved z-order but
    made large hybrid exports quadratic in Python/Qt object overhead.  The
    equations below are the same source-over operation applied to only the
    marker footprint, preserving event order and overlap intensity.
    """
    x_positions = np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5 - center_x
    y_positions = np.arange(min_y, max_y + 1, dtype=np.float64)[:, None] + 0.5 - center_y
    if shape == "circle":
      inside = x_positions[None, :] ** 2 + y_positions ** 2 <= radius * radius
    else:
      inside = (
        np.abs(x_positions[None, :]) <= radius
        ) & (np.abs(y_positions) <= radius)
    local_y, local_x = np.nonzero(inside)
    if not len(local_x):
      return
    pixel_y = min_y + local_y
    pixel_x = min_x + local_x
    destination = rgba[pixel_y, pixel_x].astype(np.float64)
    source_alpha = max(0.0, min(1.0, alpha))
    destination_alpha = destination[:, 3] / 255.0
    output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha)
    nonzero = output_alpha > 0.0
    output_rgb = np.zeros((len(destination), 3), dtype=np.float64)
    output_rgb[nonzero] = (
      np.asarray(color, dtype=np.float64)[None, :] * source_alpha
      + destination[nonzero, :3]
      * destination_alpha[nonzero, None]
      * (1.0 - source_alpha)
    ) / output_alpha[nonzero, None]
    rgba[pixel_y, pixel_x, :3] = np.rint(output_rgb).astype(np.uint8)
    rgba[pixel_y, pixel_x, 3] = np.rint(output_alpha * 255.0).astype(np.uint8)

  def blend_uniform_alpha_layer(
    x_values: Sequence[float],
    y_values: Sequence[float],
    radius: float,
    shape: str,
    color: tuple[int, int, int],
    alpha: float,
  ) -> None:
    """Composite a uniform-color layer using one count raster.

    For one source with one color, drawing events one at a time is
    commutative: ``n`` identical source-over operations equal one operation
    with alpha ``1 - (1 - a) ** n``.  Accumulating marker coverage with
    ``np.add.at`` removes the per-event Pillow/NumPy allocation while keeping
    overlap density and source z-order intact.
    """
    extent = max(1, math.ceil(radius + 1.0))
    counts = np.zeros((raster_height, raster_width), dtype=np.int32)
    x = np.asarray(x_values, dtype=np.float64) * (raster_width - 1)
    y = (1.0 - np.asarray(y_values, dtype=np.float64)) * (raster_height - 1)

    # For a small/medium raster, accumulate flat pixel indices in C with
    # bincount.  The operation is exactly equivalent to the old add.at loop:
    # each event contributes one count to every pixel satisfying the same
    # pixel-center predicate.  Keep a bounded chunk size and a raster-size
    # guard so high-DPI exports do not allocate a second full-sized count
    # array.  The fallback below is intentionally retained for that case.
    # Combining repeated source-over operations is algebraically exact on a
    # transparent destination.  On an already populated destination, the
    # legacy event-by-event path is required because it rounds to 8-bit after
    # every event; collapsing those rounded intermediates can change a pixel
    # by one.  This preserves multi-source z-order and byte-level parity.
    fast_path = counts.size <= 4_000_000 and not np.any(rgba[:, :, 3])
    chunk_size = 100_000
    for chunk_start in range(0, len(x), chunk_size):
      chunk_end = min(len(x), chunk_start + chunk_size)
      chunk_x = x[chunk_start:chunk_end]
      chunk_y = y[chunk_start:chunk_end]
      base_x = np.floor(chunk_x).astype(np.int64)
      base_y = np.floor(chunk_y).astype(np.int64)
      frac_x = chunk_x - base_x
      frac_y = chunk_y - base_y
      if fast_path:
        targets: list[np.ndarray] = []
      for offset_y in range(-extent, extent + 1):
        pixel_y = base_y + offset_y
        valid_y = (pixel_y >= 0) & (pixel_y < raster_height)
        if not np.any(valid_y):
          continue
        dy = offset_y + 0.5 - frac_y
        for offset_x in range(-extent, extent + 1):
          pixel_x = base_x + offset_x
          valid = valid_y & (pixel_x >= 0) & (pixel_x < raster_width)
          if shape == "circle":
            valid &= (offset_x + 0.5 - frac_x) ** 2 + dy ** 2 <= radius * radius
          else:
            valid &= np.abs(offset_x + 0.5 - frac_x) <= radius
            valid &= np.abs(dy) <= radius
          if not np.any(valid):
            continue
          if fast_path:
            targets.append(pixel_y[valid] * raster_width + pixel_x[valid])
          else:
            np.add.at(counts, (pixel_y[valid], pixel_x[valid]), 1)
        if cancel_check is not None:
          cancel_check()
      if fast_path and targets:
        flat_targets = np.concatenate(targets)
        counts.flat += np.bincount(
          flat_targets, minlength=counts.size,
        ).astype(np.int32, copy=False)
    pixel_y, pixel_x = np.nonzero(counts)
    if not len(pixel_x):
      return
    destination = rgba[pixel_y, pixel_x].astype(np.float64)
    source_alpha = max(0.0, min(1.0, alpha))
    output_alpha = 1.0 - (1.0 - source_alpha) ** counts[pixel_y, pixel_x]
    destination_alpha = destination[:, 3] / 255.0
    combined_alpha = output_alpha + destination_alpha * (1.0 - output_alpha)
    output_rgb = (
      np.asarray(color, dtype=np.float64)[None, :] * output_alpha[:, None]
      + destination[:, :3]
      * destination_alpha[:, None]
      * (1.0 - output_alpha[:, None])
    ) / combined_alpha[:, None]
    rgba[pixel_y, pixel_x, :3] = np.rint(output_rgb).astype(np.uint8)
    rgba[pixel_y, pixel_x, 3] = np.rint(combined_alpha * 255.0).astype(np.uint8)

  for z_index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color_text = "#000000" if style is None or style.color is None else style.color
    alpha = 1.0 if style is None else style.alpha
    shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
    marker_size = 3.0 if style is None else style.marker_size
    radius = marker_size * raster_scale / 2.0
    x_values, y_values = layers[source_id]
    colors = None if event_colors is None else event_colors.get(source_id)
    if alpha < 1.0 and colors is None:
      for index, (x_value, y_value) in enumerate(
        zip(x_values, y_values, strict=False)
      ):
        if cancel_check is not None and index % 256 == 0:
          cancel_check()
        point_hasher.update(source_id.encode("utf-8"))
        point_hasher.update(b"\0")
        point_hasher.update(struct.pack(">dd", float(x_value), float(y_value)))
        point_hasher.update(color_text.encode("utf-8"))
        point_hasher.update(b"\0")
        point_hasher.update(struct.pack(">ddI", float(alpha), float(marker_size), z_index))
        point_hasher.update(shape.encode("utf-8"))
        point_hasher.update(b"\0")
        rendered_event_count += 1
      blend_uniform_alpha_layer(
        x_values, y_values, radius, shape, rgb_cache.setdefault(color_text, _rgb(color_text)), alpha
      )
      continue
    for index, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=False)):
      if cancel_check is not None and index % 256 == 0:
        cancel_check()
      point_color_text = (
        color_text if colors is None or index >= len(colors) else colors[index]
      )
      point_color = rgb_cache.get(point_color_text)
      if point_color is None:
        point_color = _rgb(point_color_text)
        rgb_cache[point_color_text] = point_color
      x = float(x_value) * (raster_width - 1)
      y = (1.0 - float(y_value)) * (raster_height - 1)
      rendered_event_count += 1
      # The provenance contract needs a deterministic point-plan identity,
      # not the full JSON record list.  Hash a stable binary record directly
      # to avoid constructing hundreds of thousands of temporary dictionaries.
      point_hasher.update(source_id.encode("utf-8"))
      point_hasher.update(b"\0")
      point_hasher.update(struct.pack(">dd", float(x_value), float(y_value)))
      point_hasher.update(point_color_text.encode("utf-8"))
      point_hasher.update(b"\0")
      point_hasher.update(struct.pack(">ddI", float(alpha), float(marker_size), z_index))
      point_hasher.update(shape.encode("utf-8"))
      point_hasher.update(b"\0")
      min_x = max(0, math.floor(x - radius - 1))
      max_x = min(raster_width - 1, math.ceil(x + radius + 1))
      min_y = max(0, math.floor(y - radius - 1))
      max_y = min(raster_height - 1, math.ceil(y + radius + 1))
      if alpha >= 1.0:
        for pixel_y in range(min_y, max_y + 1):
          blend_opaque_row(
            pixel_y, min_x, max_x, x, y, radius, shape, point_color,
          )
      else:
        blend_alpha_marker(
          min_x, max_x, min_y, max_y, x, y, radius, shape,
          point_color, alpha,
        )

    if cancel_check is not None:
      cancel_check()

  composite_seconds = time.perf_counter() - composite_started
  encoding_started = time.perf_counter()
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
  encoding_seconds = time.perf_counter() - encoding_started
  point_hasher.update(struct.pack(">III", dpi, raster_width, raster_height))
  point_hasher.update(b"hybrid_scatter_raster.v3\0")
  point_hasher.update("\0".join(prepared.source_order).encode("utf-8"))
  return {
    "png": png, "rgb": bytes(value for index, value in enumerate(pixels) if index % 4 != 3),
    "alpha": bytes(pixels[index] for index in range(3, len(pixels), 4)),
    "width": raster_width, "height": raster_height, "dpi": dpi,
    "rendered_event_count": rendered_event_count,
    "point_plan_hash": point_hasher.hexdigest(),
    "algorithm_version": "hybrid_scatter_raster.v3",
    "timings": {
      "scatter_composite_seconds": composite_seconds,
      "scatter_png_encode_seconds": encoding_seconds,
      "scatter_total_seconds": composite_seconds + encoding_seconds,
    },
  }
