"""CLI adapter for persisted, per-sample batch plot export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  run_batch_plot_export,
)
from flowdesk_core.density_colors import estimate_density_colors
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
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
from flowdesk_core.vector_scatter import preflight_vector_scatter_export
from flowdesk_storage.project import load_project, resolve_sample_paths


def batch_plot_command(
  project_path: str,
  export_id: str,
  output_dir: str,
  *,
  renderer_backend: str = "headless",
  execution_control: ExecutionControl | None = None,
  execution_options: ExecutionOptions | None = None,
) -> int:
  try:
    if execution_control is None and execution_options is not None:
      execution_control = ExecutionControl(options=execution_options)
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
    sample_by_id = {str(sample.get("id")): sample for sample in samples}
    group_members: dict[str, tuple[str, ...]] = {}
    for group in project.get("sample_groups", ()):
      if not isinstance(group, Mapping) or not group.get("id"):
        continue
      members = tuple(str(value) for value in group.get("sample_ids", ()))
      rule = group.get("membership_rule")
      if isinstance(rule, Mapping) and set(rule) == {"all"}:
        members = tuple(sample_by_id)
      group_members[str(group["id"])] = members
    if spec.target == "all":
      target_sample_ids = tuple(sample_by_id)
    elif spec.target == "explicit":
      target_sample_ids = tuple(spec.sample_ids)
    else:
      target_sample_ids = group_members.get(spec.group_id or "", ())
    advanced_overlay_ids = tuple(
      str(source.get("sample_id"))
      for source in sorted(
        view.get("overlay_sources", ()),
        key=lambda item: (int(item.get("order", 0)), str(item.get("source_id", ""))),
      )
      if source.get("visible", True) and source.get("sample_id")
    )
    overlay_ids_by_sample = {
      sample_id: tuple(dict.fromkeys((
        *advanced_overlay_ids,
        *(str(value) for value in view.get("manual_overlay_sample_ids", ())),
      )))
      for sample_id in sample_by_id
    }
    required_source_ids = {
      sample_id
      for sample_id in target_sample_ids
      if sample_id in sample_by_id
    }
    for sample_id in target_sample_ids:
      required_source_ids.update(overlay_ids_by_sample.get(sample_id, ()))
    required_source_ids = {
      sample_id for sample_id in required_source_ids if sample_id in sample_by_id
    }
    prepared_layers: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    layer_metadata: dict[str, dict[str, Any]] = {}
    layer_event_colors: dict[str, np.ndarray] = {}
    shared_bounds: tuple[float, float, float, float] | None = None
    preflight_holder: dict[str, Any] = {}
    display_scene = dict(view.get("display_scene", {}))

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
      raw_x_values = np.asarray(x_values, dtype=np.float64).copy()
      raw_y_values = np.asarray(y_values, dtype=np.float64).copy()
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
      event_colors = _population_event_colors(
        project, str(sample["id"]), processed.preview_report,
        processed.display_mask, default_color="#000000",
      )
      if event_colors is not None:
        event_colors = event_colors[finite]
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
        "raw_x": raw_x_values[finite], "raw_y": raw_y_values[finite],
        "event_colors": event_colors,
      }

    def prepare_sources() -> None:
      nonlocal shared_bounds
      for candidate in samples:
        candidate_id = str(candidate["id"])
        if candidate_id not in required_source_ids:
          continue
        x_values, y_values, metadata = extract_layer(candidate)
        prepared_layers[candidate_id] = (x_values, y_values)
        layer_metadata[candidate_id] = metadata
        if metadata.get("event_colors") is not None:
          layer_event_colors[candidate_id] = metadata["event_colors"]
      if spec.layout_policy == "shared_ranges":
        all_x = np.concatenate([value[0] for value in prepared_layers.values()])
        all_y = np.concatenate([value[1] for value in prepared_layers.values()])
        shared_bounds = (
          float(np.min(all_x)), float(np.max(all_x)),
          float(np.min(all_y)), float(np.max(all_y)),
        )
      max_rendered_event_count = max(
        (
          sum(
            len(prepared_layers[source_id][0])
            for source_id in (
              sample_id,
              *overlay_ids_by_sample.get(sample_id, ()),
            )
            if source_id in prepared_layers
          )
          for sample_id in target_sample_ids
        ),
        default=0,
      )
      preflight = preflight_vector_scatter_export(
        spec,
        rendered_event_count=max_rendered_event_count,
        logical_plot_width=max(1.0, spec.width - 80.0),
        logical_plot_height=max(1.0, spec.height - 110.0),
      )
      preflight_holder["value"] = preflight.to_mapping()
      if preflight.status == "failed":
        raise ValueError(json.dumps(preflight.to_mapping(), ensure_ascii=False))

    def estimate_render_bytes() -> int:
      """Estimate one concurrently prepared render item's working memory."""
      if not prepared_layers:
        return 0
      return max(
        int(x_values.nbytes + y_values.nbytes) * 4
        for x_values, y_values in prepared_layers.values()
      )

    def render(
      sample: Mapping[str, Any], path: Path, _spec: BatchPlotExportSpec
    ) -> None:
      sample_id = str(sample["id"])
      x_values, y_values = prepared_layers[sample_id]
      metadata = layer_metadata[sample_id]
      x_id, y_id = metadata["x_id"], metadata["y_id"]
      persisted_bounds = _scene_view_range(display_scene)
      active_bounds = (
        (shared_bounds[:2], shared_bounds[2:])
        if shared_bounds is not None
        else (
          persisted_bounds
          if spec.layout_policy == "current_view" and persisted_bounds is not None
          else (
            (float(np.min(x_values)), float(np.max(x_values))),
            (float(np.min(y_values)), float(np.max(y_values))),
          )
        )
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
      visible_masks: dict[str, np.ndarray] = {}
      visible_event_colors: dict[str, tuple[str, ...]] = {}
      for order, source_id in enumerate(source_ids):
        source_sample = source_by_id[source_id]
        source_metadata = layer_metadata[source_id]
        source_x, source_y = prepared_layers[source_id]
        normalized_x = _normalize(source_x, active_bounds[0])
        normalized_y = _normalize(source_y, active_bounds[1])
        visible = (
          (normalized_x >= 0.0) & (normalized_x <= 1.0)
          & (normalized_y >= 0.0) & (normalized_y <= 1.0)
        )
        visible_masks[source_id] = visible
        layers[source_id] = (tuple(normalized_x[visible]), tuple(normalized_y[visible]))
        colors = layer_event_colors.get(source_id)
        if colors is not None:
          visible_event_colors[source_id] = tuple(str(color) for color in colors[visible])
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
      density_coloring = presentation.get("colormap") == "density" and len(source_ids) == 1
      if density_coloring:
        active_id = source_ids[0]
        full_x, full_y = prepared_layers[active_id]
        density_bounds = (
          float(np.min(full_x)), float(np.max(full_x)),
          float(np.min(full_y)), float(np.max(full_y)),
        )
        visible = visible_masks[active_id]
        density_result = estimate_density_colors(
          full_x, full_y, full_x[visible], full_y[visible],
          bounds=density_bounds, logical_size=(512, 512),
        )
        visible_event_colors = {
          active_id: tuple(density_result.colors)
        }
      elif len(source_ids) > 1:
        # Overlay comparisons use one color per source.  Population/gate display
        # colors must not leak into the active layer while overlays are present.
        visible_event_colors = {}
      presentation["x_axis_display_label"] = str(
        display_scene.get("x_axis_label") or metadata["x_label"]
      )
      presentation["y_axis_display_label"] = str(
        display_scene.get("y_axis_label") or metadata["y_label"]
      )
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
          style["alpha"] = 0.60
        if "marker_shape" not in manual_fields:
          style["marker_shape"] = "circle"
        if "marker_size" not in manual_fields:
          style["marker_size"] = 1.5
      presentation["source_styles"] = list(source_styles.values())
      scene = {
        "x_ticks": _normalized_ticks(
          active_bounds[0], view.get("x_transform_id"), transform_by_id,
          str(display_scene.get("x_tick_policy", "auto")),
        ),
        "y_ticks": _normalized_ticks(
          active_bounds[1], view.get("y_transform_id"), transform_by_id,
          str(display_scene.get("y_tick_policy", "auto")),
        ),
        "title_colors": [
          str(
            manual_colors.get(source_id)
            if isinstance(manual_colors, Mapping) and manual_colors.get(source_id)
            else (
              source_styles.get(source_id, {}).get("color")
              if "color" in set(source_styles.get(source_id, {}).get("manual_fields", ()))
              else "#4c78a8"
            )
          )
          for source_id in source_ids
        ],
      }
      prepared = prepare_plot_export(
        spec.plot_view_id, cast(PlotType, str(view.get("plot_type", "scatter"))),
        tuple(sources), tuple(OverlaySourceResolution(source_id, "compatible")
                              for source_id in source_ids),
        view_presentation=presentation,
        gate_overlays=_gate_overlays(
          project, x_id, y_id, active_bounds,
          view.get("x_transform_id"), view.get("y_transform_id"),
          default_color=str(presentation.get("gate_outline_color") or "#e00000"),
        ),
        scene=scene,
      )
      prepared.metadata["vector_scatter_preflight"] = dict(preflight_holder.get("value", {}))
      if density_coloring:
        prepared.metadata["density_coloring"] = {
          "active": True,
          "algorithm_version": density_result.metadata.algorithm_version,
          "grid_shape": density_result.metadata.grid_shape,
          "sigma_cells": density_result.metadata.sigma_cells,
          "normalization_log_density": density_result.metadata.normalization_log_density,
          "valid_input_count": density_result.metadata.valid_input_count,
        }
      elif presentation.get("colormap") == "density":
        prepared.metadata["density_coloring"] = {"active": False, "reason": "overlay"}
      # Batch formats must share the renderer-neutral scene adapter. The live
      # Qt widget remains the interactive preview, while one core renderer
      # keeps PNG/JPEG/SVG/PDF coordinates, ticks, gates, and event order equal.
      if path.suffix.lower() == ".png":
        write_plot_png(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec, event_colors=visible_event_colors)
      elif path.suffix.lower() in {".jpg", ".jpeg"}:
        write_plot_jpg(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec, event_colors=visible_event_colors)
      elif path.suffix.lower() == ".svg":
        write_plot_svg(path, prepared, layers=layers, options=spec,
                       event_colors=visible_event_colors)
      elif path.suffix.lower() == ".pdf":
        write_plot_pdf(path, prepared, layers=layers, width=spec.width, height=spec.height,
                       options=spec, event_colors=visible_event_colors)
      else:
        raise ValueError(f"CLI renderer does not support {path.suffix!r}")

    batch_report = run_batch_plot_export(
      spec, samples, output_dir, render, annotations=annotations,
      preflight=preflight_holder,
      prepare=prepare_sources,
      estimate_render_bytes=estimate_render_bytes,
      execution_control=execution_control,
      group_members=group_members,
      overlay_sample_ids={
        sample_id: overlay_ids_by_sample[sample_id]
        for sample_id in sample_by_id
      },
    )
    print(f"Batch plot export {batch_report.status}: {len(batch_report.items)} samples")
    if batch_report.execution_provenance:
      print(
        "Execution: "
        f"backend={batch_report.execution_provenance['backend']} "
        f"workers={batch_report.execution_provenance['effective_max_workers']}/"
        f"{batch_report.execution_provenance['requested_max_workers']}"
      )
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


def _population_event_colors(
  project: Mapping[str, Any],
  sample_id: str,
  report: Any,
  display_mask: np.ndarray,
  *,
  default_color: str,
) -> np.ndarray | None:
  """Resolve persisted population colors for the displayed event subset.

  This mirrors the GUI's display-only population coloring. Membership arrays
  come from the canonical preview report; no gate is re-evaluated here.
  """
  settings = project.get("plot_display_settings", {})
  raw_colors = settings.get("population_display_colors", {})
  if not isinstance(raw_colors, Mapping):
    return None
  colored = {
    str(population_id): str(value.get("color"))
    for population_id, value in raw_colors.items()
    if isinstance(value, Mapping) and isinstance(value.get("color"), str)
    and value.get("color")
  }
  if not colored:
    return None
  memberships = getattr(report, "population_membership", ())
  event_count = len(display_mask)
  colors = np.full(event_count, default_color, dtype="<U7")
  for population_id in colored:
    membership = next(
      (
        value.mask for value in memberships
        if value.sample_id == sample_id
        and value.population_id == population_id
        and len(value.mask) == event_count
      ),
      None,
    )
    if membership is not None:
      colors[np.asarray(membership, dtype=bool)] = colored[population_id]
  return colors[np.asarray(display_mask, dtype=bool)]


def _normalized_ticks(
  bounds: tuple[float, float],
  transform_id: object,
  transforms: Mapping[str, Mapping[str, Any]],
  policy: str = "auto",
) -> list[dict[str, object]]:
  """Build renderer-neutral axis ticks in normalized transformed coordinates."""
  low, high = bounds
  if high == low:
    return []
  if transform_id:
    tick_policy = policy if policy in {"auto", "decades", "one_two_five"} else "auto"
    ticks = generate_transform_ticks(
      _transform_spec(transforms, str(transform_id)), low, high,
      cast(Literal["auto", "decades", "one_two_five"], tick_policy),
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


def _scene_view_range(
  scene: Mapping[str, Any],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
  """Read the GUI's persisted transformed ViewBox range without a fallback."""
  raw = scene.get("view_range")
  if not isinstance(raw, (list, tuple)) or len(raw) != 2:
    return None
  try:
    x_range = tuple(float(value) for value in raw[0])
    y_range = tuple(float(value) for value in raw[1])
  except (TypeError, ValueError):
    return None
  if len(x_range) != 2 or len(y_range) != 2:
    return None
  if not all(np.isfinite((*x_range, *y_range))):
    return None
  if x_range[0] >= x_range[1] or y_range[0] >= y_range[1]:
    return None
  return (x_range[0], x_range[1]), (y_range[0], y_range[1])


def _gate_overlays(
  project: Mapping[str, Any],
  x_parameter: str,
  y_parameter: str,
  bounds: tuple[tuple[float, float], tuple[float, float]],
  x_transform_id: str | None,
  y_transform_id: str | None,
  *,
  default_color: str,
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
      clipped = _clip_polygon_to_unit_square(tuple(normalized))
      if len(clipped) >= 2:
        result.append({
          "id": str(gate.get("id", "gate")),
          "points": clipped,
          "color": str(gate.get("color") or default_color),
        })
  return tuple(result)


def _unit_range(value: float, low: float, high: float) -> float:
  """Normalize a gate coordinate without independently clipping its vertex."""
  if high == low:
    return 0.5
  return (value - low) / (high - low)


def _clip_polygon_to_unit_square(
  points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
  """Clip a normalized gate polygon while preserving boundary intersections.

  Clamping vertices one-by-one changes a polygon when it crosses a plot edge.
  The live pyqtgraph ViewBox clips the complete path, so the headless renderer
  must retain the same line/edge intersections.
  """
  clipped = list(points)
  for axis, boundary, keep_greater in (
    (0, 0.0, True), (0, 1.0, False), (1, 0.0, True), (1, 1.0, False),
  ):
    if not clipped:
      break
    output: list[tuple[float, float]] = []
    previous = clipped[-1]
    previous_inside = previous[axis] >= boundary if keep_greater else previous[axis] <= boundary
    for current in clipped:
      current_inside = current[axis] >= boundary if keep_greater else current[axis] <= boundary
      if current_inside != previous_inside:
        output.append(_polygon_boundary_intersection(previous, current, axis, boundary))
      if current_inside:
        output.append(current)
      previous = current
      previous_inside = current_inside
    clipped = output
  return tuple(clipped)


def _polygon_boundary_intersection(
  start: tuple[float, float],
  end: tuple[float, float],
  axis: int,
  boundary: float,
) -> tuple[float, float]:
  """Return the intersection of one polygon edge with a square boundary."""
  delta = end[axis] - start[axis]
  if abs(delta) < 1e-12:
    return (boundary, start[1]) if axis == 0 else (start[0], boundary)
  fraction = (boundary - start[axis]) / delta
  x_value = start[0] + fraction * (end[0] - start[0])
  y_value = start[1] + fraction * (end[1] - start[1])
  return (boundary, y_value) if axis == 0 else (x_value, boundary)


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
