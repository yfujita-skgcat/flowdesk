from __future__ import annotations

import json

import numpy as np
from PIL import Image

from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_qt.qt_plot_export import render_batch_plot_qt


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
