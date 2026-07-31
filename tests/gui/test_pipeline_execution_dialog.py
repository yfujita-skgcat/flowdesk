"""Runtime-only controls for GUI Run Pipeline execution."""

from __future__ import annotations

import pytest

from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.pipeline_execution_dialog import (
  PipelineExecutionDialog,
  PipelineExecutionRequest,
)

pytestmark = pytest.mark.gui


def test_pipeline_execution_dialog_defaults_to_sequential(qapp) -> None:
  dialog = PipelineExecutionDialog()
  try:
    request = dialog.request()
    assert request == PipelineExecutionRequest()
    assert dialog.objectName() == "pipelineExecutionDialog"
  finally:
    dialog.deleteLater()


def test_pipeline_execution_dialog_disables_unverified_worker_controls(qapp) -> None:
  dialog = PipelineExecutionDialog()
  try:
    assert dialog._execution_backend.isEnabled() is False
    assert dialog._max_workers.isEnabled() is False
    assert dialog._memory_budget_mib.isEnabled() is False
    assert "disabled" in dialog._experimental_workers_status.text().lower()
  finally:
    dialog.deleteLater()


def test_pipeline_execution_dialog_round_trips_runtime_thread_settings(qapp) -> None:
  dialog = PipelineExecutionDialog()
  try:
    dialog._execution_backend.setCurrentIndex(
      dialog._execution_backend.findData("thread")
    )
    dialog._max_workers.setValue(3)
    dialog._memory_budget_mib.setValue(256)
    assert dialog.request() == PipelineExecutionRequest("thread", 3, 256)
  finally:
    dialog.deleteLater()


def test_main_window_keeps_pipeline_settings_runtime_only(qapp, monkeypatch) -> None:
  window = MainWindow()

  class AcceptedDialog:
    def __init__(self, *_args, **_kwargs):
      pass

    def exec(self):
      return 1

    def request(self):
      return PipelineExecutionRequest("thread", 3, 128)

  monkeypatch.setattr(
    "flowdesk_qt.main_window.PipelineExecutionDialog", AcceptedDialog
  )
  try:
    window._on_pipeline_execution_settings()
    assert window._pipeline_execution_request == PipelineExecutionRequest("thread", 3, 128)
    assert "execution_backend" not in window._build_project_manifest()
  finally:
    window.close()
    window.deleteLater()
