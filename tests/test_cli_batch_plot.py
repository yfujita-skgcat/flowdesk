from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pytest

from flowdesk_cli import batch_plot as batch_plot_module
from flowdesk_cli.batch_plot import (
  _build_overlay_dependency_graph,
  _estimate_batch_render_bytes,
  _gate_overlays,
  _layer_bounds,
  _shared_layer_bounds,
  _shared_layer_bounds_from_ranges,
  _write_render_payload,
  batch_plot_command,
  write_plot_svg,
)
from flowdesk_core.density_colors import DensityColorConfig
from flowdesk_core.execution_control import ExecutionOptions
from flowdesk_core.models import BatchPlotExportSpec, ChannelSpec
from flowdesk_core.plot_export import VectorRenderCache, prepare_plot_export
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.sample import SampleData
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import save_project


def test_overlay_dependency_graph_is_deterministic_and_deduplicated() -> None:
  graph = _build_overlay_dependency_graph(
    ("s1", "s2"),
    (
      {"sample_id": "s3", "source_id": "late", "order": 2},
      {"sample_id": "s2", "source_id": "early", "order": 1},
      {"sample_id": "s3", "source_id": "duplicate", "order": 3},
      {"sample_id": "hidden", "source_id": "hidden", "order": 0,
       "visible": False},
    ),
    ("s3", "s4", "s2"),
  )
  assert graph == {"s1": ("s2", "s3", "s4"), "s2": ("s2", "s3", "s4")}


def test_full_vector_cache_is_only_built_for_multi_format_bundle(
  tmp_path: Path, monkeypatch
) -> None:
  prepared = prepare_plot_export(
    "view", "scatter",
    ({
      "source_id": "s1", "sample_id": "s1", "population_id": "all",
      "display_name": "S1", "visible": True,
    },),
    (OverlaySourceResolution("s1", "compatible"),),
  )
  layers = {"s1": ((0.1, 0.2), (0.3, 0.4))}
  calls = 0
  original = batch_plot_module.prepare_vector_render_cache

  def counted(*args, **kwargs):
    nonlocal calls
    calls += 1
    return original(*args, **kwargs)

  monkeypatch.setattr(batch_plot_module, "prepare_vector_render_cache", counted)
  single = BatchPlotExportSpec(
    id="single", name="Single", formats=("svg",), vector_scatter_mode="full_vector",
  )
  _write_render_payload(
    tmp_path / "single.svg", prepared, layers, {}, single, vector_cache={},
  )
  assert calls == 0

  multi = BatchPlotExportSpec(
    id="multi", name="Multi", formats=("svg", "pdf"), vector_scatter_mode="full_vector",
  )
  cache: dict[str, VectorRenderCache] = {}
  _write_render_payload(
    tmp_path / "multi.svg", prepared, layers, {}, multi, vector_cache=cache,
  )
  assert calls == 1


def test_batch_memory_estimate_includes_overlay_and_hybrid_working_set() -> None:
  layers = {
    "s1": (np.zeros(100, dtype=np.float64), np.zeros(100, dtype=np.float64)),
    "s2": (np.zeros(200, dtype=np.float64), np.zeros(200, dtype=np.float64)),
  }
  spec = BatchPlotExportSpec(
    id="memory",
    name="Memory",
    width=800,
    height=600,
    vector_scatter_mode="hybrid_raster",
    hybrid_scatter_dpi=600,
  )
  one_source = _estimate_batch_render_bytes(
    spec, source_ids=("s1",), prepared_layers=layers, event_colors={},
  )
  overlay = _estimate_batch_render_bytes(
    spec, source_ids=("s1", "s2", "s1"), prepared_layers=layers,
    event_colors={"s2": tuple("#ff0000" for _ in range(200))},
  )
  assert overlay > one_source
  assert overlay > 200 * 96


