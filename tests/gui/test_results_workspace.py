"""Tests for the executed-results workspace tree-table."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTableWidget, QTabWidget, QWidget

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_core.preview import PreviewReport
from flowdesk_qt.display_format import format_display_number, format_percentage
from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.results_state import RuntimeResultState
from flowdesk_qt.results_workspace import ResultsWorkspace

pytestmark = pytest.mark.gui


def test_display_format_keeps_integer_digits_and_limits_fraction() -> None:
  assert format_display_number(123456789.12345) == "123456789.1"
  assert format_display_number(1234567890.12345) == "1234567890"
  assert format_percentage(1.0) == "100"
  assert format_percentage(0.2652) == "26.52"


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
    assert rect.text(2) == "40"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_exposes_auto_recalculate_preference(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    changes: list[bool] = []
    workspace.on_auto_recalculate_changed(changes.append)
    check = workspace.findChild(type(workspace._auto_recalculate_check))
    assert check is workspace._auto_recalculate_check
    assert check.objectName() == "resultsAutoRecalculateCheck"
    assert check.text() == "Auto"
    assert check.toolTip()
    check.setChecked(True)
    assert workspace.auto_recalculate_stale_results() is True
    assert changes == [True]
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_shows_statistic_under_all_events(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy({"all_events": None})
    workspace.set_report(
      ExecutionReport(
        project_id="project",
        execution_profile_id="default",
        pipeline_version="test",
        status="success",
        population_results=(
          PopulationResult("sample-1", "all_events", 10, None, 1.0),
        ),
        statistic_results=(
          StatisticResult(
            "sample-1", "fsc-mean", "all_events", "mean", 123.5,
            statistic_name="FSC-A mean",
          ),
        ),
      )
    )

    all_events = workspace.tree().topLevelItem(0).child(0)
    assert all_events.childCount() == 0
    assert workspace.tree().columnCount() == 6
    assert workspace.tree().headerItem().text(4) == "FSC-A mean"
    assert workspace.tree().headerItem().text(5) == "Status"
    assert all_events.text(3) == "100"
    assert all_events.text(4) == "123.5"
    assert all_events.text(5) == "current"
    assert all_events.data(0, Qt.UserRole + 1) == "population"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_uses_one_statistic_column_for_multiple_populations(qapp) -> None:
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
        statistic_results=(
          StatisticResult(
            "sample-1", "fsc-mean", "all_events", "mean", 123.5,
            statistic_name="FSC-A mean",
          ),
          StatisticResult(
            "sample-1", "fsc-mean", "rect-1", "mean", 45.5,
            statistic_name="FSC-A mean",
          ),
        ),
      )
    )

    tree = workspace.tree()
    assert tree.columnCount() == 6
    assert tree.headerItem().text(4) == "FSC-A mean"
    assert tree.headerItem().text(5) == "Status"
    all_events = tree.topLevelItem(0).child(0)
    rect = all_events.child(0)
    assert all_events.text(4) == "123.5"
    assert rect.text(4) == "45.5"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_column_chooser_and_statistics_detail_share_state(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy({"all_events": None})
    workspace.set_report(
      ExecutionReport(
        project_id="project",
        execution_profile_id="default",
        pipeline_version="test",
        status="success",
        population_results=(
          PopulationResult("sample-1", "all_events", 10, None, 1.0),
        ),
        statistic_results=(
          StatisticResult(
            "sample-1", "fsc-mean", "all_events", "mean", 123.5,
            unit="AU", statistic_name="FSC-A mean", n_valid=10, n_total=10,
          ),
        ),
      )
    )
    assert workspace.statistic_column_visibility() == {"fsc-mean": True}
    workspace.set_statistic_column_visibility({"fsc-mean": False})
    assert workspace.tree().columnCount() == 5
    workspace.set_statistic_column_visibility({"fsc-mean": True})
    workspace.set_statistic_column_widths({"fsc-mean": 180})
    assert workspace.statistic_column_widths() == {"fsc-mean": 180}
    workspace.set_mode("Statistics detail")
    assert [workspace.tree().headerItem().text(index) for index in range(10)] == [
      "Sample", "Population", "Statistic", "Value", "Unit", "Status",
      "n valid", "n total", "Reason", "Revision",
    ]
    detail = workspace.tree().topLevelItem(0)
    assert detail.text(2) == "FSC-A mean"
    assert detail.text(3) == "123.5"
    assert detail.text(4) == "AU"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_uses_statistic_definition_name_for_column(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy({"all_events": None})
    workspace.set_statistic_definition_names({"stat-1": "Cells Mean"})
    workspace.set_result_state(
      RuntimeResultState(
        ExecutionReport(
          project_id="project",
          execution_profile_id="default",
          pipeline_version="test",
          status="success",
          population_results=(PopulationResult("sample-1", "all_events", 10, None, 1.0),),
          statistic_results=(),
        ),
        statistic_definitions=(("stat-1", "all_events"),),
        sample_ids=("sample-1",),
        population_ids=("all_events",),
      )
    )
    assert workspace.tree().headerItem().text(4) == "Cells Mean"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_preserves_nested_population_expansion(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy({
      "all_events": None, "rect-1": "all_events", "rect-2": "rect-1",
    })
    report = ExecutionReport(
      project_id="project",
      execution_profile_id="default",
      pipeline_version="test",
      status="success",
      population_results=(
        PopulationResult("sample-1", "all_events", 10, None, 1.0),
        PopulationResult("sample-1", "rect-1", 8, 0.8, 0.8),
        PopulationResult("sample-1", "rect-2", 4, 0.5, 0.4),
      ),
    )
    workspace.set_report(report)
    sample = workspace.tree().topLevelItem(0)
    all_events = sample.child(0)
    rect_1 = all_events.child(0)
    rect_2 = rect_1.child(0)
    rect_1.setExpanded(True)
    rect_2.setExpanded(True)

    workspace.set_mode("Flat table")
    workspace.set_mode("Hierarchy")
    workspace.set_report(report)

    sample = workspace.tree().topLevelItem(0)
    assert sample.child(0).isExpanded()
    assert sample.child(0).child(0).isExpanded()
    assert sample.child(0).child(0).child(0).isExpanded()
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


def test_results_workspace_add_statistic_button_uses_selected_population(qapp) -> None:
  workspace = ResultsWorkspace()
  requested: list[str] = []
  workspace.on_add_statistic_requested(requested.append)
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy(
      {"all_events": None, "rect-1": "all_events"},
      {"all_events": "All Events", "rect-1": "rect_1"},
    )
    assert workspace._add_statistic_button.text() == "Edit Statistic..."
    assert workspace._add_statistic_button.objectName() == "resultsEditStatisticButton"
    workspace.tree().setCurrentItem(workspace.tree().topLevelItem(0).child(0).child(0))
    workspace._add_statistic_button.click()
    assert requested == ["rect-1"]
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
      "Sample", "Population", "Parent", "Events", "% Parent", "% Total",
      "Status",
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
    assert zero.text(6) == "zero events"
    assert missing.text(6) == "missing"
    assert zero.childCount() == 0
    assert zero.text(5) == "-"
    assert "status=undefined" in zero.toolTip(4)
    assert "status=error" in zero.toolTip(5)

    workspace.mark_results_stale()
    stale_item = workspace.tree().topLevelItem(0).child(0)
    assert stale_item.text(6) == "stale"
    assert stale_item.foreground(6).color().name() == "#c62828"
    stale_stat = stale_item
    assert stale_stat.text(5) == "-"
    assert stale_stat.foreground(5).color().name() == "#c62828"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_results_workspace_marks_missing_statistic_without_fabricating_value(qapp) -> None:
  workspace = ResultsWorkspace()
  try:
    report = ExecutionReport(
      project_id="project",
      execution_profile_id="default",
      pipeline_version="test",
      status="success",
      population_results=(PopulationResult("sample-1", "all_events", 10, None, 1.0),),
      statistic_results=(),
    )
    state = RuntimeResultState(
      report,
      authoritative_revision=4,
      sample_ids=("sample-1",),
      population_ids=("all_events",),
      statistic_definitions=(("missing-mean", "all_events"),),
    )
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy({"all_events": None})
    workspace.set_result_state(state)
    item = workspace.tree().topLevelItem(0).child(0)
    assert item.text(4) == "-"
    assert "status=missing" in item.toolTip(4)
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
      "Channels",
    ]
    channels_tab = tab_widget.widget(2)
    assert channels_tab.findChild(QWidget, "channelMetadataWorkspace") is not None
    assert channels_tab.findChild(QTableWidget, "channelMetadataTable") is not None
    assert not window._workspace_tree.isVisible()
    assert not window._population_tree.isVisible()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_right_workspace_pane_stays_visible_when_narrowed(qapp) -> None:
  window = MainWindow()
  try:
    window.resize(1200, 800)
    window.show()
    qapp.processEvents()
    outer = window.centralWidget()
    assert isinstance(outer, QSplitter)
    right = outer.widget(1)
    tabs = right.findChild(QTabWidget, "gatingResultsTabs")
    assert tabs is not None
    assert outer.isCollapsible(1) is False
    assert right.minimumWidth() == 280
    assert tabs.minimumWidth() == 280

    outer.setSizes([max(1, outer.width() - 280), 280])
    qapp.processEvents()
    assert right.width() >= 280
    assert tabs.isVisible() or not window.isVisible()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_channels_tab_tracks_selected_sample_metadata(qapp, tmp_path) -> None:
  first = tmp_path / "alpha.fcs"
  second = tmp_path / "beta.fcs"
  write_fcs_file(first, np.ones((2, 2), dtype=np.float64), ["X", "Y"])
  write_fcs_file(second, np.ones((2, 2), dtype=np.float64), ["X", "Z"])
  window = MainWindow()
  try:
    browser = window._sample_browser
    assert browser.add_samples_from_paths([str(first), str(second)]) == 2
    samples = browser.samples()
    assert browser.select_sample(samples[1].id)
    qapp.processEvents()

    metadata = window._channel_metadata
    assert metadata.findChild(QTableWidget, "parameterCatalogTable").rowCount() == 2
    assert metadata.findChild(QTableWidget, "channelMetadataTable").rowCount() == 3
    assert metadata.findChild(QWidget, "channelMetadataSampleLabel").text() == (
      f"Sample: {samples[1].name} ({samples[1].id})"
    )
    assert metadata.findChild(QWidget, "channelMetadataStatusLabel").text() == (
      "Channel status: channel mismatch"
    )
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_results_workspace_renders_preview_overlay_in_both_modes(qapp) -> None:
  report = ExecutionReport(
    project_id="project",
    execution_profile_id="default",
    pipeline_version="test",
    status="success",
    population_results=(
      PopulationResult("sample-1", "all_events", 10, None, 1.0),
      PopulationResult("sample-1", "child", 4, 0.4, 0.4),
    ),
  )
  state = RuntimeResultState(
    report,
    authoritative_revision=1,
    sample_ids=("sample-1",),
    population_ids=("all_events", "child"),
  )
  state.invalidate(
    revision=2,
    active_sample_id="sample-1",
    affected_population_ids=("child",),
  )
  workspace = ResultsWorkspace()
  try:
    workspace.set_samples([("sample-1", "1_A1")])
    workspace.set_population_hierarchy(
      {"all_events": None, "child": "all_events"},
      {"all_events": "All Events", "child": "child"},
    )
    workspace.set_result_state(state)

    child = workspace.tree().topLevelItem(0).child(0).child(0)
    assert child.text(1) == "4"
    assert child.text(4) == "recalculating"
    assert child.foreground(4).color().name() == "#b58900"
    assert child.data(0, Qt.UserRole + 3) == 1
    assert child.data(0, Qt.UserRole + 4) == "authoritative_batch"
    assert "recalculating" in child.toolTip(0)

    assert state.accept_preview(
      PreviewReport(
        revision=2,
        project_id="project",
        execution_profile_id="default",
        sample_id="sample-1",
        strategy_id="strategy",
        required_population_id="child",
        source_event_count=10,
        status="success",
        population_results=(
          PopulationResult("sample-1", "all_events", 10, None, 1.0),
          PopulationResult("sample-1", "child", 1, 0.1, 0.1),
        ),
      )
    )
    workspace.set_result_state(state)
    child = workspace.tree().topLevelItem(0).child(0).child(0)
    assert child.text(1) == "1"
    assert child.text(4) == "current"
    assert child.foreground(4).color().name() == "#2e7d32"
    assert child.data(0, Qt.UserRole + 3) == 2
    assert child.data(0, Qt.UserRole + 4) == "active_sample_preview"

    workspace.set_mode("Flat table")
    flat_child = next(
      workspace.tree().topLevelItem(index)
      for index in range(workspace.tree().topLevelItemCount())
      if workspace.tree().topLevelItem(index).data(0, Qt.UserRole)
      == "child"
    )
    assert flat_child.text(3) == "1"
    assert flat_child.text(6) == "current"
    assert flat_child.foreground(6).color().name() == "#2e7d32"
    assert flat_child.data(0, Qt.UserRole + 3) == 2
    assert flat_child.data(0, Qt.UserRole + 4) == "active_sample_preview"
  finally:
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()
