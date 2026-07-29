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
from flowdesk_qt.statistics_editor import (
  StatisticManagementDialog,
  StatisticsEditorDialog,
)

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


def test_dialog_open_does_not_create_statistic_until_new_is_clicked(qapp) -> None:
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

  assert dialog._statistics == []
  dialog._new_button.click()
  definition = dialog._statistics[-1]
  assert definition["population_id"] == "live"
  assert definition["parameter_id"] == "FL1-A"
  assert definition["metric"] == "mean"
  assert definition["value_policy"] == "full_events"
  assert definition["name"] == "FL1-A_mean"
  assert definition["id"] == "stat_fl1_a_mean"
  assert not dialog._id_edit.isReadOnly()

  dialog.definitions()
  assert dialog._id_edit.isReadOnly()


def test_new_statistic_id_is_editable_until_dialog_accept(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events", "rect_1"),
    population_labels={"all_events": "All Events", "rect_1": "rect_1"},
    new_statistic_defaults={
      "population_id": "rect_1",
      "parameter_id": "FL1-A",
      "metric": "mean",
    },
  )

  dialog._new_button.click()
  generated_id = dialog._statistics[0]["id"]
  assert not dialog._id_edit.isReadOnly()
  dialog._id_edit.setText("manually_changed")

  assert dialog.definitions()[0]["id"] == "manually_changed"
  assert dialog._id_edit.isReadOnly()
  assert generated_id != "manually_changed"


