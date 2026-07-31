from __future__ import annotations

import base64
import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

from flowdesk_core.models import (
  BatchPlotExportSpec,
  PlotPresentationSpec,
  SourceStyleSpec,
  PlotViewRegistry,
  PlotViewSpec,
)
from flowdesk_core.plot_export import (
  PlotExportError,
  _font,
  _hybrid_scatter_raster,
  _display_tick_label,
  _vertical_text_image,
  prepare_plot_export,
  prepare_vector_render_cache,
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
from flowdesk_core.vector_scatter import VectorScatterLayer, compact_scatter_batches
from flowdesk_storage.project import load_project, save_project


def test_vertical_axis_label_keeps_the_complete_pillow_glyph_bbox() -> None:
  font = _font(96, bold=True)
  source = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
  bbox = ImageDraw.Draw(source).textbbox((0, 0), "SSC-A", font=font)
  source = Image.new("RGBA", (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8))
  ImageDraw.Draw(source).text((4 - bbox[0], 4 - bbox[1]), "SSC-A", font=font, fill="black")
  source_alpha_bbox = source.getchannel("A").getbbox()
  assert source_alpha_bbox is not None
  rendered = _vertical_text_image("SSC-A", font, (0, 0, 0, 255))
  alpha_bbox = rendered.getchannel("A").getbbox()
  assert alpha_bbox is not None
  # Rotation swaps the glyph's original width and height.  A positive bbox
  # top must not remove a strip from the rendered text image.
  assert alpha_bbox[2] - alpha_bbox[0] >= source_alpha_bbox[3] - source_alpha_bbox[1] - 1
  assert alpha_bbox[3] - alpha_bbox[1] >= source_alpha_bbox[2] - source_alpha_bbox[0] - 1


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
  presentation = PlotPresentationSpec(
    source_styles=(SourceStyleSpec(source_id="s1", color="#000000", alpha=0.4),),
  )
  path = tmp_path / "full.pdf"
  write_plot_pdf(
    path, prepared, presentation, {"s1": ((0.1, 0.2), (0.2, 0.3))}, options=options
  )
  data = path.read_bytes()
  assert data.count(b"/Subtype /Form") == 1
  assert data.count(b"/M0 Do") == 2
  assert b"/XObject << /M0 7 0 R >>" in data
  assert b"/GS0 gs" in data
  assert b"/ca 0.4 /CA 0.4" in data
  assert b"/Subtype /Image" not in data


def test_full_vector_cache_preserves_svg_and_pdf_bytes(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  presentation = PlotPresentationSpec(
    source_styles=(SourceStyleSpec(source_id="s1", color="#336699", alpha=1.0),),
  )
  layers = {"s1": ((0.1, 0.2, 0.3), (0.2, 0.3, 0.4))}
  options = BatchPlotExportSpec(
    id="full-cache", name="Full cache", formats=("svg", "pdf"),
    vector_scatter_mode="full_vector",
  )
  cache = prepare_vector_render_cache(
    prepared, presentation, layers, options=options,
  )
  uncached_svg = tmp_path / "uncached.svg"
  cached_svg = tmp_path / "cached.svg"
  uncached_pdf = tmp_path / "uncached.pdf"
  cached_pdf = tmp_path / "cached.pdf"
  write_plot_svg(
    uncached_svg, prepared, presentation, layers, options=options,
  )
  write_plot_svg(
    cached_svg, prepared, presentation, layers, options=options,
    render_cache=cache,
  )
  write_plot_pdf(
    uncached_pdf, prepared, presentation, layers, options=options,
  )
  write_plot_pdf(
    cached_pdf, prepared, presentation, layers, options=options,
    render_cache=cache,
  )
  assert cached_svg.read_bytes() == uncached_svg.read_bytes()
  assert cached_pdf.read_bytes() == uncached_pdf.read_bytes()
  assert (
    cached_svg.with_suffix(".svg.json").read_bytes()
    == uncached_svg.with_suffix(".svg.json").read_bytes()
  )
  assert (
    cached_pdf.with_suffix(".pdf.json").read_bytes()
    == uncached_pdf.with_suffix(".pdf.json").read_bytes()
  )


def test_compact_batches_are_deterministic_and_preserve_duplicate_slots() -> None:
  layer = VectorScatterLayer(
    "s1", ((0.2, 0.2), (0.2, 0.2), (0.21, 0.2), (0.8, 0.8)), marker_size=3.0
  )
  batches = compact_scatter_batches((layer,), plot_width=800, plot_height=600)
  again = compact_scatter_batches((layer,), plot_width=800, plot_height=600)
  assert batches == again
  assert sum(len(batch.points) for batch in batches) == 4
  assert len(batches) >= 3
  assert all(batch.batch_key == key for batch, key in zip(batches, sorted(batch.batch_key for batch in batches)))


def test_compact_vector_svg_reduces_object_count_without_losing_points(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  layers = {"s1": (tuple(index / 100 for index in range(20)), (0.5,) * 20)}
  full = tmp_path / "full.svg"
  compact = tmp_path / "compact.svg"
  write_plot_svg(
    full, prepared, layers=layers,
    options=BatchPlotExportSpec(id="f", name="F", vector_scatter_mode="full_vector"),
  )
  write_plot_svg(
    compact, prepared, layers=layers,
    options=BatchPlotExportSpec(id="c", name="C", vector_scatter_mode="compact_vector"),
  )
  full_text = full.read_text(encoding="utf-8")
  compact_text = compact.read_text(encoding="utf-8")
  assert full_text.count("<use ") == 20
  assert compact_text.count("<path d=") < full_text.count("<use ")
  assert compact_text.count("fill-opacity=") > 0


def test_compact_vector_pdf_uses_compound_paths_and_alpha_resources(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "compact.pdf"
  write_plot_pdf(
    path, prepared,
    layers={"s1": ((0.1, 0.2, 0.3), (0.4, 0.4, 0.4))},
    options=BatchPlotExportSpec(
      id="c", name="C", vector_scatter_mode="compact_vector"
    ),
  )
  data = path.read_bytes()
  assert data.count(b"/Subtype /Form") == 0
  assert b"/ExtGState" in data
  assert b" re f" in data or b" c h f" in data
  assert b"/Subtype /Image" not in data


def test_compact_vector_cache_does_not_retain_duplicate_layer_plan() -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  options = BatchPlotExportSpec(
    id="compact-cache", name="Compact cache", formats=("svg", "pdf"),
    vector_scatter_mode="compact_vector",
  )
  cache = prepare_vector_render_cache(
    prepared, prepared.resolved_presentation.presentation,
    {"s1": ((0.1, 0.2), (0.3, 0.4))}, options=options,
  )
  assert cache.layers == ()
  assert cache.compact_batches


def test_hybrid_svg_contains_scatter_only_lossless_png_and_provenance(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "hybrid.svg"
  write_plot_svg(
    path, prepared, layers={"s1": ((0.2, 0.8), (0.2, 0.8))},
    options=BatchPlotExportSpec(
      id="h", name="H", vector_scatter_mode="hybrid_raster", hybrid_scatter_dpi=72,
    ),
  )
  text = path.read_text(encoding="utf-8")
  prefix = "href=\"data:image/png;base64,"
  encoded = text.split(prefix, 1)[1].split("\"", 1)[0]
  png = base64.b64decode(encoded)
  assert png.startswith(b"\x89PNG\r\n\x1a\n")
  assert text.count("<circle ") == 0
  metadata = json.loads(path.with_suffix(".svg.json").read_text(encoding="utf-8"))
  assert metadata["vector_scatter"]["resolved_mode"] == "hybrid_raster"
  assert metadata["vector_scatter"]["scatter_image_dpi"] == 72
  assert metadata["vector_scatter"]["rendered_event_count"] == 2


def test_hybrid_pdf_uses_image_xobject_with_soft_mask_not_full_canvas(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  path = tmp_path / "hybrid.pdf"
  write_plot_pdf(
    path, prepared, layers={"s1": ((0.2,), (0.8,))},
    options=BatchPlotExportSpec(
      id="h", name="H", vector_scatter_mode="hybrid_raster", hybrid_scatter_dpi=72,
    ),
  )
  data = path.read_bytes()
  assert data.count(b"/Subtype /Image") == 2
  assert b"/SMask" in data
  assert b"/ImScatter Do" in data
  assert b"/MediaBox [0 0 800 600]" in data
  metadata = json.loads(path.with_suffix(".pdf.json").read_text(encoding="utf-8"))
  assert metadata["vector_scatter"]["encoding"] == "png_rgba_lossless"


def test_hybrid_scatter_preserves_per_event_population_colors() -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  raster = _hybrid_scatter_raster(
    prepared, prepared.resolved_presentation.presentation,
    {"s1": ((0.25, 0.75), (0.25, 0.75))},
    event_colors={"s1": ("#ff0000", "#0000ff")},
    plot_width=96, plot_height=96, dpi=96,
  )
  assert bytes((255, 0, 0)) in raster["rgb"]
  assert bytes((0, 0, 255)) in raster["rgb"]


def test_hybrid_scatter_honors_cooperative_cancellation() -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
    view_presentation={
      "source_styles": [{"source_id": "s1", "alpha": 0.6}],
    },
  )
  values = np.linspace(0.0, 1.0, 2_048, dtype=np.float64)
  calls = 0

  def cancel() -> None:
    nonlocal calls
    calls += 1
    if calls >= 2:
      raise RuntimeError("cancelled")

  with pytest.raises(RuntimeError, match="cancelled"):
    _hybrid_scatter_raster(
      prepared, prepared.resolved_presentation.presentation,
      {"s1": (tuple(values), tuple(values[::-1]))},
      plot_width=256, plot_height=256, dpi=144, cancel_check=cancel,
    )
  assert calls >= 2


def test_png_export_honors_cooperative_cancellation_before_publish(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
  )
  values = np.linspace(0.0, 1.0, 2_048, dtype=np.float64)
  output = tmp_path / "cancelled.png"

  with pytest.raises(RuntimeError, match="cancelled"):
    write_plot_png(
      output, prepared, layers={"s1": (tuple(values), tuple(values[::-1]))},
      cancel_check=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )
  assert not output.exists()


def test_pdf_export_honors_cooperative_cancellation_before_publish(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
  )
  values = np.linspace(0.0, 1.0, 2_048, dtype=np.float64)
  output = tmp_path / "cancelled.pdf"

  with pytest.raises(RuntimeError, match="cancelled"):
    write_plot_pdf(
      output, prepared, layers={"s1": (tuple(values), tuple(values[::-1]))},
      options=BatchPlotExportSpec(
        id="cancel", name="Cancel", vector_scatter_mode="full_vector",
      ),
      cancel_check=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
    )
  assert not output.exists()


def test_hybrid_opaque_fast_path_matches_pixel_center_coverage() -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view",
    "scatter",
    source,
    (OverlaySourceResolution("s1", "compatible"),),
    view_presentation={
      "source_styles": [{
        "source_id": "s1", "color": "#ff0000", "alpha": 1.0,
        "marker_size": 3.0,
      }],
    },
  )
  width = height = 24
  raster = _hybrid_scatter_raster(
    prepared, prepared.resolved_presentation.presentation,
    {"s1": ((0.5,), (0.5,))},
    plot_width=width, plot_height=height, dpi=96,
  )
  expected = bytearray(width * height * 4)
  radius = 3.0 / 2.0
  center = (0.5 * (width - 1), 0.5 * (height - 1))
  for pixel_y in range(height):
    for pixel_x in range(width):
      dx = pixel_x + 0.5 - center[0]
      dy = pixel_y + 0.5 - center[1]
      if dx * dx + dy * dy <= radius * radius:
        index = (pixel_y * width + pixel_x) * 4
        expected[index:index + 4] = bytes((255, 0, 0, 255))
  assert raster["rgb"] == bytes(
    value for index, value in enumerate(expected) if index % 4 != 3
  )
  assert raster["alpha"] == bytes(
    expected[index] for index in range(3, len(expected), 4)
  )


def test_hybrid_pdf_matches_png_layout_at_pdf_logical_resolution(tmp_path) -> None:
  """PDF at 72 DPI has the same logical canvas as the PNG export."""
  if shutil.which("pdftoppm") is None:
    pytest.skip("pdftoppm is required to rasterize PDF for this comparison")
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),)
  )
  presentation = PlotPresentationSpec(
    title="PDF / PNG layout", x_axis_display_label="FITC-A",
    y_axis_display_label="APC-A", background_color="#ffffff",
  )
  options = BatchPlotExportSpec(
    id="hybrid", name="Hybrid", width=400, height=300,
    vector_scatter_mode="hybrid_raster", hybrid_scatter_dpi=144,
  )
  layers = {"s1": ((0.2, 0.5, 0.8), (0.8, 0.5, 0.2))}
  png_path = tmp_path / "plot.png"
  pdf_path = tmp_path / "plot.pdf"
  write_plot_png(png_path, prepared, presentation, layers, options=options)
  write_plot_pdf(pdf_path, prepared, presentation, layers, options=options)
  raster_prefix = tmp_path / "pdf-raster"
  subprocess.run(
    ["pdftoppm", "-r", "72", "-png", "-singlefile", str(pdf_path), str(raster_prefix)],
    check=True, capture_output=True,
  )
  with Image.open(png_path) as png_image, Image.open(raster_prefix.with_suffix(".png")) as pdf_image:
    assert pdf_image.size == png_image.size == (400, 300)
    png = np.asarray(png_image.convert("RGB"), dtype=np.float64)
    pdf = np.asarray(pdf_image.convert("RGB"), dtype=np.float64)
  normalized_rmse = float(np.sqrt(np.mean(np.square(png - pdf))) / 255.0)
  normalized_mean_error = float(np.mean(np.abs(png - pdf)) / 255.0)
  # Text rasterizers use different anti-aliasing, but the logical canvas,
  # plot rectangle, and scatter positions must remain visually aligned.
  assert normalized_rmse < 0.15
  assert normalized_mean_error < 0.03


@pytest.mark.parametrize("mode", ("full_vector", "compact_vector", "hybrid_raster"))
def test_all_pdf_scatter_modes_keep_y_axis_gates_and_scientific_ticks(mode, tmp_path) -> None:
  if shutil.which("pdftoppm") is None:
    pytest.skip("pdftoppm is required to rasterize PDF for this comparison")
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
    view_presentation={
      "source_styles": [{
        "source_id": "s1", "color": "#ff00ff", "alpha": 1.0,
        "marker_shape": "square", "marker_size": 12.0,
      }],
    },
    gate_overlays=({
      "id": "gate", "points": ((0.65, 0.65), (0.9, 0.65), (0.9, 0.9)),
      "color": "#e00000",
    },),
    scene={
      "x_ticks": [{"position": 0.5, "label": "2e6", "major": True}],
      "y_ticks": [{"position": 0.5, "label": "1e6", "major": True}],
    },
  )
  path = tmp_path / f"{mode}.pdf"
  png_path = tmp_path / f"{mode}.png"
  options = BatchPlotExportSpec(
    id=mode, name=mode, width=400, height=300,
    vector_scatter_mode=mode, hybrid_scatter_dpi=96,
  )
  write_plot_pdf(
    path, prepared, layers={"s1": ((0.75,), (0.8,))},
    event_colors={"s1": ("#ff00ff",)}, options=options,
  )
  write_plot_png(
    png_path, prepared, layers={"s1": ((0.75,), (0.8,))},
    event_colors={"s1": ("#ff00ff",)}, options=options,
  )
  data = path.read_bytes()
  assert b"(1e6)" not in data
  assert b"2 \xd7 10" in data
  assert b"(10)" in data
  raster_prefix = tmp_path / mode
  subprocess.run(
    ["pdftoppm", "-r", "72", "-png", "-singlefile", str(path), str(raster_prefix)],
    check=True, capture_output=True,
  )
  with Image.open(raster_prefix.with_suffix(".png")) as image:
    pixels = np.asarray(image.convert("RGB"))
  with Image.open(png_path) as image:
    png_pixels = np.asarray(image.convert("RGB"))
  magenta = (pixels[:, :, 0] > 180) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] > 180)
  png_magenta = (
    (png_pixels[:, :, 0] > 180) & (png_pixels[:, :, 1] < 80)
    & (png_pixels[:, :, 2] > 180)
  )
  assert np.any(magenta)
  assert np.any(png_magenta)
  # A normalized Y value of 0.8 must remain in the upper half of the plot,
  # not be reflected into the lower half by a PDF coordinate conversion.
  assert float(np.mean(np.where(magenta)[0])) < pixels.shape[0] / 2
  assert abs(float(np.mean(np.where(magenta)[0])) - float(np.mean(np.where(png_magenta)[0]))) < 3
  red = (pixels[:, :, 0] > 180) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
  png_red = (
    (png_pixels[:, :, 0] > 180) & (png_pixels[:, :, 1] < 80)
    & (png_pixels[:, :, 2] < 80)
  )
  assert np.any(red)
  assert np.any(png_red)
  # A gate is PlotScene geometry, so its PDF coordinates must use the same
  # top-origin normalized Y convention as PNG for every scatter mode.
  assert abs(float(np.mean(np.where(red)[0])) - float(np.mean(np.where(png_red)[0]))) < 3
  assert abs(float(np.mean(np.where(red)[1])) - float(np.mean(np.where(png_red)[1]))) < 3


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
    vector_scatter_mode="full_vector",
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


def test_export_uses_captured_scene_plot_area_margins(tmp_path) -> None:
  source = ({
    "source_id": "s1", "sample_id": "sample-1", "population_id": "all",
    "display_name": "Control", "visible": True,
  },)
  prepared = prepare_plot_export(
    "view", "scatter", source, (OverlaySourceResolution("s1", "compatible"),),
    scene={"plot_area": [11, 12, 13, 14]},
  )
  path = tmp_path / "captured-area.svg"
  write_plot_svg(
    path, prepared, layers={"s1": ((0.2,), (0.8,))},
    options=BatchPlotExportSpec(id="export", name="Export", width=200, height=160),
  )
  text = path.read_text(encoding="utf-8")
  assert 'x="11" y="12" width="176" height="134"' in text


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
    vector_scatter_mode="full_vector",
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
