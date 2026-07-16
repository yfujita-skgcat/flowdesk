"""GUI entry points for persisted statistic definitions."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QToolButton

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import ChannelSpec, PopulationResult
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
