"""GUI entry points for persisted statistic definitions."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QToolButton

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import ChannelSpec, PopulationResult, StatisticResult
from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.plot_toolbar import PlotToolbar
from flowdesk_qt.population_tree import PopulationTree
from flowdesk_qt.statistics_editor import StatisticsEditorDialog

pytestmark = pytest.mark.gui


def test_population_tree_add_statistic_uses_selected_population(qapp) -> None:
  tree = PopulationTree()
  report = ExecutionReport(
    project_id="project",
    execution_profile_id="default",
    pipeline_version="0.1",
    status="success",
    population_results=(
      PopulationResult("s1", "all_events", 10, None, 1.0),
      PopulationResult("s1", "live", 5, 10, 0.5),
    ),
  )
  tree.set_report(report)
  tree._table.selectRow(1)
  selected: list[str] = []
  tree.on_add_statistic_requested(selected.append)

  tree._add_statistic_button.click()

  assert selected == ["live"]


def test_graph_add_statistic_button_emits_callback(qapp) -> None:
  toolbar = PlotToolbar()
  calls: list[str] = []
  toolbar.on_add_statistic(lambda: calls.append("called"))

  button = toolbar.findChild(QToolButton, "addStatisticFromGraphButton")
  assert button is not None
  button.click()

  assert calls == ["called"]


def test_dialog_new_statistic_defaults_are_persisted_state(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events", "live"),
    new_statistic_defaults={
      "population_id": "live",
      "parameter_id": "FL1-A",
      "metric": "mean",
    },
  )

  definition = dialog._statistics[-1]
  assert definition["population_id"] == "live"
  assert definition["parameter_id"] == "FL1-A"
  assert definition["metric"] == "mean"
  assert definition["value_policy"] == "full_events"


def test_value_metric_enables_parameter_selector(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  assert not dialog._parameter_combo.isEnabled()
  dialog._metric_combo.setCurrentText("mean")
  assert dialog._parameter_combo.isEnabled()


def test_results_add_statistic_defaults_to_active_x_parameter(qapp, monkeypatch) -> None:
  window = MainWindow()
  captured: dict[str, object] = {}
  window._channel_selector.set_channel_specs(
    (ChannelSpec(id="FL1-A", name="FL1-A"),)
  )
  monkeypatch.setattr(
    window,
    "_open_statistics_editor",
    lambda **kwargs: captured.update(kwargs),
  )
  try:
    window._on_add_statistic_from_results("all_events")
    assert captured == {
      "population_id": "all_events",
      "parameter_id": "FL1-A",
    }
  finally:
    window.close()
    window.deleteLater()


def test_statistics_editor_duplicate_creates_new_definition(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[{
      "id": "mean", "name": "Mean", "population_id": "live",
      "parameter_id": "FL1-A", "metric": "mean", "source_stage": "compensated",
      "value_policy": "full_events", "settings": {}, "format": None, "notes": "",
    }],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("live",),
  )
  dialog._duplicate_button.click()
  assert len(dialog._statistics) == 2
  assert dialog._statistics[1]["id"] == "mean-copy"


def test_statistics_editor_persists_nonfinite_policy(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[{
      "id": "mean", "name": "Mean", "population_id": "live",
      "parameter_id": "FL1-A", "metric": "mean", "source_stage": "compensated",
      "non_finite_policy": "exclude_invalid",
    }],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("live",),
  )
  assert dialog._nonfinite_combo.currentData() == "exclude_invalid"
  dialog._commit_current()
  assert dialog._statistics[0]["non_finite_policy"] == "exclude_invalid"


def test_statistics_are_population_child_nodes_and_clear_when_stale(qapp) -> None:
  tree = PopulationTree()
  tree.set_population_names({"live": "Live cells"})
  tree.set_report(
    ExecutionReport(
      project_id="project",
      execution_profile_id="default",
      pipeline_version="0.1",
      status="success",
      population_results=(PopulationResult("s1", "live", 5, 10, 0.5),),
      statistic_results=(
        StatisticResult(
          sample_id="s1",
          statistic_id="live_mean",
          statistic_name="Live mean FL1",
          population_id="live",
          metric="mean",
          value=12.5,
          status="ok",
        ),
      ),
    )
  )

  population_node = tree._statistics_tree.topLevelItem(0)
  assert population_node.text(0) == "Live cells"
  assert population_node.data(0, Qt.UserRole) == "live"
  statistic_node = population_node.child(0)
  assert statistic_node.text(0) == "Live mean FL1"
  assert statistic_node.text(1) == "mean"
  assert statistic_node.text(2) == "12.5"
  assert statistic_node.text(3) == "ok"

  tree.clear()
  tree.mark_results_stale()
  assert tree._statistics_tree.topLevelItemCount() == 0
  assert tree._status_label.text() == "Results stale; rerun pipeline"


def test_graph_entry_opens_dialog_with_graph_context(qapp, monkeypatch) -> None:
  captured: dict[str, object] = {}

  class RejectedDialog:
    def __init__(self, *args, **kwargs) -> None:
      captured["defaults"] = kwargs["new_statistic_defaults"]

    def exec(self) -> QDialog.DialogCode:
      return QDialog.DialogCode.Rejected

  monkeypatch.setattr(
    "flowdesk_qt.statistics_editor.StatisticsEditorDialog",
    RejectedDialog,
  )
  window = MainWindow()
  try:
    window._selected_population_id = "live"
    window._channel_selector.set_channel_specs(
      (ChannelSpec(id="FL1-A", name="FL1-A"),)
    )

    window._on_add_statistic_from_graph()

    assert captured["defaults"] == {
      "population_id": "live",
      "parameter_id": "FL1-A",
      "metric": "mean",
    }
  finally:
    window.close()
    window.deleteLater()


def test_results_add_statistic_entrypoint_uses_shared_editor(qapp, monkeypatch) -> None:
  window = MainWindow()
  captured: list[str] = []
  monkeypatch.setattr(
    window, "_open_statistics_editor",
    lambda **kwargs: captured.append(str(kwargs["population_id"])),
  )
  try:
    window._results_workspace._on_add_statistic()
    assert captured == ["all_events"]
  finally:
    window.close()
    window.deleteLater()


def test_main_window_exposes_sample_sheet_and_batch_plot_actions(qapp) -> None:
  window = MainWindow()
  try:
    assert window.action_sample_sheet.objectName() == "actionSampleSheet"
    assert window.action_batch_plot_export.objectName() == "actionBatchPlotExport"
  finally:
    window.close()
    window.deleteLater()


def test_gui_batch_plot_action_delegates_to_cli_core_runner(qapp, monkeypatch, tmp_path) -> None:
  window = MainWindow()
  calls: list[tuple[str, str, str]] = []
  window._project_path = tmp_path / "project.flowdesk"
  window._batch_plot_exports = [{"id": "export"}]
  monkeypatch.setattr(
    "flowdesk_qt.main_window.QFileDialog.getExistingDirectory",
    lambda *_args: str(tmp_path / "plots"),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.batch_plot_command",
    lambda project, export_id, output: calls.append((project, export_id, output)) or 0,
  )
  try:
    window._on_batch_plot_export()
    assert calls == [(str(window._project_path), "export", str(tmp_path / "plots"))]
  finally:
    window.close()
    window.deleteLater()
