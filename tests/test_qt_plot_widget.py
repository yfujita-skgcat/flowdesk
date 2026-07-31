"""Tests for Qt plot display helpers."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
shiboken6 = pytest.importorskip("shiboken6")
pytestmark = pytest.mark.gui

from pyqtgraph import ScatterPlotItem  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QAction, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
  QApplication,
  QCheckBox,
  QLabel,
  QMenu,
  QPushButton,
  QSplitter,
)

from flowdesk_cli.run_project import run_project_command  # noqa: E402
from flowdesk_core.density_colors import estimate_density_colors  # noqa: E402
from flowdesk_core.execution_context import ExecutionContext  # noqa: E402
from flowdesk_core.execution_report import ExecutionReport  # noqa: E402
from flowdesk_core.fcs_io import FcsFileInfo, write_fcs_file  # noqa: E402
from flowdesk_core.gating_strategy import (  # noqa: E402
  GatingStrategyError,
  evaluate_gating_strategy,
  evaluate_gating_strategy_with_membership,
)
from flowdesk_core.models import (  # noqa: E402
  ChannelSpec,
  GateSpec,
  GatingStrategySpec,
  PopulationResult,
  TransformSpec,
)
from flowdesk_core.overlays import Overlay2DLayer  # noqa: E402
from flowdesk_core.pipeline_runner import PipelineRunner  # noqa: E402
from flowdesk_core.transforms import (  # noqa: E402
  LOGICLE_IMPLEMENTATION_VERSION,
  apply_transform,
)
from flowdesk_qt.annotation_editor import AnnotationEditorDialog  # noqa: E402
from flowdesk_qt.channel_metadata import ChannelMetadataWorkspace  # noqa: E402
from flowdesk_qt.gate_editor import GateEditor, _GateDialog  # noqa: E402
from flowdesk_qt.gate_override_editor import GateOverrideDialog  # noqa: E402
from flowdesk_qt.group_panel import GroupPanel  # noqa: E402
from flowdesk_qt.main_window import MainWindow, _project_bundle_path  # noqa: E402
from flowdesk_qt.plot_export_dialog import PlotExportDialog  # noqa: E402
from flowdesk_qt.plot_widget import PlotWidget  # noqa: E402
from flowdesk_qt.sample_browser import SampleBrowser  # noqa: E402
from flowdesk_storage.project import load_project  # noqa: E402


def _app() -> QApplication:
  app = QApplication.instance()
  if app is None:
    app = QApplication([])
  return app


def _flush_deferred_delete(item: object) -> None:
  QCoreApplication.sendPostedEvents(item, QEvent.Type.DeferredDelete)


def test_prepared_overlay_layers_render_without_recomputing_membership() -> None:
  _app()
  plot = PlotWidget()
  layers = (
    Overlay2DLayer(
      "ancestor", np.array([1.0, 2.0]), np.array([2.0, 3.0]),
      {"color": "blue", "alpha": 0.2},
    ),
    Overlay2DLayer(
      "target", np.array([1.5]), np.array([2.5]),
      {"color": "red", "alpha": 1.0},
    ),
  )
  plot.plot_overlay_layers(layers)
  assert len(plot._overlay_scatter_items) == 2
  plot.clear_overlay_layers()
  assert plot._overlay_scatter_items == []


def test_plot_widget_exports_vector_formats_with_metadata(tmp_path: Path) -> None:
  _app()
  plot = PlotWidget()
  plot.plot_events(np.array([1.0, 2.0]), np.array([2.0, 3.0]), "X", "Y")
  svg_path = tmp_path / "plot.svg"
  pdf_path = tmp_path / "plot.pdf"
  plot.export_vector(svg_path, "SVG")
  plot.export_vector(pdf_path, "PDF")
  assert svg_path.stat().st_size > 0
  assert pdf_path.stat().st_size > 0
  assert (tmp_path / "plot.svg.json").exists()
  assert (tmp_path / "plot.pdf.json").exists()
  plot.close()


def test_plot_export_can_use_equal_aspect_without_changing_view(tmp_path: Path) -> None:
  app = _app()
  plot = PlotWidget()
  try:
    plot.resize(480, 360)
    plot.show()
    plot.plot_events(
      np.array([0.0, 10.0]), np.array([0.0, 20.0]), "X", "Y"
    )
    plot.set_manual_view_range((0.0, 10.0), (0.0, 20.0))
    app.processEvents()
    before = plot.view_range()
    out = tmp_path / "equal.png"
    plot.export_png(out, width=320, height=240, aspect_1_to_1=True)
    assert plot.view_range() == before
    metadata = json.loads((tmp_path / "equal.png.json").read_text())
    assert metadata["aspect_1_to_1"] is True
  finally:
    plot.close()
    plot.deleteLater()
    app.processEvents()


def test_plot_context_menu_exposes_display_only_appearance_actions() -> None:
  _app()
  plot = PlotWidget()
  try:
    menu = plot._build_context_menu()
    action_ids = {
      action.objectName()
      for action in menu.actions()
      if not action.menu()
    }
    assert {"plotAppearance", "plotResetAppearance"} == action_ids
    assert menu.findChild(QMenu, "plotLegendMenu") is not None
    assert menu.findChild(QMenu, "plotViewRangeMenu") is not None
    export_menu = menu.findChild(QMenu, "plotExportMenu")
    assert export_menu is not None
    assert {
      "plotExportPngAction", "plotExportJpegAction", "plotExportSvgAction",
      "plotExportPdfAction", "plotExportBatchAction",
    } == {action.objectName() for action in export_menu.actions()}
    requested: list[str] = []
    plot.export_requested.connect(requested.append)
    export_menu.findChild(QAction, "plotExportJpegAction").trigger()
    assert requested == ["JPEG"]
    assert plot._glw.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    plot.set_interaction_mode("gate")
    assert plot._interaction_mode == "gate"
  finally:
    plot.close()
  plot.deleteLater()
  QApplication.processEvents()


def test_group_panel_renders_and_edits_persisted_groups() -> None:
  _app()
  panel = GroupPanel()
  changed: list[list[dict[str, object]]] = []
  panel.groups_changed.connect(changed.append)
  panel.set_groups([{
    "id": "all-samples",
    "name": "All Samples",
    "role": "all_samples",
    "sample_ids": [],
  }])
  assert panel._list.count() == 1
  assert panel._list.item(0).data(0x0100) == "all-samples"
  panel.set_sample_ids(["s1"])
  assert panel._sample_list.item(0).text() == "s1"
  assert panel.add_sample_to_group("all-samples", "s1")
  assert changed[-1][0]["sample_ids"] == ["s1"]
  panel._groups.append({
    "id": "user-group",
    "name": "User Group",
    "role": "user",
    "sample_ids": ["s1"],
  })
  panel._emit_groups()
  assert changed[-1][1]["id"] == "user-group"
  assert panel._groups[1]["role"] == "user"
  panel.deleteLater()


def test_annotation_editor_uses_typed_core_operations() -> None:
  _app()
  dialog = AnnotationEditorDialog(
    ("s1", "s2"),
    [{
      "sample_id": "s1",
      "keyword": "Condition",
      "value": "old",
      "source": "fcs",
    }],
  )
  dialog.import_csv_text("sample_id,Dose\ns1,2\ns2,3\n")
  dialog.replace_value("Condition", "old", "new")
  dialog.fill_series("Replicate", 1, 1)
  values = dialog.annotations()
  assert any(item["value"] == "new" for item in values)
  assert any(item["keyword"] == "Dose" and item["value"] == 3 for item in values)
  assert sum(item["keyword"] == "Replicate" for item in values) == 2
  dialog.deleteLater()


def _fcs_info(channels: tuple[str, ...] = ("FSC-A", "SSC-A")) -> FcsFileInfo:
  return FcsFileInfo(
    fcs_version="3.1",
    instrument="",
    date="",
    sample="sample",
    event_count=10,
    channel_count=len(channels),
    channels=tuple(
      ChannelSpec(id=f"ch_{idx}", name=name)
      for idx, name in enumerate(channels)
    ),
    metadata={},
  )


def test_plot_widget_exports_png(tmp_path: Path) -> None:
  app = _app()
  widget = PlotWidget()
  try:
    widget.resize(480, 360)
    widget.show()

    x = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    y = np.array([1.0, 4.0, 9.0, 16.0], dtype=np.float64)
    widget.plot_events(x, y, x_label="X", y_label="Y")
    app.processEvents()

    out = tmp_path / "plot.png"
    widget.export_png(out, width=320, height=240)
    app.processEvents()

    image = QImage(str(out))
    assert out.exists()
    assert image.width() == 320
    assert image.height() == 240
    assert image.isNull() is False
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_plot_widget_exports_jpeg_with_display_metadata(tmp_path: Path) -> None:
  app = _app()
  widget = PlotWidget()
  try:
    widget.resize(320, 240)
    widget.show()
    widget.plot_events(
      np.array([1.0, 2.0]), np.array([2.0, 1.0]), x_label="X", y_label="Y"
    )
    out = tmp_path / "plot.jpg"
    widget.set_export_metadata({"ordered_source_ids": ["s1"]})
    widget.export_jpg(out, width=240, height=180)
    image = QImage(str(out))
    metadata = json.loads(out.with_suffix(".jpg.json").read_text(encoding="utf-8"))
    assert image.width() == 240
    assert image.height() == 180
    assert metadata["format"] == "JPEG"
    assert metadata["ordered_source_ids"] == ["s1"]
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_plot_export_dialog_returns_display_only_options() -> None:
  _app()
  dialog = PlotExportDialog("JPEG")
  assert dialog.objectName() == "plotExportOptionsDialog"
  assert dialog.findChild(QCheckBox, "plotExportIncludeGatesCheckBox") is not None
  request = dialog.request()
  assert request.format_name == "JPEG"
  assert request.layout_policy == "current_view"
  dialog.deleteLater()


def test_export_gate_style_hides_edit_handles_and_restores_editing_state() -> None:
  _app()
  plot = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-1", name="Gate", gate_type="rectangle",
      x_parameter="x", y_parameter="y",
      thresholds={"x_min": 1.0, "x_max": 3.0, "y_min": 1.0, "y_max": 3.0},
    )
    plot.plot_events(np.array([1.0, 2.0]), np.array([1.0, 2.0]), x_label="x", y_label="y")
    plot.add_gate_overlays([gate])
    item = plot._gate_items[0]
    original_style = item.pen.style()
    handles = list(item.getHandles())
    state = plot._begin_export_visibility({})
    assert item.pen.style() == Qt.PenStyle.SolidLine
    assert all(not handle.isVisible() for handle in handles)
    plot._end_export_visibility(state)
    assert item.pen.style() == original_style
    assert all(handle.isVisible() for handle in handles)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_plot_events_accepts_population_display_colors_without_changing_data() -> None:
  _app()
  plot = PlotWidget()
  x = np.array([1.0, 2.0, 3.0])
  y = np.array([3.0, 2.0, 1.0])
  colors = np.array(["#ff0000", "#00ff00", "#0000ff"])
  try:
    plot.plot_events(x, y, event_colors=colors)
    assert np.array_equal(plot._cached_x, x)
    assert np.array_equal(plot._cached_y, y)
    assert np.array_equal(plot._event_colors, colors)
    plot.set_style(replace(plot.style(), dot_opacity=0.5))
    assert np.array_equal(plot._event_colors, colors)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_coloring_replaces_supplied_population_colors_for_display() -> None:
  _app()
  plot = PlotWidget()
  x = np.array([0.1, 0.1, 0.1, 0.9])
  y = np.array([0.1, 0.1, 0.1, 0.9])
  try:
    plot.plot_events(
      x, y, event_colors=np.array(["#ff00ff"] * 4), density_coloring=True,
    )
    assert plot._event_colors is not None
    assert len(set(plot._event_colors.tolist()[:3])) == 1
    assert plot._event_colors.tolist()[0] != plot._event_colors.tolist()[3]
    assert plot._event_colors.tolist()[3] != "#ff00ff"
    assert isinstance(plot._scatter, ScatterPlotItem)
    assert plot._population_scatter_items == []
    assert np.array_equal(plot._cached_x, x)
    assert np.array_equal(plot._cached_y, y)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_coloring_replaces_uniform_plot_with_colored_scatter_item() -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(42)
  x = np.concatenate((rng.normal(0.0, 0.2, 2000), rng.normal(2.0, 0.05, 200)))
  y = np.concatenate((rng.normal(0.0, 0.2, 2000), rng.normal(2.0, 0.05, 200)))
  try:
    plot.plot_events(x, y, density_coloring=True)
    assert isinstance(plot._scatter, ScatterPlotItem)
    assert plot._event_colors is not None
    assert len(set(plot._event_colors.tolist())) > 32
    assert plot._scatter.opts["brush"] is not None
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_coloring_can_resolve_off_gui_thread_and_apply_brushes() -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(43)
  x = np.concatenate((rng.normal(0.0, 0.2, 1000), rng.normal(2.0, 0.05, 100)))
  y = np.concatenate((rng.normal(0.0, 0.2, 1000), rng.normal(2.0, 0.05, 100)))
  expected = estimate_density_colors(
    x,
    y,
    x,
    y,
    bounds=(float(x.min()), float(x.max()), float(y.min()), float(y.max())),
    logical_size=(512, 512),
  ).colors
  try:
    plot.plot_events(x, y, density_coloring=True, density_async=True)
    assert plot._event_colors is None
    assert plot._scatter is None
    for _ in range(400):
      QApplication.processEvents()
      time.sleep(0.005)
      if plot._event_colors is not None:
        break
    assert plot._event_colors is not None
    assert plot._scatter is not None
    assert np.array_equal(plot._event_colors, expected)
    assert plot._density_pending_key is None
    assert plot._density_scheduler.is_running() is False
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_async_discards_stale_result_after_replot() -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(44)
  first_x = rng.normal(0.0, 0.2, 1200)
  first_y = rng.normal(0.0, 0.2, 1200)
  second_x = rng.normal(2.0, 0.1, 1200)
  second_y = rng.normal(2.0, 0.1, 1200)
  scheduler = plot._get_density_scheduler()
  original_executor = scheduler._executor

  def slow_executor(request):
    time.sleep(0.04)
    return original_executor(request)

  scheduler._executor = slow_executor
  expected = estimate_density_colors(
    second_x,
    second_y,
    second_x,
    second_y,
    bounds=(
      float(second_x.min()), float(second_x.max()),
      float(second_y.min()), float(second_y.max()),
    ),
    logical_size=(512, 512),
  ).colors
  try:
    plot.plot_events(first_x, first_y, density_coloring=True, density_async=True)
    plot.plot_events(second_x, second_y, density_coloring=True, density_async=True)
    for _ in range(200):
      QApplication.processEvents()
      time.sleep(0.005)
      if plot._event_colors is not None and not plot._density_scheduler.is_running():
        break
    assert plot._event_colors is not None
    assert np.array_equal(plot._event_colors, expected)
    assert np.array_equal(plot._rendered_x, second_x)
    assert np.array_equal(plot._rendered_y, second_y)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_coloring_submits_final_scatter_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(73)
  x = np.concatenate((rng.normal(0.0, 0.2, 1000), rng.normal(2.0, 0.05, 100)))
  y = np.concatenate((rng.normal(0.0, 0.2, 1000), rng.normal(2.0, 0.05, 100)))
  expected = estimate_density_colors(
    x,
    y,
    x,
    y,
    bounds=(float(x.min()), float(x.max()), float(y.min()), float(y.max())),
    logical_size=(512, 512),
  ).colors
  calls = 0
  original_set_data = ScatterPlotItem.setData

  def counting_set_data(self, *args, **kwargs):
    nonlocal calls
    if kwargs.get("x") is not None or args:
      calls += 1
    return original_set_data(self, *args, **kwargs)

  monkeypatch.setattr(ScatterPlotItem, "setData", counting_set_data)
  try:
    plot.plot_events(x, y, density_coloring=True)
    assert calls == 1
    assert np.array_equal(plot._rendered_x, x)
    assert np.array_equal(plot._rendered_y, y)
    assert np.array_equal(plot._event_colors, expected)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_colors_do_not_change_with_view_range_or_resize() -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(8)
  x = rng.normal(size=5000)
  y = rng.normal(size=5000)
  try:
    plot.plot_events(x, y, density_coloring=True)
    original = plot._event_colors.copy()
    cache = dict(plot._density_color_cache)
    plot.set_manual_view_range((-0.5, 0.5), (-0.5, 0.5))
    plot.resize(1200, 300)
    QApplication.processEvents()
    assert np.array_equal(plot._event_colors, original)
    assert plot._density_color_cache == cache
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_replot_reuses_existing_scatter_for_same_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(81)
  x = rng.normal(size=5000)
  y = rng.normal(size=5000)
  calls = 0
  original_set_data = ScatterPlotItem.setData

  def counting_set_data(self, *args, **kwargs):
    nonlocal calls
    if kwargs.get("x") is not None or args:
      calls += 1
    return original_set_data(self, *args, **kwargs)

  monkeypatch.setattr(ScatterPlotItem, "setData", counting_set_data)
  try:
    context = ("revision-1", "sample-1", "all-events", "x", "y")
    plot.plot_events(x, y, density_coloring=True, density_cache_context=context)
    original_scatter = plot._scatter
    original_colors = plot._event_colors.copy()
    plot.plot_events(x, y, density_coloring=True, density_cache_context=context)
    assert calls == 1
    assert plot._scatter is original_scatter
    assert np.array_equal(plot._event_colors, original_colors)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_style_change_reuses_density_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(82)
  x = rng.normal(size=3000)
  y = rng.normal(size=3000)
  calls = 0
  original_estimator = estimate_density_colors

  def counting_estimator(*args, **kwargs):
    nonlocal calls
    calls += 1
    return original_estimator(*args, **kwargs)

  monkeypatch.setattr("flowdesk_qt.plot_widget.estimate_density_colors", counting_estimator)
  try:
    plot.plot_events(x, y, density_coloring=True, density_cache_context=("same",))
    original_colors = plot._event_colors.copy()
    plot.set_style(replace(plot.style(), dot_size=3.0, dot_opacity=0.4))
    assert calls == 1
    assert np.array_equal(plot._event_colors, original_colors)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_style_changes_do_not_resubmit_event_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(83)
  x = rng.normal(size=4000)
  y = rng.normal(size=4000)
  calls = 0
  original_set_data = ScatterPlotItem.setData

  def counting_set_data(self, *args, **kwargs):
    nonlocal calls
    if kwargs.get("x") is not None or args:
      calls += 1
    return original_set_data(self, *args, **kwargs)

  monkeypatch.setattr(ScatterPlotItem, "setData", counting_set_data)
  try:
    plot.plot_events(x, y, density_coloring=True, density_cache_context=("style",))
    original_colors = plot._event_colors.copy()
    plot.set_style(replace(plot.style(), dot_size=3.0))
    plot.set_style(replace(plot.style(), dot_opacity=0.4))

    assert calls == 1
    assert np.array_equal(plot._event_colors, original_colors)
    assert isinstance(plot._scatter, ScatterPlotItem)
    assert all(
      brush.color().alphaF() == pytest.approx(0.4)
      for brush in plot._scatter.data["brush"]
    )
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_density_brush_payload_reuses_same_colors_and_opacity() -> None:
  _app()
  plot = PlotWidget()
  rng = np.random.default_rng(84)
  x = rng.normal(size=1200)
  y = rng.normal(size=1200)
  try:
    plot.plot_events(x, y, density_coloring=True, density_cache_context=("brush",))
    first_payload = plot._density_brushes()
    assert plot._density_brushes() is first_payload
    plot.set_style(replace(plot.style(), dot_size=3.0))
    assert plot._density_brushes() is first_payload
    plot.set_style(replace(plot.style(), dot_opacity=0.4))
    assert plot._density_brushes() is not first_payload
    assert all(
      brush.color().alphaF() == pytest.approx(0.4)
      for brush in plot._density_brushes()
    )
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_population_colors_render_as_uniform_layers_without_per_event_brushes() -> None:
  _app()
  plot = PlotWidget()
  x = np.arange(100.0)
  y = np.arange(100.0)
  colors = np.where(np.arange(100) % 2, "#ff0000", "#0000ff")
  try:
    calls = 0
    original_make_brush = plot._make_brush

    def counting_make_brush(color: str, opacity: float):
      nonlocal calls
      calls += 1
      return original_make_brush(color, opacity)

    plot._make_brush = counting_make_brush
    plot.plot_events(x, y, event_colors=colors)
    first_count = calls
    assert first_count == 2
    assert len(plot._population_scatter_items) == 2
    assert sum(len(item.xData) for item, _color in plot._population_scatter_items) == 100
    assert {
      item.scatter.opts["brush"].color().name()
      for item, _color in plot._population_scatter_items
    } == {"#0000ff", "#ff0000"}
    plot.set_presentation({})
    assert calls == first_count
    plot.plot_events(x, y, event_colors=colors)
    assert calls == first_count + 2
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_population_event_colors_preserve_full_hex_values() -> None:
  app = _app()
  window = MainWindow()
  try:
    window._gate_editor._population_display_colors = {"positive": "#800080"}
    class Membership:
      sample_id = "s1"
      population_id = "positive"
      mask = np.array([True, False, True])

    class Report:
      population_membership = (Membership(),)

    window._last_result_report = Report()
    colors = window._population_event_colors("s1", 3, None)
    assert colors is not None
    assert colors.tolist() == ["#800080", "#000000", "#800080"]
    window._plot_widget.plot_events(
      np.arange(3.0), np.arange(3.0), event_colors=colors
    )
    rendered = {
      color: item.xData.tolist()
      for item, color in window._plot_widget._population_scatter_items
    }
    assert rendered == {"#800080": [0.0, 2.0], "#000000": [1.0]}
    window._plot_widget.set_presentation({})
    rendered_after_presentation = {
      color: item.xData.tolist()
      for item, color in window._plot_widget._population_scatter_items
    }
    assert rendered_after_presentation == rendered
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_active_base_layer_does_not_inherit_manual_overlay_color() -> None:
  app = _app()
  window = MainWindow()
  try:
    window._sample_browser._manual_overlay_colors["active"] = "#ff6600"

    # Without an explicit population color, MainWindow leaves event_colors
    # unset and PlotWidget uses its base-layer dot color.
    assert window._population_event_colors("active", 2, None) is None
    assert window._plot_widget.style().dot_color == "#000000"
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_overlay_display_disables_population_colors_for_active_base_layer() -> None:
  app = _app()
  window = MainWindow()
  try:
    window._current_sample_id = "active"
    window._sample_browser._manual_overlay_sample_ids.add("overlay")
    window._gate_editor._population_display_colors = {"positive": "#ff0000"}

    class Membership:
      sample_id = "active"
      population_id = "positive"
      mask = np.array([True, False])

    class Report:
      population_membership = (Membership(),)

    window._last_result_report = Report()
    view = {"presentation": {"colormap": "density"}}
    assert window._has_visible_overlay(view) is True
    assert window._density_coloring_active(view) is False
    overlay_colors = window._base_layer_event_colors(
      "active", 2, None, overlay_display_active=True,
    )
    assert overlay_colors is None
    window._plot_widget.plot_events(
      np.arange(2.0), np.arange(2.0), event_colors=overlay_colors,
    )
    assert window._plot_widget._population_scatter_items == []
    assert window._base_layer_event_colors("active", 2, None).tolist() == [
      "#ff0000", "#000000",
    ]
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_display_sampling_defaults_to_20000_and_zero_disables_it() -> None:
  _app()
  plot = PlotWidget()
  values = np.arange(25_000, dtype=np.float64)
  try:
    plot.plot_events(values, values)
    assert plot.max_display_points() == 20_000
    assert len(plot._scatter.xData) == 20_000
    assert plot.display_state()["display_sampling_active"] is True

    plot.set_max_display_points(0)
    plot.plot_events(values, values)
    assert len(plot._scatter.xData) == 25_000
    assert plot.display_state()["display_sampling_active"] is False
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_population_color_sampling_keeps_rare_color_and_is_deterministic() -> None:
  _app()
  plot = PlotWidget()
  values = np.arange(100, dtype=np.float64)
  colors = np.full(100, "#0000ff", dtype="<U7")
  colors[-1] = "#ff0000"
  try:
    plot.set_max_display_points(10)
    plot.plot_events(values, values, event_colors=colors)
    first = {
      color: item.xData.copy()
      for item, color in plot._population_scatter_items
    }
    assert sum(len(points) for points in first.values()) == 10
    assert first["#ff0000"].tolist() == [99.0]

    plot.plot_events(values, values, event_colors=colors)
    second = {
      color: item.xData.copy()
      for item, color in plot._population_scatter_items
    }
    assert all(np.array_equal(first[color], second[color]) for color in first)
  finally:
    plot.close()
    plot.deleteLater()
    QApplication.processEvents()


def test_plot_parameters_expose_persisted_display_max_points() -> None:
  app = _app()
  window = MainWindow()
  try:
    assert window._channel_selector.display_max_points() == 20_000
    window._channel_selector._display_max_points_spin.setValue(12_345)
    assert window._plot_widget.max_display_points() == 12_345
    manifest = window._build_project_manifest()
    view = next(item for item in manifest["plot_views"] if item["id"] == "main-view")
    assert view["rendering_downsample"] == {"max_points": 12_345}
    assert manifest["plot_display_settings"]["display_max_points"] == 12_345
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_project_manifest_persists_complete_active_plot_view() -> None:
  app = _app()
  window = MainWindow()
  try:
    window._channel_selector.set_channels(["x", "y"], preserve_selection=False)
    window._channel_selector.set_selected_channels("x", "y")
    window._plot_views = [{"id": "main-view"}]
    window._display_population_id = "gate-1"
    window._plot_transform_overrides = {"x": "tx", "y": "ty"}
    window._plot_widget._x_label = "FITC B525-A"
    window._plot_widget._y_label = "APC R660-A"
    window._plot_widget.set_manual_view_range((1.0, 6.0), (0.5, 4.5))
    window._transforms = [
      {
        "id": "tx", "name": "X log", "transform_type": "log",
        "parameter": "x", "settings": {"base": 10.0},
      },
      {
        "id": "ty", "name": "Y log", "transform_type": "log",
        "parameter": "y", "settings": {"base": 10.0},
      },
    ]
    manifest = window._build_project_manifest()
    view = next(item for item in manifest["plot_views"] if item["id"] == "main-view")
    assert view["x_parameter"] == "x"
    assert view["y_parameter"] == "y"
    assert view["x_transform_id"] == "tx"
    assert view["y_transform_id"] == "ty"
    assert view["population_id"] == "gate-1"
    assert view["plot_type"] == "scatter"
    assert view["display_scene"]["x_axis_label"] == "FITC B525-A"
    assert view["display_scene"]["y_axis_label"] == "APC R660-A"
    assert view["display_scene"]["view_range"] == ((1.0, 6.0), (0.5, 4.5))
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_project_save_name_becomes_flowdesk_bundle_directory(tmp_path: Path) -> None:
  assert _project_bundle_path(tmp_path / "experiment") == (
    tmp_path / "experiment.flowdesk"
  )
  assert _project_bundle_path(tmp_path / "experiment.flowdesk") == (
    tmp_path / "experiment.flowdesk"
  )
  assert _project_bundle_path(tmp_path / "Experiment.FLOWDESK") == (
    tmp_path / "Experiment.FLOWDESK"
  )


def test_save_project_dialog_uses_entered_name(monkeypatch, tmp_path: Path) -> None:
  app = _app()
  window = MainWindow()
  saved: list[Path] = []
  monkeypatch.setattr(
    "flowdesk_qt.main_window.QFileDialog.getSaveFileName",
    lambda *_args, **_kwargs: (str(tmp_path / "named-analysis"), "Flowdesk projects (*.flowdesk)"),
  )
  monkeypatch.setattr(window, "_save_project_to_path", saved.append)
  try:
    assert window._save_project_interactively()
    assert saved == [tmp_path / "named-analysis.flowdesk"]
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_save_project_reuses_current_bundle_without_dialog(monkeypatch, tmp_path: Path) -> None:
  app = _app()
  window = MainWindow()
  current = tmp_path / "current.flowdesk"
  saved: list[Path] = []
  window._project_path = current
  monkeypatch.setattr(window, "_save_project_to_path", saved.append)
  monkeypatch.setattr(
    "flowdesk_qt.main_window.QFileDialog.getSaveFileName",
    lambda *_args, **_kwargs: pytest.fail("Save Project must not open a dialog"),
  )
  try:
    window._on_save_project()
    assert saved == [current]
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_file_menu_exposes_save_project_as_action() -> None:
  app = _app()
  window = MainWindow()
  try:
    assert window.action_save_project.shortcut().toString() == "Ctrl+S"
    assert window.action_save_project_as.objectName() == "actionSaveProjectAs"
    assert window.action_save_project.text() == "&Save Project"
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_default_drag_delegates_mouse_drag_to_viewbox() -> None:
  app = _app()
  widget = PlotWidget()
  original_drag = widget._default_mouse_drag_event
  try:
    calls: list[object] = []

    class FakeDragEvent:
      pass

    event = FakeDragEvent()

    def default_drag(received: object) -> None:
      calls.append(received)

    widget._default_mouse_drag_event = default_drag
    widget.clear_gate_creation()
    widget._on_mouse_drag(event)

    assert calls == [event]
  finally:
    vb = widget._view_box()
    if vb is not None:
      vb.mouseClickEvent = widget._default_mouse_click_event
      vb.mouseDragEvent = original_drag
    widget._default_mouse_drag_event = original_drag
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_ctrl_left_drag_matches_historical_right_drag_zoom() -> None:
  app = _app()
  widget = PlotWidget()
  original_drag = widget._default_mouse_drag_event
  try:
    class FakeDragEvent:
      def __init__(self, start: bool, finish: bool) -> None:
        self._start = start
        self._finish = finish
        self.accepted = False

      def button(self) -> Qt.MouseButton:
        return Qt.LeftButton

      def modifiers(self) -> Qt.KeyboardModifier:
        return Qt.ControlModifier

      def screenPos(self) -> QPointF:
        return QPointF(20.0, 20.0)

      def lastScreenPos(self) -> QPointF:
        return QPointF(10.0, 20.0)

      def buttonDownPos(self, _button: Qt.MouseButton) -> QPointF:
        return QPointF(5.0, 5.0)

      def isStart(self) -> bool:
        return self._start

      def isFinish(self) -> bool:
        return self._finish

      def accept(self) -> None:
        self.accepted = True

    calls: list[object] = []
    widget._default_mouse_drag_event = calls.append
    widget.set_manual_view_range((0.0, 10.0), (0.0, 10.0))
    before = widget.view_range()
    finish = FakeDragEvent(False, True)
    widget._on_mouse_drag(finish)
    after = widget.view_range()
    assert calls == []
    assert finish.accepted is True
    assert before is not None and after is not None
    assert after != before
    assert widget._range_mode == "manual"
  finally:
    vb = widget._view_box()
    if vb is not None:
      vb.mouseClickEvent = widget._default_mouse_click_event
      vb.mouseDragEvent = original_drag
    widget._default_mouse_drag_event = original_drag
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_rectangle_gate_creation_captures_drag_until_finish() -> None:
  app = _app()
  widget = PlotWidget()
  original_drag = widget._default_mouse_drag_event
  original_get_data_position = widget._get_data_position
  try:
    default_calls: list[object] = []
    gate_calls: list[dict[str, object]] = []

    class FakeDragEvent:
      def __init__(self, data_pos: tuple[float, float], start: bool, finish: bool) -> None:
        self.data_pos = data_pos
        self._start = start
        self._finish = finish
        self.accepted = False

      def isStart(self) -> bool:
        return self._start

      def isFinish(self) -> bool:
        return self._finish

      def accept(self) -> None:
        self.accepted = True

    def default_drag(received: object) -> None:
      default_calls.append(received)

    def on_click(
      data_x: float,
      data_y: float,
      is_double_click: bool,
      **kwargs: object,
    ) -> None:
      gate_calls.append(
        {
          "x": data_x,
          "y": data_y,
          "double": is_double_click,
          **kwargs,
        }
      )

    widget._default_mouse_drag_event = default_drag
    widget._get_data_position = lambda event: event.data_pos
    widget.on_mouse_clicked(on_click)
    widget.begin_gate_creation("rectangle")

    start_event = FakeDragEvent((1.0, 2.0), start=True, finish=False)
    finish_event = FakeDragEvent((5.0, 8.0), start=False, finish=True)
    widget._on_mouse_drag(start_event)
    move_event = FakeDragEvent((3.0, 4.0), start=False, finish=False)
    widget._on_mouse_drag(move_event)
    assert widget._preview_item is not None
    widget._on_mouse_drag(finish_event)

    assert default_calls == []
    assert start_event.accepted is True
    assert move_event.accepted is True
    assert finish_event.accepted is True
    assert widget._preview_item is None
    assert gate_calls == [
      {
        "x": 3.0,
        "y": 4.0,
        "double": False,
        "dragging": True,
      },
      {
        "x": 1.0,
        "y": 2.0,
        "double": False,
        "dragging": False,
        "rect_end_x": 5.0,
        "rect_end_y": 8.0,
      }
    ]
  finally:
    widget._get_data_position = original_get_data_position
    vb = widget._view_box()
    if vb is not None:
      vb.mouseClickEvent = widget._default_mouse_click_event
      vb.mouseDragEvent = original_drag
    widget._default_mouse_drag_event = original_drag
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_rectangle_preview_reuses_and_disposes_single_roi() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    widget.begin_gate_creation("rectangle")
    widget._update_rectangle_preview((1.0, 2.0), (3.0, 5.0))
    preview = widget._preview_item
    assert preview is not None
    assert preview.pen.color().name() == "#0057b8"
    assert preview.pen.style() == Qt.PenStyle.DotLine

    for offset in range(100):
      widget._update_rectangle_preview(
        (2.0, 4.0),
        (7.0 + offset, 10.0 + offset),
      )

    assert widget._preview_item is preview
    state = preview.saveState()
    assert tuple(state["pos"]) == pytest.approx((2.0, 4.0))
    assert tuple(state["size"]) == pytest.approx((104.0, 105.0))

    widget.clear_gate_creation()
    _flush_deferred_delete(preview)
    assert shiboken6.isValid(preview) is False
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_clear_gates_disconnects_and_disposes_roi() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-disposal",
      name="disposal",
      gate_type="rectangle",
      x_parameter="X",
      y_parameter="Y",
      thresholds={
        "x_min": 1.0,
        "x_max": 3.0,
        "y_min": 2.0,
        "y_max": 5.0,
      },
    )
    for _iteration in range(25):
      widget.add_gate_overlay(gate, gate_index=0)
      item = widget._gate_items[0]

      widget.clear_gates()
      _flush_deferred_delete(item)

      assert widget._gate_items == []
      assert widget._gate_item_callbacks == {}
      assert shiboken6.isValid(item) is False
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_selected_gate_uses_contrast_safe_outline_and_fill() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="selected-gate",
      name="selected",
      gate_type="polygon",
      x_parameter="X",
      y_parameter="Y",
      coordinates=((1.0, 1.0), (3.0, 1.0), (2.0, 3.0)),
    )
    widget.add_gate_overlay(gate, gate_index=0)
    item = widget._gate_items[0]
    widget.highlight_gate_index(0)

    assert item.pen.color().name() == "#0057b8"
    assert item.pen.style() == Qt.PenStyle.SolidLine
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_polygon_gate_creation_uses_scene_click_and_double_click() -> None:
  app = _app()
  widget = PlotWidget()
  original_get_data_position = widget._get_data_position
  try:
    gate_calls: list[tuple[float, float, bool]] = []

    class FakeClickEvent:
      def __init__(self, data_pos: tuple[float, float], double: bool = False) -> None:
        self.data_pos = data_pos
        self._double = double
        self.accepted = False

      def button(self) -> Qt.MouseButton:
        return Qt.LeftButton

      def double(self) -> bool:
        return self._double

      def accept(self) -> None:
        self.accepted = True

    def on_click(data_x: float, data_y: float, is_double_click: bool) -> None:
      gate_calls.append((data_x, data_y, is_double_click))

    widget._get_data_position = lambda event: event.data_pos
    widget.on_mouse_clicked(on_click)
    widget.begin_gate_creation("polygon")

    click_event = FakeClickEvent((1.0, 2.0))
    double_event = FakeClickEvent((3.0, 4.0), double=True)
    widget._on_scene_mouse_click(click_event)
    widget._on_scene_mouse_click(double_event)

    assert click_event.accepted is True
    assert double_event.accepted is True
    assert gate_calls == [(1.0, 2.0, False), (3.0, 4.0, True)]
  finally:
    widget._get_data_position = original_get_data_position
    vb = widget._view_box()
    if vb is not None:
      vb.mouseClickEvent = widget._default_mouse_click_event
      vb.mouseDragEvent = widget._default_mouse_drag_event
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_log10_rectangle_drag_keeps_log_gate_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  original_get_data_position = widget._get_data_position
  try:
    calls: list[dict[str, float | bool]] = []

    class FakeDragEvent:
      def __init__(
        self,
        data_pos: tuple[float, float],
        *,
        start: bool = False,
        finish: bool = False,
      ) -> None:
        self.data_pos = data_pos
        self._start = start
        self._finish = finish

      def isStart(self) -> bool:
        return self._start

      def isFinish(self) -> bool:
        return self._finish

      def accept(self) -> None:
        pass

    widget.set_axis_transforms("log10", "log10")
    widget._get_data_position = lambda event: event.data_pos
    widget.on_mouse_clicked(
      lambda x, y, double, **kwargs: calls.append(
        {"x": x, "y": y, "double": double, **kwargs}
      )
    )
    widget.begin_gate_creation("rectangle")
    widget._on_mouse_drag(FakeDragEvent((2.0, 3.0), start=True))
    widget._on_mouse_drag(FakeDragEvent((4.0, 5.0), finish=True))

    assert calls == [{
      "x": 2.0, "y": 3.0, "double": False, "dragging": False,
      "rect_end_x": 4.0, "rect_end_y": 5.0,
    }]
  finally:
    widget._get_data_position = original_get_data_position
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_asinh_polygon_click_keeps_asinh_gate_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  original_get_data_position = widget._get_data_position
  try:
    calls: list[tuple[float, float]] = []

    class FakeClickEvent:
      def button(self) -> Qt.MouseButton:
        return Qt.LeftButton

      def double(self) -> bool:
        return False

      def accept(self) -> None:
        pass

    widget.set_axis_transforms("asinh", "asinh")
    widget._get_data_position = lambda _event: (np.arcsinh(12.0), np.arcsinh(-7.0))
    widget.on_mouse_clicked(lambda x, y, _double: calls.append((x, y)))
    widget.begin_gate_creation("polygon")
    widget._on_scene_mouse_click(FakeClickEvent())

    assert calls[0] == pytest.approx((np.arcsinh(12.0), np.arcsinh(-7.0)))
  finally:
    widget._get_data_position = original_get_data_position
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_log10_polygon_preview_uses_view_coordinates_once() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    widget.set_axis_transforms("log10", "log10")
    widget.plot_events(
      np.array([1.0, 10.0, 100.0]),
      np.array([1.0, 10.0, 100.0]),
    )
    widget.begin_gate_creation("polygon")
    widget.add_polygon_preview_vertex(1.0, 1.5)
    widget.add_polygon_preview_vertex(2.0, 2.5)

    preview = widget._preview_item
    assert preview is not None
    assert preview.opts["logMode"] == [False, False]
    np.testing.assert_allclose(preview._datasetMapped.x, [1.0, 2.0])
    np.testing.assert_allclose(preview._datasetMapped.y, [1.5, 2.5])
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_log10_rectangle_overlay_edit_keeps_log_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    x_transform = TransformSpec(
      id="log_x", name="Log X", transform_type="log", parameter="X",
      settings={"base": 10.0},
    )
    y_transform = TransformSpec(
      id="log_y", name="Log Y", transform_type="log", parameter="Y",
      settings={"base": 10.0},
    )
    gate = GateSpec(
      id="gate-log",
      name="log rectangle",
      gate_type="rectangle",
      x_parameter="X",
      y_parameter="Y",
      x_transform_id=x_transform.id,
      y_transform_id=y_transform.id,
      thresholds={
        "x_min": 2.0, "x_max": 4.0, "y_min": 3.0, "y_max": 5.0,
      },
    )
    updates: list[GateSpec] = []
    widget.set_axis_transform_specs(x_transform, y_transform)
    widget.set_axis_transforms("linear", "linear")
    widget.on_gate_geometry_changed(
      lambda _index, updated: updates.append(updated)
    )
    widget.add_gate_overlay(gate, gate_index=0)

    item = widget._gate_items[0]
    state = item.saveState()
    assert tuple(state["pos"]) == pytest.approx((2.0, 3.0))
    assert tuple(state["size"]) == pytest.approx((2.0, 2.0))
    item.setPos(3.0, 4.0)

    assert updates[-1].thresholds == pytest.approx({
      "x_min": 3.0, "x_max": 5.0, "y_min": 4.0, "y_max": 6.0,
    })
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_ellipse_gate_overlay_round_trips_data_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  gate = GateSpec(
    id="gate-ellipse",
    name="ellipse",
    gate_type="ellipse",
    x_parameter="X",
    y_parameter="Y",
    thresholds={
      "center_x": 12.5,
      "center_y": 20.0,
      "radius_x": 4.0,
      "radius_y": 8.0,
      "rotation": 0.25,
    },
  )
  try:
    widget.add_gate_overlay(gate, gate_index=0)
    assert len(widget._gate_items) == 1
    item = widget._gate_items[0]
    state = item.saveState()
    assert tuple(state["size"]) == pytest.approx((8.0, 16.0))
    assert state["angle"] == pytest.approx(np.degrees(0.25))
    center = item.mapToParent(item.state["size"][0] / 2, item.state["size"][1] / 2)
    assert (center.x(), center.y()) == pytest.approx((12.5, 20.0))
    assert widget._gate_from_item(gate, item).thresholds == pytest.approx(
      gate.thresholds
    )
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_main_window_polygon_create_gate_flow_finishes_on_double_click() -> None:
  app = _app()
  window = MainWindow()
  original_get_data_position = window._plot_widget._get_data_position
  try:
    window._current_sample_id = "sample-1"
    window._gate_editor.set_plot_channels("FSC-A", "SSC-A")
    window._plot_widget._get_data_position = lambda event: event.data_pos

    class FakeClickEvent:
      def __init__(self, data_pos: tuple[float, float], double: bool = False) -> None:
        self.data_pos = data_pos
        self._double = double
        self.accepted = False

      def button(self) -> Qt.MouseButton:
        return Qt.LeftButton

      def double(self) -> bool:
        return self._double

      def accept(self) -> None:
        self.accepted = True

    assert window._on_interactive_gate_requested("polygon") is True
    window._plot_widget._on_scene_mouse_click(FakeClickEvent((1.0, 1.0)))
    window._plot_widget._on_scene_mouse_click(FakeClickEvent((5.0, 1.0)))
    window._plot_widget._on_scene_mouse_click(FakeClickEvent((3.0, 4.0), double=True))

    gates = window._gate_editor.gates()
    assert len(gates) == 1
    assert gates[0].gate_type == "polygon"
    assert gates[0].x_parameter == "FSC-A"
    assert gates[0].y_parameter == "SSC-A"
    assert gates[0].coordinates == ((1.0, 1.0), (5.0, 1.0), (3.0, 4.0))
    assert window._gate_editor.is_collecting_polygon() is False
  finally:
    window._plot_widget._get_data_position = original_get_data_position
    window.close()
    window.deleteLater()
    app.processEvents()


def test_polygon_gate_overlay_uses_editable_polyline_roi() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-1",
      name="poly",
      gate_type="polygon",
      x_parameter="FSC-A",
      y_parameter="SSC-A",
      coordinates=((1.0, 1.0), (5.0, 1.0), (3.0, 4.0)),
    )

    widget.add_gate_overlay(gate, gate_index=0)

    assert len(widget._gate_items) == 1
    item = widget._gate_items[0]
    assert item.__class__.__name__ == "PolyLineROI"
    assert item.closed is True
    assert len(item.getHandles()) == 3
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_log_polygon_is_editable_only_on_matching_display_scale() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    x_transform = TransformSpec(
      id="log_x", name="Log X", transform_type="log", parameter="X",
      settings={"base": 10.0},
    )
    y_transform = TransformSpec(
      id="log_y", name="Log Y", transform_type="log", parameter="Y",
      settings={"base": 10.0},
    )
    gate = GateSpec(
      id="gate-log",
      name="log gate",
      gate_type="polygon",
      x_parameter="X",
      y_parameter="Y",
      x_transform_id=x_transform.id,
      y_transform_id=y_transform.id,
      coordinates=((2.0, 3.0), (4.0, 3.0), (3.0, 5.0)),
    )
    widget.set_axis_transforms("linear", "linear")
    widget.add_gate_overlay(gate, gate_index=0)
    assert widget._gate_items == []

    widget.set_axis_transform_specs(x_transform, y_transform)
    widget.set_axis_transforms("linear", "linear")
    widget.add_gate_overlay(gate, gate_index=0)
    item = widget._gate_items[0]
    assert item.__class__.__name__ == "PolyLineROI"
    assert len(item.getHandles()) == 3
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_linear_polygon_is_hidden_on_log_display_without_rewrite() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-linear",
      name="linear gate",
      gate_type="polygon",
      x_parameter="X",
      y_parameter="Y",
      coordinates=((1.0, 1.0), (100.0, 20.0), (10.0, 100.0)),
    )
    widget.set_axis_transforms("log10", "asinh")
    widget.add_gate_overlay(gate, gate_index=0)
    assert widget._gate_items == []

    widget.set_axis_transforms("linear", "linear")
    widget.add_gate_overlay(gate, gate_index=0)
    assert widget._gate_items[0].__class__.__name__ == "PolyLineROI"
    assert gate.coordinates == ((1.0, 1.0), (100.0, 20.0), (10.0, 100.0))
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_plot_widget_uses_core_logicle_coordinates_ticks_and_gate_ids() -> None:
  app = _app()
  widget = PlotWidget()
  x_transform = TransformSpec(
    id="logicle_x",
    name="Logicle X",
    transform_type="logicle",
    parameter="X",
    settings={
      "T": 262144.0,
      "W": 0.5,
      "M": 4.5,
      "A": 0.0,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
  )
  y_transform = TransformSpec(
    id="logicle_y",
    name="Logicle Y",
    transform_type="logicle",
    parameter="Y",
    settings=dict(x_transform.settings),
  )
  raw = np.array([-100.0, 0.0, 100.0, 262144.0], dtype=np.float64)
  try:
    widget.set_axis_transform_specs(x_transform, y_transform)
    widget.plot_events(raw, raw, x_label="X", y_label="Y")

    expected = apply_transform(x_transform, raw)
    np.testing.assert_allclose(widget._scatter.xData, expected, atol=1e-12)
    assert {tick.event_value for tick in widget.axis_ticks("x")} >= {
      0.0,
      262144.0,
    }

    gate = GateSpec(
      id="logicle_gate",
      name="Logicle gate",
      gate_type="rectangle",
      x_parameter="X",
      y_parameter="Y",
      x_transform_id=x_transform.id,
      y_transform_id=y_transform.id,
      thresholds={
        "x_min": float(expected[0]),
        "x_max": float(expected[2]),
        "y_min": float(expected[0]),
        "y_max": float(expected[2]),
      },
    )
    widget.add_gate_overlay(gate)
    polygon = GateSpec(
      id="logicle_polygon",
      name="Logicle polygon",
      gate_type="polygon",
      x_parameter="X",
      y_parameter="Y",
      x_transform_id=x_transform.id,
      y_transform_id=y_transform.id,
      coordinates=(
        (float(expected[0]), float(expected[0])),
        (float(expected[2]), float(expected[0])),
        (float(expected[2]), float(expected[2])),
        (float(expected[0]), float(expected[2])),
      ),
    )
    widget.add_gate_overlay(polygon)
    assert len(widget._gate_items) == 2

    _results, masks = evaluate_gating_strategy_with_membership(
      GatingStrategySpec(
        id="logicle_strategy",
        name="Logicle strategy",
        gates=(gate, polygon),
      ),
      np.column_stack((raw, raw)),
      ["X", "Y"],
      transforms=(x_transform, y_transform),
    )
    assert masks[gate.id].tolist() == [True, True, True, False]
    assert masks[polygon.id].tolist() == [True, True, True, False]
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_plot_widget_formats_exponent_ticks_and_applies_readable_tick_style() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    assert widget._format_tick_label("1e+06") == "10⁶"
    assert widget._format_tick_label("1.0e+06") == "10⁶"
    assert widget._format_tick_label("-2.5e-03") == "-2.5 × 10⁻³"
    assert widget._format_tick_label("-1e-03") == "-1 × 10⁻³"
    assert widget._format_tick_label("0") == "0"
    assert widget._foreground_color("#ffffff") == "#000000"
    assert widget._foreground_color("#000000") == "#e8e8e8"
    axis = widget._plot_item.getAxis("bottom")
    assert "⁶" in axis.tickStrings([1_000_000.0], 1.0, 1_000_000.0)[0]
    widget.resize(320, 240)
    widget.show()
    app.processEvents()
    fitted = widget._fit_tick_labels(
      "bottom",
      [0.0, 0.01, 0.02, 0.03, 0.04],
      ["1 × 10⁶"] * 5,
      axis,
    )
    assert sum(bool(label) for label in fitted) < len(fitted)
    widget.set_presentation({
      "title": "Sample title",
      "title_font": {"family": "DejaVu Sans", "size": 24, "weight": "normal"},
      "tick_font": {"family": "DejaVu Sans", "size": 16, "weight": "bold"},
      "axis_line_width": 3.0,
    })
    assert widget._plot_item.titleLabel.text == "Sample title"
    assert widget._plot_item.titleLabel.opts["size"] == "24pt"
    assert widget._plot_item.titleLabel.opts["bold"] is False
    assert widget.style().tick_font_size == 16
    assert widget.style().tick_font_weight == "bold"
    assert widget.style().axis_line_width == 3.0
    widget.set_presentation({"title": "A\nB"})
    assert widget._plot_item.titleLabel.text == "A<br/>B"
    widget.set_presentation(
      {"title": "A\nB"}, title_colors=("#0000ff", "#ffff00")
    )
    assert widget._plot_item.titleLabel.text == (
      '<span style="color:#0000ff">A</span><br/>'
      '<span style="color:#ffff00">B</span>'
    )
    assert widget._plot_item.titleLabel.maximumHeight() > 30
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_log_axis_tick_policy_can_switch_and_restore_legacy_auto() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    widget.set_axis_transforms("log10", "log10")
    values = np.array([3e5, 5e5, 1e6, 2e6, 3e6], dtype=np.float64)
    widget.plot_events(values, values, "FSC-A", "SSC-A")
    widget.set_manual_view_range((4.0, 8.0), (4.0, 8.0))
    assert {tick.event_value for tick in widget.axis_ticks("x")} >= {
      1e4, 1e8,
    }
    assert widget.tick_policy() == "auto"
    assert any(tick.event_value == 1e6 for tick in widget.axis_ticks("x"))
    assert any(tick.level == "minor" for tick in widget.axis_ticks("x"))

    widget.set_tick_policy("decades")
    assert all(tick.level == "major" for tick in widget.axis_ticks("x"))
    widget.set_tick_policy("legacy_auto")
    assert widget.axis_ticks("x") == ()
    menu = widget._build_context_menu()
    assert menu.findChild(QMenu, "plotAxisTicksMenu") is not None
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_gui_created_logicle_rectangle_binds_ids_and_matches_headless() -> None:
  app = _app()
  window = MainWindow()
  x_transform = TransformSpec(
    id="logicle_x",
    name="Logicle X",
    transform_type="logicle",
    parameter="X",
    settings={
      "T": 262144.0, "W": 0.5, "M": 4.5, "A": 0.0,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
  )
  y_transform = TransformSpec(
    id="logicle_y",
    name="Logicle Y",
    transform_type="logicle",
    parameter="Y",
    settings=dict(x_transform.settings),
  )
  raw = np.array([-100.0, 0.0, 100.0, 1000.0])
  coordinates = apply_transform(x_transform, raw)
  try:
    window._transforms = [asdict(x_transform), asdict(y_transform)]
    window._current_sample_id = "sample"
    window._event_data["sample"] = np.column_stack((raw, raw))
    window._channel_names = ["X", "Y"]
    window._channel_selector.set_channels(["X", "Y"])
    window._replot()
    window._create_rectangle_gate(
      float(coordinates[0]), float(coordinates[0]),
      float(coordinates[2]), float(coordinates[2]),
    )

    gate = window._gate_editor.gates()[0]
    assert gate.x_transform_id == x_transform.id
    assert gate.y_transform_id == y_transform.id
    _results, masks = evaluate_gating_strategy_with_membership(
      GatingStrategySpec(id="s", name="s", gates=(gate,)),
      window._event_data["sample"],
      ["X", "Y"],
      transforms=(x_transform, y_transform),
    )
    assert masks[gate.id].tolist() == [True, True, True, False]
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_gui_created_rectangle_uses_active_display_coordinate_context() -> None:
  """New gates use the same coordinates as the plot that received the drag."""
  app = _app()
  window = MainWindow()
  try:
    window._current_sample_id = "sample"
    window._channel_names = ["X", "Y"]
    window._channel_selector.set_channels(["X", "Y"])
    transform = TransformSpec(
      id="log_x", name="Log X", transform_type="log", parameter="X",
      settings={"base": 10.0},
    )
    window._gate_editor.set_plot_scales("linear", "linear")
    window._gate_editor.set_plot_transforms(transform.id, None)

    window._create_rectangle_gate(2.0, 10.0, 4.0, 20.0)

    gate = window._gate_editor.gates()[0]
    assert gate.x_transform_id == transform.id
    assert gate.y_transform_id is None
    window._plot_widget.set_axis_transform_specs(transform, None)
    window._plot_widget.set_axis_transforms("linear", "linear")
    window._plot_widget.add_gate_overlay(gate)
    assert len(window._plot_widget._gate_items) == 1
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_gui_created_logicle_polygon_binds_ids_and_matches_headless() -> None:
  app = _app()
  editor = GateEditor()
  transform = TransformSpec(
    id="logicle_signal",
    name="Logicle signal",
    transform_type="logicle",
    parameter="X",
    settings={
      "T": 262144.0, "W": 0.5, "M": 4.5, "A": 0.0,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
  )
  raw = np.array([-100.0, 0.0, 100.0, 1000.0])
  coordinates = apply_transform(transform, raw)
  try:
    editor.set_plot_channels("X", "Y")
    editor.set_plot_scales("linear", "linear")
    editor.set_plot_transforms(transform.id, "logicle_y")
    editor.start_polygon_collection()
    for point in (
      (coordinates[0], coordinates[0]),
      (coordinates[2], coordinates[0]),
      (coordinates[2], coordinates[2]),
      (coordinates[0], coordinates[2]),
    ):
      editor.receive_polygon_vertex(float(point[0]), float(point[1]))
    editor.finish_polygon_gate("GUI polygon")

    gate = editor.gates()[0]
    y_transform = TransformSpec(
      id="logicle_y",
      name="Logicle Y",
      transform_type="logicle",
      parameter="Y",
      settings=dict(transform.settings),
    )
    assert gate.x_transform_id == transform.id
    assert gate.y_transform_id == y_transform.id
    _results, masks = evaluate_gating_strategy_with_membership(
      GatingStrategySpec(id="s", name="s", gates=(gate,)),
      np.column_stack((raw, raw)),
      ["X", "Y"],
      transforms=(transform, y_transform),
    )
    assert masks[gate.id].tolist() == [True, True, True, False]
  finally:
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_polygon_roi_edit_emits_updated_gate_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-1",
      name="poly",
      gate_type="polygon",
      x_parameter="FSC-A",
      y_parameter="SSC-A",
      coordinates=((1.0, 1.0), (5.0, 1.0), (3.0, 4.0)),
    )
    updates: list[tuple[int, GateSpec]] = []
    widget.on_gate_geometry_changed(
      lambda index, updated_gate: updates.append((index, updated_gate))
    )
    widget.add_gate_overlay(gate, gate_index=2)

    item = widget._gate_items[0]
    item.setPos(10.0, 20.0)

    assert updates[-1] == (
      2,
      GateSpec(
        id="gate-1",
        name="poly",
        gate_type="polygon",
        x_parameter="FSC-A",
        y_parameter="SSC-A",
        coordinates=((11.0, 21.0), (15.0, 21.0), (13.0, 24.0)),
      ),
    )
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_gate_editor_defined_gate_item_rename_updates_gate_name() -> None:
  app = _app()
  editor = GateEditor()
  try:
    gate = GateSpec(
      id="gate-1",
      name="old_name",
      gate_type="polygon",
      x_parameter="FSC-A",
      y_parameter="SSC-A",
      coordinates=((1.0, 1.0), (5.0, 1.0), (3.0, 4.0)),
    )

    editor.add_gate(gate)
    item = editor._list_widget.item(0)
    item.setText("new_name")
    app.processEvents()
    gates = editor.gates()
    assert len(gates) == 1
    assert gates[0].name == "new_name"
    assert item.text() == "new_name (polygon)"
  finally:
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_geometric_gate_numeric_editor_round_trips_ellipse_and_polygon() -> None:
  app = _app()
  ellipse = GateSpec(
    id="ellipse-1",
    name="ellipse",
    gate_type="ellipse",
    x_parameter="FSC-A",
    y_parameter="SSC-A",
    thresholds={
      "center_x": 12.5,
      "center_y": 20.0,
      "radius_x": 4.0,
      "radius_y": 8.0,
      "rotation": 0.25,
    },
  )
  polygon = GateSpec(
    id="polygon-1",
    name="polygon",
    gate_type="polygon",
    x_parameter="FSC-A",
    y_parameter="SSC-A",
    coordinates=((1.0, 2.0), (5.0, 2.0), (3.0, 6.0)),
  )
  dialogs = []
  try:
    ellipse_dialog = _GateDialog("ellipse", "FSC-A", "SSC-A", initial_gate=ellipse)
    ellipse_dialog._collect_ok_values()
    assert ellipse_dialog.thresholds() == ellipse.thresholds
    dialogs.append(ellipse_dialog)

    polygon_dialog = _GateDialog("polygon", "FSC-A", "SSC-A", initial_gate=polygon)
    polygon_dialog._collect_ok_values()
    assert polygon_dialog.coordinates() == list(polygon.coordinates)
    dialogs.append(polygon_dialog)
  finally:
    for dialog in dialogs:
      dialog.deleteLater()
    app.processEvents()


def test_boolean_expression_json_editor_round_trips_nested_tree() -> None:
  app = _app()
  dialog = _GateDialog("boolean", "X", "Y")
  try:
    expression = {
      "op": "or",
      "children": [
        {"op": "ref", "id": "a"},
        {"op": "not", "child": {"op": "ref", "id": "b"}},
      ],
    }
    dialog._expression_edit.setPlainText(json.dumps(expression))
    dialog._collect_ok_values()
    assert dialog.thresholds()["expression"] == expression
    dialog._expression_edit.setPlainText("{")
    dialog._collect_ok_values()
    assert dialog._expression_error
  finally:
    dialog.deleteLater()
    app.processEvents()


def test_numeric_ellipse_editor_stores_display_values_in_asinh_gate_coordinates() -> None:
  app = _app()
  dialog = _GateDialog(
    "ellipse", "FSC-A", "SSC-A", x_scale="asinh", y_scale="asinh"
  )
  try:
    dialog._center_x.setValue(100.0)
    dialog._center_y.setValue(200.0)
    dialog._radius_x.setValue(20.0)
    dialog._radius_y.setValue(30.0)
    dialog._collect_ok_values()
    values = dialog.thresholds()
    assert values["center_x"] == pytest.approx(np.arcsinh(100.0), rel=1e-6)
    assert values["center_y"] == pytest.approx(np.arcsinh(200.0), rel=1e-6)
    assert values["radius_x"] > 0
    assert values["radius_x"] < np.arcsinh(20.0)
  finally:
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_sample_browser_skips_duplicate_path_and_releases_on_remove(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  app = _app()
  browser = SampleBrowser()
  try:
    path = tmp_path / "a.fcs"
    path.write_text("not real fcs")
    monkeypatch.setattr("flowdesk_qt.sample_browser.read_fcs_info", lambda _path: _fcs_info())

    assert browser.add_samples_from_paths([str(path)]) == 1
    assert browser.add_samples_from_paths([str(path)]) == 0
    assert len(browser.samples()) == 1

    browser._list_widget.setCurrentRow(0)
    removed = browser.remove_selected_sample()
    assert removed is not None
    assert browser.add_samples_from_paths([str(path)]) == 1
  finally:
    browser.close()
    browser.deleteLater()
    app.processEvents()


def test_sample_browser_same_stem_different_paths_get_unique_ids(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  app = _app()
  browser = SampleBrowser()
  try:
    p1 = tmp_path / "one" / "same.fcs"
    p2 = tmp_path / "two" / "same.fcs"
    p1.parent.mkdir()
    p2.parent.mkdir()
    p1.write_text("a")
    p2.write_text("b")
    monkeypatch.setattr("flowdesk_qt.sample_browser.read_fcs_info", lambda _path: _fcs_info())

    assert browser.add_samples_from_paths([str(p1), str(p2)]) == 2
    ids = [sample.id for sample in browser.samples()]
    assert len(set(ids)) == 2
    assert all(sample.name == "same" for sample in browser.samples())
  finally:
    browser.close()
    browser.deleteLater()
    app.processEvents()


def test_sample_browser_metadata_columns_filter_and_mismatch_badges(
  tmp_path: Path,
) -> None:
  app = _app()
  browser = SampleBrowser()
  metadata = ChannelMetadataWorkspace()
  try:
    first = tmp_path / "alpha.fcs"
    second = tmp_path / "beta.fcs"
    write_fcs_file(first, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    write_fcs_file(second, np.ones((2, 2), dtype=np.float64), ["X", "Z"])

    assert browser.add_samples_from_paths([str(first), str(second)]) == 2
    assert browser.samples()[1].status == "channel mismatch"
    row = browser._list_widget.itemWidget(browser._list_widget.item(1))
    assert row is not None
    label = row.findChild(QLabel, f"sampleName_{browser.samples()[1].id}")
    assert label is not None and "[≠]" in label.text()
    assert [
      browser._sample_header.findChild(QLabel, object_name).text()
      for object_name in (
        "sampleHeaderOv", "sampleHeaderCol", "sampleHeaderName", "sampleHeaderRel"
      )
    ] == ["Ov", "Col", "Name", "Rel"]
    assert browser._list_widget.item(1).text() == ""

    metadata.set_sample(browser.samples()[0])
    metadata.set_column_visible("id", True)
    assert not metadata.table.isColumnHidden(0)
    browser._filter_edit.setText("alpha")
    assert not browser._list_widget.item(0).isHidden()
    assert browser._list_widget.item(1).isHidden()
  finally:
    browser.close()
    browser.deleteLater()
    metadata.close()
    metadata.deleteLater()
    app.processEvents()


def test_sample_browser_manual_overlay_column_is_separate_from_active_selection(
  tmp_path: Path,
) -> None:
  app = _app()
  browser = SampleBrowser()
  try:
    first = tmp_path / "active.fcs"
    second = tmp_path / "overlay.fcs"
    write_fcs_file(first, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    write_fcs_file(second, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    assert browser.add_samples_from_paths([str(first), str(second)]) == 2
    browser.select_sample(browser.samples()[0].id)
    row = browser._list_widget.itemWidget(browser._list_widget.item(1))
    assert row is not None
    checkbox = row.findChild(QCheckBox)
    assert checkbox is not None
    checkbox.setChecked(True)
    assert browser.overlay_state()["manual_overlay_sample_ids"] == [browser.samples()[1].id]
    browser.select_sample(browser.samples()[1].id)
    active_row = browser._list_widget.itemWidget(browser._list_widget.item(1))
    active_checkbox = active_row.findChild(QCheckBox)
    active_swatch = active_row.findChild(
      QPushButton, f"overlayColor_{browser.samples()[1].id}"
    )
    assert active_checkbox is not None and not active_checkbox.isEnabled()
    assert active_swatch is not None and not active_swatch.isEnabled()
    assert active_row.findChild(
      QLabel, f"overlayRelation_{browser.samples()[1].id}"
    ).text() == "active"
    assert browser.overlay_state()["manual_overlay_sample_ids"] == [browser.samples()[1].id]
  finally:
    browser.close()
    browser.deleteLater()
    app.processEvents()


def test_sample_browser_stays_visible_when_narrowed_and_keeps_details_in_tooltip(
  tmp_path: Path,
) -> None:
  app = _app()
  window = MainWindow()
  try:
    browser = window._sample_browser
    splitter = window.findChild(QSplitter, "mainContentSplitter")
    assert splitter is not None
    assert browser.minimumWidth() == window.LEFT_PANE_MIN_WIDTH
    assert not splitter.isCollapsible(0)
    sample_path = tmp_path / "compact.fcs"
    write_fcs_file(sample_path, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    assert browser.add_samples_from_paths([str(sample_path)]) == 1
    splitter.setSizes([window.LEFT_PANE_MIN_WIDTH, 900])
    app.processEvents()
    assert splitter.sizes()[0] >= window.LEFT_PANE_MIN_WIDTH

    item = browser._list_widget.item(0)
    assert item is not None and "events" in item.toolTip()
    assert "compact" in item.toolTip()
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_manual_overlay_loads_checked_sample_and_uses_its_color(tmp_path: Path) -> None:
  app = _app()
  window = MainWindow()
  try:
    first = tmp_path / "active.fcs"
    second = tmp_path / "overlay.fcs"
    values = np.array([[1.0, 2.0], [2.0, 3.0]], dtype=np.float64)
    write_fcs_file(first, values, ["X", "Y"])
    write_fcs_file(second, values * 2.0, ["X", "Y"])
    assert window._sample_browser.add_samples_from_paths([str(first), str(second)]) == 2
    active, overlay = window._sample_browser.samples()
    assert window._sample_browser.select_sample(active.id)
    assert overlay.id not in window._event_data
    window._sample_browser._manual_overlay_colors[overlay.id] = "#ff0000"
    window._sample_browser._set_manual_overlay(overlay.id, True)
    for _ in range(200):
      if len(window._plot_widget._overlay_scatter_items) == 1:
        break
      QTest.qWait(5)
    assert overlay.id in window._event_data
    assert len(window._plot_widget._overlay_scatter_items) == 1
    brush = window._plot_widget._overlay_scatter_items[0].scatter.opts["brush"]
    assert brush.color().name() == "#ff0000"
    window._sample_browser._clear_overlay_color(overlay.id)
    app.processEvents()
    brush = window._plot_widget._overlay_scatter_items[0].scatter.opts["brush"]
    assert brush.color().name() == "#4c78a8"
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_sample_browser_comparison_set_and_overlay_mode_union(
  tmp_path: Path,
) -> None:
  app = _app()
  browser = SampleBrowser()
  try:
    paths = [tmp_path / f"sample-{index}.fcs" for index in range(3)]
    for path in paths:
      write_fcs_file(path, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    assert browser.add_samples_from_paths([str(path) for path in paths]) == 3
    ids = [sample.id for sample in browser.samples()]
    browser._comparison_sets = [{
      "id": "pair_001",
      "name": "Pair",
      "members": [
        {"sample_id": ids[0], "role": "reference"},
        {"sample_id": ids[1], "role": "target"},
      ],
    }]
    browser._overlay_mode = "manual_plus_comparison"
    assert browser.comparison_overlay_sample_ids(ids[0]) == {ids[1]}
    assert browser.comparison_overlay_sample_ids(ids[2]) == set()
  finally:
    browser.close()
    browser.deleteLater()
    app.processEvents()


def test_sample_browser_overlay_state_round_trips_without_active_selection_change(
  tmp_path: Path,
) -> None:
  app = _app()
  browser = SampleBrowser()
  restored = SampleBrowser()
  try:
    paths = [tmp_path / f"roundtrip-{index}.fcs" for index in range(2)]
    for path in paths:
      write_fcs_file(path, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    assert browser.add_samples_from_paths([str(path) for path in paths]) == 2
    ids = [sample.id for sample in browser.samples()]
    browser.set_overlay_state(
      [ids[1]], {ids[1]: "#123456"}, {ids[1]: "positive_control"},
      [{"id": "pair", "members": [{"sample_id": ids[0]}, {"sample_id": ids[1]}]}],
      "manual_plus_comparison",
    )
    browser.select_sample(ids[0])
    state = browser.overlay_state()
    assert browser.selected_sample().id == ids[0]
    assert state["manual_overlay_colors"] == {ids[1]: "#123456"}
    assert state["overlay_mode"] == "manual_plus_comparison"
    assert restored.add_samples_from_paths([str(path) for path in paths]) == 2
    restored.set_overlay_state(
      state["manual_overlay_sample_ids"], state["manual_overlay_colors"],
      state["overlay_roles"], state["comparison_sets"], state["overlay_mode"],
    )
    assert restored.overlay_state() == state
  finally:
    browser.close()
    restored.close()
    browser.deleteLater()
    restored.deleteLater()
    app.processEvents()


def test_sample_browser_reconnect_requires_confirmation_on_hash_mismatch(
  tmp_path: Path,
) -> None:
  app = _app()
  browser = SampleBrowser()
  try:
    original = tmp_path / "original.fcs"
    identical = tmp_path / "identical.fcs"
    changed = tmp_path / "changed.fcs"
    write_fcs_file(original, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    assert browser.add_samples_from_paths([str(original)]) == 1
    source = browser.samples()[0]
    shutil.copyfile(original, identical)
    write_fcs_file(changed, np.zeros((2, 2), dtype=np.float64), ["X", "Y"])
    project_sample = {
      "id": source.id,
      "name": source.name,
      "path": str(tmp_path / "missing.fcs"),
      "fingerprint": source.fingerprint.to_mapping(),
      "channels": [asdict(channel) for channel in source.info.channels],
    }

    browser.clear_samples()
    assert browser.add_project_samples([project_sample]) == 1
    restored = browser.samples()[0]
    assert restored.status == "missing"
    accepted, details = browser.reconnect_sample(restored.id, identical)
    assert accepted, details

    accepted, details = browser.reconnect_sample(restored.id, changed)
    assert not accepted
    assert "DIFFERENT" in details
    accepted, _ = browser.reconnect_sample(restored.id, changed, allow_mismatch=True)
    assert accepted
  finally:
    browser.close()
    browser.deleteLater()
    app.processEvents()


def test_channel_selection_preserved_when_sample_channels_match() -> None:
  app = _app()
  window = MainWindow()
  try:
    info = _fcs_info(("A", "B", "C"))
    sample1 = type("Sample", (), {"id": "s1", "name": "s1", "info": info, "path": ""})()
    sample2 = type("Sample", (), {"id": "s2", "name": "s2", "info": info, "path": ""})()
    window._event_data = {
      "s1": np.ones((3, 3), dtype=np.float64),
      "s2": np.ones((3, 3), dtype=np.float64),
    }

    window._on_sample_selected(sample1)
    window._channel_selector._x_combo.setCurrentText("B")
    window._channel_selector._y_combo.setCurrentText("C")
    window._on_sample_selected(sample2)

    assert window._channel_selector.x_channel() == "B"
    assert window._channel_selector.y_channel() == "C"
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_manual_view_range_survives_replot() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    x = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    y = np.array([4.0, 5.0, 6.0], dtype=np.float64)
    widget.plot_events(x, y)
    widget.set_manual_view_range((10.0, 20.0), (30.0, 40.0))
    widget.plot_events(x + 100.0, y + 100.0)

    assert widget.range_mode() == "manual"
    assert widget.view_range() == ((10.0, 20.0), (30.0, 40.0))
  finally:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_gate_geometry_change_marks_population_results_stale() -> None:
  app = _app()
  window = MainWindow()
  try:
    report = ExecutionReport(
      project_id="p1",
      execution_profile_id="default",
      pipeline_version="0.1",
      status="success",
      population_results=(
        PopulationResult("s1", "all_events", 4, None, 1.0),
      ),
    )
    window._population_tree.set_report(report)
    window._results_stale = False
    gate = GateSpec(
      id="gate-1",
      name="gate",
      gate_type="rectangle",
      x_parameter="FSC-A",
      y_parameter="SSC-A",
      thresholds={"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
    )
    window._gate_editor.add_gate(gate)
    window._results_stale = False
    window._population_tree.set_report(report)

    updated = GateSpec(
      id="gate-1",
      name="gate",
      gate_type="rectangle",
      x_parameter="FSC-A",
      y_parameter="SSC-A",
      thresholds={"x_min": 1.0, "x_max": 2.0, "y_min": 1.0, "y_max": 2.0},
    )
    window._replot = lambda: pytest.fail(
      "finished ROI edits must wait for the preview instead of replotting twice"
    )
    window._on_gate_geometry_changed(0, updated)

    assert window._gate_editor.gates()[0].thresholds["x_min"] == 1.0
    assert window._results_stale is True
    assert window._population_tree.last_report() is None
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_project_manifest_flushes_pending_polygon_roi_edit() -> None:
  app = _app()
  window = MainWindow()
  try:
    editor = window._gate_editor
    editor.set_plot_channels("X", "Y")
    editor.start_polygon_collection()
    for point in ((1.0, 1.0), (5.0, 1.0), (3.0, 4.0)):
      editor.receive_polygon_vertex(*point)
    editor.finish_polygon_gate("polygon")
    gate = editor.gates()[0]
    updated = replace(
      gate,
      coordinates=((2.0, 2.0), (6.0, 2.0), (4.0, 5.0)),
    )

    window._queue_gate_geometry_changed(0, updated)
    manifest = window._build_project_manifest()

    saved_gate = manifest["gating_strategies_data"]["default_strategy"]["gates"][0]
    assert saved_gate["coordinates"] == updated.coordinates
    assert editor.gates()[0].coordinates == updated.coordinates
    assert window._pending_gate_geometry_updates == {}
    assert editor.undo()
    assert editor.gates()[0].coordinates == gate.coordinates
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_population_results_export_uses_core_export(tmp_path: Path) -> None:
  app = _app()
  window = MainWindow()
  try:
    report = ExecutionReport(
      project_id="p1",
      execution_profile_id="default",
      pipeline_version="0.1",
      status="success",
      population_results=(
        PopulationResult("s1", "gate-1", 2, 0.5, 0.5),
      ),
    )
    window._population_tree.set_report(report)
    window._results_stale = False
    out = tmp_path / "results.tsv"

    window._export_population_results_to_path(out)

    assert out.read_text().splitlines() == [
      "sample_id\tpopulation_id\tmetric\tvalue",
      "s1\tgate-1\tevent_count\t2",
      "s1\tgate-1\tfrequency_of_parent\t0.5",
      "s1\tgate-1\tfrequency_of_total\t0.5",
    ]
  finally:
    window.close()
    window.deleteLater()
    app.processEvents()


def test_boolean_gate_runs_through_gating_strategy_without_parameter() -> None:
  data = np.array(
    [
      [1.0, 1.0],
      [2.0, 2.0],
      [3.0, 3.0],
      [4.0, 4.0],
    ],
    dtype=np.float64,
  )
  gate_a = GateSpec(
    id="a",
    name="a",
    gate_type="range",
    parent_population_id="all_events",
    x_parameter="FSC-A",
    thresholds={"min": 2.0},
  )
  gate_b = GateSpec(
    id="b",
    name="b",
    gate_type="range",
    parent_population_id="all_events",
    x_parameter="SSC-A",
    thresholds={"max": 3.0},
  )
  gate_and = GateSpec(
    id="a_and_b",
    name="a_and_b",
    gate_type="boolean",
    parent_population_id="all_events",
    thresholds={"operation": "and", "source_ids": ["a", "b"]},
  )

  results = evaluate_gating_strategy(
    GatingStrategySpec(id="s", name="s", gates=(gate_a, gate_b, gate_and)),
    data,
    ["FSC-A", "SSC-A"],
  )

  counts = {result.population_id: result.event_count for result in results}
  assert counts["a_and_b"] == 2


def test_gate_editor_rejects_invalid_dependencies_and_referenced_delete(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  app = _app()
  editor = GateEditor()
  warnings: list[str] = []
  monkeypatch.setattr(
    "flowdesk_qt.gate_editor.QMessageBox.warning",
    lambda _parent, _title, message: warnings.append(message),
  )
  parent = GateSpec(
    id="parent",
    name="parent",
    gate_type="range",
    parent_population_id="all_events",
    x_parameter="x",
    thresholds={"min": 0.0},
  )
  child = GateSpec(
    id="child",
    name="child",
    gate_type="range",
    parent_population_id="parent",
    x_parameter="x",
    thresholds={"min": 1.0},
  )
  try:
    editor.set_gates([parent, child])
    editor._list_widget.setCurrentRow(0)
    editor._delete_selected_gate()
    assert [gate.id for gate in editor.gates()] == ["parent", "child"]
    assert "referenced by: child" in warnings[0]

    invalid = GateSpec(
      id="invalid",
      name="invalid",
      gate_type="boolean",
      thresholds={"operation": "not", "source_ids": ["missing"]},
    )
    with pytest.raises(GatingStrategyError, match="unknown source"):
      editor.set_gates([invalid])
  finally:
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_gui_project_save_reload_and_headless_results_match(tmp_path: Path) -> None:
  app = _app()
  fcs_path = tmp_path / "sample.fcs"
  events = np.array([[0.0, 1.0], [2.0, 1.0], [3.0, 1.0]], dtype=np.float64)
  write_fcs_file(fcs_path, events, ["X", "Y"])
  project_path = tmp_path / "saved.flowdesk"

  window = MainWindow()
  reloaded_window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    window._channel_selector.set_x_transform("asinh")
    gate = GateSpec(
      id="positive",
      name="positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter=sample.info.channels[0].id,
      thresholds={"min": 1.0},
    )
    window._gate_editor.set_gates([gate])
    window._annotations = [{
      "sample_id": sample.id,
      "keyword": "Condition",
      "value": "treated",
      "source": "workspace",
    }]
    window._channel_selector._display_max_points_spin.setValue(12_345)
    saved_viewport = ((0.5, 2.5), (0.25, 1.75))
    window._plot_widget.set_manual_view_range(*saved_viewport)
    assert not window.action_advanced_groups.isChecked()
    assert window._group_panel.isHidden()
    window.action_advanced_groups.setChecked(True)
    assert not window._group_panel.isHidden()
    gui_manifest = window._build_project_manifest()
    simple_assignments = PipelineRunner(gui_manifest).resolve_group_assignments()
    window.action_advanced_groups.setChecked(True)
    advanced_manifest = window._build_project_manifest()
    advanced_assignments = PipelineRunner(advanced_manifest).resolve_group_assignments()
    assert advanced_assignments == simple_assignments
    gui_report = PipelineRunner(gui_manifest).run_samples(
      ExecutionContext(),
      tuple(window._sample_data.values()),
    )

    window._save_project_to_path(project_path)
    saved = load_project(project_path)
    assert saved["transforms"] == []
    assert saved["advanced_groups_enabled"] is True
    assert saved["sample_groups"][0]["id"] == "all-samples"
    assert saved["annotations"][0]["value"] == "treated"
    assert saved["plot_display_settings"]["x_scale"] == "asinh"
    assert saved["plot_display_settings"]["display_max_points"] == 12_345
    assert saved["plot_views"][0]["rendering_downsample"] == {
      "max_points": 12_345
    }
    assert saved["plot_views"][0]["display_scene"]["view_range"] == [
      list(saved_viewport[0]), list(saved_viewport[1]),
    ]
    assert isinstance(
      saved["gating_strategies_data"]["default_strategy"]["gates"][0], dict
    )

    reloaded_window._load_project_from_path(project_path)
    for _ in range(20):
      app.processEvents()
      if np.allclose(reloaded_window._plot_widget.view_range(), saved_viewport):
        break
      QTest.qWait(20)
    assert reloaded_window._channel_selector.display_max_points() == 12_345
    assert reloaded_window._plot_widget.max_display_points() == 12_345
    assert np.allclose(reloaded_window._plot_widget.view_range(), saved_viewport)
    assert reloaded_window.action_advanced_groups.isChecked()
    assert not reloaded_window._group_panel.isHidden()
    reloaded_window.action_advanced_groups.setChecked(False)
    hidden_manifest = reloaded_window._build_project_manifest()
    assert hidden_manifest["advanced_groups_enabled"] is False
    assert hidden_manifest["sample_groups"] == saved["sample_groups"]
    assert hidden_manifest["group_strategy_bindings"] == saved[
      "group_strategy_bindings"
    ]
    assert [gate.id for gate in reloaded_window._gate_editor.gates()] == ["positive"]

    headless_report = PipelineRunner(saved).run_samples(
      ExecutionContext(),
      tuple(reloaded_window._sample_data.values()),
    )
    gui_counts = {
      result.population_id: result.event_count for result in gui_report.population_results
    }
    headless_counts = {
      result.population_id: result.event_count
      for result in headless_report.population_results
    }
    assert headless_counts == gui_counts

    output_path = tmp_path / "cli-results.tsv"
    assert run_project_command(str(project_path), output=str(output_path)) == 0
    output_text = output_path.read_text(encoding="utf-8")
    assert "All Events/positive\t2\t" in output_text
  finally:
    window.close()
    reloaded_window.close()
    window.deleteLater()
    reloaded_window.deleteLater()
    app.processEvents()


def test_gate_override_dialog_requires_reason_and_returns_auditable_geometry() -> None:
  app = _app()
  gate = GateSpec(
    id="gate", name="Gate", gate_type="range", x_parameter="X",
    thresholds={"min": 1.0, "max": 4.0},
  )
  dialog = GateOverrideDialog(gate, "s1", ("s1", "s2"))
  try:
    dialog._reason.setText("technical cleanup")
    dialog._thresholds.setPlainText('{"min": 2.0, "max": 4.0}')
    dialog._validate_and_accept()
    assert dialog.result() == 1
    spec = dialog.specification()
    assert spec["sample_id"] == "s1"
    assert spec["base_gate_id"] == "gate"
    assert spec["reason"] == "technical cleanup"
    assert spec["thresholds"] == {"min": 2.0, "max": 4.0}
  finally:
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
