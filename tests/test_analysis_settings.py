"""Tests for portable analysis settings extraction and application."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowdesk_core.analysis_settings import (
  AnalysisSettingsError,
  extract_analysis_settings,
  preflight_analysis_settings,
  replace_analysis_settings,
)
from flowdesk_core.project_commands import (
  ReplaceAnalysisSettingsCommand,
  UndoStack,
)
from flowdesk_storage.analysis_settings import (
  load_analysis_settings,
  save_analysis_settings,
)


def _project() -> dict[str, object]:
  return {
    "project_id": "target-project",
    "samples": [{
      "id": "sample-1",
      "path": "/data/sample-1.fcs",
      "channels": [
        {"id": "FSC-A", "name": "FSC-A"},
        {"id": "SSC-A", "name": "SSC-A"},
      ],
    }],
    "gating_strategies_data": {
      "default_strategy": {
        "id": "default_strategy",
        "name": "Default",
        "root_population_id": "all_events",
        "gates": [{
          "id": "old-gate",
          "name": "old",
          "gate_type": "rectangle",
          "x_parameter": "FSC-A",
          "y_parameter": "SSC-A",
          "thresholds": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1},
        }],
      }
    },
    "derived_parameters": [],
    "transforms": [],
    "compensation_matrices": [],
    "statistics": [],
    "auto_gate_templates": [],
    "magnetic_gate_templates": [],
    "tethered_gate_templates": [],
    "plot_views": [{
      "id": "view",
      "presentation": {"background": "black"},
      "overlay_sources": [{
        "source_id": "source-1",
        "display_name": "sample-1",
        "x_parameter_id": "FSC-A",
        "sample_id": "sample-1",
        "population_id": "all_events",
        "order": 0,
      }],
    }],
    "execution_profiles": [{
      "id": "default",
      "gating_strategy_id": "default_strategy",
    }],
    "group_strategy_bindings": [],
    "default_compensation_matrix_id": None,
    "results": [{"sample_id": "sample-1", "count": 123}],
  }


def test_extract_excludes_samples_results_and_sample_overlay_sources() -> None:
  settings = extract_analysis_settings(_project())
  assert settings["document_kind"] == "analysis_settings"
  assert "samples" not in settings
  assert "results" not in settings
  assert settings["analysis_definition"]["plot_views"] == [{
    "id": "view",
    "presentation": {"background": "black"},
  }]


def test_save_and_load_settings_bundle(tmp_path: Path) -> None:
  path = tmp_path / "日本 語" / "settings.flowdesk-settings"
  save_analysis_settings(path, _project())
  loaded = load_analysis_settings(path)
  assert loaded["document_kind"] == "analysis_settings"
  assert loaded["analysis_definition"]["gating_strategies_data"] == (
    extract_analysis_settings(_project())["analysis_definition"]["gating_strategies_data"]
  )


def test_load_project_as_settings_source(tmp_path: Path) -> None:
  from flowdesk_storage.project import save_project

  project_path = tmp_path / "source.flowdesk"
  project = _project()
  project.update({
    "project_version": "0.1",
    "pipeline_version": "0.1",
  })
  save_project(project_path, project)
  loaded = load_analysis_settings(project_path)
  assert "samples" not in loaded
  assert "results" not in loaded


def test_preflight_blocks_missing_target_channel() -> None:
  settings = extract_analysis_settings(_project())
  target = _project()
  target["samples"] = [{
    "id": "other",
    "channels": [{"id": "FSC-A", "name": "FSC-A"}],
  }]
  diagnostics = preflight_analysis_settings(target, settings)
  assert any("SSC-A" in message for message in diagnostics)


def test_replace_preserves_target_samples_and_drops_source_results() -> None:
  source = _project()
  source["gating_strategies_data"] = {
    "default_strategy": {
      "id": "default_strategy",
      "name": "Imported",
      "gates": [],
    }
  }
  settings = extract_analysis_settings(source)
  target = _project()
  replaced = replace_analysis_settings(target, settings)
  assert replaced["samples"] == target["samples"]
  assert replaced["results"] == target["results"]
  assert replaced["gating_strategies_data"]["default_strategy"]["name"] == "Imported"


def test_settings_command_undo_redo_restores_definitions() -> None:
  target = _project()
  source = _project()
  source["gating_strategies_data"]["default_strategy"]["gates"] = []
  settings = extract_analysis_settings(source)
  stack = UndoStack(target)
  stack.execute(ReplaceAnalysisSettingsCommand(settings))
  assert stack.state["gating_strategies_data"]["default_strategy"]["gates"] == []
  stack.undo()
  assert stack.state["gating_strategies_data"]["default_strategy"]["gates"]
  stack.redo()
  assert stack.state["gating_strategies_data"]["default_strategy"]["gates"] == []


def test_invalid_settings_are_rejected_before_replacement() -> None:
  settings = extract_analysis_settings(_project())
  settings["analysis_definition"]["gating_strategies_data"] = {}
  with pytest.raises(AnalysisSettingsError):
    replace_analysis_settings(_project(), settings)