def test_shared_layer_bounds_reduces_extrema_without_array_concatenation() -> None:
  layers = {
    "s1": (np.array([1.0, 2.0]), np.array([5.0, 6.0])),
    "s2": (np.array([-3.0, 4.0]), np.array([0.5, 8.0])),
  }
  assert _shared_layer_bounds(layers) == (-3.0, 4.0, 0.5, 8.0)
  ranges = {source_id: _layer_bounds(*values) for source_id, values in layers.items()}
  assert _shared_layer_bounds_from_ranges(ranges) == (-3.0, 4.0, 0.5, 8.0)


def test_layer_bounds_rejects_empty_prepared_source() -> None:
  with pytest.raises(ValueError, match="finite events"):
    _layer_bounds(np.array([], dtype=np.float64), np.array([], dtype=np.float64))


def test_batch_plot_uses_canonical_derived_display_data(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-derived",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{
      "id": "s1", "path": "sample.fcs",
      "channels": [
        {"id": "signal", "name": "Signal", "metadata": {}},
        {"id": "reference", "name": "Reference", "metadata": {}},
      ],
    }],
    "derived_parameters": [{
      "id": "ratio_definition", "name": "Ratio", "output_channel_id": "ratio",
      "expression": "signal / reference", "source_stage": "raw",
      "input_parameters": ["signal", "reference"],
      "invalid_value_policy": "emit_nan_with_warning",
    }],
    "plot_views": [{
      "id": "derived-view", "plot_type": "scatter",
      "population_id": "all_events", "x_parameter": "ratio",
      "y_parameter": "signal", "rendering_downsample": {"max_points": 0},
      "presentation": {"colormap": "density"},
    }],
    "batch_plot_exports": [{
      "id": "derived-export", "name": "Derived export", "target": "all",
      "plot_view_id": "derived-view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-derived.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1",
    np.array([[2.0, 1.0], [4.0, 2.0], [6.0, 1.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"), ChannelSpec(id="reference", name="Reference")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )

  output_dir = tmp_path / "exports"
  assert batch_plot_command(
    str(project_path), "derived-export", str(output_dir),
    density_config=DensityColorConfig(histogram_workers=2, histogram_memory_budget_bytes=1),
  ) == 0
  output = next(output_dir.glob("*.svg"))
  assert output.stat().st_size > 0
  sidecar = json.loads(output.with_suffix(".svg.json").read_text(encoding="utf-8"))
  assert sidecar["plot_view_id"] == "derived-view"
  assert sidecar["sources"][0]["x_parameter_id"] == "ratio"
  assert sidecar["sources"][0]["y_parameter_id"] == "signal"
  assert sidecar["presentation"]["x_axis_display_label"] == "Ratio"
  assert sidecar["presentation"]["y_axis_display_label"] == "Signal"
  density = sidecar["density_coloring"]
  assert density["requested_histogram_workers"] == 2
  assert density["effective_histogram_workers"] == 1
  assert density["histogram_memory_budget_bytes"] == 1


def test_batch_plot_renders_manual_overlay_sources_in_order(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-overlay",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [
      {"id": "s1", "path": "a.fcs", "name": "A", "channels": []},
      {"id": "s2", "path": "b.fcs", "name": "B", "channels": []},
    ],
    "plot_views": [{
      "id": "overlay-view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "manual_overlay_sample_ids": ["s2"],
      "presentation": {"title": "Overlay", "source_styles": [
        {"source_id": "s2", "color": "#ff0000"},
      ]},
    }],
    "gating_strategies_data": {"default": {
      "id": "default", "name": "Default", "gates": [{
        "id": "gate-1", "name": "Gate", "gate_type": "rectangle",
        "x_parameter": "x", "y_parameter": "y",
        "thresholds": {"x_min": 1.0, "x_max": 2.0, "y_min": 1.0, "y_max": 2.0},
        "color": "#00ff00",
      }],
    }},
    "batch_plot_exports": [{
      "id": "overlay-export", "name": "Overlay export", "target": "all",
      "plot_view_id": "overlay-view", "formats": ["svg"],
      "layout_policy": "shared_ranges",
    }],
  }
  project_path = tmp_path / "batch-overlay.flowdesk"
  save_project(project_path, project)
  samples = {
    "s1": SampleData("s1", np.array([[1.0, 1.0], [2.0, 2.0]]),
                     (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y"))),
    "s2": SampleData("s2", np.array([[3.0, 3.0], [4.0, 4.0]]),
                     (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y"))),
  }
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": key, "path": f"{key}.fcs", "name": key.upper()}
                    for key in ("s1", "s2")],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample",
    lambda path, *_args: (None, samples[Path(path).stem]),
  )
  normalize_calls = 0
  original_normalize = batch_plot_module._normalize
  gate_overlay_calls = 0
  original_gate_overlays = batch_plot_module._gate_overlays
  tick_calls = 0
  original_normalized_ticks = batch_plot_module._normalized_ticks

  def count_normalize(values, bounds=None):
    nonlocal normalize_calls
    normalize_calls += 1
    return original_normalize(values, bounds)

  def count_gate_overlays(*args, **kwargs):
    nonlocal gate_overlay_calls
    gate_overlay_calls += 1
    return original_gate_overlays(*args, **kwargs)

  def count_normalized_ticks(*args, **kwargs):
    nonlocal tick_calls
    tick_calls += 1
    return original_normalized_ticks(*args, **kwargs)

  monkeypatch.setattr(batch_plot_module, "_normalize", count_normalize)
  monkeypatch.setattr(batch_plot_module, "_gate_overlays", count_gate_overlays)
  monkeypatch.setattr(batch_plot_module, "_normalized_ticks", count_normalized_ticks)
  output_dir = tmp_path / "exports"
  assert batch_plot_command(
    str(project_path), "overlay-export", str(output_dir),
    execution_options=ExecutionOptions(backend="thread", max_workers=2),
  ) == 0
  text = next(output_dir.glob("*s1*.svg")).read_text(encoding="utf-8")
  assert 'fill="#ff0000"' in text
  assert 'stroke="#00ff00"' in text
  # Both target scenes use the same shared range.  Each source is normalized
  # once (X/Y), then reused when it appears as the other target's overlay.
  assert normalize_calls == 4
  assert gate_overlay_calls == 1
  assert tick_calls == 2
  metadata = json.loads(next(output_dir.glob("*s1*.svg.json")).read_text(encoding="utf-8"))
  assert metadata["ordered_source_ids"] == ["s1", "s2"]

  # current_view uses the same cache when every target has the same persisted
  # bounds.  This must not depend on the layout policy name.
  project["plot_views"][0]["display_scene"] = {
    "view_range": [[0.0, 5.0], [0.0, 5.0]],
  }
  project["batch_plot_exports"][0]["layout_policy"] = "current_view"
  save_project(project_path, project)
  normalize_calls = 0
  current_output = tmp_path / "exports-current"
  assert batch_plot_command(
    str(project_path), "overlay-export", str(current_output),
    execution_options=ExecutionOptions(backend="thread", max_workers=2),
  ) == 0
  assert normalize_calls == 4
  assert gate_overlay_calls == 2
  assert tick_calls == 4


def test_batch_plot_prepares_only_target_and_overlay_sources(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-source-scope",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [
      {"id": "s1", "path": "s1.fcs", "name": "A", "channels": []},
      {"id": "s2", "path": "s2.fcs", "name": "B", "channels": []},
      {"id": "s3", "path": "s3.fcs", "name": "Unused", "channels": []},
    ],
    "sample_groups": [{"id": "selected", "role": "user", "sample_ids": ["s1"]}],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "manual_overlay_sample_ids": ["s2"],
    }],
    "batch_plot_exports": [{
      "id": "source-scope", "name": "Source scope", "target": "group",
      "group_id": "selected", "plot_view_id": "view", "formats": ["svg", "png"],
    }],
  }
  project_path = tmp_path / "source-scope.flowdesk"
  save_project(project_path, project)
  sample_data = {
    sample_id: SampleData(
      sample_id,
      np.array([[1.0, 1.0], [2.0, 2.0]]),
      (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
    )
    for sample_id in ("s1", "s2", "s3")
  }
  loaded_ids: list[str] = []
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [
      {"id": sample_id, "path": f"{sample_id}.fcs", "name": sample_id}
      for sample_id in ("s1", "s2", "s3")
    ],
  )

  def read_sample(path, *_args):
    sample_id = Path(path).stem
    loaded_ids.append(sample_id)
    return None, sample_data[sample_id]

  monkeypatch.setattr("flowdesk_cli.batch_plot.read_fcs_sample", read_sample)
  original_prepare = batch_plot_module.prepare_plot_export
  prepare_calls: list[str] = []

  def prepare_once(*args, **kwargs):
    prepare_calls.append(str(args[0]))
    return original_prepare(*args, **kwargs)

  monkeypatch.setattr("flowdesk_cli.batch_plot.prepare_plot_export", prepare_once)

  assert batch_plot_command(
    str(project_path), "source-scope", str(tmp_path / "exports")
  ) == 0
  assert loaded_ids == ["s1", "s2"]
  assert prepare_calls == ["view"]


def test_batch_plot_thread_backend_prepares_sources_concurrently(
  tmp_path: Path, monkeypatch,
) -> None:
  project = {
    "project_id": "batch-prepare-thread",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [
      {"id": "s1", "path": "s1.fcs", "name": "A", "channels": []},
      {"id": "s2", "path": "s2.fcs", "name": "B", "channels": []},
    ],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y",
      "rendering_downsample": {"max_points": 0},
    }],
    "batch_plot_exports": [{
      "id": "prepare-thread", "name": "Prepare thread", "target": "all",
      "plot_view_id": "view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "prepare-thread.flowdesk"
  save_project(project_path, project)
  sample_data = {
    sample_id: SampleData(
      sample_id,
      np.array([[1.0, 1.0], [2.0, 2.0]], dtype=np.float64),
      (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
    )
    for sample_id in ("s1", "s2")
  }
  entered = threading.Barrier(2)
  both_prepared = threading.Event()

  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [
      {"id": sample_id, "path": f"{sample_id}.fcs", "name": sample_id}
      for sample_id in ("s1", "s2")
    ],
  )

  def read_sample(path, *_args):
    try:
      entered.wait(2.0)
    except threading.BrokenBarrierError as exc:
      raise AssertionError("source preparation did not overlap") from exc
    both_prepared.set()
    return None, sample_data[Path(path).stem]

  monkeypatch.setattr("flowdesk_cli.batch_plot.read_fcs_sample", read_sample)
  output_dir = tmp_path / "exports"
  assert batch_plot_command(
    str(project_path), "prepare-thread", str(output_dir),
    execution_options=ExecutionOptions(backend="thread", max_workers=2),
  ) == 0
  assert both_prepared.is_set()
  assert len(tuple(output_dir.glob("*.svg"))) == 2
  manifest = json.loads(next(output_dir.glob("*.batch.json")).read_text(encoding="utf-8"))
  assert manifest["execution"]["preparation"]["backend"] == "thread"
  assert manifest["execution"]["preparation"]["effective_max_workers"] == 2
  assert manifest["execution"]["preparation"]["submitted_sources"] == 2
  assert manifest["execution"]["preparation"]["peak_in_flight_sources"] <= 2


def test_batch_plot_clips_gate_edges_at_the_viewport_boundary() -> None:
  project = {
    "gating_strategies_data": {"default": {"gates": [{
      "id": "gate", "gate_type": "polygon", "x_parameter": "x", "y_parameter": "y",
      # The first vertex lies above the visible range.  The two adjacent
      # edges must intersect the top at x=0.7 and x=0.85, rather than moving
      # the hidden vertex itself to (0.8, 1.0).
      "coordinates": ((0.8, 1.2), (0.6, 0.8), (0.9, 0.8)),
    }]}},
  }
  overlays = _gate_overlays(
    project, "x", "y", ((0.0, 1.0), (0.0, 1.0)), None, None,
    default_color="#e00000",
  )
  assert len(overlays) == 1
  points = overlays[0]["points"]
  assert (0.7, 1.0) in points
  assert any(np.allclose(point, (0.85, 1.0)) for point in points)
  assert (0.8, 1.0) not in points


def test_batch_plot_applies_persisted_transform_once(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-transform",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{"id": "s1", "path": "sample.fcs", "channels": []}],
    "transforms": [{
      "id": "tx", "name": "X log", "transform_type": "log", "parameter": "x",
      "settings": {"base": 10.0, "invalid_value_policy": "to_nan"}, "role": "analysis",
    }],
    "plot_views": [{
      "id": "transform-view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "x_transform_id": "tx",
      "y_transform_id": None, "rendering_downsample": {"max_points": 0},
    }],
    "gating_strategies_data": {"default_strategy": {
      "id": "default_strategy", "name": "Default", "root_population_id": "all_events",
      "gates": [{
        "id": "gate-x", "name": "Gate", "gate_type": "rectangle",
        "parent_population_id": "all_events", "x_parameter": "x", "y_parameter": "y",
        "x_transform_id": "tx", "y_transform_id": None,
        "thresholds": {"x_min": 0.0, "x_max": 2.0, "y_min": 1.0, "y_max": 3.0},
      }],
    }},
    "batch_plot_exports": [{
      "id": "transform-export", "name": "Transform export", "target": "all",
      "plot_view_id": "transform-view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-transform.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1", np.array([[1.0, 1.0], [10.0, 2.0], [100.0, 3.0]]),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )
  captured: dict[str, object] = {}
  def capture(*args, **kwargs):
    captured["layers"] = kwargs["layers"]
    return write_plot_svg(*args, **kwargs)

  monkeypatch.setattr("flowdesk_cli.batch_plot.write_plot_svg", capture)
  assert batch_plot_command(
    str(project_path), "transform-export", str(tmp_path / "exports")
  ) == 0
  layer = captured["layers"]["s1"]
  assert len(layer[0]) == 3
  assert isinstance(layer[0], np.ndarray)
  assert not layer[0].flags.writeable
  np.testing.assert_allclose(layer[0], (0.0, 0.5, 1.0))
  sidecar = json.loads(
    next((tmp_path / "exports").glob("*.svg.json")).read_text(encoding="utf-8")
  )
  assert len(sidecar["gate_overlays"]) == 1
  assert sidecar["gate_overlays"][0]["color"] == "#e00000"


def test_batch_plot_current_view_uses_persisted_labels_and_range(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-current-view",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{"id": "s1", "path": "sample.fcs", "channels": []}],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "display_scene": {
        "x_axis_label": "FITC B525-A", "y_axis_label": "APC R660-A",
        "view_range": [[0.0, 4.0], [0.0, 4.0]],
      },
    }],
    "batch_plot_exports": [{
      "id": "export", "name": "Export", "target": "all", "plot_view_id": "view",
      "formats": ["svg"], "layout_policy": "current_view",
    }],
  }
  project_path = tmp_path / "batch-current-view.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1", np.array([[1.0, 1.0], [2.0, 2.0], [8.0, 8.0]]),
    (ChannelSpec(id="x", name="FL1-A"), ChannelSpec(id="y", name="FL3-A")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )
  captured: dict[str, object] = {}

  def capture(*args, **kwargs):
    captured["layers"] = kwargs["layers"]
    return write_plot_svg(*args, **kwargs)

  monkeypatch.setattr("flowdesk_cli.batch_plot.write_plot_svg", capture)
  assert batch_plot_command(str(project_path), "export", str(tmp_path / "exports")) == 0
  np.testing.assert_allclose(captured["layers"]["s1"][0], (0.25, 0.5))
  np.testing.assert_allclose(captured["layers"]["s1"][1], (0.25, 0.5))
  sidecar = json.loads(
    next((tmp_path / "exports").glob("*.svg.json")).read_text(encoding="utf-8")
  )
  assert sidecar["presentation"]["x_axis_display_label"] == "FITC B525-A"
  assert sidecar["presentation"]["y_axis_display_label"] == "APC R660-A"
