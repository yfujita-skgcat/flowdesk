"""Cross-suite pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

_QT_APP: Any | None = None


@pytest.fixture(autouse=True)
def cleanup_gui_qt_objects(request: pytest.FixtureRequest) -> Iterator[None]:
  """Keep QApplication alive and finish deferred deletion after every GUI test."""
  if request.node.get_closest_marker("gui") is None:
    yield
    return

  from PySide6.QtWidgets import QApplication

  global _QT_APP
  _QT_APP = QApplication.instance() or QApplication([])
  yield

  for widget in QApplication.topLevelWidgets():
    try:
      widget.close()
      widget.deleteLater()
    except RuntimeError:
      # The C++ object may already have been deleted by the test.
      continue
  _QT_APP.processEvents()
  # A global DeferredDelete flush can invoke pyqtgraph C++ destructors while
  # their parent widgets are still unwinding. Keep teardown bounded and safe.
  _QT_APP.processEvents()
