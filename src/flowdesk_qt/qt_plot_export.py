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
  PreparedPlotExport,
  prepare_plot_export,
  write_plot_jpg,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.transforms import apply_transform


def render_prepared_plot_qt(
  path: str | Path,
  *,
  prepared: PreparedPlotExport,
  layers: Mapping[str, tuple[Any, Any]],
  event_colors: Mapping[str, NDArray[np.str_]] | None = None,
  options: BatchPlotExportSpec,
  export_metadata: Mapping[str, Any] | None = None,
  input_event_count: int | None = None,
) -> None:
  """Dispatch an already prepared renderer-neutral plot to a format writer.

  This is the only entry point used by the live current-view export path.
  Coordinates in ``layers`` must already be normalized to the scene view
  range; no Qt state, transform, title, gate, or layout information is
  reconstructed here.  The older ``render_batch_plot_qt`` wrapper below is
  retained solely for callers/tests that still provide raw Qt-shaped inputs.
  """
  source_ids = tuple(prepared.source_order)
  if set(layers) != set(source_ids):
    missing = [source_id for source_id in source_ids if source_id not in layers]
    extra = [source_id for source_id in layers if source_id not in source_ids]
    detail = []
    if missing:
      detail.append("missing=" + ",".join(missing))
    if extra:
      detail.append("extra=" + ",".join(extra))
    raise ValueError(
      "prepared plot layers do not match source order ("
      + "; ".join(detail) + ")"
    )
  suffix = Path(path).suffix.lower()
  if suffix == ".png":
    writer = write_plot_png
  elif suffix in {".jpg", ".jpeg"}:
    writer = write_plot_jpg
  elif suffix == ".svg":
    writer = write_plot_svg
  elif suffix == ".pdf":
    writer = write_plot_pdf
  else:
    raise ValueError(f"plot renderer does not support {suffix!r}")
  writer(
    path, prepared, layers=layers, event_colors=event_colors, options=options,
    width=options.width, height=options.height,
  )
  if export_metadata:
    sidecar = Path(path).with_suffix(Path(path).suffix + ".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata.update(dict(export_metadata))
    # The prepared core payload is authoritative.  Provenance from the GUI
    # must never overwrite its resolved source/style/scene contract.
    metadata["ordered_source_ids"] = list(prepared.source_order)
    metadata["source_draw_order"] = list(prepared.draw_order)
    metadata["presentation"] = dict(prepared.metadata["presentation"])
    metadata["scene"] = prepared.scene.to_mapping()
    metadata["scene_hash"] = prepared.scene.scene_hash()
    displayed_count = sum(len(layers[source_id][0]) for source_id in source_ids)
    metadata["display_state"] = {
      "mode": "scatter",
      "input_event_count": (
        displayed_count if input_event_count is None else input_event_count
      ),
      "displayed_event_count": displayed_count,
    }
    sidecar.write_text(
      json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


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
  prepared: PreparedPlotExport | None = None,
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
  if not source_ids:
    raise ValueError("at least one source is required")
  if prepared is None:
    sources = tuple({
      "source_id": source_id, "sample_id": source_id,
      "population_id": "all_events",
      "display_name": (
        "\n".join(title_lines) if len(source_ids) == 1 and title_lines
        else title_lines[index] if index < len(title_lines)
        else source_id
      ),
      "visible": True, "order": index,
    } for index, source_id in enumerate(source_ids))
    resolved_presentation = dict(presentation)
    resolved_presentation["title"] = "\n".join(title_lines)
    resolved_presentation["source_styles"] = [
      {"source_id": source_id, **dict(source_styles.get(source_id, {}))}
      for source_id in source_ids
    ]
    scene = {
      "x_parameter": x_parameter, "y_parameter": y_parameter,
      "x_transform_id": x_spec.id if x_spec else None,
      "y_transform_id": y_spec.id if y_spec else None,
      "view_range": [list(x_range), list(y_range)],
      "plot_area": list(plot_area or (60.0, 50.0, 20.0, 60.0)),
      "title_lines": list(title_lines), "title_colors": list(title_colors),
      "x_axis_label": str(presentation.get("x_axis_display_label", "")),
      "y_axis_label": str(presentation.get("y_axis_display_label", "")),
      "source_order": list(source_ids), "gates": [dict(gate) for gate in gates],
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
  normalized_event_colors: dict[str, Any] | None = None
  if event_colors is not None:
    normalized_event_colors = {}
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
    x_array = np.asarray(x_values, dtype=np.float64)
    y_array = np.asarray(y_values, dtype=np.float64)
    finite = np.isfinite(x_array) & np.isfinite(y_array)
    normalized_layers[source_id] = (
      tuple(((x_array[finite] - x_range[0]) / x_span).tolist()),
      tuple(((y_array[finite] - y_range[0]) / y_span).tolist()),
    )
    if normalized_event_colors is not None and source_id in event_colors:
      colors = np.asarray(event_colors[source_id])
      count = min(len(finite), len(colors))
      normalized_event_colors[source_id] = colors[:count][finite[:count]]
  render_prepared_plot_qt(
    path, prepared=prepared, layers=normalized_layers,
    event_colors=normalized_event_colors, options=options,
    export_metadata=export_metadata,
    input_event_count=sum(len(raw_layers[source_id][0]) for source_id in source_ids),
  )


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
