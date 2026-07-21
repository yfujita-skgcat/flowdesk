from __future__ import annotations

import json

import pytest

from flowdesk_core.models import PlotPresentationSpec, PlotViewRegistry, PlotViewSpec
from flowdesk_core.plot_export import (
  PlotExportError,
  prepare_plot_export,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import (
  OverlaySourceResolution,
  resolve_presentation_layers,
)
from flowdesk_core.plot_reuse import (
  LayoutPlotReference,
  TemplateSourceRole,
  map_template_sources,
)
from flowdesk_storage.project import load_project, save_project


def test_presentation_precedence_and_source_provenance() -> None:
  resolved = resolve_presentation_layers(
    {"title": "view", "source_styles": [{"source_id": "s1", "color": "#ff0000"}]},
    {"title": "project", "background_color": "#eeeeee"},
    {"title": "global", "background_color": "#dddddd"},
    source_ids=("s1", "s2"),
  )

  assert resolved.presentation.title == "view"
  assert resolved.presentation.background_color == "#eeeeee"
  assert resolved.presentation.source_styles[0].color == "#ff0000"
  assert resolved.provenance["title"] == "view_override"
  assert resolved.provenance["background_color"] == "project_display_default"
  assert resolved.provenance["source:s1:color"] == "view_override"


def test_export_rejects_visible_missing_source_and_preserves_hidden_diagnostic() -> None:
  sources = (
    {
      "source_id": "ok", "sample_id": "s1", "population_id": "p",
      "display_name": "OK", "visible": True,
    },
    {
      "source_id": "missing", "sample_id": "s2", "population_id": "p",
      "display_name": "Missing", "visible": False,
    },
  )
  resolutions = (
    OverlaySourceResolution("ok", "compatible", 0),
    OverlaySourceResolution("missing", "missing"),
  )
  prepared = prepare_plot_export("view", "histogram", sources, resolutions)
  assert prepared.source_order == ("ok",)
  assert prepared.metadata["ordered_source_ids"] == ["ok"]
  assert prepared.metadata["diagnostics"][0]["source_id"] == "missing"

  with pytest.raises(PlotExportError, match="missing"):
    prepare_plot_export(
      "view", "histogram",
      [{**sources[1], "visible": True}],
      resolutions[1:],
    )


def test_svg_export_contains_title_labels_legend_and_metadata(tmp_path) -> None:
  sources = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  resolutions = (OverlaySourceResolution("s1", "compatible", 0),)
  prepared = prepare_plot_export("view", "histogram", sources, resolutions)
  presentation = PlotPresentationSpec(
    title="CD3 overlay", x_axis_display_label="CD3", legend_source_ids=("s1",)
  )
  path = tmp_path / "plot.svg"
  write_plot_svg(path, prepared, presentation, {"s1": ((1.0, 2.0), (2.0, 3.0))})

  text = path.read_text(encoding="utf-8")
  assert "CD3 overlay" in text
  assert "Control" in text
  assert "CD3" in text
  metadata = json.loads(path.with_suffix(".svg.json").read_text(encoding="utf-8"))
  assert metadata["ordered_source_ids"] == ["s1"]
  assert metadata["scientific_note"]


def test_png_export_is_nonblank_and_has_metadata(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "plot.png"
  write_plot_png(path, prepared, layers={"s1": ((0.2, 0.8), (0.2, 0.8))})
  assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
  assert path.stat().st_size > 100


def test_layout_reference_and_template_mapping_are_explicit() -> None:
  reference = LayoutPlotReference("layout-plot", "view", "reference")
  copied = LayoutPlotReference("layout-copy", "view", "copy")
  assert reference.to_mapping()["mode"] == "reference"
  assert copied.to_mapping()["copied_from"] == "view"

  role = TemplateSourceRole(
    source_role="control", population_path="Cells/CD3", parameter_role="cd3"
  )
  mapped = map_template_sources(
    (role,),
    ({
      "sample_id": "s1", "source_role": "control",
      "population_path": "Cells/CD3", "parameter_id": "cd3",
    },),
  )
  assert mapped[0].status == "exact"
  assert mapped[0].sample_id == "s1"


def test_template_mapping_does_not_silently_choose_ambiguous_source() -> None:
  role = TemplateSourceRole("control", "Cells/CD3", "cd3")
  mapped = map_template_sources(
    (role,),
    (
      {
        "sample_id": "s1", "source_role": "control",
        "population_path": "Cells/CD3", "parameter_id": "cd3",
      },
      {
        "sample_id": "s2", "source_role": "control",
        "population_path": "Cells/CD3", "parameter_id": "cd3",
      },
    ),
  )
  assert mapped[0].status == "ambiguous"
  assert mapped[0].sample_id is None


def test_plot_view_duplicate_and_project_round_trip_preserve_definition(tmp_path) -> None:
  source = {
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "x_parameter_id": "cd3", "order": 0,
    "visible": True,
  }
  presentation = {
    "title": "CD3", "x_axis_display_label": "CD3-A",
    "source_styles": [{"source_id": "s1", "color": "#ff0000"}],
  }
  manifest = {
    "project_id": "plot-round-trip", "project_version": "0.1",
    "pipeline_version": "0.1", "samples": [],
    "plot_views": [{
      "id": "view", "overlay_sources": [source],
      "presentation": presentation,
    }],
  }
  bundle = tmp_path / "project.flowdesk"
  save_project(bundle, manifest)
  reloaded = load_project(bundle)
  assert reloaded["plot_views"][0]["overlay_sources"] == [source]
  assert reloaded["plot_views"][0]["presentation"] == presentation

  typed = PlotViewSpec(
    id="view", x_parameter="cd3", y_parameter="cd4",
    overlay_sources=(), presentation=PlotPresentationSpec(title="CD3"),
  )
  duplicate = PlotViewRegistry((typed,)).duplicate("view", "view-copy")
  assert duplicate.views[1].presentation == typed.presentation
