from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  plan_batch_plot_export,
  run_batch_plot_export,
)
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_export import (
  prepare_plot_export,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_storage.project import load_project, save_project


def _samples() -> list[dict[str, str]]:
  return [
    {"id": "s1", "name": "Control", "path": "/tmp/control.fcs"},
    {"id": "s2", "name": "Control", "path": "/tmp/other.fcs"},
  ]


def test_batch_plan_is_deterministic_and_suffixes_duplicate_titles(tmp_path) -> None:
  spec = BatchPlotExportSpec(
    id="all-plots", name="All", formats=("svg",), collision_policy="suffix"
  )
  items = plan_batch_plot_export(
    spec, _samples(), tmp_path,
    annotations=[
      {"sample_id": "s1", "keyword": "sample_title", "value": "Same", "source": "workspace"},
      {"sample_id": "s2", "keyword": "sample_title", "value": "Same", "source": "workspace"},
    ],
  )
  assert [item.sample_id for item in items] == ["s1", "s2"]
  assert items[0].output_paths[0].endswith("Same_s1_main-view.svg")
  assert items[1].output_paths[0].endswith("Same_s2_main-view.svg")


def test_batch_plan_rejects_unknown_explicit_sample(tmp_path) -> None:
  spec = BatchPlotExportSpec(
    id="explicit", name="Explicit", target="explicit", sample_ids=("missing",)
  )
  with pytest.raises(BatchPlotExportError, match="unknown samples"):
    plan_batch_plot_export(spec, _samples(), tmp_path)


def test_batch_plan_prefixes_explicit_and_filename_wells(tmp_path) -> None:
  samples = [
    {"id": "s1", "name": "Control", "path": r"C:\results\plate_A01.fcs"},
    {"id": "s2", "name": "Treatment", "path": "/results/B02_sample.fcs"},
  ]
  explicit = plan_batch_plot_export(
    BatchPlotExportSpec(id="explicit", name="Explicit", target="explicit", sample_ids=("s1",)),
    samples, tmp_path,
  )
  assert explicit[0].output_paths[0].endswith("A1_Control_s1_main-view.png")
  assert explicit[0].well_ids == ("A1",)
  assert explicit[0].well_sources == ("filename_token",)

  inferred = plan_batch_plot_export(
    BatchPlotExportSpec(id="inferred", name="Inferred", target="explicit", sample_ids=("s2",)),
    samples, tmp_path,
  )
  assert inferred[0].output_paths[0].endswith("B2_Treatment_s2_main-view.png")


def test_batch_plan_uses_ordered_wells_for_multiple_sources(tmp_path) -> None:
  samples = [
    {"id": "s1", "name": "A", "path": "/results/A01.fcs"},
    {"id": "s2", "name": "B", "path": "/results/B02.fcs"},
  ]
  spec = BatchPlotExportSpec(id="overlay", name="Overlay", target="explicit", sample_ids=("s1",))
  items = plan_batch_plot_export(spec, samples, tmp_path, overlay_sample_ids={"s1": ("s2",)})
  assert items[0].output_paths[0].endswith("A1_B2_A_s1_main-view.png")
  assert items[0].source_sample_ids == ("s1", "s2")
  assert items[0].well_ids == ("A1", "B2")


def test_batch_plan_does_not_infer_ambiguous_well(tmp_path) -> None:
  sample = {"id": "s1", "name": "A1_B2", "path": "/results/A1_B2.fcs"}
  spec = BatchPlotExportSpec(
    id="ambiguous", name="Ambiguous", target="explicit", sample_ids=("s1",)
  )
  item = plan_batch_plot_export(spec, [sample], tmp_path)[0]
  assert item.well_ids == ()
  assert item.output_paths[0].endswith("A1_B2_s1_main-view.png")


def test_batch_run_writes_outputs_sidecars_and_manifest(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="export", name="Export", formats=("svg",))
  original_samples = [dict(sample) for sample in _samples()]

  def render(sample, path, _spec):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<svg>{sample['id']}</svg>", encoding="utf-8")

  preflight = {"value": {"mode": "full_vector", "status": "ok"}}
  report = run_batch_plot_export(spec, _samples(), tmp_path, render, preflight=preflight)
  assert report.status == "success"
  assert len(report.items) == 2
  manifest = json.loads((tmp_path / "export.batch.json").read_text(encoding="utf-8"))
  assert manifest["status"] == "success"
  assert manifest["export_options"]["formats"] == ["svg"]
  assert manifest["vector_scatter_preflight"]["mode"] == "full_vector"
  sidecar = tmp_path / "Control_s1_main-view.svg.json"
  sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
  assert sidecar_data["sample_id"] == "s1"
  assert sidecar_data["source_sample_ids"] == ["s1"]
  assert sidecar_data["export_options"]["plot_view_id"] == "main-view"
  assert _samples() == original_samples


def test_batch_run_reports_renderer_failure(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="export", name="Export", formats=("svg",))

  def render(_sample, _path, _spec):
    raise RuntimeError("renderer failure")

  report = run_batch_plot_export(spec, _samples(), tmp_path, render)
  assert report.status == "failed"
  assert all(item.status == "failed" for item in report.items)


def test_batch_run_prepares_once_and_reports_each_written_format(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="export", name="Export", formats=("svg", "png"))
  prepared: list[str] = []
  events = []

  def prepare() -> None:
    prepared.append("once")

  def render(sample, path, _spec) -> None:
    assert path.suffix in {".svg", ".png"}
    path.write_text(sample["id"], encoding="utf-8")

  report = run_batch_plot_export(
    spec,
    _samples(),
    tmp_path,
    render,
    prepare=prepare,
    execution_control=ExecutionControl(progress_sink=events.append),
  )

  assert report.status == "success"
  assert prepared == ["once"]
  rendering = [event for event in events if event.phase == "rendering"]
  assert [event.completed_units for event in rendering] == [1, 2, 3, 4]
  assert {event.total_units for event in events} == {4}
  assert (tmp_path / "Control_s1_main-view.svg").read_text(encoding="utf-8") == "s1"
  assert not list(tmp_path.glob(".*.flowdesk-*"))


def test_batch_run_thread_backend_keeps_plan_order_and_manifest(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="threaded", name="Threaded", formats=("svg",))
  control = ExecutionControl(options=ExecutionOptions(backend="thread", max_workers=2))

  def render(sample, path, _spec) -> None:
    path.write_text(sample["id"], encoding="utf-8")

  report = run_batch_plot_export(
    spec,
    _samples(),
    tmp_path,
    render,
    estimate_render_bytes=lambda: 128,
    execution_control=control,
  )

  assert report.status == "success"
  assert [item.sample_id for item in report.items] == ["s1", "s2"]
  assert [item.status for item in report.items] == ["success", "success"]
  assert report.execution_provenance is not None
  assert report.execution_provenance["backend"] == "thread"
  manifest = json.loads((tmp_path / "threaded.batch.json").read_text(encoding="utf-8"))
  assert manifest["execution"]["backend"] == "thread"
  assert not list(tmp_path.glob(".*.flowdesk-*"))


def test_batch_run_thread_backend_respects_memory_bound(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="bounded", name="Bounded", formats=("svg",))
  control = ExecutionControl(
    options=ExecutionOptions(
      backend="thread", max_workers=4, memory_budget_bytes=100,
    )
  )

  def render(sample, path, _spec) -> None:
    path.write_text(sample["id"], encoding="utf-8")

  report = run_batch_plot_export(
    spec, _samples(), tmp_path, render,
    estimate_render_bytes=lambda: 100,
    execution_control=control,
  )

  assert report.status == "success"
  assert report.execution_provenance is not None
  assert report.execution_provenance["effective_max_workers"] == 1
  assert "memory_budget" in report.execution_provenance["limiting_factors"]


def test_batch_run_thread_backend_preserves_real_writer_bytes(tmp_path) -> None:
  spec = BatchPlotExportSpec(
    id="writer-parity",
    name="Writer parity",
    formats=("png", "svg", "pdf"),
    width=160,
    height=120,
    vector_scatter_mode="full_vector",
  )
  samples = [
    {"id": "s1", "name": "One", "path": "/tmp/one.fcs"},
    {"id": "s2", "name": "Two", "path": "/tmp/two.fcs"},
    {"id": "s3", "name": "Three", "path": "/tmp/three.fcs"},
  ]
  prepared = {
    sample["id"]: prepare_plot_export(
      "main-view",
      "scatter",
      ({
        "source_id": sample["id"],
        "sample_id": sample["id"],
        "population_id": "all_events",
        "display_name": sample["name"],
        "visible": True,
      },),
      (OverlaySourceResolution(sample["id"], "compatible"),),
    )
    for sample in samples
  }
  layers = {
    sample["id"]: {
      sample["id"]: ((0.1, 0.4, 0.8), (0.2, 0.6, 0.9)),
    }
    for sample in samples
  }

  def render(sample, path, options) -> None:
    sample_id = sample["id"]
    path_suffix = path.suffix.lower()
    kwargs = {
      "path": path,
      "prepared": prepared[sample_id],
      "layers": layers[sample_id],
      "options": options,
    }
    if path_suffix == ".png":
      write_plot_png(**kwargs, width=options.width, height=options.height)
    elif path_suffix == ".svg":
      write_plot_svg(**kwargs)
    elif path_suffix == ".pdf":
      write_plot_pdf(**kwargs, width=options.width, height=options.height)
    else:
      raise AssertionError(path_suffix)

  sequential_dir = tmp_path / "sequential"
  threaded_dir = tmp_path / "threaded"
  sequential = run_batch_plot_export(spec, samples, sequential_dir, render)
  threaded = run_batch_plot_export(
    spec,
    samples,
    threaded_dir,
    render,
    estimate_render_bytes=lambda: 4096,
    execution_control=ExecutionControl(
      options=ExecutionOptions(backend="thread", max_workers=3),
    ),
  )

  assert sequential.status == threaded.status == "success"
  assert [item.sample_id for item in sequential.items] == [
    item.sample_id for item in threaded.items
  ]
  for sample in samples:
    for extension in spec.formats:
      sequential_path = next(sequential_dir.glob(f"*_{sample['id']}_*.{extension}"))
      threaded_path = next(threaded_dir.glob(f"*_{sample['id']}_*.{extension}"))
      assert sequential_path.read_bytes() == threaded_path.read_bytes()
      sequential_sidecar = json.loads(
        sequential_path.with_suffix(sequential_path.suffix + ".json").read_text()
      )
      threaded_sidecar = json.loads(
        threaded_path.with_suffix(threaded_path.suffix + ".json").read_text()
      )
      sequential_sidecar.pop("output", None)
      threaded_sidecar.pop("output", None)
      assert sequential_sidecar == threaded_sidecar


def test_batch_run_cancellation_keeps_completed_files_and_manifest(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="export", name="Export", formats=("svg",))
  control = ExecutionControl()
  rendered: list[Path] = []

  def render(sample, path, _spec) -> None:
    path.write_text(sample["id"], encoding="utf-8")
    rendered.append(path)
    control.cancellation_token.cancel()

  report = run_batch_plot_export(
    spec, _samples(), tmp_path, render, execution_control=control
  )

  assert report.status == "partial_cancelled"
  assert [item.status for item in report.items] == ["success", "not_started"]
  assert len(rendered) == 1
  assert Path(report.items[0].output_paths[0]).exists()
  manifest = json.loads((tmp_path / "export.batch.json").read_text(encoding="utf-8"))
  assert manifest["status"] == "partial_cancelled"
  assert [item["status"] for item in manifest["items"]] == ["success", "not_started"]


def test_batch_run_discards_failed_staged_output(tmp_path) -> None:
  spec = BatchPlotExportSpec(id="export", name="Export", formats=("svg",))

  def render(_sample, path, _spec) -> None:
    path.write_text("partial", encoding="utf-8")
    raise RuntimeError("after write")

  report = run_batch_plot_export(spec, _samples(), tmp_path, render)

  assert report.status == "failed"
  assert not list(tmp_path.glob("*.svg"))
  assert not list(tmp_path.glob(".*.flowdesk-*"))


def test_batch_definition_project_round_trip(tmp_path) -> None:
  manifest = {
    "project_id": "batch-project",
    "project_version": "0.1",
    "pipeline_version": "0.1",
    "samples": [],
    "batch_plot_exports": [{
      "id": "export",
      "name": "Export",
      "target": "all",
      "plot_view_id": "main-view",
      "formats": ["svg"],
    }],
  }
  path = tmp_path / "project.flowdesk"
  save_project(path, manifest)
  assert load_project(path)["batch_plot_exports"][0]["id"] == "export"


def test_batch_spec_mapping_normalizes_json_lists() -> None:
  spec = batch_plot_export_spec_from_mapping({
    "id": "e", "name": "E", "formats": ["jpg"], "sample_ids": ["s1"],
    "target": "explicit", "dpi": 144, "aspect_1_to_1": True,
    "layout_policy": "shared_ranges",
  })
  assert spec.formats == ("jpg",)
  assert spec.sample_ids == ("s1",)
  assert spec.dpi == 144
  assert spec.vector_scatter_mode == "full_vector"
  assert spec.hybrid_scatter_dpi == 600
  assert spec.raster_resolution_mode == "legacy_pixel_dimensions"
  assert spec.aspect_1_to_1 is True
  assert spec.layout_policy == "shared_ranges"
