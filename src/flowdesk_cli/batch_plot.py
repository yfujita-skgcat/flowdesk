"""CLI adapter for persisted, per-sample batch plot export."""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import (
  FIRST_COMPLETED,
  CancelledError,
  ThreadPoolExecutor,
  wait,
)
from pathlib import Path
from threading import Event, Lock, local
from typing import Any, Literal, cast

import numpy as np

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  run_batch_plot_export,
)
from flowdesk_core.density_colors import DensityColorConfig, estimate_density_colors
from flowdesk_core.execution_control import (
  ExecutionCancelled,
  ExecutionControl,
  ExecutionOptions,
  ProgressEvent,
  resolve_execution_workers,
)
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.models import BatchPlotExportSpec, PlotType, PlotViewSpec, TransformSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.plot_export import (
  LayerValues,
  PreparedPlotExport,
  VectorRenderCache,
  prepare_plot_export,
  prepare_vector_render_cache,
  write_plot_jpg,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.processed_display import ProcessedDisplayRequest
from flowdesk_core.transforms import apply_transform, generate_transform_ticks
from flowdesk_core.vector_scatter import preflight_vector_scatter_export
from flowdesk_storage.manifest import ManifestValidationError
from flowdesk_storage.project import load_project, resolve_sample_paths
from flowdesk_storage.serialization import atomic_write_json

NormalizedPayload = tuple[LayerValues, np.ndarray, np.ndarray | None]


class _RawSampleCache:
  """Bounded queue-scoped cache for immutable raw FCS sample objects."""

  def __init__(self, max_bytes: int) -> None:
    self._max_bytes = max(0, int(max_bytes))
    self._items: OrderedDict[
      tuple[str, str, str], tuple[Any, Any, int]
    ] = OrderedDict()
    self._bytes = 0
    self.hits = 0
    self.misses = 0
    self.evictions = 0
    self._lock = Lock()

  @staticmethod
  def _size(sample_data: Any) -> int:
    events = getattr(sample_data, "events", None)
    return max(0, int(getattr(events, "nbytes", 0)))

  def get(self, key: tuple[str, str, str]) -> tuple[Any, Any] | None:
    with self._lock:
      value = self._items.get(key)
      if value is None:
        self.misses += 1
        return None
      self._items.move_to_end(key)
      self.hits += 1
      return value[:2]

  def put(self, key: tuple[str, str, str], info: Any, sample_data: Any) -> None:
    size = self._size(sample_data)
    if size > self._max_bytes:
      return
    with self._lock:
      previous = self._items.pop(key, None)
      if previous is not None:
        self._bytes -= previous[2]
      self._items[key] = (info, sample_data, size)
      self._bytes += size
      while self._bytes > self._max_bytes and self._items:
        _, (_, _, evicted_size) = self._items.popitem(last=False)
        self._bytes -= evicted_size
        self.evictions += 1

  def stats(self) -> dict[str, int]:
    with self._lock:
      return {
        "max_bytes": self._max_bytes,
        "retained_bytes": self._bytes,
        "retained_samples": len(self._items),
        "hits": self.hits,
        "misses": self.misses,
        "evictions": self.evictions,
      }


def _raw_sample_cache_key(sample: Mapping[str, Any]) -> tuple[str, str, str]:
  """Include the persisted fingerprint so a changed file is never reused."""
  fingerprint = json.dumps(
    sample.get("fingerprint", ""), sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, default=str,
  )
  return str(sample.get("id", "")), str(sample.get("path", "")), fingerprint


def batch_plot_definition_ids(project_path: str) -> tuple[str, ...]:
  """Return saved batch-plot definition IDs in project declaration order."""
  project = load_project(project_path)
  return tuple(
    str(item["id"])
    for item in project.get("batch_plot_exports", ())
    if isinstance(item, Mapping) and item.get("id")
  )


def batch_plot_command(
  project_path: str,
  export_id: str,
  output_dir: str,
  *,
  renderer_backend: str = "headless",
  execution_control: ExecutionControl | None = None,
  execution_options: ExecutionOptions | None = None,
  density_config: DensityColorConfig | None = None,
  _project_snapshot: Mapping[str, Any] | None = None,
  _definition_snapshot: Mapping[str, Any] | None = None,
  _raw_sample_cache: _RawSampleCache | None = None,
) -> int:
  try:
    if execution_control is None and execution_options is not None:
      execution_control = ExecutionControl(options=execution_options)
    project = (
      _project_snapshot
      if _project_snapshot is not None
      else load_project(project_path)
    )
    raw = _definition_snapshot
    if raw is None:
      raw = next(
        item for item in project.get("batch_plot_exports", [])
        if str(item.get("id")) == export_id
      )
    spec = batch_plot_export_spec_from_mapping(raw)
    samples = resolve_sample_paths(project, Path(project_path))
    annotations = project.get("annotations", [])
    runner_local = local()

    def runner_for_current_thread() -> PipelineRunner:
      """Return a runner whose mutable display cache is thread-confined."""
      current = getattr(runner_local, "runner", None)
      if current is None:
        current = PipelineRunner(project)
        runner_local.runner = current
      return current
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
    overlay_ids_by_sample = _build_overlay_dependency_graph(
      tuple(sample_by_id),
      view.get("overlay_sources", ()),
      view.get("manual_overlay_sample_ids", ()),
    )
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
    prepared_layer_bounds: dict[
      str, tuple[tuple[float, float], tuple[float, float]]
    ] = {}
    layer_metadata: dict[str, dict[str, Any]] = {}
    layer_event_colors: dict[str, np.ndarray] = {}
    shared_bounds: tuple[float, float, float, float] | None = None
    preflight_holder: dict[str, Any] = {}
    preparation_provenance_holder: dict[str, Any] = {}
    display_scene = dict(view.get("display_scene", {}))
    population_display_colors = project.get("plot_display_settings", {}).get(
      "population_display_colors", {}
    )
    population_colors_configured = isinstance(population_display_colors, Mapping) and any(
      isinstance(value, Mapping) and isinstance(value.get("color"), str)
      and bool(value.get("color"))
      for value in population_display_colors.values()
    )
    prepared_render_cache: dict[
      str,
      tuple[
        Any,
        dict[str, Any],
        dict[str, Any],
        dict[str, VectorRenderCache],
      ],
    ] = {}
    rendered_format_counts: dict[str, int] = {}
    presentation_template = dict(view.get("presentation", {}))
    persisted_source_styles: dict[str, dict[str, Any]] = {
      str(style.get("source_id")): dict(style)
      for style in presentation_template.get("source_styles", ())
      if isinstance(style, Mapping) and style.get("source_id")
    }
    overlay_style_by_id: dict[str, dict[str, Any]] = {}
    for overlay_source in view.get("overlay_sources", ()):
      if not isinstance(overlay_source, Mapping):
        continue
      source_id = overlay_source.get("sample_id")
      style = overlay_source.get("style")
      if source_id and isinstance(style, Mapping):
        overlay_style_by_id.setdefault(str(source_id), dict(style))
    manual_overlay_colors = (
      dict(view.get("manual_overlay_colors", {}))
      if isinstance(view.get("manual_overlay_colors", {}), Mapping)
      else {}
    )
    normalized_layer_cache: OrderedDict[
      tuple[str, tuple[tuple[float, float], tuple[float, float]]],
      NormalizedPayload,
    ] = OrderedDict()
    normalized_cache_max_entries = max(
      1, min(256, max(1, len(required_source_ids)) * 4)
    )
    normalized_cache_max_bytes = 128 * 1024 * 1024
    normalized_cache_bytes = 0
    normalized_cache_sizes: dict[
      tuple[str, tuple[tuple[float, float], tuple[float, float]]], int
    ] = {}
    normalized_cache_inflight: dict[
      tuple[str, tuple[tuple[float, float], tuple[float, float]]], Event
    ] = {}
    gate_overlay_cache: OrderedDict[
      tuple[object, ...], tuple[dict[str, Any], ...]
    ] = OrderedDict()
    gate_overlay_inflight: dict[tuple[object, ...], Event] = {}
    tick_cache: OrderedDict[
      tuple[object, ...], tuple[dict[str, object], ...]
    ] = OrderedDict()
    tick_inflight: dict[tuple[object, ...], Event] = {}
    presentation_cache_max_entries = 256
    render_cache_lock = Lock()

    def extract_layer(sample: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
      cache_key = _raw_sample_cache_key(sample)
      cached_raw = None if _raw_sample_cache is None else _raw_sample_cache.get(cache_key)
      if cached_raw is None:
        _info, sample_data = read_fcs_sample(sample["path"], str(sample["id"]))
        if _raw_sample_cache is not None:
          # The cache is queue-scoped and only retains the immutable raw sample
          # object. All transformed layers, masks, colours, and renderer caches
          # remain definition-scoped below this boundary.
          _raw_sample_cache.put(cache_key, _info, sample_data)
      else:
        _info, sample_data = cached_raw
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
      processed = runner_for_current_thread().prepare_display_layer(ProcessedDisplayRequest(
        revision=0,
        sample=sample_data,
        population_id=view_spec.population_id,
        x_parameter_id=x_id,
        y_parameter_id=y_id,
        x_transform_id=view.get("x_transform_id"),
        y_transform_id=view.get("y_transform_id"),
        display_max_points=int(view_spec.rendering_downsample.get("max_points", 20_000)),
      ), require_preview=population_colors_configured)
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
        "event_colors": event_colors,
      }

    def prepare_sources(
      report_progress: Callable[[str, int, int], None] | None = None,
    ) -> None:
      nonlocal shared_bounds
      candidates = tuple(
        candidate for candidate in samples
        if str(candidate["id"]) in required_source_ids
      )

      def prepare_one(candidate: Mapping[str, Any]) -> tuple[
        str, np.ndarray, np.ndarray, dict[str, Any]
      ]:
        candidate_id = str(candidate["id"])
        if execution_control is not None:
          execution_control.cancellation_token.raise_if_cancelled()
        x_values, y_values, metadata = extract_layer(candidate)
        if execution_control is not None:
          execution_control.cancellation_token.raise_if_cancelled()
        return candidate_id, x_values, y_values, metadata

      def estimate_source_bytes(candidate: Mapping[str, Any]) -> int:
        """Bound source-preparation workers using a conservative file estimate."""
        try:
          file_bytes = os.path.getsize(str(candidate["path"]))
        except (KeyError, OSError, TypeError, ValueError):
          file_bytes = 0
        # FCS decoding, transformed display arrays, and processed masks can
        # coexist during preparation.  This factor is deliberately conservative
        # and is only used for an explicit runtime memory budget.
        return max(1, file_bytes * 6)

      options = (
        execution_control.options
        if execution_control is not None else ExecutionOptions()
      )
      preparation_resolution = resolve_execution_workers(
        options,
        selected_sample_count=len(candidates),
        estimated_sample_bytes=max(
          (estimate_source_bytes(candidate) for candidate in candidates),
          default=0,
        ),
      )
      preparation_provenance_holder.update({
        "backend": preparation_resolution.backend,
        "requested_max_workers": preparation_resolution.requested_max_workers,
        "effective_max_workers": preparation_resolution.effective_max_workers,
        "selected_source_count": preparation_resolution.selected_sample_count,
        "estimated_source_bytes": preparation_resolution.estimated_sample_bytes,
        "limiting_factors": list(preparation_resolution.limiting_factors),
      })
      prepared_results: list[tuple[str, np.ndarray, np.ndarray, dict[str, Any]]] = []
      submitted_preparations = 0
      peak_preparation_in_flight = 0
      if (
        preparation_resolution.backend == "thread"
        and preparation_resolution.effective_max_workers > 1
      ):
        executor = ThreadPoolExecutor(
          max_workers=preparation_resolution.effective_max_workers,
          thread_name_prefix="flowdesk-batch-prepare",
        )
        pending: dict[Any, int] = {}
        completed: dict[int, tuple[str, np.ndarray, np.ndarray, dict[str, Any]]] = {}
        next_candidate = 0
        try:
          while pending or next_candidate < len(candidates):
            while (
              next_candidate < len(candidates)
              and len(pending) < preparation_resolution.effective_max_workers
            ):
              if execution_control is not None:
                execution_control.cancellation_token.raise_if_cancelled()
              pending[executor.submit(
                prepare_one, candidates[next_candidate]
              )] = next_candidate
              next_candidate += 1
              submitted_preparations += 1
              peak_preparation_in_flight = max(
                peak_preparation_in_flight, len(pending)
              )
            if not pending:
              break
            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda value: pending[value]):
              candidate_index = pending.pop(future)
              completed[candidate_index] = future.result()
              if report_progress is not None:
                report_progress(
                  completed[candidate_index][0],
                  len(completed),
                  len(candidates),
                )
        except BaseException:
          for future in pending:
            future.cancel()
          raise
        finally:
          executor.shutdown(wait=True, cancel_futures=True)
        prepared_results = [completed[index] for index in range(len(candidates))]
      else:
        prepared_results = []
        for candidate in candidates:
          prepared_results.append(prepare_one(candidate))
          if report_progress is not None:
            report_progress(
              prepared_results[-1][0], len(prepared_results), len(candidates)
            )
        submitted_preparations = len(candidates)
        peak_preparation_in_flight = 1 if candidates else 0
      preparation_provenance_holder.update({
        "submitted_sources": submitted_preparations,
        "peak_in_flight_sources": peak_preparation_in_flight,
      })

      # Merge in project/source order regardless of worker completion order.
      for candidate_id, x_values, y_values, metadata in prepared_results:
        prepared_layers[candidate_id] = (x_values, y_values)
        prepared_layer_bounds[candidate_id] = _layer_bounds(x_values, y_values)
        layer_metadata[candidate_id] = metadata
        if metadata.get("event_colors") is not None:
          layer_event_colors[candidate_id] = metadata["event_colors"]
      if spec.layout_policy == "shared_ranges":
        shared_bounds = _shared_layer_bounds_from_ranges(prepared_layer_bounds)
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
      """Estimate the largest concurrently prepared render item.

      The previous estimate considered only the largest single source array.
      An output item may include several overlay sources, normalized tuple
      copies, per-event colors, and a hybrid scatter image, so underestimating
      it could admit too many workers under an explicit memory budget.
      """
      if not prepared_layers:
        return 0
      return max(
        (
          _estimate_batch_render_bytes(
            spec,
            source_ids=(sample_id, *overlay_ids_by_sample.get(sample_id, ())),
            prepared_layers=prepared_layers,
            event_colors=layer_event_colors,
            density_coloring=(
              presentation_template.get("colormap") == "density"
              and not overlay_ids_by_sample.get(sample_id, ())
            ),
          )
          for sample_id in target_sample_ids
        ),
        default=0,
      )

    def discard_render_cache(sample_id: str) -> None:
      """Release an item cache after a failed or cancelled format."""
      with render_cache_lock:
        prepared_render_cache.pop(sample_id, None)
        rendered_format_counts.pop(sample_id, None)

    def normalized_payload_for(
      source_id: str,
      active_bounds: tuple[tuple[float, float], tuple[float, float]],
    ) -> NormalizedPayload:
      """Return one normalized source payload with per-key single-flight."""
      nonlocal normalized_cache_bytes
      normalized_key = (source_id, active_bounds)
      while True:
        with render_cache_lock:
          cached = normalized_layer_cache.get(normalized_key)
          if cached is not None:
            normalized_layer_cache.move_to_end(normalized_key)
            return cached
          waiter = normalized_cache_inflight.get(normalized_key)
          if waiter is None:
            waiter = Event()
            normalized_cache_inflight[normalized_key] = waiter
            owner = True
          else:
            owner = False
        if not owner:
          waiter.wait()
          continue
        try:
          source_x, source_y = prepared_layers[source_id]
          normalized_x = _normalize(source_x, active_bounds[0])
          normalized_y = _normalize(source_y, active_bounds[1])
          visible = (
            (normalized_x >= 0.0) & (normalized_x <= 1.0)
            & (normalized_y >= 0.0) & (normalized_y <= 1.0)
          )
          visible.setflags(write=False)
          normalized_x_visible = np.asarray(normalized_x[visible], dtype=np.float64)
          normalized_y_visible = np.asarray(normalized_y[visible], dtype=np.float64)
          normalized_x_visible.setflags(write=False)
          normalized_y_visible.setflags(write=False)
          colors = layer_event_colors.get(source_id)
          normalized_colors = None
          if colors is not None:
            normalized_colors = np.asarray(colors[visible])
            normalized_colors.setflags(write=False)
          payload = cast(NormalizedPayload, (
            (normalized_x_visible, normalized_y_visible),
            visible,
            normalized_colors,
          ))
          with render_cache_lock:
            normalized_layer_cache[normalized_key] = payload
            normalized_layer_cache.move_to_end(normalized_key)
            payload_bytes = _estimate_normalized_layer_bytes(payload)
            if payload_bytes > normalized_cache_max_bytes:
              normalized_layer_cache.pop(normalized_key, None)
            else:
              previous_bytes = normalized_cache_sizes.pop(normalized_key, 0)
              normalized_cache_sizes[normalized_key] = payload_bytes
              normalized_cache_bytes += payload_bytes - previous_bytes
              while (
                len(normalized_layer_cache) > normalized_cache_max_entries
                or normalized_cache_bytes > normalized_cache_max_bytes
              ):
                evicted_key, _ = normalized_layer_cache.popitem(last=False)
                normalized_cache_bytes -= normalized_cache_sizes.pop(evicted_key, 0)
          return payload
        finally:
          with render_cache_lock:
            normalized_cache_inflight.pop(normalized_key, None)
            waiter.set()

    def cached_presentation_value(
      cache: OrderedDict,
      inflight: dict[tuple[object, ...], Event],
      key: tuple[object, ...],
      factory: Callable[[], Any],
    ) -> Any:
      """Compute one presentation value once when render workers race."""
      while True:
        with render_cache_lock:
          cached = cache.get(key)
          if cached is not None:
            cache.move_to_end(key)
            return cached
          waiter = inflight.get(key)
          if waiter is None:
            waiter = Event()
            inflight[key] = waiter
            owner = True
          else:
            owner = False
        if not owner:
          waiter.wait()
          continue
        try:
          value = factory()
          with render_cache_lock:
            cache[key] = value
            cache.move_to_end(key)
            while len(cache) > presentation_cache_max_entries:
              cache.popitem(last=False)
          return value
        finally:
          with render_cache_lock:
            inflight.pop(key, None)
            waiter.set()

    def render_one(
      sample: Mapping[str, Any], path: Path, _spec: BatchPlotExportSpec
    ) -> None:
      nonlocal normalized_cache_bytes
      sample_id = str(sample["id"])
      cancel_check = (
        None if execution_control is None
        else execution_control.cancellation_token.raise_if_cancelled
      )
      with render_cache_lock:
        cached_payload = prepared_render_cache.get(sample_id)
      if cached_payload is not None:
        (
          cached_prepared, cached_layers, cached_event_colors, cached_writer_cache,
        ) = cached_payload
        _write_render_payload(
          path, cached_prepared, cached_layers, cached_event_colors, spec,
          vector_cache=cached_writer_cache, cancel_check=cancel_check,
        )
        with render_cache_lock:
          rendered_format_counts[sample_id] = rendered_format_counts.get(sample_id, 0) + 1
          if rendered_format_counts[sample_id] >= len(spec.formats):
            prepared_render_cache.pop(sample_id, None)
            rendered_format_counts.pop(sample_id, None)
        return
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
            prepared_layer_bounds[sample_id]
          )
        )
      )
      overlay_candidates = list(overlay_ids_by_sample.get(sample_id, ()))
      overlay_ids = tuple(
        value for index, value in enumerate(overlay_candidates)
        if value in prepared_layers and value != sample_id
        and value not in overlay_candidates[:index]
      )
      source_ids = (sample_id, *overlay_ids)
      sources = []
      layers: dict[str, LayerValues] = {}
      visible_masks: dict[str, np.ndarray] = {}
      visible_event_colors: dict[str, np.ndarray] = {}
      for order, source_id in enumerate(source_ids):
        source_sample = sample_by_id[source_id]
        source_metadata = layer_metadata[source_id]
        normalized_payload = normalized_payload_for(source_id, active_bounds)
        normalized_points, visible, normalized_colors = normalized_payload
        visible_masks[source_id] = visible
        layers[source_id] = normalized_points
        if normalized_colors is not None:
          visible_event_colors[source_id] = normalized_colors
        sources.append({
          "source_id": source_id, "sample_id": source_id,
          "population_id": str(view.get("population_id", "all_events")),
          "display_name": str(source_sample.get("name", source_id)),
          "x_parameter_id": source_metadata["x_id"],
          "y_parameter_id": source_metadata["y_id"], "visible": True, "order": order,
          "style": dict(overlay_style_by_id.get(source_id, {})),
        })
      presentation = dict(presentation_template)
      density_coloring = presentation.get("colormap") == "density" and len(source_ids) == 1
      if density_coloring:
        active_id = source_ids[0]
        full_x, full_y = prepared_layers[active_id]
        density_x_bounds, density_y_bounds = prepared_layer_bounds[active_id]
        density_bounds = (
          density_x_bounds[0], density_x_bounds[1],
          density_y_bounds[0], density_y_bounds[1],
        )
        visible = visible_masks[active_id]
        density_result = estimate_density_colors(
          full_x, full_y, full_x[visible], full_y[visible],
          bounds=density_bounds, logical_size=(512, 512),
          config=density_config or DensityColorConfig(),
          cancel_check=(
            None if execution_control is None
            else execution_control.cancellation_token.raise_if_cancelled
          ),
        )
        density_colors = np.asarray(density_result.colors)
        density_colors.setflags(write=False)
        visible_event_colors = {active_id: density_colors}
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
        source_id: dict(persisted_source_styles[source_id])
        for source_id in source_ids
        if source_id in persisted_source_styles
      }
      manual_colors = manual_overlay_colors
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
        source_style = overlay_style_by_id.get(source_id)
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
      gate_color = str(presentation.get("gate_outline_color") or "#e00000")
      gate_cache_key = (
        x_id, y_id, active_bounds, view.get("x_transform_id"),
        view.get("y_transform_id"), gate_color,
      )
      gate_overlays = cached_presentation_value(
        gate_overlay_cache, gate_overlay_inflight, gate_cache_key,
        lambda: _gate_overlays(
          project, x_id, y_id, active_bounds,
          view.get("x_transform_id"), view.get("y_transform_id"),
          default_color=gate_color,
        ),
      )
      x_tick_key = (
        "x", active_bounds[0], view.get("x_transform_id"),
        str(display_scene.get("x_tick_policy", "auto")),
      )
      y_tick_key = (
        "y", active_bounds[1], view.get("y_transform_id"),
        str(display_scene.get("y_tick_policy", "auto")),
      )
      x_ticks = cached_presentation_value(
        tick_cache, tick_inflight, x_tick_key,
        lambda: tuple(_normalized_ticks(
          active_bounds[0], view.get("x_transform_id"), transform_by_id,
          str(display_scene.get("x_tick_policy", "auto")),
        )),
      )
      y_ticks = cached_presentation_value(
        tick_cache, tick_inflight, y_tick_key,
        lambda: tuple(_normalized_ticks(
          active_bounds[1], view.get("y_transform_id"), transform_by_id,
          str(display_scene.get("y_tick_policy", "auto")),
        )),
      )
      scene = {
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
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
        gate_overlays=gate_overlays,
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
          "requested_histogram_workers": density_result.metadata.requested_histogram_workers,
          "effective_histogram_workers": density_result.metadata.effective_histogram_workers,
          "histogram_memory_budget_bytes": density_result.metadata.histogram_memory_budget_bytes,
        }
      elif presentation.get("colormap") == "density":
        prepared.metadata["density_coloring"] = {"active": False, "reason": "overlay"}
      writer_cache: dict[str, VectorRenderCache] = {}
      with render_cache_lock:
        prepared_render_cache[sample_id] = (
          prepared, layers, visible_event_colors, writer_cache,
        )
        rendered_format_counts[sample_id] = 1
      # Batch formats must share the renderer-neutral scene adapter. The live
      # Qt widget remains the interactive preview, while one core renderer
      # keeps PNG/JPEG/SVG/PDF coordinates, ticks, gates, and event order equal.
      _write_render_payload(
        path, prepared, layers, visible_event_colors, spec,
        vector_cache=writer_cache, cancel_check=cancel_check,
      )
      if len(spec.formats) <= 1:
        discard_render_cache(sample_id)

    def render(
      sample: Mapping[str, Any], path: Path, _spec: BatchPlotExportSpec
    ) -> None:
      sample_id = str(sample["id"])
      try:
        render_one(sample, path, _spec)
      except BaseException:
        # A failed first format otherwise leaves the prepared scene, normalized
        # tuples, event colors, and hybrid raster alive until the whole batch
        # ends.  Release it immediately; successful format bundles still retain
        # the cache until their final format completes.
        discard_render_cache(sample_id)
        raise

    try:
      batch_report = run_batch_plot_export(
        spec, samples, output_dir, render, annotations=annotations,
        preflight=preflight_holder,
        preparation_provenance=preparation_provenance_holder,
        prepare_with_progress=prepare_sources,
        estimate_render_bytes=estimate_render_bytes,
        execution_control=execution_control,
        group_members=group_members,
        overlay_sample_ids={
          sample_id: overlay_ids_by_sample[sample_id]
          for sample_id in sample_by_id
        },
      )
    finally:
      # Cancellation can stop before the next format callback, so clear any
      # remaining bundle caches after the coordinator has joined all workers.
      with render_cache_lock:
        prepared_render_cache.clear()
        rendered_format_counts.clear()
    print(f"Batch plot export {batch_report.status}: {len(batch_report.items)} samples")
    if batch_report.execution_provenance:
      print(
        "Execution: "
        f"backend={batch_report.execution_provenance['backend']} "
        f"workers={batch_report.execution_provenance['effective_max_workers']}/"
        f"{batch_report.execution_provenance['requested_max_workers']}"
      )
    if batch_report.status in {"cancelled", "partial_cancelled"}:
      return 130
    return 0 if batch_report.status == "success" else 1
  except (BatchPlotExportError, FileNotFoundError, KeyError, ValueError) as exc:
    print(f"Error: batch plot export failed: {exc}")
    return 1


