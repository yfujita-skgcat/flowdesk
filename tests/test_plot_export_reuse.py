from __future__ import annotations

import json

import pytest

from flowdesk_core.models import (
  BatchPlotExportSpec,
  PlotPresentationSpec,
  SourceStyleSpec,
  PlotViewRegistry,
  PlotViewSpec,
)
from flowdesk_core.plot_export import (
  PlotExportError,
  _display_tick_label,
  prepare_plot_export,
  resolve_export_canvas,
  write_plot_jpg,
  write_plot_pdf,
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
from flowdesk_core.plot_scene import PlotScene
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


def test_full_vector_svg_reuses_markers_and_places_each_event_once(tmp_path) -> None:
  sources = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", sources, (OverlaySourceResolution("s1", "compatible"),)
  )
  presentation = PlotPresentationSpec(
    source_styles=(
      SourceStyleSpec(
        source_id="s1", color="#ff0000", alpha=0.4, marker_shape="square"
      ),
    )
  )
  options = BatchPlotExportSpec(
    id="full", name="Full", formats=("svg",), vector_scatter_mode="full_vector"
  )
  path = tmp_path / "full.svg"
  write_plot_svg(
    path, prepared, presentation, {"s1": ((0.1, 0.2, 0.3), (0.2, 0.3, 0.4))},
    options=options,
  )
  text = path.read_text(encoding="utf-8")
  assert text.count('id="scatter-marker-0"') == 1
  assert text.count("<use ") == 3
  assert 'clip-path="url(#plot-clip)"' in text
  assert 'fill-opacity="0.4"' in text


def test_full_vector_pdf_uses_form_xobject_and_one_do_per_event(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  options = BatchPlotExportSpec(
    id="full", name="Full", formats=("pdf",), vector_scatter_mode="full_vector"
  )
  path = tmp_path / "full.pdf"
  write_plot_pdf(
    path, prepared, layers={"s1": ((0.1, 0.2), (0.2, 0.3))}, options=options
  )
  data = path.read_bytes()
  assert data.count(b"/Subtype /Form") == 1
  assert data.count(b"/M0 Do") == 2
  assert b"/XObject << /M0 5 0 R >>" in data
  assert b"/Subtype /Image" not in data


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


def test_dpi_scaled_png_preserves_logical_canvas_and_increases_pixels(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all_events",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  options = BatchPlotExportSpec(
    id="export", name="Export", width=800, height=600, dpi=300,
    raster_resolution_mode="dpi_scaled",
  )
  canvas = resolve_export_canvas(options)
  assert canvas.raster_width == 2500
  assert canvas.raster_height == 1875
  path = tmp_path / "scaled.png"
  write_plot_png(path, prepared, layers={"s1": ((0.2,), (0.8,))}, options=options)
  from PIL import Image

  with Image.open(path) as image:
    assert image.size == (2500, 1875)
    assert image.info["dpi"] == pytest.approx((300, 300), abs=0.5)
  metadata = json.loads(path.with_suffix(".png.json").read_text(encoding="utf-8"))
  assert metadata["export_canvas"]["raster_resolution_mode"] == "dpi_scaled"


def test_legacy_png_dimensions_ignore_dpi_for_compatibility(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all_events",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  options = BatchPlotExportSpec(
    id="export", name="Export", width=800, height=600, dpi=300,
    raster_resolution_mode="legacy_pixel_dimensions",
  )
  path = tmp_path / "legacy.png"
  write_plot_png(path, prepared, layers={"s1": ((0.2,), (0.8,))}, options=options)
  from PIL import Image

  with Image.open(path) as image:
    assert image.size == (800, 600)


def test_png_export_scene_preserves_colored_titles_and_labeled_ticks(tmp_path) -> None:
  source = (
    {
      "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
      "display_name": "Control", "visible": True,
    },
    {
      "source_id": "s2", "sample_id": "sample-2", "population_id": "cd3",
      "display_name": "Treated", "visible": True,
    },
  )
  prepared = prepare_plot_export(
    "view", "scatter", source,
    (OverlaySourceResolution("s1", "compatible"), OverlaySourceResolution("s2", "compatible")),
    view_presentation={
      "x_axis_display_label": "FITC B525-A",
      "y_axis_display_label": "APC R660-A",
      "source_styles": [
        {"source_id": "s1", "color": "#4c78a8", "alpha": 0.75, "marker_size": 3},
        {"source_id": "s2", "color": "#f8e45c", "alpha": 0.65, "marker_size": 3},
      ],
    },
    scene={
      "x_ticks": [{"position": 0.5, "label": "1e3", "major": True}],
      "y_ticks": [{"position": 0.5, "label": "1e2", "major": True}],
    },
  )
  path = tmp_path / "scene.png"
  write_plot_png(
    path, prepared,
    layers={"s1": ((0.2,), (0.2,)), "s2": ((0.8,), (0.8,))},
  )

  metadata = json.loads(path.with_suffix(".png.json").read_text(encoding="utf-8"))
  assert metadata["scene"]["title_lines"] == ["Control", "Treated"]
  assert metadata["scene"]["title_colors"] == ["#4c78a8", "#f8e45c"]
  assert metadata["scene"]["x_ticks"][0]["label"] == "1e3"
  assert path.stat().st_size > 1_000


def test_export_tick_labels_use_gui_superscript_notation() -> None:
  assert _display_tick_label("1e3") == "10³"
  assert _display_tick_label("1.0e3") == "10³"
  assert _display_tick_label("2e3") == "2 × 10³"
  assert _display_tick_label("-1e-2") == "-1 × 10⁻²"


def test_export_options_control_svg_elements_and_aspect(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "plot.svg"
  options = BatchPlotExportSpec(
    id="export", name="Export", width=900, height=600, aspect_1_to_1=True,
    include_title=False, include_axis_labels=False, include_legend=False,
  )
  write_plot_svg(path, prepared, layers={"s1": ((0.2,), (0.8,))}, options=options)
  text = path.read_text(encoding="utf-8")
  assert 'width="600" height="600"' in text
  assert "Control" not in text


def test_export_scene_uses_same_plot_area_for_axes_and_gate(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
    gate_overlays=({
      "id": "gate-1", "points": ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)),
      "color": "#ff0000",
    },),
  )
  path = tmp_path / "plot.svg"
  write_plot_svg(path, prepared, layers={"s1": ((0.2,), (0.8,))})
  text = path.read_text(encoding="utf-8")
  assert 'stroke="#ff0000"' in text
  assert 'stroke="#808080"' in text
  assert prepared.metadata["plot_area"] == {"left": 60, "top": 50, "right": 20, "bottom": 60}


