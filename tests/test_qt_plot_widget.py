"""Tests for Qt plot display helpers."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from flowdesk_cli.run_project import run_project_command  # noqa: E402
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
from flowdesk_core.pipeline_runner import PipelineRunner  # noqa: E402
from flowdesk_core.transforms import (  # noqa: E402
  LOGICLE_IMPLEMENTATION_VERSION,
  apply_transform,
)
from flowdesk_qt.annotation_editor import AnnotationEditorDialog  # noqa: E402
from flowdesk_qt.gate_editor import GateEditor, _GateDialog  # noqa: E402
from flowdesk_qt.gate_override_editor import GateOverrideDialog  # noqa: E402
from flowdesk_qt.group_panel import GroupPanel  # noqa: E402
from flowdesk_qt.main_window import MainWindow  # noqa: E402
from flowdesk_qt.plot_widget import PlotWidget  # noqa: E402
from flowdesk_qt.sample_browser import SampleBrowser  # noqa: E402
from flowdesk_storage.project import load_project  # noqa: E402


def _app() -> QApplication:
  app = QApplication.instance()
  if app is None:
    app = QApplication([])
  return app


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


def test_log10_rectangle_overlay_edit_keeps_log_coordinates() -> None:
  app = _app()
  widget = PlotWidget()
  try:
    gate = GateSpec(
      id="gate-log",
      name="log rectangle",
      gate_type="rectangle",
      x_parameter="X",
      y_parameter="Y",
      x_scale="log10",
      y_scale="log10",
      thresholds={
        "x_min": 2.0, "x_max": 4.0, "y_min": 3.0, "y_max": 5.0,
      },
    )
    updates: list[GateSpec] = []
    widget.set_axis_transforms("log10", "log10")
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
    gate = GateSpec(
      id="gate-log",
      name="log gate",
      gate_type="polygon",
      x_parameter="X",
      y_parameter="Y",
      x_scale="log10",
      y_scale="log10",
      coordinates=((2.0, 3.0), (4.0, 3.0), (3.0, 5.0)),
    )
    widget.set_axis_transforms("linear", "linear")
    widget.add_gate_overlay(gate, gate_index=0)
    assert widget._gate_items == []

    widget.set_axis_transforms("log10", "log10")
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
    assert gate.x_scale == gate.y_scale == "linear"
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
  try:
    first = tmp_path / "alpha.fcs"
    second = tmp_path / "beta.fcs"
    write_fcs_file(first, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
    write_fcs_file(second, np.ones((2, 2), dtype=np.float64), ["X", "Z"])

    assert browser.add_samples_from_paths([str(first), str(second)]) == 2
    assert browser.samples()[1].status == "channel mismatch"
    assert "[≠]" in browser._list_widget.item(1).text()

    browser.set_channel_column_visible("id", True)
    assert not browser._channel_table.isColumnHidden(0)
    browser._filter_edit.setText("alpha")
    assert not browser._list_widget.item(0).isHidden()
    assert browser._list_widget.item(1).isHidden()
  finally:
    browser.close()
    browser.deleteLater()
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
    window._on_gate_geometry_changed(0, updated)

    assert window._gate_editor.gates()[0].thresholds["x_min"] == 1.0
    assert window._results_stale is True
    assert window._population_tree.last_report() is None
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
    assert isinstance(
      saved["gating_strategies_data"]["default_strategy"]["gates"][0], dict
    )

    reloaded_window._load_project_from_path(project_path)
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
    assert f"{sample.id}\tpositive\t2\t" in output_text
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