def batch_plot_queue_command(
  project_path: str,
  export_ids: Sequence[str],
  output_dir: str,
  *,
  failure_policy: str = "fail-fast",
  queue_all: bool = False,
  execution_control: ExecutionControl | None = None,
  execution_options: ExecutionOptions | None = None,
  density_config: DensityColorConfig | None = None,
  queue_workers: int = 1,
) -> int:
  """Run several saved plot definitions with one cooperative queue control."""
  if failure_policy not in {"continue", "fail-fast"}:
    raise ValueError("failure_policy must be 'continue' or 'fail-fast'")
  if queue_workers < 1:
    raise ValueError("queue_workers must be positive")
  base_options = (
    execution_options
    if execution_options is not None
    else execution_control.options if execution_control is not None else ExecutionOptions()
  )
  if queue_workers > 1 and base_options.backend == "thread":
    raise ValueError(
      "queue_workers cannot be combined with the per-definition thread backend"
    )
  try:
    project_snapshot = load_project(project_path)
  except (FileNotFoundError, KeyError, ValueError, ManifestValidationError) as exc:
    print(f"Error: batch plot queue project load failed: {exc}")
    return 1
  if queue_all:
    queue = tuple(
      str(item["id"])
      for item in project_snapshot.get("batch_plot_exports", ())
      if isinstance(item, Mapping) and item.get("id")
    )
  else:
    queue = tuple(dict.fromkeys(str(value) for value in export_ids if str(value)))
  if not queue:
    print("Error: project has no saved batch plot definitions")
    return 1
  definition_index = {
    str(item["id"]): item
    for item in project_snapshot.get("batch_plot_exports", ())
    if isinstance(item, Mapping) and item.get("id")
  }
  estimated_queue_definition_bytes = _estimate_queue_definition_bytes(
    project_snapshot, project_path,
  )
  queue_memory_limit = None
  queue_limiting_factors: list[str] = []
  if base_options.memory_budget_bytes is not None and estimated_queue_definition_bytes > 0:
    queue_memory_limit = max(
      1, base_options.memory_budget_bytes // estimated_queue_definition_bytes
    )
    if queue_memory_limit < queue_workers:
      queue_limiting_factors.append("memory_budget")
  effective_queue_workers = min(
    queue_workers, len(queue), queue_memory_limit or queue_workers,
  )
  root = Path(output_dir)
  root.mkdir(parents=True, exist_ok=True)
  queue_manifest_path = root / "batch-queue-manifest.json"
  queue_items = [
    {
      "index": index,
      "export_id": export_id,
      "output_directory": str(root / f"{index:03d}_{_queue_slug(export_id)}"),
      "status": "not_started",
      "result_code": None,
    }
    for index, export_id in enumerate(queue, start=1)
  ]
  queue_manifest = {
    "schema_version": 1,
    "status": "running",
    "failure_policy": failure_policy,
    "queue_execution": {
      "backend": "sequential" if queue_workers == 1 else "thread",
      "requested_workers": queue_workers,
      "effective_workers": effective_queue_workers,
      "planned_definitions": len(queue),
      "submitted_definitions": 0,
      "completed_definitions": 0,
      "peak_in_flight_definitions": 0,
      "memory_budget_bytes": base_options.memory_budget_bytes,
      "estimated_definition_bytes": estimated_queue_definition_bytes,
      "limiting_factors": queue_limiting_factors,
      "nested_definition_backend": (
        "sequential" if queue_workers > 1 else (
          base_options.backend
        )
      ),
    },
    "definitions": queue_items,
  }
  _write_queue_manifest(queue_manifest_path, queue_manifest)
  # Raw FCS arrays are immutable inputs and can safely be shared between
  # sequential definitions. Definition-scoped transformed/display layers are
  # still rebuilt because their views, gates, and presentation may differ.
  requested_cache_budget = base_options.memory_budget_bytes
  raw_cache_budget = 256 * 1024 * 1024
  if requested_cache_budget is not None:
    raw_cache_budget = min(raw_cache_budget, max(0, requested_cache_budget // 2))
  raw_sample_cache = _RawSampleCache(raw_cache_budget)
  queue_manifest["raw_sample_cache"] = raw_sample_cache.stats()
  _write_queue_manifest(queue_manifest_path, queue_manifest)
  results_by_index: dict[int, int] = {}

  def run_definition(index: int, export_id: str) -> tuple[int, int]:
    definition_dir = root / f"{index:03d}_{_queue_slug(export_id)}"
    child_control = execution_control
    child_options = execution_options
    cache = raw_sample_cache
    if queue_workers > 1:
      # Definition-level workers must not recursively create sample-level
      # workers. Each child retains the shared cancellation token but has no
      # progress sink; the queue coordinator owns ordered progress events.
      child_options = ExecutionOptions(
        backend="sequential", max_workers=1,
        memory_budget_bytes=base_options.memory_budget_bytes,
      )
      child_control = (
        None if execution_control is None else ExecutionControl(
          options=child_options,
          cancellation_token=execution_control.cancellation_token,
        )
      )
      cache = None
    try:
      result = batch_plot_command(
        project_path, export_id, str(definition_dir),
        execution_control=child_control,
        execution_options=child_options,
        density_config=density_config,
        _project_snapshot=project_snapshot,
        _definition_snapshot=definition_index.get(export_id),
        _raw_sample_cache=cache,
      )
    except ExecutionCancelled:
      result = 130
    except Exception as exc:
      print(f"Error: batch plot definition {export_id!r} raised: {exc}")
      result = 1
    return index, result

  def record_definition(index: int, result: int, completed: int) -> None:
    export_id = queue[index - 1]
    queue_item = queue_items[index - 1]
    results_by_index[index] = result
    queue_item["status"] = (
      "success" if result == 0 else "cancelled" if result == 130 else "failed"
    )
    queue_item["result_code"] = result
    if queue_workers == 1:
      queue_item["raw_sample_cache"] = raw_sample_cache.stats()
      queue_manifest["raw_sample_cache"] = raw_sample_cache.stats()
    if execution_control is not None:
      execution_control.emit_progress(ProgressEvent(
        operation_id="batch_plot_queue",
        operation="batch_plot_queue",
        phase="definition_completed",
        completed_units=completed,
        total_units=len(queue),
        sample_id=export_id,
        message=f"definition {index}/{len(queue)} completed with status {result}",
      ))

  if queue_workers == 1:
    for index, export_id in enumerate(queue, start=1):
      queue_item = queue_items[index - 1]
      if execution_control is not None:
        try:
          execution_control.cancellation_token.raise_if_cancelled()
        except ExecutionCancelled:
          queue_item["status"] = "cancelled"
          queue_manifest["status"] = "cancelled"
          _write_queue_manifest(queue_manifest_path, queue_manifest)
          return 130
      queue_item["status"] = "running"
      _write_queue_manifest(queue_manifest_path, queue_manifest)
      if execution_control is not None:
        execution_control.emit_progress(ProgressEvent(
          operation_id="batch_plot_queue",
          operation="batch_plot_queue",
          phase="definition_started",
          completed_units=index - 1,
          total_units=len(queue),
          sample_id=export_id,
          message=f"definition {index}/{len(queue)}: {export_id}",
        ))
      queue_manifest["queue_execution"]["submitted_definitions"] += 1
      queue_manifest["queue_execution"]["peak_in_flight_definitions"] = 1
      _, result = run_definition(index, export_id)
      record_definition(index, result, index)
      queue_manifest["queue_execution"]["completed_definitions"] += 1
      _write_queue_manifest(queue_manifest_path, queue_manifest)
      if result == 130:
        queue_manifest["status"] = "cancelled"
        _write_queue_manifest(queue_manifest_path, queue_manifest)
        return 130
      if result != 0 and failure_policy == "fail-fast":
        queue_manifest["status"] = "failed"
        _write_queue_manifest(queue_manifest_path, queue_manifest)
        return result
  else:
    queue_manifest["raw_sample_cache"] = {
      "enabled": False, "reason": "definition_parallelism",
    }
    _write_queue_manifest(queue_manifest_path, queue_manifest)
    effective_workers = effective_queue_workers
    executor = ThreadPoolExecutor(
      max_workers=effective_workers, thread_name_prefix="flowdesk-batch-queue",
    )
    pending: dict[Any, int] = {}
    next_index = 1
    completed = 0
    stop_submitting = False
    try:
      while pending or next_index <= len(queue):
        while (
          not stop_submitting
          and len(pending) < effective_workers
          and next_index <= len(queue)
        ):
          if execution_control is not None:
            execution_control.cancellation_token.raise_if_cancelled()
          queue_items[next_index - 1]["status"] = "running"
          export_id = queue[next_index - 1]
          if execution_control is not None:
            execution_control.emit_progress(ProgressEvent(
              operation_id="batch_plot_queue",
              operation="batch_plot_queue",
              phase="definition_started",
              completed_units=completed,
              total_units=len(queue), sample_id=export_id,
              message=f"definition {next_index}/{len(queue)}: {export_id}",
            ))
          pending[executor.submit(run_definition, next_index, export_id)] = next_index
          queue_manifest["queue_execution"]["submitted_definitions"] += 1
          queue_manifest["queue_execution"]["peak_in_flight_definitions"] = max(
            queue_manifest["queue_execution"]["peak_in_flight_definitions"],
            len(pending),
          )
          next_index += 1
        if not pending:
          break
        done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
        for future in sorted(done, key=lambda value: pending[value]):
          index = pending.pop(future)
          try:
            _, result = future.result()
          except CancelledError:
            queue_items[index - 1]["status"] = "not_started"
            queue_items[index - 1]["result_code"] = None
            _write_queue_manifest(queue_manifest_path, queue_manifest)
            continue
          except Exception as exc:
            print(f"Error: batch plot definition {queue[index - 1]!r} raised: {exc}")
            result = 1
          completed += 1
          record_definition(index, result, completed)
          queue_manifest["queue_execution"]["completed_definitions"] = completed
          if result == 130 or (result != 0 and failure_policy == "fail-fast"):
            stop_submitting = True
            if result == 130:
              queue_manifest["status"] = "cancelled"
            elif failure_policy == "fail-fast":
              queue_manifest["status"] = "failed"
          _write_queue_manifest(queue_manifest_path, queue_manifest)
        if stop_submitting:
          for future in pending:
            future.cancel()
    except ExecutionCancelled:
      queue_manifest["status"] = "cancelled"
      for future in pending:
        future.cancel()
    finally:
      executor.shutdown(wait=True, cancel_futures=True)
    if queue_manifest["status"] == "cancelled":
      for item in queue_items:
        if item["status"] == "running":
          item["status"] = "cancelled"
      _write_queue_manifest(queue_manifest_path, queue_manifest)
      return 130
    if queue_manifest["status"] == "failed" and failure_policy == "fail-fast":
      for item in queue_items:
        if item["status"] == "running":
          item["status"] = "not_started"
      _write_queue_manifest(queue_manifest_path, queue_manifest)
      return next((code for code in results_by_index.values() if code != 0), 1)
  results = [
    (export_id, results_by_index[index])
    for index, export_id in enumerate(queue, start=1)
    if index in results_by_index
  ]
  succeeded = sum(result == 0 for _export_id, result in results)
  queue_manifest["status"] = "success" if succeeded == len(results) else "partial_failure"
  _write_queue_manifest(queue_manifest_path, queue_manifest)
  print(f"Batch plot queue completed: {succeeded}/{len(results)} definitions")
  return 0 if succeeded == len(results) else 1


def _queue_slug(export_id: str) -> str:
  """Make a definition ID safe and deterministic as a queue subdirectory."""
  slug = "".join(char if char.isalnum() or char in "-_" else "_" for char in export_id)
  return slug[:80] or "export"


def _estimate_queue_definition_bytes(
  project: Mapping[str, Any], project_path: str,
) -> int:
  """Estimate one definition's queue working set from tracked FCS files.

  The estimate is intentionally conservative and only limits explicit queue
  concurrency. It does not alter event arrays or scientific execution.
  """
  total_file_bytes = 0
  project_root = Path(project_path).expanduser().resolve().parent
  for sample in project.get("samples", ()):
    if not isinstance(sample, Mapping):
      continue
    raw_path = sample.get("path")
    if not raw_path:
      continue
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
      path = project_root / path
    try:
      total_file_bytes += max(0, path.stat().st_size)
    except OSError:
      continue
  if total_file_bytes <= 0:
    return 0
  # FCS decode, processed arrays, normalized layers, and writer temporaries
  # can coexist. Six times the file bytes is deliberately conservative.
  return max(64 * 1024 * 1024, total_file_bytes * 6)


def _write_queue_manifest(path: Path, payload: Mapping[str, Any]) -> None:
  """Publish queue status without making image output depend on its audit file."""
  try:
    atomic_write_json(path, dict(payload))
  except OSError as exc:
    print(f"Warning: could not write batch queue manifest: {exc}")


def _write_render_payload(
  path: Path,
  prepared: PreparedPlotExport,
  layers: dict[str, LayerValues],
  event_colors: Mapping[str, Any],
  spec: BatchPlotExportSpec,
  *,
  vector_cache: dict[str, VectorRenderCache] | None = None,
  cancel_check: Callable[[], None] | None = None,
) -> None:
  """Write one format from an item-scoped immutable prepared payload."""
  cache: VectorRenderCache | None = None
  if (
    path.suffix.lower() in {".svg", ".pdf"}
    and vector_cache is not None
    and spec.vector_scatter_mode in {"full_vector", "compact_vector", "hybrid_raster"}
    and not event_colors
    and (
      spec.vector_scatter_mode != "full_vector"
      or len(spec.formats) > 1
    )
  ):
    cache = vector_cache.get("scatter")
    if cache is None:
      selected = prepared.resolved_presentation.presentation
      cache = prepare_vector_render_cache(
        prepared, selected, layers, options=spec, event_colors=event_colors,
        cancel_check=cancel_check,
      )
      vector_cache["scatter"] = cache
  if path.suffix.lower() == ".png":
    write_plot_png(
      path, prepared, layers=layers, width=spec.width, height=spec.height,
      options=spec, event_colors=event_colors, cancel_check=cancel_check,
    )
  elif path.suffix.lower() in {".jpg", ".jpeg"}:
    write_plot_jpg(
      path, prepared, layers=layers, width=spec.width, height=spec.height,
      options=spec, event_colors=event_colors, cancel_check=cancel_check,
    )
  elif path.suffix.lower() == ".svg":
    write_plot_svg(
      path, prepared, layers=layers, options=spec, event_colors=event_colors,
      render_cache=cache, cancel_check=cancel_check,
    )
  elif path.suffix.lower() == ".pdf":
    write_plot_pdf(
      path, prepared, layers=layers, width=spec.width, height=spec.height,
      options=spec, event_colors=event_colors, render_cache=cache,
      cancel_check=cancel_check,
    )
  else:
    raise ValueError(f"CLI renderer does not support {path.suffix!r}")


def _estimate_batch_render_bytes(
  spec: BatchPlotExportSpec,
  *,
  source_ids: Sequence[str],
  prepared_layers: Mapping[str, tuple[np.ndarray, np.ndarray]],
  event_colors: Mapping[str, Any],
  density_coloring: bool = False,
) -> int:
  """Estimate one prepared output item's temporary renderer memory.

  This is deliberately conservative and presentation-only. It bounds worker
  concurrency; it never changes the selected events or scientific results.
  """
  unique_source_ids = tuple(dict.fromkeys(
    source_id for source_id in source_ids if source_id in prepared_layers
  ))
  event_count = 0
  estimate = 0
  for source_id in unique_source_ids:
    x_values, y_values = prepared_layers[source_id]
    count = min(len(x_values), len(y_values))
    event_count += count
    # Prepared NumPy arrays, normalized coordinate arrays, and visibility masks
    # are retained at different points of the format-bundle lifetime.
    estimate += int(x_values.nbytes + y_values.nbytes) * 4
    estimate += count * 49
    colors = event_colors.get(source_id)
    if colors is not None:
      estimate += len(colors) * 16
    if density_coloring and len(unique_source_ids) == 1:
      # Density rendering allocates an event-sized UTF-32 colour array and a
      # float64 normalized-density query array in addition to ordinary points.
      estimate += count * (28 + 8)
  plot_width = max(1, spec.width - 80)
  plot_height = max(1, spec.height - 110)
  if spec.vector_scatter_mode == "hybrid_raster":
    scale = spec.hybrid_scatter_dpi / 96.0
    raster_pixels = max(1, round(plot_width * scale)) * max(
      1, round(plot_height * scale)
    )
    # RGBA pixels, encoded PNG bytes, and point provenance records coexist.
    estimate += raster_pixels * 8 + event_count * 96
  elif spec.vector_scatter_mode == "compact_vector":
    estimate += event_count * 48
  else:
    estimate += event_count * 32
  if density_coloring and len(unique_source_ids) == 1:
    # Histogram, smoothing, and convolution working arrays can coexist briefly.
    estimate += 512 * 512 * 8 * 6
  return max(0, int(estimate))


def _build_overlay_dependency_graph(
  sample_ids: Sequence[str],
  overlay_sources: object,
  manual_overlay_sample_ids: object,
) -> dict[str, tuple[str, ...]]:
  """Build the deterministic base-sample to overlay-source dependency graph.

  The graph is display-only planning state.  It is resolved once before source
  preparation so every target reuses the same source order and each unique FCS
  is prepared at most once.  Invalid entries are ignored here and remain
  subject to the existing unknown-source validation in ``plan_batch_plot_export``.
  """
  advanced: list[tuple[int, str, str]] = []
  if isinstance(overlay_sources, Sequence) and not isinstance(
    overlay_sources, (str, bytes)
  ):
    for source in overlay_sources:
      if not isinstance(source, Mapping):
        continue
      source_id = source.get("sample_id")
      if not source.get("visible", True) or not source_id:
        continue
      try:
        order = int(source.get("order", 0))
      except (TypeError, ValueError):
        order = 0
      advanced.append((order, str(source.get("source_id", "")), str(source_id)))
  advanced_ids = tuple(item[2] for item in sorted(advanced, key=lambda item: item[:2]))
  manual_ids = (
    tuple(str(value) for value in manual_overlay_sample_ids)
    if isinstance(manual_overlay_sample_ids, Sequence)
    and not isinstance(manual_overlay_sample_ids, (str, bytes))
    else ()
  )
  ordered_sources = tuple(dict.fromkeys((*advanced_ids, *manual_ids)))
  return {str(sample_id): ordered_sources for sample_id in sample_ids}


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


def _estimate_normalized_layer_bytes(
  payload: NormalizedPayload,
) -> int:
  """Conservatively estimate the retained renderer-layer payload size."""
  points, visible, colors = payload
  point_bytes = sum(
    int(getattr(values, "nbytes", len(values) * 8))
    for values in points
  )
  color_bytes = 0 if colors is None else int(
    getattr(colors, "nbytes", len(colors) * 16)
  )
  return int(point_bytes + visible.nbytes + color_bytes)


def _shared_layer_bounds(
  layers: Mapping[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[float, float, float, float]:
  """Reduce per-source bounds without concatenating event arrays.

  Shared-range export needs only extrema.  Concatenating all source arrays
  creates a temporary copy proportional to the complete batch, which can
  unnecessarily multiply peak memory before rendering starts.
  """
  if not layers:
    raise ValueError("shared ranges require at least one prepared source")
  nonempty = tuple(value for value in layers.values() if value[0].size and value[1].size)
  if not nonempty:
    raise ValueError("shared ranges require finite events")
  return (
    min(float(np.min(x_values)) for x_values, _ in nonempty),
    max(float(np.max(x_values)) for x_values, _ in nonempty),
    min(float(np.min(y_values)) for _, y_values in nonempty),
    max(float(np.max(y_values)) for _, y_values in nonempty),
  )


def _shared_layer_bounds_from_ranges(
  layer_bounds: Mapping[str, tuple[tuple[float, float], tuple[float, float]]],
) -> tuple[float, float, float, float]:
  """Reduce already computed source extrema without rescanning event arrays."""
  if not layer_bounds:
    raise ValueError("shared ranges require at least one prepared source")
  return (
    min(bounds[0][0] for bounds in layer_bounds.values()),
    max(bounds[0][1] for bounds in layer_bounds.values()),
    min(bounds[1][0] for bounds in layer_bounds.values()),
    max(bounds[1][1] for bounds in layer_bounds.values()),
  )


def _layer_bounds(
  x_values: np.ndarray, y_values: np.ndarray,
) -> tuple[tuple[float, float], tuple[float, float]]:
  """Return one prepared layer's extrema without retaining event copies."""
  if not x_values.size or not y_values.size:
    raise ValueError("plot requires finite events")
  return (
    (float(np.min(x_values)), float(np.max(x_values))),
    (float(np.min(y_values)), float(np.max(y_values))),
  )


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
  return np.asarray(colors[np.asarray(display_mask, dtype=bool)], dtype=str)


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
