"""Tests for the unified compensation controls/matrix workspace."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QDialog, QDialogButtonBox  # noqa: E402

from flowdesk_qt.compensation_workspace import (  # noqa: E402
  CompensationWorkspaceDialog,
)
from flowdesk_qt.main_window import MainWindow  # noqa: E402


def _matrix() -> dict[str, object]:
  return {
    "id": "matrix-1",
    "name": "Matrix 1",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": [[1.0, 0.1], [0.2, 1.0]],
  }


def _channels() -> tuple[dict[str, str], ...]:
  return (
    {"id": "FL1-A", "name": "FITC-A", "display_name": "FITC-A"},
    {"id": "FL2-A", "name": "PE-A", "display_name": "PE-A"},
  )


def _workspace() -> CompensationWorkspaceDialog:
  return CompensationWorkspaceDialog(
    [_matrix()],
    [],
    [],
    _channels(),
    ("all_events",),
    ("sample-1",),
    sample_data={
      "sample-1": {
        "events": np.array([[100.0, 20.0], [200.0, 30.0]]),
        "channel_ids": ["FL1-A", "FL2-A"],
        "population_mask": np.array([True, True]),
        "masks": {"all_events": np.array([True, True])},
      }
    },
  )


def test_workspace_has_one_save_boundary_and_two_review_tabs(qapp) -> None:
  dialog = _workspace()
  try:
    tabs = dialog.findChild(QDialogButtonBox, "compensationWorkspaceButtons")
    assert tabs is not None
    assert dialog._tabs.count() == 3
    assert dialog._tabs.tabText(0) == "Controls & Calculate"
    assert dialog._tabs.tabText(1) == "Matrix Preview"
    assert dialog._tabs.tabText(2) == "Application / Bindings"
    assert dialog._matrix_editor.findChild(QDialogButtonBox).isHidden()
    assert dialog._calculation_editor.findChild(QDialogButtonBox).isHidden()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_workspace_cancel_does_not_return_candidate_changes(qapp) -> None:
  dialog = _workspace()
  try:
    dialog._matrix_editor._duplicate_matrix()
    assert len(dialog.matrices()) == 2
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_workspace_accept_returns_matrix_binding_and_calculation_state(qapp) -> None:
  dialog = _workspace()
  try:
    dialog._matrix_editor._name_edit.setText("Updated")
    dialog._accept_if_valid()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog._matrix_editor._preview_scheduler._closed
    assert dialog.matrices()[0]["name"] == "Updated"
    assert dialog.bindings() == []
    assert dialog.calculations() == []
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_workspace_links_single_stain_control_to_matrix_preview(qapp) -> None:
  dialog = CompensationWorkspaceDialog(
    [_matrix()],
    [],
    [{
      "id": "calc-1",
      "name": "Control",
      "controls": [{
        "detector_channel_id": "FL1-A",
        "sample_id": "sample-1",
        "positive_population_id": "pos",
        "negative_population_id": "neg",
      }],
    }],
    _channels(),
    ("all_events", "pos", "neg"),
    ("sample-1",),
    sample_data={
      "sample-1": {
        "events": np.array([[100.0, 20.0], [200.0, 30.0]]),
        "channel_ids": ["FL1-A", "FL2-A"],
        "population_mask": np.array([True, True]),
        "masks": {
          "all_events": np.array([True, True]),
          "pos": np.array([True, False]),
          "neg": np.array([False, True]),
        },
      }
    },
  )
  try:
    assert dialog._matrix_editor._control_assignments["FL1-A"]["sample_id"] == (
      "sample-1"
    )
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_matrix_preview_accepts_calculated_matrix_once(qapp) -> None:
  dialog = _workspace()
  try:
    calculated = _matrix()
    calculated["id"] = "calculated-1"
    calculated["source"] = "calculated"
    assert dialog._matrix_editor.add_matrix_mapping(calculated)
    assert not dialog._matrix_editor.add_matrix_mapping(calculated)
    assert dialog._matrix_editor.matrices()[-1]["source"] == "calculated"
    assert not dialog._matrix_editor._heat_map.isEnabled()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_main_window_builds_one_workspace_input_snapshot(qapp) -> None:
  window = MainWindow()
  try:
    channels, sample_ids, population_ids, sample_data, sample_labels, population_labels = (
      window._compensation_workspace_inputs()
    )
    assert isinstance(channels, tuple)
    assert isinstance(sample_ids, tuple)
    assert "all_events" in population_ids
    assert sample_data == {}
    assert sample_labels == {}
    assert population_labels == {"all_events": "All Events"}
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
