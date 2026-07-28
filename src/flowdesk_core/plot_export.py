"""Renderer-neutral plot export preparation and a dependency-free SVG adapter."""

from __future__ import annotations

import json
import re
import struct
import zlib
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
  left, top, right, bottom = 60, 50, 20, 60
  plot_width, plot_height = width - left - right, height - top - bottom
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
  for index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color = "#000000" if style is None or style.color is None else style.color
    x_values, y_values = layers[source_id]
    for x_value, y_value in zip(x_values, y_values, strict=False):
      x = left + float(x_value) * plot_width
      y = top + (1.0 - float(y_value)) * plot_height
      if full_vector:
        elements.append(f'<use href="#{marker_ids[source_id]}" x="{x:g}" y="{y:g}"/>')
      else:
        elements.append(f'<circle cx="{x:g}" cy="{y:g}" r="3" fill="{escape(color)}"/>')
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
    json.dumps(_export_metadata(prepared, options), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_png(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
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
    color = _rgb("#000000" if style is None or style.color is None else style.color)
    alpha = 1.0 if style is None else style.alpha
    marker_size = 3.0 if style is None else style.marker_size
    radius = max(1, round(marker_size * device_scale / 2))
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    for x_value, y_value in zip(*layers[source_id], strict=False):
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
  left, top, right, bottom = 60, 50, 20, 60
  plot_width, plot_height = width - left - right, height - top - bottom
  commands = [
    f"{background[0] / 255:g} {background[1] / 255:g} {background[2] / 255:g} rg",
    f"0 0 {width} {height} re f",
  ]
  if options is None or options.include_ticks:
    commands.extend(_pdf_axes(left, top, plot_width, plot_height, height))
  style_by_id = {style.source_id: style for style in selected.source_styles}
  full_vector = options is None or options.vector_scatter_mode == "full_vector"
  form_specs: list[tuple[tuple[int, int, int], float, str, float]] = []
  marker_refs: dict[str, int] = {}
  if full_vector:
    for source_id in prepared.source_order:
      style = style_by_id.get(source_id)
      color = _rgb("#4c78a8" if style is None or style.color is None else style.color)
      alpha = 1.0 if style is None else style.alpha
      marker_size = 2.0 if style is None else style.marker_size
      marker_shape = "circle" if style is None or style.marker_shape is None else style.marker_shape
      marker_refs[source_id] = len(form_specs)
      form_specs.append((color, alpha, marker_shape, marker_size))
    commands.append("q")
    commands.append(f"{left:g} {height - top - plot_height:g} {plot_width:g} {plot_height:g} re W n")
  for source_id in prepared.source_order:
    style = style_by_id.get(source_id)
    color = _rgb("#4c78a8" if style is None or style.color is None else style.color)
    if not full_vector:
      commands.append(f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} rg")
    for x_value, y_value in zip(*layers[source_id], strict=False):
      x = left + float(x_value) * plot_width
      y = height - top - float(y_value) * plot_height
      if full_vector:
        size = (2.0 if style is None else style.marker_size) / 2.0
        commands.extend(("q", f"{size:g} 0 0 {size:g} {x:g} {y:g} cm", f"/M{marker_refs[source_id]} Do", "Q"))
      else:
        commands.append(f"{x:g} {y:g} 2 2 re f")
  if full_vector:
    commands.append("Q")
  if options is None or options.include_gates:
    commands.extend(_pdf_gates(_scene_gates(prepared), left, top, plot_width, plot_height, height))
  stream = ("\n".join(commands) + "\n").encode("ascii")
  form_start = 5
  xobjects = " ".join(
    f"/M{index} {form_start + index * 2} 0 R" for index in range(len(form_specs))
  )
  objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    (
      f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
      f"/Resources << /XObject << {xobjects} >> >> /Contents 4 0 R >>"
    ).encode("ascii"),
    b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
    + stream + b"endstream",
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
    json.dumps(_export_metadata(prepared, options), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )


def write_plot_jpg(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
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
                 options=options)
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
) -> dict[str, Any]:
  metadata = dict(prepared.metadata)
  metadata["export_canvas"] = resolve_export_canvas(options).to_mapping()
  if options is not None:
    metadata["export_options"] = asdict(options)
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
        if not isinstance(tick, dict) or not tick.get("major", True):
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
  from PIL import Image, ImageDraw

  bbox = draw.textbbox((0, 0), text, font=font)
  text_width = bbox[2] - bbox[0]
  text_height = bbox[3] - bbox[1]
  label = Image.new("RGBA", (text_width + 4, text_height + 4), (0, 0, 0, 0))
  ImageDraw.Draw(label).text((2, 2), text, font=font, fill=fill)
  rotated = label.rotate(90, expand=True)
  draw._image.alpha_composite(
    rotated, (round(x - rotated.width // 2), round(y - rotated.height // 2))
  )


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


def _pdf_axes(left: int, top: int, width: int, plot_height: int, height: int) -> list[str]:
  bottom = height - top
  commands = ["0.5 0.5 0.5 RG 1 w", f"{left} {top} m {left} {bottom} l {left + width} {bottom} l S"]
  for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
    x = left + fraction * width
    y = top + fraction * plot_height
    commands.append(f"{x:g} {bottom} m {x:g} {bottom - 5} l {left - 5} {y:g} m {left} {y:g} l S")
  return commands


def _pdf_marker_stream(shape: str, color: tuple[int, int, int]) -> bytes:
  """Build a normalized reusable Form XObject marker centered at (0, 0)."""
  red, green, blue = (value / 255 for value in color)
  prefix = f"{red:g} {green:g} {blue:g} rg\n"
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


def _pdf_gates(gates: tuple[dict[str, Any], ...], left: int, top: int,
               width: int, plot_height: int, height: int) -> list[str]:
  commands: list[str] = []
  for gate in gates:
    points = _gate_points(gate)
    if len(points) < 2:
      continue
    color = _rgb(str(gate.get("color", "#ffffff")))
    commands.append(f"{color[0] / 255:g} {color[1] / 255:g} {color[2] / 255:g} RG 2 w")
    transformed = [(left + x * width, height - top - y * plot_height) for x, y in points]
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
