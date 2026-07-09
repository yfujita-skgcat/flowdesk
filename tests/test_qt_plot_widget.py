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
