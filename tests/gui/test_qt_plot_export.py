from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_scene import PlotScene, resolve_plot_layout
from flowdesk_qt.plot_widget import PlotWidget
from flowdesk_qt.qt_plot_export import render_batch_plot_qt

pytestmark = pytest.mark.gui


def test_qt_batch_renderer_writes_the_shared_scene_and_image(qapp, tmp_path) -> None:
  path = tmp_path / "plot.png"
  render_batch_plot_qt(
    path,
    raw_layers={"s1": (np.array([1.0, 10.0]), np.array([2.0, 20.0]))},
    source_ids=("s1",),
    source_styles={"s1": {"color": "#000000", "alpha": 0.6, "marker_size": 1.5}},
    presentation={
      "background_color": "#ffffff", "x_axis_display_label": "X",
      "y_axis_display_label": "Y", "show_grid": True,
    },
    x_parameter="x", y_parameter="y",
    title_lines=("Sample 1",), title_colors=("#4c78a8",),
    x_transform=None, y_transform=None,
    x_range=(1.0, 10.0), y_range=(2.0, 20.0), gates=(),
    width=400, height=300,
    options=BatchPlotExportSpec(
      id="export", name="Export", include_title=True,
      include_axis_labels=True, include_ticks=True,
    ),
    export_metadata={"scene_hash": "test-scene"},
  )
  assert path.exists() and path.stat().st_size > 1_000
  metadata = json.loads(path.with_suffix(".png.json").read_text(encoding="utf-8"))
  assert metadata["scene_hash"] == "test-scene"
  assert metadata["display_state"]["displayed_event_count"] == 2


def test_live_gui_and_core_export_resolve_the_same_layout(qapp, tmp_path) -> None:
  widget = PlotWidget()
  try:
    widget.resize(400, 300)
    widget.show()
    widget.plot_events(
      np.array([1.0, 10.0, 5.0]), np.array([2.0, 20.0, 8.0]),
      x_label="X", y_label="Y",
    )
    widget.set_manual_view_range((1.0, 10.0), (2.0, 20.0))
    widget.set_presentation({
      "title": "Line one\nLine two", "x_axis_display_label": "X",
      "y_axis_display_label": "Y",
    })
    qapp.processEvents()
    gui_path = tmp_path / "gui.png"
    assert widget.grab().save(str(gui_path))
    width, height = widget.canvas_size()
    margins = widget.plot_area_margins()
    assert widget.scene_ticks()["x_ticks"]
    assert widget.scene_ticks()["y_ticks"]
    scene = PlotScene.from_mapping({
      "plot_area": margins, "title_lines": ["Line one", "Line two"],
      "title_colors": ["#000000", "#000000"],
      "x_axis_label": "X", "y_axis_label": "Y", "source_order": ["s1"],
    })
    gui_layout = resolve_plot_layout(
      scene, {"title_font": {"size": 14}, "tick_font": {"size": 10},
              "axis_label_font": {"size": 14}}, width=width, height=height,
    ).to_mapping()
  finally:
    widget.close()
    widget.deleteLater()
  path = tmp_path / "core.png"
  render_batch_plot_qt(
    path,
    raw_layers={"s1": (np.array([1.0, 10.0, 5.0]), np.array([2.0, 20.0, 8.0]))},
    source_ids=("s1",), source_styles={"s1": {"color": "#000000", "alpha": 0.6}},
    presentation={"background_color": "#ffffff", "x_axis_display_label": "X",
                  "y_axis_display_label": "Y"},
    x_parameter="x", y_parameter="y", title_lines=("Line one", "Line two"),
    title_colors=("#000000", "#000000"), x_transform=None, y_transform=None,
    x_range=(1.0, 10.0), y_range=(2.0, 20.0), gates=(), width=width, height=height,
    options=BatchPlotExportSpec(
      id="layout", name="Layout", width=width, height=height,
      include_title=True, include_axis_labels=True, include_ticks=True,
    ),
    plot_area=margins,
  )
  export_layout = json.loads(
    path.with_suffix(path.suffix + ".json").read_text()
  )["plot_layout"]
  assert export_layout["plot_rect"] == gui_layout["plot_rect"]
  assert export_layout["title_baselines"] == gui_layout["title_baselines"]
  with Image.open(gui_path) as gui_image, Image.open(path) as export_image:
    gui_pixels = np.asarray(gui_image.convert("RGB"), dtype=np.float64)
    export_pixels = np.asarray(export_image.convert("RGB"), dtype=np.float64)
  normalized_rmse = float(
    np.sqrt(np.mean(np.square(gui_pixels - export_pixels))) / 255.0
  )
  assert normalized_rmse < 0.22


def test_plot_widget_uses_the_presentation_axis_label_font(qapp) -> None:
  widget = PlotWidget()
  try:
    widget.set_presentation({
      "x_axis_display_label": "FSC-A",
      "y_axis_display_label": "SSC-A",
    })
    bottom_html = widget._plot_item.getAxis("bottom").label.toHtml()
    left_html = widget._plot_item.getAxis("left").label.toHtml()
    for html, label in ((bottom_html, "FSC-A"), (left_html, "SSC-A")):
      assert label in html
      assert "font-size:14pt" in html
      assert "font-weight:700" in html
  finally:
    widget.close()
    widget.deleteLater()


def test_plot_widget_canvas_size_excludes_status_banner(qapp) -> None:
  widget = PlotWidget()
  try:
    widget.resize(800, 600)
    widget.set_status_banner("Preparing…")
    widget.show()
    qapp.processEvents()
    assert widget.canvas_size() == (widget._glw.width(), widget._glw.height())
    assert widget.canvas_size()[0] == widget.width()
    assert widget.canvas_size()[1] < widget.height()
  finally:
    widget.close()
    widget.deleteLater()


