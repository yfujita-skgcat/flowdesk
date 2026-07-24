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
from flowdesk_core.transforms import apply_transform, generate_transform_ticks
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
    view = next(
      (item for item in project.get("plot_views", [])
       if str(item.get("id")) == spec.plot_view_id),
      None,
    )
    if view is None:
      raise ValueError(
        f"batch plot view {spec.plot_view_id!r} is missing from the project"
      )
    try:
      persisted_view = PlotViewSpec(
        id=str(view.get("id", spec.plot_view_id)),
        population_id=str(view.get("population_id", "all_events")),
        x_parameter=str(view.get("x_parameter", "")),
        y_parameter=(
          None if view.get("y_parameter") is None
          else str(view.get("y_parameter"))
        ),
        x_transform_id=view.get("x_transform_id"),
        y_transform_id=view.get("y_transform_id"),
        plot_type=cast(PlotType, str(view.get("plot_type", "scatter"))),
        rendering_downsample=dict(view.get("rendering_downsample", {})),
      )
    except (TypeError, ValueError) as exc:
      raise ValueError(
        f"invalid batch plot view {spec.plot_view_id!r}: {exc}"
      ) from exc
    transform_by_id = {
      str(item.get("id")): item for item in project.get("transforms", [])
      if isinstance(item, Mapping) and item.get("id")
    }
    prepared_layers: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    layer_metadata: dict[str, dict[str, Any]] = {}
    shared_bounds: tuple[float, float, float, float] | None = None

    def extract_layer(sample: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
      _info, sample_data = read_fcs_sample(sample["path"], str(sample["id"]))
      names = [channel.id for channel in sample_data.channels]
      if len(names) < 2:
        raise ValueError("plot requires at least two channels")
      x_id = persisted_view.x_parameter
      y_id = persisted_view.y_parameter or names[1]
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
      processed_ids = {channel.id for channel in processed.channels}
      if x_id not in processed_ids or y_id not in processed_ids:
        raise ValueError(
          f"batch plot view {spec.plot_view_id!r} references unavailable axes "
          f"{x_id!r}, {y_id!r} for sample {sample['id']!r}"
        )
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
      x_label = next(
        (channel.name for channel in processed.channels if channel.id == x_id),
        x_id,
      )
      y_label = next(
        (channel.name for channel in processed.channels if channel.id == y_id),
        y_id,
      )
      return x_values[finite], y_values[finite], {
        "x_id": x_id, "y_id": y_id, "x_label": x_label, "y_label": y_label,
        "view_spec": view_spec,
      }

    def render(
      sample: Mapping[str, Any], path: Path, _spec: BatchPlotExportSpec
    ) -> None:
      nonlocal shared_bounds
      sample_id = str(sample["id"])
      if not prepared_layers:
        for candidate in samples:
          candidate_id = str(candidate["id"])
          x_values, y_values, metadata = extract_layer(candidate)
          prepared_layers[candidate_id] = (x_values, y_values)
          layer_metadata[candidate_id] = metadata
        if spec.layout_policy == "shared_ranges":
          all_x = np.concatenate([value[0] for value in prepared_layers.values()])
          all_y = np.concatenate([value[1] for value in prepared_layers.values()])
          shared_bounds = (
            float(np.min(all_x)), float(np.max(all_x)),
            float(np.min(all_y)), float(np.max(all_y)),
          )
      x_values, y_values = prepared_layers[sample_id]
      metadata = layer_metadata[sample_id]
      x_id, y_id = metadata["x_id"], metadata["y_id"]
      active_bounds = (
        shared_bounds[:2], shared_bounds[2:]
      ) if shared_bounds else (
        (float(np.min(x_values)), float(np.max(x_values))),
        (float(np.min(y_values)), float(np.max(y_values))),
      )
      advanced_overlay_ids = [
        str(source.get("sample_id"))
        for source in sorted(
          view.get("overlay_sources", ()),
          key=lambda item: (
            int(item.get("order", 0)), str(item.get("source_id", ""))
          ),
        )
        if source.get("visible", True) and source.get("sample_id")
      ]
      overlay_candidates = [
        *advanced_overlay_ids,
        *(str(value) for value in view.get("manual_overlay_sample_ids", ())),
      ]
      overlay_ids = tuple(
        value for index, value in enumerate(overlay_candidates)
        if value in prepared_layers and value != sample_id
        and value not in overlay_candidates[:index]
      )
      source_ids = (sample_id, *overlay_ids)
      source_by_id = {str(item["id"]): item for item in samples}
      sources = []
      layers: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {}
      for order, source_id in enumerate(source_ids):
        source_sample = source_by_id[source_id]
        source_metadata = layer_metadata[source_id]
        source_x, source_y = prepared_layers[source_id]
        layers[source_id] = (
          tuple(_normalize(source_x, active_bounds[0])),
          tuple(_normalize(source_y, active_bounds[1])),
        )
        sources.append({
          "source_id": source_id, "sample_id": source_id,
          "population_id": str(view.get("population_id", "all_events")),
          "display_name": str(source_sample.get("name", source_id)),
          "x_parameter_id": source_metadata["x_id"],
          "y_parameter_id": source_metadata["y_id"], "visible": True, "order": order,
          "style": next(
            (
              dict(item.get("style", {}))
              for item in view.get("overlay_sources", [])
              if str(item.get("sample_id")) == source_id
            ),
            {},
          ),
        })
      presentation = dict(view.get("presentation", {}))
      if not presentation.get("x_axis_display_label"):
        presentation["x_axis_display_label"] = metadata["x_label"]
      if not presentation.get("y_axis_display_label"):
        presentation["y_axis_display_label"] = metadata["y_label"]
      source_styles = {
        str(style.get("source_id")): dict(style)
        for style in presentation.get("source_styles", [])
        if isinstance(style, Mapping) and style.get("source_id")
      }
      manual_colors = view.get("manual_overlay_colors", {})
      for source_id in source_ids:
        explicit_color = (
          manual_colors.get(source_id)
          if isinstance(manual_colors, Mapping) else None
        )
        if explicit_color and not source_styles.get(source_id, {}).get("color"):
          source_styles[source_id] = {
            **source_styles.get(source_id, {}),
            "source_id": source_id,
            "color": str(explicit_color),
          }
        source_style = next(
          (item.get("style") for item in sources if item.get("source_id") == source_id),
          None,
        )
        if isinstance(source_style, Mapping):
          source_styles[source_id] = {
            **source_styles.get(source_id, {}),
            **dict(source_style),
            "source_id": source_id,
          }
        if explicit_color:
          source_styles[source_id] = {
            **source_styles.get(source_id, {}),
            "source_id": source_id,
            "color": str(explicit_color),
          }
      for source_id in source_ids:
        style = source_styles.setdefault(source_id, {"source_id": source_id})
        manual_fields = set(style.get("manual_fields", ()))
        if not style.get("color"):
          style["color"] = "#4c78a8"
        if "alpha" not in manual_fields:
          style["alpha"] = 0.75 if source_id == sample_id else 0.65
        if "marker_shape" not in manual_fields:
          style["marker_shape"] = "circle"
        if "marker_size" not in manual_fields:
          style["marker_size"] = 3.0
      presentation["source_styles"] = list(source_styles.values())
      scene = {
        "x_ticks": _normalized_ticks(
          active_bounds[0], view.get("x_transform_id"), transform_by_id
        ),
        "y_ticks": _normalized_ticks(
          active_bounds[1], view.get("y_transform_id"), transform_by_id
        ),
      }
      prepared = prepare_plot_export(
        spec.plot_view_id, cast(PlotType, str(view.get("plot_type", "scatter"))),
        tuple(sources), tuple(OverlaySourceResolution(source_id, "compatible")
                              for source_id in source_ids),
        view_presentation=presentation,
        gate_overlays=_gate_overlays(
          project, x_id, y_id, active_bounds,
          view.get("x_transform_id"), view.get("y_transform_id"),
        ),
        scene=scene,
      )
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
      overlay_sample_ids={
        str(sample.get("id")): tuple(
          str(value) for value in view.get("manual_overlay_sample_ids", ())
        )
        for sample in samples
      },
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


def _normalized_ticks(
  bounds: tuple[float, float],
  transform_id: object,
  transforms: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, object]]:
  """Build renderer-neutral axis ticks in normalized transformed coordinates."""
  low, high = bounds
  if high == low:
    return []
  if transform_id:
    ticks = generate_transform_ticks(
      _transform_spec(transforms, str(transform_id)), low, high, "auto"
    )
    return [
      {
        "position": (tick.coordinate - low) / (high - low),
        "label": tick.label,
        "major": tick.level == "major",
      }
      for tick in ticks
    ]
  return [
    {
      "position": index / 4,
      "label": f"{low + (high - low) * index / 4:g}",
      "major": True,
    }
    for index in range(5)
  ]