def test_plot_scene_round_trip_is_renderer_neutral_and_excludes_analysis_data() -> None:
  scene = PlotScene.from_mapping({
    "x_parameter": "x",
    "y_parameter": "y",
    "x_transform_id": "log-x",
    "y_transform_id": "log-y",
    "view_range": [[1.0, 4.0], [2.0, 8.0]],
    "source_order": ["s1", "s2"],
    "x_ticks": [{"position": 0.5, "label": "1e2", "major": True}],
    "title_lines": ["Control", "Treated"],
    "gates": [{"id": "gate-1", "points": [[0.1, 0.2], [0.8, 0.9]]}],
  })
  restored = PlotScene.from_mapping(scene.to_mapping())
  assert restored == scene
  assert len(scene.scene_hash()) == 64
  assert "events" not in scene.to_mapping()
  assert "membership" not in scene.to_mapping()


def test_gui_and_headless_adapters_consume_the_same_scene(tmp_path) -> None:
  sources = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  scene = {
    "x_parameter": "FITC B525-A", "y_parameter": "APC R660-A",
    "x_transform_id": "log-x", "y_transform_id": "log-y",
    "view_range": [[1.0, 5.0], [2.0, 6.0]],
    "x_ticks": [{"position": 0.25, "label": "1e2", "major": True}],
    "y_ticks": [{"position": 0.75, "label": "1e3", "major": True}],
    "title_lines": ["Control"], "title_colors": ["#4c78a8"],
    "source_order": ["s1"],
    "gates": [{"id": "gate-1", "points": [[0.2, 0.2], [0.8, 0.8]], "color": "#ffd400"}],
  }
  prepared = prepare_plot_export(
    "view", "scatter", sources, (OverlaySourceResolution("s1", "compatible"),),
    scene=scene,
  )
  assert prepared.scene.to_mapping() == PlotScene.from_mapping(scene).to_mapping()
  png = tmp_path / "scene.png"
  svg = tmp_path / "scene.svg"
  layers = {"s1": ((0.25, 0.75), (0.25, 0.75))}
  write_plot_png(png, prepared, layers=layers)
  write_plot_svg(svg, prepared, layers=layers)
  png_metadata = json.loads(png.with_suffix(".png.json").read_text(encoding="utf-8"))
  svg_metadata = json.loads(svg.with_suffix(".svg.json").read_text(encoding="utf-8"))
  assert png_metadata["scene"] == svg_metadata["scene"] == prepared.scene.to_mapping()
  assert png_metadata["scene_hash"] == svg_metadata["scene_hash"] == prepared.scene.scene_hash()
  assert "#ffd400" in svg.read_text(encoding="utf-8")
  assert png.stat().st_size > 1_000


def test_pdf_export_is_nonblank_and_has_metadata(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "plot.pdf"
  write_plot_pdf(path, prepared, layers={"s1": ((0.2,), (0.8,))})
  assert path.read_bytes().startswith(b"%PDF-1.4")
  assert path.stat().st_size > 100
  assert b"/Subtype /Image" not in path.read_bytes()


def test_vector_canvas_ignores_raster_dpi(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all_events",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  options = BatchPlotExportSpec(
    id="export", name="Export", width=800, height=600, dpi=300,
    raster_resolution_mode="dpi_scaled",
  )
  path = tmp_path / "vector.pdf"
  write_plot_pdf(path, prepared, layers={"s1": ((0.2,), (0.8,))}, options=options)
  metadata = json.loads(path.with_suffix(".pdf.json").read_text(encoding="utf-8"))
  assert metadata["export_canvas"]["raster_width"] == 2500
  assert metadata["export_canvas"]["logical_width"] == 800
  assert b"/Subtype /Image" not in path.read_bytes()


def test_jpeg_export_is_nonblank_and_has_metadata(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "cd3",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "plot.jpg"
  write_plot_jpg(
    path, prepared, layers={"s1": ((0.2, 0.8), (0.2, 0.8))},
    options=BatchPlotExportSpec(id="export", name="Export", dpi=144),
  )
  assert path.read_bytes().startswith(b"\xff\xd8\xff")
  metadata = json.loads(path.with_suffix(".jpg.json").read_text(encoding="utf-8"))
  assert metadata["export_options"]["dpi"] == 144


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
