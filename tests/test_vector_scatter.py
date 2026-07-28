import pytest

from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_export import resolve_export_canvas
from flowdesk_core.vector_scatter import (
  VectorScatterLayer,
  build_vector_scatter_plan,
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
