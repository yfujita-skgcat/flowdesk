"""Tests for Qt plot display helpers."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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
