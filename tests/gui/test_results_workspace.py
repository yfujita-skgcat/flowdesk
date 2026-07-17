"""Tests for the executed-results workspace tree-table."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_qt.main_window import MainWindow
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


def test_flat_table_uses_same_report_values_without_tree_indentation(qapp) -> None:
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
    workspace.set_mode("Flat table")
    tree = workspace.tree()
    assert tree.columnCount() == 7
    assert [tree.headerItem().text(index) for index in range(7)] == [
      "Sample", "Population", "Parent", "Events", "% Parent", "% Total", "Status"
    ]
    assert tree.topLevelItem(1).text(1) == "rect_1"
    assert tree.topLevelItem(1).text(2) == "All Events"
    assert tree.topLevelItem(1).text(3) == "4"
    workspace.set_mode("Hierarchy")
    assert workspace.tree().columnCount() == 5
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_status_distinguishes_missing_zero_stale_and_statistic_errors(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy(
      {
        "all_events": None,
        "zero": "all_events",
        "missing": "all_events",
      },
      {
        "all_events": "All Events",
        "zero": "Zero",
        "missing": "Missing",
      },
    )
    workspace.set_report(
      ExecutionReport(
        project_id="project",
        execution_profile_id="default",
        pipeline_version="test",
        status="success",
        population_results=(
          PopulationResult("sample-1", "all_events", 10, None, 1.0),
          PopulationResult("sample-1", "zero", 0, 0.0, 0.0),
        ),
        statistic_results=(
          StatisticResult(
            "sample-1", "undefined-stat", "zero", "mean", None,
            status="undefined",
          ),
          StatisticResult(
            "sample-1", "error-stat", "zero", "mean", None,
            status="error",
          ),
        ),
      )
    )
    all_events = workspace.tree().topLevelItem(0).child(0)
    zero = all_events.child(0)
    missing = all_events.child(1)
    assert zero.text(4) == "zero events"
    assert missing.text(4) == "missing"
    assert zero.childCount() == 2
    assert {zero.child(index).text(4) for index in range(2)} == {
      "undefined", "error"
    }

    workspace.mark_results_stale()
    assert workspace.tree().topLevelItem(0).child(0).text(4) == "stale"
    assert workspace.tree().topLevelItem(0).child(0).child(0).text(4) == "stale"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_main_window_exposes_exclusive_gating_and_results_tabs(qapp) -> None:
  window = MainWindow()
  try:
    right = window.centralWidget().widget(1)
    tab_widget = right.findChild(QTabWidget, "gatingResultsTabs")
    assert tab_widget is not None
    assert [tab_widget.tabText(index) for index in range(tab_widget.count())] == [
      "Gating",
      "Results",
    ]
    assert not window._workspace_tree.isVisible()
    assert not window._population_tree.isVisible()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
