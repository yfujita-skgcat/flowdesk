"""Tests for Qt plot display helpers."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from flowdesk_core.models import GateSpec  # noqa: E402
from flowdesk_qt.gate_editor import GateEditor  # noqa: E402
from flowdesk_qt.main_window import MainWindow  # noqa: E402
from flowdesk_qt.plot_widget import PlotWidget  # noqa: E402


def _app() -> QApplication:
  app = QApplication.instance()
  if app is None:
    app = QApplication([])
  return app


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
    widget._on_mouse_drag(finish_event)

    assert default_calls == []
    assert start_event.accepted is True
    assert finish_event.accepted is True
    assert gate_calls == [
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