def _gate_overlays(
  project: Mapping[str, Any],
  x_parameter: str,
  y_parameter: str,
  bounds: tuple[tuple[float, float], tuple[float, float]],
  x_transform_id: str | None,
  y_transform_id: str | None,
) -> tuple[dict[str, Any], ...]:
  """Convert persisted gate geometry to the renderer's normalized scene."""
  x_low, x_high = bounds[0]
  y_low, y_high = bounds[1]
  strategies = project.get("gating_strategies_data", {})
  if not isinstance(strategies, Mapping):
    return ()
  result: list[dict[str, Any]] = []
  for strategy in strategies.values():
    if not isinstance(strategy, Mapping):
      continue
    for gate in strategy.get("gates", ()):
      if not isinstance(gate, Mapping):
        continue
      if gate.get("x_parameter") not in {None, x_parameter}:
        continue
      if gate.get("y_parameter") not in {None, y_parameter}:
        continue
      if gate.get("x_transform_id") != x_transform_id:
        continue
      if gate.get("y_transform_id") != y_transform_id:
        continue
      points = gate.get("coordinates", ())
      if not points and gate.get("gate_type") == "rectangle":
        thresholds = gate.get("thresholds", {})
        if isinstance(thresholds, Mapping):
          x_min = thresholds.get("x_min", thresholds.get("min"))
          x_max = thresholds.get("x_max", thresholds.get("max"))
          y_min = thresholds.get("y_min", thresholds.get("min"))
          y_max = thresholds.get("y_max", thresholds.get("max"))
          if all(isinstance(value, (int, float)) for value in (x_min, x_max, y_min, y_max)):
            points = ((x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max))
      normalized: list[tuple[float, float]] = []
      for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
          continue
        x_value, y_value = point[0], point[1]
        if not isinstance(x_value, (int, float)) or not isinstance(y_value, (int, float)):
          continue
        normalized.append((_unit_range(float(x_value), x_low, x_high),
                           _unit_range(float(y_value), y_low, y_high)))
      if len(normalized) >= 2:
        result.append({
          "id": str(gate.get("id", "gate")),
          "points": tuple(normalized),
          "color": str(gate.get("color", "#ffffff")),
        })
  return tuple(result)


def _unit_range(value: float, low: float, high: float) -> float:
  if high == low:
    return 0.5
  return min(1.0, max(0.0, (value - low) / (high - low)))


def _transform_spec(
  transform_by_id: Mapping[str, Mapping[str, Any]], transform_id: str,
) -> TransformSpec:
  """Build the typed transform used once for canonical display coordinates."""
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
