from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

from flowdesk_qt.app_info import APP_NAME, application_version
from flowdesk_qt.diagnostics import invoke_callback
from flowdesk_qt.main_window import MainWindow
from tests.gui.helpers import sanitize_node_id, save_failure_artifacts

pytestmark = pytest.mark.gui


def test_main_window_object_names_and_debug_state(qapp) -> None:
  window = MainWindow()
  try:
    assert window.objectName() == "flowdeskMainWindow"
    assert window.findChild(QPushButton, "createGateButton") is not None
    assert window.action_run_pipeline.objectName() == "actionRunPipeline"
    state = window.debug_state()
    assert state["application"] == {
      "name": APP_NAME,
      "version": application_version(),
    }
    assert state["status"] == "Ready"
    assert state["pipeline"] == {
      "worker_present": False,
      "running": False,
      "analysis_revision": 0,
      "authoritative_result_revision": None,
      "preview_result_revision": None,
      "preview_status": "idle",
      "error_type": None,
      "error_message": None,
    }
    json.dumps(state)
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_strict_callback_logs_and_reraises(
  monkeypatch: pytest.MonkeyPatch,
  caplog: pytest.LogCaptureFixture,
) -> None:
  monkeypatch.setenv("FLOWDESK_GUI_STRICT_CALLBACKS", "1")

  def broken() -> None:
    raise RuntimeError("callback exploded")

  with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="exploded"):
    invoke_callback(broken)
  assert "GUI callback failed" in caplog.text


def test_normal_callback_logs_without_reraising(
  monkeypatch: pytest.MonkeyPatch,
  caplog: pytest.LogCaptureFixture,
) -> None:
  monkeypatch.delenv("FLOWDESK_GUI_STRICT_CALLBACKS", raising=False)

  def broken() -> None:
    raise RuntimeError("logged only")

  with caplog.at_level(logging.ERROR):
    assert invoke_callback(broken) is None
  assert "logged only" in caplog.text


def test_failure_artifact_helper_writes_png_and_state(
  qapp,
  tmp_path: Path,
) -> None:
  window = MainWindow()
  try:
    window.resize(640, 480)
    window.show()
    qapp.processEvents()
    test_dir = save_failure_artifacts(
      tmp_path, "tests/gui/test_x.py::test bad", [window], "failure details"
    )
    assert test_dir.name == sanitize_node_id("tests/gui/test_x.py::test bad")
    assert (test_dir / "main-window.png").stat().st_size > 0
    assert json.loads((test_dir / "ui-state.json").read_text())["status"] == "Ready"
    assert (test_dir / "failure.txt").read_text() == "failure details"
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
