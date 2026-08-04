from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from flowdesk_cli import batch_plot as batch_plot_module
from flowdesk_cli.batch_plot import (
  _build_overlay_dependency_graph,
  _estimate_batch_render_bytes,
  _gate_overlays,
  _layer_bounds,
  _ProcessedDisplayCache,
  _RawSampleCache,
  _shared_layer_bounds,
  _shared_layer_bounds_from_ranges,
  _write_render_payload,
  batch_plot_command,
  batch_plot_queue_command,
  write_plot_svg,
)
from flowdesk_core.density_colors import DensityColorConfig
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
from flowdesk_core.models import BatchPlotExportSpec, ChannelSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.plot_export import VectorRenderCache, prepare_plot_export
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.processed_display import ProcessedDisplayLayer
from flowdesk_core.sample import SampleData
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import save_project


def test_batch_plot_queue_uses_definition_subdirectories_and_continues(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  calls: list[tuple[str, str]] = []

  def fake_batch(project: str, export_id: str, output_dir: str, **kwargs: object) -> int:
    calls.append((export_id, output_dir))
    return 1 if export_id == "bad/id" else 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  assert batch_plot_queue_command(
    "project.flowdesk", ("ok", "bad/id", "last"), str(tmp_path),
    failure_policy="continue",
  ) == 1
  assert [item[0] for item in calls] == ["ok", "bad/id", "last"]
  assert calls[0][1].endswith("001_ok")
  assert calls[1][1].endswith("002_bad_id")
  assert calls[2][1].endswith("003_last")
  manifest = json.loads(
    (tmp_path / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert manifest["status"] == "partial_failure"
  assert [item["status"] for item in manifest["definitions"]] == [
    "success", "failed", "success",
  ]


def test_batch_plot_queue_manifest_preserves_not_started_items_on_fail_fast(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  monkeypatch.setattr(
    batch_plot_module, "batch_plot_command", lambda *_args, **_kwargs: 1,
  )
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second"), str(tmp_path),
  ) == 1
  manifest = json.loads(
    (tmp_path / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert manifest["status"] == "failed"
  assert [item["status"] for item in manifest["definitions"]] == [
    "failed", "not_started",
  ]


def test_batch_plot_queue_normalizes_definition_exception_for_continue(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  calls: list[str] = []

  def fake_batch(_project, export_id, _output_dir, **_kwargs):
    calls.append(export_id)
    if export_id == "raises":
      raise RuntimeError("writer crashed")
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", ("raises", "last"), str(tmp_path),
    failure_policy="continue",
  ) == 1
  assert calls == ["raises", "last"]
  manifest = json.loads(
    (tmp_path / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert manifest["status"] == "partial_failure"
  assert [item["status"] for item in manifest["definitions"]] == [
    "failed", "success",
  ]


def test_batch_plot_queue_all_uses_snapshot_declaration_order(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  snapshot = {"batch_plot_exports": [{"id": "second"}, {"id": "first"}]}
  loads: list[str] = []
  calls: list[tuple[str, object]] = []
  monkeypatch.setattr(
    batch_plot_module, "load_project",
    lambda path: loads.append(str(path)) or snapshot,
  )

  def fake_batch(_project, export_id, _output_dir, **kwargs):
    calls.append((export_id, kwargs["_project_snapshot"], kwargs["_definition_snapshot"]))
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", (), str(tmp_path), queue_all=True,
  ) == 0
  assert loads == ["project.flowdesk"]
  assert [item[0] for item in calls] == ["second", "first"]
  assert calls[0][1] is calls[1][1] is snapshot
  assert calls[0][2] is snapshot["batch_plot_exports"][0]
  assert calls[1][2] is snapshot["batch_plot_exports"][1]


def test_batch_plot_queue_emits_definition_progress(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  events = []
  control = ExecutionControl(progress_sink=events.append)

  def fake_batch(*_args, **_kwargs) -> int:
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second"), str(tmp_path),
    execution_control=control,
  ) == 0
  assert [(event.phase, event.completed_units, event.total_units, event.sample_id)
          for event in events] == [
    ("definition_started", 0, 2, "first"),
    ("definition_completed", 1, 2, "first"),
    ("definition_started", 1, 2, "second"),
    ("definition_completed", 2, 2, "second"),
  ]


def test_batch_plot_queue_loads_project_snapshot_once(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  loads: list[str] = []
  path_resolutions: list[str] = []
  calls: list[object] = []

  monkeypatch.setattr(
    batch_plot_module, "load_project",
    lambda path: loads.append(str(path)) or {"batch_plot_exports": []},
  )
  monkeypatch.setattr(
    batch_plot_module, "resolve_sample_paths",
    lambda manifest, path: path_resolutions.append(str(path)) or [],
  )

  def fake_batch(*_args, **kwargs) -> int:
    calls.append(kwargs.get("_project_snapshot"))
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second"), str(tmp_path),
  ) == 0
  assert loads == ["project.flowdesk"]
  assert path_resolutions == ["project.flowdesk"]
  assert len(calls) == 2
  assert calls[0] is calls[1]


def test_batch_plot_queue_reports_sample_path_resolution_failure(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
  monkeypatch.setattr(
    batch_plot_module, "load_project", lambda _path: {"batch_plot_exports": []},
  )
  monkeypatch.setattr(
    batch_plot_module, "resolve_sample_paths",
    lambda *_args: (_ for _ in ()).throw(ValueError("bad sample path")),
  )
  assert batch_plot_queue_command(
    "project.flowdesk", ("first",), str(tmp_path),
  ) == 1
  assert "sample path resolution failed" in capsys.readouterr().out


def test_batch_plot_queue_shares_one_raw_cache_between_definitions(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  caches = []
  display_caches = []

  def fake_batch(*_args, **kwargs) -> int:
    caches.append(kwargs["_raw_sample_cache"])
    display_caches.append(kwargs["_processed_display_cache"])
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second"), str(tmp_path),
  ) == 0
  assert len(caches) == 2
  assert caches[0] is caches[1]
  assert isinstance(caches[0], _RawSampleCache)
  assert display_caches[0] is display_caches[1]
  assert isinstance(display_caches[0], _ProcessedDisplayCache)


def _display_layer(event_count: int = 2) -> ProcessedDisplayLayer:
  return ProcessedDisplayLayer(
    sample_id="sample",
    population_id="all_events",
    x_parameter_id="x",
    y_parameter_id="y",
    x_transform_id=None,
    y_transform_id=None,
    plot_type="scatter",
    display_max_points=20_000,
    events=np.zeros((event_count, 2), dtype=np.float64),
    channels=(ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
    display_mask=np.ones(event_count, dtype=bool),
  )


def test_processed_display_cache_is_bounded_lru() -> None:
  first = _display_layer(2)
  second = _display_layer(2)
  cache = _ProcessedDisplayCache(first.events.nbytes + first.display_mask.nbytes)
  assert cache.get_or_load(("first",), lambda: first) is first
  assert cache.get_or_load(("second",), lambda: second) is second
  assert cache.stats()["retained_layers"] == 1
  assert cache.stats()["evictions"] == 1
  assert cache.get_or_load(("first",), lambda: first) is first
  assert cache.stats()["misses"] == 3


def test_processed_display_cache_zero_budget_does_not_retain() -> None:
  cache = _ProcessedDisplayCache(0)
  calls = 0

  def load() -> ProcessedDisplayLayer:
    nonlocal calls
    calls += 1
    return _display_layer()

  cache.get_or_load(("same",), load)
  cache.get_or_load(("same",), load)
  assert calls == 2
  assert cache.stats()["retained_layers"] == 0
  assert cache.stats()["retained_bytes"] == 0


def test_processed_display_cache_keeps_distinct_requests_separate() -> None:
  cache = _ProcessedDisplayCache(1024 * 1024)
  first = _display_layer()
  second = _display_layer()
  assert cache.get_or_load(("view", "all_events", "x", "y"), lambda: first) is first
  assert cache.get_or_load(("view", "all_events", "x", "z"), lambda: second) is second
  assert cache.stats()["retained_layers"] == 2
  assert cache.stats()["hits"] == 0


def test_batch_plot_queue_supports_explicit_definition_parallelism(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  caches = []
  shared_sample = SampleData(
    "shared", np.zeros((2, 2), dtype=np.float64),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  shared_key = ("shared", "shared.fcs", "fingerprint")
  lock = threading.Lock()
  active = 0
  peak = 0

  def fake_batch(*_args, **kwargs) -> int:
    nonlocal active, peak
    cache = kwargs.get("_raw_sample_cache")
    caches.append(cache)
    assert cache is not None
    cache.get_or_load(shared_key, lambda: ("info", shared_sample))
    with lock:
      active += 1
      peak = max(peak, active)
    import time
    time.sleep(0.03)
    with lock:
      active -= 1
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second", "third"), str(tmp_path),
    queue_workers=2,
  ) == 0
  assert peak == 2
  assert len(caches) == 3
  assert caches[0] is caches[1] is caches[2]
  assert isinstance(caches[0], _RawSampleCache)
  manifest = json.loads(
    (tmp_path / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert manifest["status"] == "success"
  assert manifest["queue_execution"]["effective_workers"] == 2
  assert manifest["queue_execution"]["resolved_backend"] == "thread"
  assert manifest["queue_execution"]["nested_definition_backend"] == "sequential"
  assert manifest["queue_execution"]["planned_definitions"] == 3
  assert manifest["queue_execution"]["submitted_definitions"] == 3
  assert manifest["queue_execution"]["completed_definitions"] == 3
  assert manifest["queue_execution"]["peak_in_flight_definitions"] == 2
  assert manifest["raw_sample_cache"]["enabled"] is True
  assert manifest["raw_sample_cache"]["hits"] >= 1
  assert manifest["processed_display_cache"]["retained_layers"] == 0
  assert [item["status"] for item in manifest["definitions"]] == [
    "success", "success", "success",
  ]


def test_batch_plot_queue_parallel_fail_fast_tracks_cancelled_pending_work(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: {})
  failure_started = threading.Event()
  second_started = threading.Event()

  def fake_batch(_project, export_id, _output_dir, **_kwargs) -> int:
    import time
    if export_id == "first":
      failure_started.set()
      # Do not let the result timing decide whether the second worker was
      # submitted.  The assertion is about fail-fast queue accounting after
      # both initial workers are in flight.
      second_started.wait(timeout=1)
      return 1
    if export_id == "second":
      failure_started.wait(timeout=1)
      second_started.set()
      time.sleep(0.1)
    return 0

  monkeypatch.setattr(batch_plot_module, "batch_plot_command", fake_batch)
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second", "third", "fourth"), str(tmp_path),
    queue_workers=2,
  ) == 1
  manifest = json.loads(
    (tmp_path / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert [item["status"] for item in manifest["definitions"]] == [
    "failed", "success", "not_started", "not_started",
  ]
  execution = manifest["queue_execution"]
  assert execution["submitted_definitions"] == 2
  assert execution["completed_definitions"] == 2
  assert execution["peak_in_flight_definitions"] == 2


def test_batch_plot_queue_rejects_nested_thread_backends(tmp_path: Path) -> None:
  with pytest.raises(ValueError, match="cannot be combined"):
    batch_plot_queue_command(
      "project.flowdesk", ("first", "second"), str(tmp_path),
      queue_workers=2,
      execution_options=ExecutionOptions(backend="thread", max_workers=2),
    )


def test_batch_plot_queue_applies_memory_budget_to_queue_workers(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  sample_path = tmp_path / "sample.fcs"
  sample_path.write_bytes(b"fcs")
  snapshot = {
    "samples": [{"id": "s1", "path": str(sample_path)}],
    "batch_plot_exports": [],
  }
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: snapshot)
  caches = []
  monkeypatch.setattr(
    batch_plot_module, "batch_plot_command",
    lambda *_args, **kwargs: caches.append(kwargs.get("_raw_sample_cache")) or 0,
  )
  assert batch_plot_queue_command(
    "project.flowdesk", ("first", "second"), str(tmp_path / "out"),
    queue_workers=2,
    execution_options=ExecutionOptions(
      memory_budget_bytes=32 * 1024 * 1024,
    ),
  ) == 0
  manifest = json.loads(
    (tmp_path / "out" / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  assert manifest["queue_execution"]["effective_workers"] == 1
  assert manifest["queue_execution"]["resolved_backend"] == "sequential"
  assert "memory_budget" in manifest["queue_execution"]["limiting_factors"]
  assert manifest["queue_execution"]["planned_definitions"] == 2
  assert manifest["queue_execution"]["submitted_definitions"] == 2
  assert manifest["queue_execution"]["completed_definitions"] == 2
  assert manifest["queue_execution"]["peak_in_flight_definitions"] == 1
  assert caches == [None, None]
  assert manifest["raw_sample_cache"]["enabled"] is False
  assert manifest["raw_sample_cache"]["reason"] == "no_residual_memory_budget"


def test_batch_plot_queue_memory_estimate_uses_definition_sources(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  small_path = tmp_path / "small.fcs"
  small_path.write_bytes(b"small")
  large_path = tmp_path / "large.fcs"
  with large_path.open("wb") as handle:
    handle.truncate(16 * 1024 * 1024)
  snapshot = {
    "samples": [
      {"id": "small", "path": str(small_path)},
      {"id": "large", "path": str(large_path)},
    ],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "x_parameter": "x",
      "y_parameter": "y",
    }],
    "batch_plot_exports": [
      {
        "id": "small-a", "name": "Small A", "target": "explicit",
        "sample_ids": ["small"], "plot_view_id": "view", "formats": ["svg"],
      },
      {
        "id": "small-b", "name": "Small B", "target": "explicit",
        "sample_ids": ["small"], "plot_view_id": "view", "formats": ["svg"],
      },
    ],
  }
  monkeypatch.setattr(batch_plot_module, "load_project", lambda _path: snapshot)
  monkeypatch.setattr(
    batch_plot_module, "batch_plot_command", lambda *_args, **_kwargs: 0,
  )
  output_dir = tmp_path / "out"
  assert batch_plot_queue_command(
    "project.flowdesk", ("small-a", "small-b"), str(output_dir),
    queue_workers=2,
    execution_options=ExecutionOptions(memory_budget_bytes=128 * 1024 * 1024),
  ) == 0
  manifest = json.loads(
    (output_dir / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )
  execution = manifest["queue_execution"]
  assert execution["effective_workers"] == 2
  assert execution["estimated_definition_bytes"] == 64 * 1024 * 1024

  snapshot["batch_plot_exports"][1]["formats"] = ["png"]
  snapshot["batch_plot_exports"][1]["width"] = 6_000
  snapshot["batch_plot_exports"][1]["height"] = 4_000
  large_output_dir = tmp_path / "large-output"
  assert batch_plot_queue_command(
    "project.flowdesk", ("small-a", "small-b"), str(large_output_dir),
    queue_workers=2,
    execution_options=ExecutionOptions(memory_budget_bytes=192 * 1024 * 1024),
  ) == 0
  large_execution = json.loads(
    (large_output_dir / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )["queue_execution"]
  assert large_execution["effective_workers"] == 2
  assert 64 * 1024 * 1024 < large_execution["estimated_definition_bytes"] < 128 * 1024 * 1024

  snapshot["batch_plot_exports"].extend([
    {
      "id": "large-a", "name": "Large A", "target": "explicit",
      "sample_ids": ["large"], "plot_view_id": "view", "formats": ["svg"],
    },
    {
      "id": "large-b", "name": "Large B", "target": "explicit",
      "sample_ids": ["large"], "plot_view_id": "view", "formats": ["svg"],
    },
  ])
  corrected_output_dir = tmp_path / "corrected-estimate"
  assert batch_plot_queue_command(
    "project.flowdesk", ("large-a", "large-b"), str(corrected_output_dir),
    queue_workers=2,
    execution_options=ExecutionOptions(memory_budget_bytes=192 * 1024 * 1024),
  ) == 0
  corrected_execution = json.loads(
    (corrected_output_dir / "batch-queue-manifest.json").read_text(encoding="utf-8")
  )["queue_execution"]
  assert corrected_execution["estimated_definition_bytes"] == 96 * 1024 * 1024
  assert corrected_execution["effective_workers"] == 2


def test_raw_sample_cache_is_bounded_and_tracks_fingerprint_hits() -> None:
  cache = _RawSampleCache(32)
  sample = SampleData(
    "s1", np.zeros((2, 2), dtype=np.float64),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  key = ("s1", "sample.fcs", "fingerprint-a")
  cache.put(key, "info", sample)
  assert cache.get(key) == ("info", sample)
  assert cache.stats()["hits"] == 1
  assert cache.get(("s1", "sample.fcs", "fingerprint-b")) is None
  assert cache.stats()["misses"] == 1
  assert cache.stats()["retained_samples"] == 1


def test_raw_sample_cache_coalesces_concurrent_misses() -> None:
  cache = _RawSampleCache(1024)
  sample = SampleData(
    "s1", np.zeros((2, 2), dtype=np.float64),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  started = threading.Event()
  release = threading.Event()
  reads = 0

  def loader() -> tuple[str, SampleData]:
    nonlocal reads
    reads += 1
    started.set()
    assert release.wait(timeout=2)
    return "info", sample

  key = ("s1", "sample.fcs", "fingerprint-a")
  with ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(cache.get_or_load, key, loader) for _ in range(2)]
    assert started.wait(timeout=2)
    release.set()
    assert [future.result(timeout=2) for future in futures] == [
      ("info", sample), ("info", sample),
    ]
  assert reads == 1
  assert cache.stats()["retained_samples"] == 1


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
  density = _estimate_batch_render_bytes(
    spec, source_ids=("s1",), prepared_layers=layers, event_colors={},
    density_coloring=True,
  )
  assert overlay > one_source
  assert overlay > 200 * 96
  assert density > one_source + 512 * 512 * 8 * 6


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


def test_batch_plot_command_reuses_queue_raw_sample_cache(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  project = {
    "project_id": "cache-project",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "samples": [{
      "id": "s1", "name": "Sample", "path": "sample.fcs", "channels": [],
    }],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "presentation": {},
    }],
    "batch_plot_exports": [{
      "id": "export", "name": "Export", "plot_view_id": "view", "target": "all",
      "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "cache.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1", np.array([[1.0, 2.0], [2.0, 3.0]], dtype=np.float64),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "name": "Sample", "path": "sample.fcs"}],
  )
  reads = 0
  display_preparations = 0

  def read_sample(*_args):
    nonlocal reads
    reads += 1
    return None, sample

  monkeypatch.setattr("flowdesk_cli.batch_plot.read_fcs_sample", read_sample)
  original_prepare = PipelineRunner.prepare_display_layer

  def count_display_preparation(self, *args, **kwargs):
    nonlocal display_preparations
    display_preparations += 1
    return original_prepare(self, *args, **kwargs)

  monkeypatch.setattr(
    PipelineRunner, "prepare_display_layer", count_display_preparation,
  )
  cache = _RawSampleCache(1024)
  display_cache = _ProcessedDisplayCache(1024 * 1024)
  assert batch_plot_command(
    str(project_path), "export", str(tmp_path / "first"),
    _raw_sample_cache=cache,
    _processed_display_cache=display_cache,
  ) == 0
  assert batch_plot_command(
    str(project_path), "export", str(tmp_path / "second"),
    _raw_sample_cache=cache,
    _processed_display_cache=display_cache,
  ) == 0
  assert reads == 1
  assert cache.stats()["hits"] == 1
  assert display_preparations == 1
  assert display_cache.stats()["hits"] == 1


def test_batch_plot_command_maps_cancellation_to_sigint_exit_code(
  tmp_path: Path, monkeypatch,
) -> None:
  project = {
    "project_id": "batch-cancel-cli",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "samples": [],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y",
    }],
    "batch_plot_exports": [{
      "id": "cancel-export", "name": "Cancel export", "target": "all",
      "plot_view_id": "view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-cancel-cli.flowdesk"
  save_project(project_path, project)
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths", lambda *_args: [],
  )
  control = batch_plot_module.ExecutionControl()
  control.cancellation_token.cancel()

  assert batch_plot_command(
    str(project_path), "cancel-export", str(tmp_path / "exports"),
    execution_control=control,
  ) == 130


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
      {"id": "s3", "path": "c.fcs", "name": "C", "channels": []},
    ],
    "plot_views": [{
      "id": "overlay-view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "manual_overlay_sample_ids": ["s2", "s3"],
      "presentation": {"title": "Overlay", "single_color": "#00aa66",
        "source_styles": [
        {"source_id": "s1", "color": "#4c78a8"},
        {"source_id": "s2", "color": "#ff0000"},
        {"source_id": "s3", "color": "#00aa66"},
      ]},
    }],
    "annotations": [
      {
        "sample_id": "s1", "keyword": "sample_title",
        "value": "Active title", "source": "workspace",
      },
      {
        "sample_id": "s2", "keyword": "sample_title",
        "value": "Overlay title", "source": "workspace",
      },
      {
        "sample_id": "s3", "keyword": "sample_title",
        "value": "Green title", "source": "workspace",
      },
    ],
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
    "s3": SampleData("s3", np.array([[5.0, 5.0], [6.0, 6.0]]),
                     (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y"))),
  }
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": key, "path": f"{key}.fcs", "name": key.upper()}
                    for key in ("s1", "s2", "s3")],
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
  assert 'fill="#00aa66"' in text
  assert 'fill="#ff0000"' in text
  assert "Active title" in text
  assert "Overlay title" in text
  assert "Green title" in text
  assert text.index("Active title") < text.index("Overlay title") < text.index("Green title")
  assert 'stroke="#00ff00"' in text
  # Both target scenes use the same shared range.  Each source is normalized
  # once (X/Y), then reused when it appears as the other target's overlay.
  assert normalize_calls == 6
  assert gate_overlay_calls == 1
  assert tick_calls == 2
  metadata = json.loads(next(output_dir.glob("*s1*.svg.json")).read_text(encoding="utf-8"))
  assert metadata["ordered_source_ids"] == ["s1", "s2", "s3"]
  assert metadata["scene"]["source_draw_order"] == ["s1", "s3", "s2"]

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
  assert normalize_calls == 6
  assert gate_overlay_calls == 2
  assert tick_calls == 4


def test_batch_overlay_graph_keeps_semantic_sample_order() -> None:
  """Manual overlay reversal belongs to painter order, not title order."""
  graph = _build_overlay_dependency_graph(
    ("active", "red", "green"), (), ("red", "green"),
  )
  assert graph["active"] == ("red", "green")


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
  runner_ids: set[int] = set()
  runner_ids_lock = threading.Lock()

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
  original_prepare_display_layer = PipelineRunner.prepare_display_layer

  def record_runner(self, *args, **kwargs):
    with runner_ids_lock:
      runner_ids.add(id(self))
    return original_prepare_display_layer(self, *args, **kwargs)

  monkeypatch.setattr(PipelineRunner, "prepare_display_layer", record_runner)
  output_dir = tmp_path / "exports"
  assert batch_plot_command(
    str(project_path), "prepare-thread", str(output_dir),
    execution_options=ExecutionOptions(backend="thread", max_workers=2),
  ) == 0
  assert both_prepared.is_set()
  assert len(runner_ids) == 2
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
