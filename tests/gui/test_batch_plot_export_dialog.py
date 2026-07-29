from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

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
