"""GUI coverage for the unified Results export entry points."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.results_export_dialog import ResultsExportDialog, ResultsExportOptions

pytestmark = pytest.mark.gui


def test_results_export_dialog_defaults(qapp) -> None:
  dialog = ResultsExportDialog()
  try:
    options = dialog.options()
    assert options.destination == "file"
    assert options.layout == "wide"
    assert options.include_population_metrics is True
    assert options.include_custom_statistics is True
    assert options.include_internal_ids is False
    assert options.include_qc is False
    assert dialog.objectName() == "resultsExportDialog"
    assert dialog.findChild(
      type(dialog._destination), "resultsExportDestinationCombo"
    ) is dialog._destination
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_results_export_dialog_selects_population_ids(qapp) -> None:
  dialog = ResultsExportDialog(
    population_options=(
      ("all_events", "All Events"),
      ("gate_polygon", "All Events/gate_polygon"),
    )
  )
  try:
    dialog._populations.item(0).setCheckState(Qt.CheckState.Unchecked)
    options = dialog.options()
    assert options.population_ids == ("gate_polygon",)
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_results_menu_has_only_unified_result_export(qapp) -> None:
  window = MainWindow()
  try:
    assert window.action_export_results.text() == "Export &Results..."
    assert window.action_export_results.objectName() == "actionExportResults"
    assert not hasattr(window, "action_export_statistics")
    result_actions = [
      action for action in window.menuBar().actions()
      if action.menu() is not None and action.menu().title().replace("&", "") == "Results"
    ]
    assert len(result_actions) == 1
    texts = [action.text() for action in result_actions[0].menu().actions()]
    assert "Export &Results..." in texts
    assert all("Population" not in text for text in texts)
    assert all("Export" not in text or "Statistics" not in text for text in texts)
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_stale_results_export_queues_export_and_runs_pipeline(qapp, monkeypatch, tmp_path) -> None:
  window = MainWindow()
  try:
    window._sample_data = {"sample-1": object()}
    window._results_stale = True
    pipeline_calls: list[bool] = []

    class FakeExportDialog:
      def __init__(self, parent, *args) -> None:
        self.parent = parent

      def exec(self) -> int:
        return 1

      def options(self) -> ResultsExportOptions:
        return ResultsExportOptions()

    monkeypatch.setattr(
      "flowdesk_qt.results_export_dialog.ResultsExportDialog",
      FakeExportDialog,
    )
    monkeypatch.setattr(
      "flowdesk_qt.main_window.QFileDialog.getSaveFileName",
      lambda *args: (str(tmp_path / "results.tsv"), "TSV files (*.tsv)"),
    )
    monkeypatch.setattr(
      window,
      "_on_run_pipeline",
      lambda: pipeline_calls.append(True),
    )

    window._on_export_results()

    assert pipeline_calls == [True]
    assert window._pending_results_export is not None
    assert window._pending_results_export[1].endswith("results.tsv")
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_clipboard_results_export_does_not_open_file_picker(qapp, monkeypatch) -> None:
  window = MainWindow()
  try:
    window._sample_data = {"sample-1": object()}
    window._results_stale = True

    class FakeExportDialog:
      def __init__(self, parent, *args) -> None:
        self.parent = parent

      def exec(self) -> int:
        return 1

      def options(self) -> ResultsExportOptions:
        return ResultsExportOptions(destination="clipboard")

    monkeypatch.setattr(
      "flowdesk_qt.results_export_dialog.ResultsExportDialog",
      FakeExportDialog,
    )
    monkeypatch.setattr(
      "flowdesk_qt.main_window.QFileDialog.getSaveFileName",
      lambda *_args: (_ for _ in ()).throw(AssertionError("file picker opened")),
    )
    monkeypatch.setattr(window, "_on_run_pipeline", lambda: None)

    window._on_export_results()

    assert window._pending_results_export is not None
    assert window._pending_results_export[1] is None
    assert window._pending_results_export[2] == "\t"
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
