from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONFAULTHANDLER", "1")
os.environ.setdefault("FLOWDESK_GUI_STRICT_CALLBACKS", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from flowdesk_qt.diagnostics import configure_gui_logging  # noqa: E402
from tests.gui.helpers import save_failure_artifacts  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def gui_logging() -> None:
  artifact_dir = Path(
    os.environ.get("FLOWDESK_GUI_ARTIFACT_DIR", "artifacts/gui/pytest")
  )
  configure_gui_logging(artifact_dir)


@pytest.fixture
def qapp() -> Iterator[QApplication]:
  app = QApplication.instance() or QApplication([])
  yield app
  app.processEvents()


@pytest.fixture
def gui_artifact_widgets() -> list[object]:
  return []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
  outcome = yield
  report = outcome.get_result()
  if report.when != "call" or report.passed:
    return
  widgets = item.funcargs.get("gui_artifact_widgets", [])
  if not widgets:
    return
  all_widgets = list(widgets)
  all_widgets.extend(
    widget
    for widget in QApplication.topLevelWidgets()
    if widget.isVisible() and widget not in all_widgets
  )
  artifact_dir = Path(
    os.environ.get("FLOWDESK_GUI_ARTIFACT_DIR", "artifacts/gui/pytest")
  )
  save_failure_artifacts(artifact_dir, item.nodeid, all_widgets, report.longreprtext)
