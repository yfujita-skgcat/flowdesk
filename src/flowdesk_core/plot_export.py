"""Renderer-neutral plot export preparation and a dependency-free SVG adapter."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any

from flowdesk_core.models import PlotPresentationSpec, PlotType
from flowdesk_core.plot_presentation import (
  OverlaySourceResolution,
  PresentationDiagnostic,
  ResolvedPresentation,
  resolve_presentation_layers,
  validate_presentation,
)


class PlotExportError(ValueError):
  """Raised when a plot cannot be exported without losing visible content."""


@dataclass(frozen=True)
class PreparedPlotExport:
  plot_id: str
  plot_type: PlotType
  source_order: tuple[str, ...]
  metadata: dict[str, Any]
  resolved_presentation: ResolvedPresentation


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
    "diagnostics": diagnostics,
    "scientific_note": (
      "Presentation settings and display sampling do not alter scientific results."
    ),
  }
  return PreparedPlotExport(
    plot_id, plot_type, tuple(visible_order), metadata, resolved
  )


def write_plot_svg(
  path: str | Path,
  prepared: PreparedPlotExport,
  presentation: PlotPresentationSpec | None = None,
  layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] | None = None,
) -> None:
  """Write a small deterministic SVG using the prepared source order."""
  selected = presentation or prepared.resolved_presentation.presentation
  layers = layers or {}
  if any(source_id not in layers for source_id in prepared.source_order):
    missing = [source_id for source_id in prepared.source_order if source_id not in layers]
    raise PlotExportError(f"missing prepared layer data: {', '.join(missing)}")
  if not prepared.source_order:
    raise PlotExportError("cannot export a plot with no visible source")
  width, height = 800, 600
  elements = [
    f'<rect width="100%" height="100%" fill="{escape(selected.background_color)}"/>',
    f'<text x="400" y="32" text-anchor="middle" font-size="{selected.title_font.size}">'
    f"{escape(selected.title)}</text>",
    f'<text x="400" y="580" text-anchor="middle">'
    f"{escape(selected.x_axis_display_label or '')}</text>",
    f'<text x="15" y="300" text-anchor="middle" transform="rotate(-90 15 300)">'
    f"{escape(selected.y_axis_display_label or '')}</text>",
  ]
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
  for index, source_id in enumerate(prepared.source_order):
    style = style_by_id.get(source_id)
    color = "#4c78a8" if style is None or style.color is None else style.color
    x_values, y_values = layers[source_id]
    for x_value, y_value in zip(x_values, y_values, strict=False):
      x = 60.0 + float(x_value) * 680.0
      y = 520.0 - float(y_value) * 460.0
      elements.append(
        f'<circle cx="{x:g}" cy="{y:g}" r="3" fill="{escape(color)}"/>'
      )
    label = style.legend_label if style and style.legend_label else source_labels[source_id]
    elements.append(
      f'<text x="620" y="{55 + index * 20}" fill="{escape(color)}">'
      f"{escape(str(label))}</text>"
    )
  svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
    + "".join(elements) + "</svg>\n"
  )
  out_path = Path(path)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(svg, encoding="utf-8")
  out_path.with_suffix(out_path.suffix + ".json").write_text(
    json.dumps(prepared.metadata, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
  )
