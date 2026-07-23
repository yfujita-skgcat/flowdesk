"""GUI coverage for the unified Results export entry points."""

from __future__ import annotations

import pytest

from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.results_export_dialog import ResultsExportDialog

pytestmark = pytest.mark.gui


def test_results_export_dialog_defaults(qapp) -> None:
  dialog = ResultsExportDialog()
  try:
    options = dialog.options()
    assert options.layout == "wide"
    assert options.include_population_metrics is True
    assert options.include_custom_statistics is True
    assert options.include_internal_ids is False
    assert options.include_qc is False
    assert dialog.objectName() == "resultsExportDialog"
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
