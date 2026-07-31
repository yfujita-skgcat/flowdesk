"""GUI integration checks for analysis settings actions and application."""

from __future__ import annotations

import pytest

from flowdesk_core.analysis_settings import extract_analysis_settings
from flowdesk_core.project_commands import (
  ReplaceAnalysisSettingsCommand,
  UndoStack,
)
from flowdesk_qt.main_window import MainWindow

pytestmark = pytest.mark.gui


def _settings() -> dict[str, object]:
  return extract_analysis_settings({
    "project_id": "source",
    "gating_strategies_data": {
      "default_strategy": {
        "id": "default_strategy",
        "name": "Imported",
        "root_population_id": "all_events",
        "gates": [],
      }
    },
    "derived_parameters": [],
    "transforms": [],
    "compensation_matrices": [],
    "statistics": [],
    "auto_gate_templates": [],
    "magnetic_gate_templates": [],
    "tethered_gate_templates": [],
    "plot_views": [],
  })


def test_analysis_settings_actions_have_stable_names_and_apply(qapp) -> None:
  window = MainWindow()
  try:
    assert window.action_save_analysis_settings.objectName() == (
      "actionSaveAnalysisSettings"
    )
    assert window.action_load_analysis_settings.objectName() == (
      "actionLoadAnalysisSettings"
    )
    assert window.action_undo_analysis_settings.objectName() == (
      "actionUndoAnalysisSettings"
    )
    assert window.action_redo_analysis_settings.objectName() == (
      "actionRedoAnalysisSettings"
    )
    assert window.action_pipeline_execution_settings.objectName() == (
      "actionPipelineExecutionSettings"
    )
    window._analysis_settings_undo_stack = UndoStack(
      window._build_project_manifest(),
      on_changed=window._on_analysis_settings_state_changed,
    )
    window._analysis_settings_undo_stack.execute(
      ReplaceAnalysisSettingsCommand(_settings())
    )
    assert window._results_stale
    assert window.action_undo_analysis_settings.isEnabled()
    window._on_undo_analysis_settings()
    assert window.action_redo_analysis_settings.isEnabled()
  finally:
    window.close()
    window.deleteLater()