def test_value_metric_enables_parameter_selector(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  assert not dialog._parameter_combo.isEnabled()
  dialog._metric_combo.setCurrentText("mean")
  assert dialog._parameter_combo.isEnabled()


def test_statistics_editor_persists_population_scope_and_compute_flag(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events", "live", "marker"),
    population_parents={"live": "all_events", "marker": "live"},
  )
  dialog._new_button.click()
  dialog._id_edit.setText("live_mean")
  dialog._name_edit.setText("Live mean")
  dialog._population_combo.setCurrentText("all_events")
  dialog._population_scope_combo.setCurrentText(
    "Current population and descendants"
  )
  dialog._metric_combo.setCurrentText("mean")
  dialog._parameter_combo.setCurrentText("FL1-A [FL1-A]")
  dialog._compute_check.setChecked(False)

  definition = dialog.definitions()[0]
  assert definition["population_id"] == "all_events"
  assert definition["population_ids"] == ["all_events", "live", "marker"]
  assert definition["compute_enabled"] is False


def test_statistics_editor_undo_redo_and_missing_target_diagnostic(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  dialog._new_button.click()
  dialog._id_edit.setText("missing")
  dialog._name_edit.setText("Missing target")
  dialog._target_population_ids = ("deleted_gate",)
  dialog._update_population_scope_label()
  assert "deleted_gate" in dialog._diag_label.text()
  with pytest.raises(ValueError, match="missing population target"):
    dialog.definitions()

  dialog._undo_button.click()
  assert dialog._statistics == []
  dialog._redo_button.click()
  assert len(dialog._statistics) == 1


def test_statistics_editor_reports_removed_population_dependency(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[{
      "id": "gate_mean",
      "name": "Gate mean",
      "population_id": "removed_gate",
      "population_ids": ["removed_gate"],
      "parameter_id": "FL1-A",
      "metric": "mean",
      "source_stage": "compensated",
    }],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  assert "removed_gate" in dialog._diag_label.text()
  with pytest.raises(ValueError, match="missing population target"):
    dialog.definitions()


def test_statistics_editor_assigns_id_to_named_legacy_definition(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[{
      "id": "",
      "name": "FITC B525-H",
      "population_id": "all_events",
      "population_ids": ["all_events"],
      "parameter_id": "FITC B525-H",
      "metric": "mean",
      "source_stage": "raw",
    }],
    available_channels=(ChannelSpec(id="FITC B525-H", name="FITC B525-H"),),
    population_ids=("all_events",),
  )

  definitions = dialog.definitions()

  assert definitions[0]["id"] == "stat_fitc_b525_h"


def test_statistic_management_repairs_missing_id_and_drops_blank_rows(qapp) -> None:
  dialog = StatisticManagementDialog(
    statistics=[
      {"id": "", "name": "FITC B525-H", "parameter_id": "FITC B525-H"},
      {"id": "", "name": "", "parameter_id": None},
    ],
  )

  definitions = dialog.definitions()

  assert [value["id"] for value in definitions] == ["stat_fitc_b525_h"]


def test_statistics_editor_blocks_delete_with_downstream_reference(qapp, monkeypatch) -> None:
  messages: list[str] = []
  monkeypatch.setattr(
    "flowdesk_qt.statistics_editor.QMessageBox.information",
    lambda _parent, _title, message: messages.append(str(message)),
  )
  dialog = StatisticsEditorDialog(
    statistics=[{"id": "mean", "name": "Mean", "population_id": "all_events"}],
    available_channels=(),
    population_ids=("all_events",),
    statistic_references={"mean": ("Group strategy binding: binding-1",)},
  )
  dialog._delete_button.click()
  assert len(dialog._statistics) == 1
  assert "binding-1" in messages[0]


def test_statistics_editor_rejects_empty_selected_scope(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  dialog._new_button.click()
  dialog._id_edit.setText("empty")
  dialog._name_edit.setText("Empty target")
  dialog._population_scope_combo.blockSignals(True)
  dialog._population_scope_combo.setCurrentText("Selected populations...")
  dialog._population_scope_combo.blockSignals(False)
  dialog._target_population_ids = ()
  with pytest.raises(ValueError, match="no population targets"):
    dialog.definitions()


def test_statistics_editor_population_targets_dialog_uses_qt6_item_data(
  qapp, monkeypatch,
) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events", "live", "marker"),
    population_parents={"live": "all_events", "marker": "live"},
  )
  dialog._new_button.click()
  dialog._target_population_ids = ("all_events", "live")
  monkeypatch.setattr(
    QDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted,
  )

  dialog._select_population_targets()

  assert dialog._target_population_ids == ("all_events", "live")


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


def test_results_manage_statistics_entrypoint_uses_shared_editor(qapp) -> None:
  from flowdesk_qt.results_workspace import ResultsWorkspace

  workspace = ResultsWorkspace()
  calls: list[str] = []
  workspace.on_manage_statistics_requested(lambda: calls.append("manage"))
  workspace._manage_statistics_button.click()
  assert calls == ["manage"]


def test_statistic_management_dialog_separates_compute_and_show(qapp) -> None:
  dialog = StatisticManagementDialog(
    [{
      "id": "mean",
      "name": "Mean",
      "population_ids": ["all_events", "live"],
      "parameter_id": "FL1-A",
      "metric": "mean",
      "source_stage": "compensated",
      "compute_enabled": True,
    }],
    {"mean": True},
    parameter_labels={"FL1-A": "FSC-A"},
    population_labels={"all_events": "All Events", "live": "Live cells"},
  )
  compute = dialog.findChild(type(dialog._compute_checks["mean"]), "statisticComputeCheck_mean")
  show = dialog.findChild(type(dialog._show_checks["mean"]), "statisticShowCheck_mean")
  assert compute is not None and show is not None
  compute.setChecked(False)
  show.setChecked(False)
  assert dialog.definitions()[0]["compute_enabled"] is False
  assert dialog.visibility() == {"mean": False}
  assert [dialog._table.horizontalHeaderItem(index).text() for index in range(7)] == [
    "Compute", "Show", "Statistic", "Parameter", "Metric", "Value domain",
    "Applies to",
  ]
  assert dialog._table.item(0, 3).text() == "FSC-A"
  assert dialog._table.item(0, 6).text() == "All Events, Live cells"


def test_statistic_management_edits_population_targets(qapp, monkeypatch) -> None:
  dialog = StatisticManagementDialog(
    [{
      "id": "mean",
      "name": "Mean",
      "population_ids": ["all_events"],
      "parameter_id": "FL1-A",
      "metric": "mean",
    }],
    population_labels={"all_events": "All Events", "live": "Live cells"},
    population_ids=("all_events", "live"),
    population_parents={"all_events": None, "live": "all_events"},
  )
  monkeypatch.setattr(
    "flowdesk_qt.statistics_editor.choose_population_targets",
    lambda *_args: ("all_events", "live"),
  )

  dialog._edit_targets(0)

  definition = dialog.definitions()[0]
  assert definition["population_ids"] == ["all_events", "live"]
  assert definition["population_id"] == "all_events"
  assert dialog._table.item(0, 6).text() == "All Events, Live cells"


def test_statistic_definition_fields_are_editable(qapp) -> None:
  dialog = StatisticsEditorDialog(
    statistics=[{
      "id": "stat_mean",
      "name": "Old name",
      "population_id": "all_events",
      "population_ids": ["all_events"],
      "parameter_id": "FL1-A",
      "metric": "mean",
      "source_stage": "raw",
      "value_policy": "full_events",
    }],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )
  dialog._name_edit.setText("Renamed statistic")
  dialog._parameter_combo.setCurrentIndex(
    dialog._parameter_combo.findData("FL1-A")
  )
  dialog._metric_combo.setCurrentText("median")
  dialog._source_combo.setCurrentText("compensated")

  definition = dialog.definitions()[0]
  assert definition["id"] == "stat_mean"
  assert definition["name"] == "Renamed statistic"
  assert definition["parameter_id"] == "FL1-A"
  assert definition["metric"] == "median"
  assert definition["source_stage"] == "compensated"


def test_statistic_management_opens_definition_editor(qapp, monkeypatch) -> None:
  dialog = StatisticManagementDialog(
    [{
      "id": "stat_mean",
      "name": "Old name",
      "population_ids": ["all_events"],
      "parameter_id": "FL1-A",
      "metric": "mean",
      "source_stage": "raw",
    }],
    available_channels=(ChannelSpec(id="FL1-A", name="FL1-A"),),
    population_ids=("all_events",),
  )

  class AcceptedEditor:
    def __init__(self, statistics, *_args, **_kwargs) -> None:
      self._definition = dict(statistics[0])

    def exec(self):
      return QDialog.DialogCode.Accepted

    def definitions(self):
      updated = dict(self._definition)
      updated["name"] = "Edited name"
      updated["parameter_id"] = "FL1-A"
      updated["metric"] = "median"
      updated["source_stage"] = "transformed"
      return [updated]

  monkeypatch.setattr(
    "flowdesk_qt.statistics_editor.StatisticsEditorDialog", AcceptedEditor,
  )
  dialog._table.selectRow(0)
  dialog._edit_selected_definition()

  updated = dialog.definitions()[0]
  assert updated["id"] == "stat_mean"
  assert updated["name"] == "Edited name"
  assert updated["metric"] == "median"
  assert updated["source_stage"] == "transformed"


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
  window._batch_plot_exports = [{"id": "export", "name": "Export"}]

  class AcceptedDialog:
    def __init__(self, *_args, **_kwargs):
      pass

    def exec(self):
      return 1

    def request(self):
      from flowdesk_qt.batch_plot_export_dialog import BatchPlotExportRequest

      return BatchPlotExportRequest(
        {"id": "export", "name": "Export", "target": "all", "formats": ["png"]},
        str(tmp_path / "plots"),
        True,
      )

  monkeypatch.setattr("flowdesk_qt.main_window.BatchPlotExportDialog", AcceptedDialog)
  monkeypatch.setattr(
    "flowdesk_qt.main_window.batch_plot_export_spec_from_mapping",
    lambda value: value,
  )
  monkeypatch.setattr(
    "flowdesk_qt.main_window.MainWindow._save_project_to_path",
    lambda *_args: None,
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


def test_gui_batch_plot_action_deletes_persisted_definition(qapp, monkeypatch, tmp_path) -> None:
  window = MainWindow()
  window._project_path = tmp_path / "project.flowdesk"
  window._batch_plot_exports = [{"id": "export", "name": "Export"}]

  class AcceptedDialog:
    def __init__(self, *_args, **_kwargs):
      pass

    def exec(self):
      return QDialog.DialogCode.Accepted

    def request(self):
      from flowdesk_qt.batch_plot_export_dialog import BatchPlotExportRequest

      return BatchPlotExportRequest({}, "", False, delete_definition_id="export")

  saved: list[str] = []
  monkeypatch.setattr("flowdesk_qt.main_window.BatchPlotExportDialog", AcceptedDialog)
  monkeypatch.setattr(
    "flowdesk_qt.main_window.MainWindow._save_project_to_path",
    lambda path: saved.append(str(path)),
  )
  try:
    window._on_batch_plot_export()
    assert window._batch_plot_exports == []
    assert saved == [str(window._project_path)]
  finally:
    window.close()
    window.deleteLater()
