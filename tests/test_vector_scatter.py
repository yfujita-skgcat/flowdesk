import pytest

from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_export import (
  prepare_plot_export,
  prepare_vector_render_cache,
  resolve_export_canvas,
  write_plot_pdf,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution
from flowdesk_core.vector_scatter import (
  COMPACT_VECTOR_CHUNK_POINTS,
  VectorScatterLayer,
  build_vector_scatter_plan,
  compact_scatter_batches,
  preflight_vector_scatter_export,
)
from flowdesk_core.vector_scatter_benchmark import (
  ScatterBenchmarkMeasurement,
  deterministic_scatter_fixture,
  release_acceptance_invariants,
  run_scatter_benchmark,
)


def _canvas():
  return resolve_export_canvas(BatchPlotExportSpec(id="e", name="E"))


def test_new_definition_uses_hybrid_default_and_parser_preserves_old_full_vector():
  assert BatchPlotExportSpec(id="new", name="New").vector_scatter_mode == "hybrid_raster"
  old = BatchPlotExportSpec(id="old", name="Old")
  from flowdesk_core.batch_plot_export import batch_plot_export_spec_from_mapping

  parsed = batch_plot_export_spec_from_mapping({"id": old.id, "name": old.name})
  assert parsed.vector_scatter_mode == "full_vector"
  assert parsed.hybrid_scatter_dpi == 600


def test_plan_hash_and_provenance_are_deterministic():
  layer = VectorScatterLayer("sample", ((1.0, 2.0), (3.0, 4.0)), color="#123456")
  plan = build_vector_scatter_plan(
    mode="hybrid_raster",
    logical_canvas=_canvas(),
    clip_rect=(10.0, 20.0, 100.0, 80.0),
    layers=(layer,),
    sampling_identity="sample:s1:display:v2",
    input_event_count=2,
  )
  assert plan.plan_hash() == plan.plan_hash()
  provenance = plan.provenance_mapping()
  assert provenance["rendered_event_count"] == 2
  assert provenance["scatter_image_dpi"] == 600
  assert provenance["point_plan_hash"] == plan.plan_hash()

  changed = build_vector_scatter_plan(
    mode="hybrid_raster",
    logical_canvas=_canvas(),
    clip_rect=(10.0, 20.0, 100.0, 80.0),
    layers=(VectorScatterLayer("sample", ((1.0, 2.0), (3.1, 4.0)), color="#123456"),),
    sampling_identity="sample:s1:display:v2",
    input_event_count=2,
  )
  assert changed.plan_hash() != plan.plan_hash()


def test_plan_rejects_nonfinite_points_and_invalid_hybrid_dpi():
  with pytest.raises(ValueError, match="finite"):
    VectorScatterLayer("sample", ((float("nan"), 1.0),))
  with pytest.raises(ValueError, match="hybrid_raster"):
    build_vector_scatter_plan(
      mode="hybrid_raster",
      logical_canvas=_canvas(),
      clip_rect=(0.0, 0.0, 10.0, 10.0),
      layers=(),
      sampling_identity="s1",
      hybrid_scatter_dpi=10,
    )


def test_non_hybrid_plan_does_not_record_raster_dpi():
  plan = build_vector_scatter_plan(
    mode="full_vector",
    logical_canvas=_canvas(),
    clip_rect=(0.0, 0.0, 10.0, 10.0),
    layers=(),
    sampling_identity="s1",
  )
  assert plan.provenance_mapping()["scatter_image_dpi"] is None


def test_preflight_reports_hybrid_raster_dimensions_and_never_changes_mode():
  spec = BatchPlotExportSpec(
    id="h", name="H", vector_scatter_mode="hybrid_raster", hybrid_scatter_dpi=600
  )
  report = preflight_vector_scatter_export(
    spec, rendered_event_count=100, logical_plot_width=720, logical_plot_height=490
  )
  assert report.status == "ok"
  assert report.mode == "hybrid_raster"
  assert report.raster_width == 4500
  assert report.raster_height == 3062


def test_hybrid_scatter_cache_is_reused_across_svg_and_pdf(tmp_path, monkeypatch):
  import flowdesk_core.plot_export as plot_export

  prepared = prepare_plot_export(
    "view",
    "scatter",
    ({
      "source_id": "s1",
      "sample_id": "s1",
      "population_id": "all_events",
      "display_name": "Sample",
      "visible": True,
    },),
    (OverlaySourceResolution("s1", "compatible"),),
  )
  layers = {"s1": ((0.1, 0.5, 0.9), (0.2, 0.6, 0.8))}
  spec = BatchPlotExportSpec(
    id="hybrid-cache",
    name="Hybrid cache",
    formats=("svg", "pdf"),
    width=160,
    height=120,
    vector_scatter_mode="hybrid_raster",
    hybrid_scatter_dpi=120,
  )
  calls = 0
  original = plot_export._hybrid_scatter_raster

  def counted(*args, **kwargs):
    nonlocal calls
    calls += 1
    return original(*args, **kwargs)

  monkeypatch.setattr(plot_export, "_hybrid_scatter_raster", counted)
  cache = prepare_vector_render_cache(
    prepared,
    prepared.resolved_presentation.presentation,
    layers,
    options=spec,
  )
  write_plot_svg(
    tmp_path / "plot.svg", prepared, layers=layers, options=spec,
    render_cache=cache,
  )
  write_plot_pdf(
    tmp_path / "plot.pdf", prepared, layers=layers, options=spec,
    width=spec.width, height=spec.height, render_cache=cache,
  )
  assert calls == 1
  assert (tmp_path / "plot.svg").stat().st_size > 0
  assert (tmp_path / "plot.pdf").stat().st_size > 0


def test_preflight_returns_structured_failure_without_auto_fallback():
  spec = BatchPlotExportSpec(id="f", name="F", vector_scatter_mode="full_vector")
  report = preflight_vector_scatter_export(
    spec, rendered_event_count=11, logical_plot_width=720, logical_plot_height=490,
    max_events=10,
  )
  assert report.status == "failed"
  assert report.mode == "full_vector"
  assert report.diagnostics[0]["code"] == "scatter_events_exceeded"


def test_compact_batches_are_chunked_at_the_documented_limit():
  points = tuple((index / 10000, 0.5) for index in range(COMPACT_VECTOR_CHUNK_POINTS + 7))
  batches = compact_scatter_batches(
    (VectorScatterLayer("s", points),), plot_width=720, plot_height=490
  )
  assert max(len(batch.points) for batch in batches) <= COMPACT_VECTOR_CHUNK_POINTS
  assert sum(len(batch.points) for batch in batches) == len(points)


def test_benchmark_fixture_and_small_baseline_are_deterministic():
  first, first_hash = deterministic_scatter_fixture(1000, profile="mixed")
  second, second_hash = deterministic_scatter_fixture(1000, profile="mixed")
  assert first == second
  assert first_hash == second_hash
  result = run_scatter_benchmark((1000,), profile="sparse", hybrid_scatter_dpi=72)
  measurements = [
    item for values in result["measurements"].values() for item in values
  ]
  assert {item["mode"] for item in measurements} == {
    "full_vector", "compact_vector", "hybrid_raster"
  }
  invariant_inputs = [ScatterBenchmarkMeasurement(**item) for item in measurements]
  assert release_acceptance_invariants(invariant_inputs)["status"] == "ok"
  assert all(item["rendered_event_count"] == 1000 for item in measurements)
