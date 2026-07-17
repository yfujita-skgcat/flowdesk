"""Tests for the executed-results workspace tree-table."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult
from flowdesk_qt.results_workspace import ResultsWorkspace

pytestmark = pytest.mark.gui


def test_results_workspace_has_explicit_sample_and_all_events_rows(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy(
      {"all_events": None, "rect-1": "all_events"},
      {"all_events": "All Events", "rect-1": "rect_1"},
    )
    workspace.set_report(
      ExecutionReport(
        project_id="project",
        execution_profile_id="default",
        pipeline_version="test",
        status="success",
        population_results=(
          PopulationResult("sample-1", "all_events", 10, None, 1.0),
          PopulationResult("sample-1", "rect-1", 4, 0.4, 0.4),
        ),
      )
    )

    tree = workspace.tree()
    sample = tree.topLevelItem(0)
    all_events = sample.child(0)
    rect = all_events.child(0)
    assert sample.text(0) == "1_A1"
    assert sample.data(0, Qt.UserRole) == "sample-1"
    assert all_events.text(0) == "All Events"
    assert all_events.data(0, Qt.UserRole) == "all_events"
    assert rect.text(0) == "rect_1"
    assert rect.text(1) == "4"
    assert rect.text(2) == "0.4000"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_selection_distinguishes_sample_and_population(qapp) -> None:
  workspace = ResultsWorkspace()
  selected: list[tuple[str, str, str]] = []
  workspace.on_selection_changed(
    lambda kind, stable_id, sample_id: selected.append(
      (kind, stable_id, sample_id)
    )
  )
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    tree = workspace.tree()
    sample = tree.topLevelItem(0)
    all_events = sample.child(0)
    tree.setCurrentItem(sample)
    tree.setCurrentItem(all_events)
    qapp.processEvents()
    assert selected == [
      ("sample", "sample-1", "sample-1"),
      ("population", "all_events", "sample-1"),
    ]
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()
