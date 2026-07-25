from __future__ import annotations

import json

import numpy as np

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
