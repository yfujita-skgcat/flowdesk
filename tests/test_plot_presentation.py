from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from flowdesk_core.models import (
  ChannelSpec,
  FontSpec,
  OverlaySourceSpec,
  PlotPresentationSpec,
  PlotViewSpec,
  SourceStyleSpec,
)
from flowdesk_core.plot_presentation import (
  PresentationValidationError,
  SamplePresentationContext,
  resolve_overlay_sources,
  validate_presentation,
)
from flowdesk_storage.manifest import validate_manifest
from flowdesk_storage.migrations import migrate_manifest_with_report


def _context(sample_id: str, channels: tuple[ChannelSpec, ...]) -> SamplePresentationContext:
  return SamplePresentationContext(
    sample_id=sample_id,
    channels=channels,
    population_ids=("all_events", "cd3"),
    transform_ids=("linear-cd3",),
    analysis_revision="r1",
  )


def test_cross_sample_sources_keep_order_and_resolve_stable_channel_identity() -> None:
  source_a = OverlaySourceSpec(
    source_id="source-a", sample_id="s1", population_id="cd3",
    display_name="A", x_parameter_id="cd3", x_transform_id="linear-cd3",
    unit="a.u.", order=0,
  )
  source_b = OverlaySourceSpec(
    source_id="source-b", sample_id="s2", population_id="cd3",
    display_name="B", x_parameter_id="cd3", x_transform_id="linear-cd3",
    unit="a.u.", order=1,
  )
  spec = PlotViewSpec(
    id="view", population_id="all_events", x_parameter="cd3",
    plot_type="histogram", overlay_sources=(source_b, source_a),
  )
  result = resolve_overlay_sources(
    spec.overlay_sources,
    {
      "s1": _context("s1", (ChannelSpec("fsc", "FSC"), ChannelSpec("cd3", "CD3", unit="a.u."))),
      "s2": _context("s2", (ChannelSpec("cd3", "CD3", unit="a.u."), ChannelSpec("fsc", "FSC"))),
    },
  )

  assert [item.source_id for item in result] == ["source-a", "source-b"]
  assert all(item.status == "compatible" for item in result)
  assert [item.x_index for item in result] == [1, 0]


@pytest.mark.parametrize("state", ("missing", "ambiguous", "incompatible"))
def test_invalid_source_is_diagnosed_without_fallback(state: str) -> None:
  if state == "missing":
    channels = (ChannelSpec("fsc", "FSC"),)
    source_parameter = "cd3"
  elif state == "ambiguous":
    channels = (ChannelSpec("cd3-a", "CD3"), ChannelSpec("cd3-b", "CD3"))
    source_parameter = "CD3"
  else:
    channels = (ChannelSpec("cd3", "CD3", unit="volts"),)
    source_parameter = "cd3"
  source = OverlaySourceSpec(
    source_id="source", sample_id="s1", population_id="cd3",
    display_name="source", x_parameter_id=source_parameter,
    x_transform_id="linear-cd3", unit="a.u.", order=0,
  )

  item = resolve_overlay_sources(
    (source,), {"s1": _context("s1", channels)},
  )[0]

  assert item.status == state
  assert item.x_index is None
  assert item.diagnostics
  assert item.diagnostics[0].code.startswith(f"overlay_{state}")


def test_presentation_labels_are_independent_from_analysis_identity() -> None:
  view = PlotViewSpec(
    id="view", population_id="all_events", x_parameter="cd3",
    x_transform_id="linear-cd3", plot_type="histogram",
    presentation=PlotPresentationSpec(
      title="CD3 comparison", x_axis_display_label="Publication CD3",
      source_styles=(SourceStyleSpec(source_id="s", legend_label="Sample A"),),
      title_font=FontSpec(family="DejaVu Sans", size=12),
    ),
  )
  assert view.x_parameter == "cd3"
  assert view.x_transform_id == "linear-cd3"
  assert view.presentation is not None
  assert view.presentation.x_axis_display_label == "Publication CD3"


def test_unsupported_style_is_rejected_by_shared_validator() -> None:
  presentation = PlotPresentationSpec(
    source_styles=(SourceStyleSpec(source_id="s", marker_shape="circle"),),
  )
  with pytest.raises(PresentationValidationError, match="marker_shape"):
    validate_presentation("histogram", presentation)


def test_typed_plot_definition_round_trips_as_json_and_legacy_migration_is_explicit() -> None:
  view = PlotViewSpec(
    id="view", population_id="all_events", x_parameter="cd3",
    plot_type="histogram", overlay_sources=(OverlaySourceSpec(
      source_id="source", sample_id="s1", population_id="cd3",
      display_name="Sample", x_parameter_id="cd3", order=0,
    ),),
    presentation=PlotPresentationSpec(title="CD3"),
  )
  encoded = json.loads(json.dumps(asdict(view)))
  assert encoded["overlay_sources"][0]["sample_id"] == "s1"
  assert encoded["presentation"]["title"] == "CD3"

  legacy = {
    "project_id": "p", "project_version": "1.5.0", "pipeline_version": "1",
    "samples": [], "overlays": [{"id": "legacy", "population_ids": ["cd3"], "parameter": "CD3"}],
  }
  report = migrate_manifest_with_report(legacy)
  assert report.migrated["overlays"][0].get("sources") is None
  assert any(
    item["code"] == "legacy_overlay_source_identity_unknown"
    for item in report.diagnostics
  )


def test_manifest_validates_explicit_sources() -> None:
  data = {
    "project_id": "p", "project_version": "1.6.0", "pipeline_version": "1",
    "samples": [{"id": "s1", "channels": []}], "plot_views": [{
      "id": "view", "overlay_sources": [{
        "source_id": "source", "sample_id": "s1", "population_id": "cd3",
        "display_name": "CD3", "x_parameter_id": "cd3", "order": 0,
      }],
    }],
  }
  validate_manifest(data)
