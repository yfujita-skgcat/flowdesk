from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QPushButton, QScrollArea

from flowdesk_qt.batch_plot_export_dialog import BatchPlotExportDialog

pytestmark = pytest.mark.gui


def test_batch_plot_dialog_creates_new_definition_with_explicit_samples(qapp, tmp_path) -> None:
  dialog = BatchPlotExportDialog(
    [],
    [{"id": "s1", "name": "Sample 1"}, {"id": "s2", "name": "Sample 2"}],
    [],
    [{"id": "main-view", "name": "Main"}],
    "main-view",
  )
  try:
    dialog._name.setText("Experiment plots")
    dialog._target.setCurrentIndex(dialog._target.findData("explicit"))
    dialog._sample_list.item(1).setSelected(True)
    dialog._output.setText(str(tmp_path))
    dialog._accept_run()
    request = dialog.request()
    assert request.run is True
    assert request.definition["name"] == "Experiment plots"
    assert request.definition["sample_ids"] == ["s2"]
    assert request.definition["raster_resolution_mode"] == "dpi_scaled"
    assert request.definition["vector_scatter_mode"] == "hybrid_raster"
    assert request.definition["hybrid_scatter_dpi"] == 600
    assert dialog._scatter_mode.currentData() == "hybrid_raster"
    assert request.output_dir == str(tmp_path)
    assert request.execution_backend == "sequential"
    assert request.max_workers == 2
    assert request.memory_budget_mib is None
    assert request.density_workers == 1
    assert request.density_memory_budget_mib is None
    assert "execution_backend" not in request.definition
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_keeps_thread_settings_runtime_only(qapp, tmp_path) -> None:
  dialog = BatchPlotExportDialog([], [], [], [], "main-view")
  try:
    dialog._execution_backend.setCurrentIndex(
      dialog._execution_backend.findData("thread")
    )
    dialog._max_workers.setValue(3)
    dialog._memory_budget_mib.setValue(128)
    dialog._density_workers.setValue(4)
    dialog._density_memory_budget_mib.setValue(64)
    dialog._output.setText(str(tmp_path))
    dialog._accept_run()
    request = dialog.request()
    assert request.execution_backend == "thread"
    assert request.max_workers == 3
    assert request.memory_budget_mib == 128
    assert request.density_workers == 4
    assert request.density_memory_budget_mib == 64
    assert "max_workers" not in request.definition
    assert "memory_budget_mib" not in request.definition
    assert "density_workers" not in request.definition
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_disables_unverified_worker_controls(qapp) -> None:
  dialog = BatchPlotExportDialog([], [], [], [], "main-view")
  try:
    assert dialog._execution_backend.isEnabled() is False
    assert dialog._max_workers.isEnabled() is False
    assert dialog._memory_budget_mib.isEnabled() is False
    assert dialog._density_workers.isEnabled() is False
    assert dialog._density_memory_budget_mib.isEnabled() is False
    assert "disabled" in dialog._experimental_workers_status.text().lower()
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_is_resizable_with_scrollable_form(qapp) -> None:
  dialog = BatchPlotExportDialog([], [], [], [], "main-view")
  try:
    assert dialog.isSizeGripEnabled() is True
    assert dialog.minimumWidth() == 480
    assert dialog.minimumHeight() == 360
    assert isinstance(dialog._scroll_area, QScrollArea)
    assert dialog._scroll_area.widgetResizable() is True
    assert dialog._scroll_area.widget().objectName() == "batchPlotExportFormContainer"
    assert dialog.findChild(QPushButton, "batchPlotSaveDefinitionButton").parentWidget() is dialog
    assert dialog.findChild(QPushButton, "batchPlotCancelButton").parentWidget() is dialog
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_runs_saved_queue_with_shared_runtime_policy(qapp, tmp_path) -> None:
  dialog = BatchPlotExportDialog(
    [
      {"id": "first", "name": "First"},
      {"id": "second", "name": "Second"},
    ], [], [], [], "main-view",
  )
  try:
    dialog._output.setText(str(tmp_path))
    dialog._queue_failure_policy.setCurrentIndex(
      dialog._queue_failure_policy.findData("continue")
    )
    dialog._execution_backend.setCurrentIndex(dialog._execution_backend.findData("thread"))
    dialog._max_workers.setValue(3)
    dialog._accept_queue()
    request = dialog.request()
    assert request.run is False
    assert request.queue_export_ids == ("first", "second")
    assert request.queue_failure_policy == "continue"
    assert request.output_dir == str(tmp_path)
    assert request.execution_backend == "thread"
    assert request.max_workers == 3
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_loads_saved_definition(qapp) -> None:
  dialog = BatchPlotExportDialog(
    [{
      "id": "saved",
      "name": "Saved PDF",
      "formats": ["pdf"],
      "width": 1200,
      "height": 900,
      "target": "all",
    }],
    [],
    [],
    [{"id": "main-view", "name": "Main"}],
    "main-view",
  )
  try:
    assert dialog._definition.currentData() == ""
    dialog._definition.setCurrentIndex(1)
    request = dialog.request()
    assert request.definition["id"] == "saved"
    assert request.definition["formats"] == ["pdf"]
    assert request.definition["width"] == 1200
    assert request.definition["raster_resolution_mode"] == "legacy_pixel_dimensions"
    assert request.definition["vector_scatter_mode"] == "full_vector"
    assert dialog._hybrid_scatter_dpi_spin.isEnabled() is False
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_deletes_selected_definition_after_confirmation(
  qapp, monkeypatch,
) -> None:
  dialog = BatchPlotExportDialog(
    [{"id": "saved", "name": "Saved definition"}], [], [], [], "main-view",
  )
  monkeypatch.setattr(
    QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
  )
  try:
    assert dialog._delete_button.isEnabled() is False
    dialog._definition.setCurrentIndex(1)
    assert dialog._delete_button.isEnabled() is True
    dialog._accept_delete()
    assert dialog.request().delete_definition_id == "saved"
  finally:
    dialog.deleteLater()


def test_batch_plot_dialog_remembers_output_directory(qapp, tmp_path) -> None:
  settings = QSettings()
  key = BatchPlotExportDialog._OUTPUT_DIRECTORY_KEY
  previous = settings.value(key, None)
  try:
    settings.remove(key)
    first = BatchPlotExportDialog([], [], [], [], "main-view")
    first._output.setText(str(tmp_path))
    first._accept_save()
    first.request()
    first.deleteLater()

    second = BatchPlotExportDialog([], [], [], [], "main-view")
    try:
      assert second._output.text() == str(tmp_path)
    finally:
      second.deleteLater()
  finally:
    if previous is None:
      settings.remove(key)
    else:
      settings.setValue(key, previous)
