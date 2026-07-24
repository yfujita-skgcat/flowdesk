from __future__ import annotations

import json

import pytest

from flowdesk_core.batch_plot_export import (
  BatchPlotExportError,
  batch_plot_export_spec_from_mapping,
  plan_batch_plot_export,
  run_batch_plot_export,
)
from flowdesk_core.models import BatchPlotExportSpec
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

  report = run_batch_plot_export(spec, _samples(), tmp_path, render)
  assert report.status == "success"
  assert len(report.items) == 2
  manifest = json.loads((tmp_path / "export.batch.json").read_text(encoding="utf-8"))
  assert manifest["status"] == "success"
  assert manifest["export_options"]["formats"] == ["svg"]
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
  assert spec.aspect_1_to_1 is True
  assert spec.layout_policy == "shared_ranges"