def test_plot_widget_reports_viewbox_margins_in_canvas_coordinates(qapp) -> None:
  widget = PlotWidget()
  try:
    widget.resize(800, 600)
    widget.set_status_banner("Preparing…")
    widget.show()
    qapp.processEvents()
    left, top, right, bottom = widget.plot_area_margins()
    width, height = widget.canvas_size()
    assert left >= 0 and top >= 0 and right >= 0 and bottom >= 0
    assert left + right < width
    assert top + bottom < height
  finally:
    widget.close()
    widget.deleteLater()


def test_qt_pdf_uses_the_same_logical_canvas_as_png(qapp, tmp_path) -> None:
  if shutil.which("pdftoppm") is None:
    pytest.skip("pdftoppm is required to rasterize PDF for this comparison")
  png_path = tmp_path / "plot.png"
  pdf_path = tmp_path / "plot.pdf"
  common = {
    "raw_layers": {"s1": (np.array([1.0, 10.0]), np.array([2.0, 20.0]))},
    "source_ids": ("s1",),
    "source_styles": {"s1": {"color": "#000000", "alpha": 0.6, "marker_size": 1.5}},
    "presentation": {
      "background_color": "#ffffff", "x_axis_display_label": "X",
      "y_axis_display_label": "Y", "show_grid": True,
    },
    "x_parameter": "x", "y_parameter": "y",
    "title_lines": ("Sample 1",), "title_colors": ("#4c78a8",),
    "x_transform": None, "y_transform": None,
    "x_range": (1.0, 10.0), "y_range": (2.0, 20.0), "gates": (),
    "width": 400, "height": 300,
    "options": BatchPlotExportSpec(
      id="export", name="Export", width=400, height=300, include_title=True,
      include_axis_labels=True, include_ticks=True,
    ),
    "export_metadata": {"scene_hash": "test-scene"},
  }
  render_batch_plot_qt(png_path, **common)
  render_batch_plot_qt(pdf_path, **common)
  raster_prefix = tmp_path / "pdf-raster"
  subprocess.run(
    ["pdftoppm", "-r", "72", "-png", "-singlefile", str(pdf_path), str(raster_prefix)],
    check=True, capture_output=True,
  )
  with (
    Image.open(png_path) as png_image,
    Image.open(raster_prefix.with_suffix(".png")) as pdf_image,
  ):
    assert png_image.size == pdf_image.size == (400, 300)
    png = np.asarray(png_image.convert("RGB"), dtype=np.float64)
    pdf = np.asarray(pdf_image.convert("RGB"), dtype=np.float64)
  normalized_rmse = float(np.sqrt(np.mean(np.square(png - pdf))) / 255.0)
  # The compatibility entry point now uses the core Pillow/PDF adapters.
  # Type1 glyph rasterisation differs from PNG, but the logical layout is
  # required to be identical and the bounded image difference must remain.
  assert normalized_rmse < 0.16
  png_layout = json.loads(
    png_path.with_suffix(png_path.suffix + ".json").read_text()
  )["plot_layout"]
  pdf_layout = json.loads(
    pdf_path.with_suffix(pdf_path.suffix + ".json").read_text()
  )["plot_layout"]
  assert png_layout == pdf_layout


def test_qt_batch_dpi_changes_sharpness_without_changing_layout(qapp, tmp_path) -> None:
  paths = {dpi: tmp_path / f"plot-{dpi}.png" for dpi in (96, 192)}
  values = np.linspace(1.0, 99.0, 120)
  for dpi, path in paths.items():
    render_batch_plot_qt(
      path,
      raw_layers={"s1": (values, 30.0 + values * 0.6)},
      source_ids=("s1",),
      source_styles={
        "s1": {"color": "#1864ab", "alpha": 0.65, "marker_size": 2.0}
      },
      presentation={
        "background_color": "#ffffff",
        "x_axis_display_label": "FITC B525-A",
        "y_axis_display_label": "APC R660-A",
        "show_grid": True,
      },
      x_parameter="x", y_parameter="y",
      title_lines=("Resolution check",), title_colors=("#1864ab",),
      x_transform=None, y_transform=None,
      x_range=(0.0, 100.0), y_range=(0.0, 100.0),
      gates=({
        "id": "gate", "name": "Gate", "gate_type": "rectangle",
        "x_parameter": "x", "y_parameter": "y",
        "thresholds": {"x_min": 55.0, "x_max": 80.0, "y_min": 55.0, "y_max": 80.0},
        "color": "#e00000",
      },),
      width=400, height=300,
      options=BatchPlotExportSpec(
        id=f"export-{dpi}", name="Export", width=400, height=300, dpi=dpi,
        raster_resolution_mode="dpi_scaled", include_title=True,
        include_axis_labels=True, include_ticks=True,
      ),
      export_metadata={"scene_hash": "same-scene"},
    )

  with Image.open(paths[96]) as low_image, Image.open(paths[192]) as high_image:
    assert low_image.size == (400, 300)
    assert high_image.size == (800, 600)
    normalized_high = high_image.convert("RGB").resize(
      low_image.size, Image.Resampling.LANCZOS
    )
    low = np.asarray(low_image.convert("RGB"), dtype=np.float64)
    high = np.asarray(normalized_high, dtype=np.float64)
  normalized_rmse = float(np.sqrt(np.mean(np.square(low - high))) / 255.0)
  assert normalized_rmse < 0.05
