"""Executed-results workspace for sample and population navigation.

The widget is a view over ``ExecutionReport``.  It does not calculate
membership, counts, frequencies, or statistic values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
  QHeaderView,
  QAbstractItemView,
  QTreeWidget,
  QTreeWidgetItem,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult
from flowdesk_qt.diagnostics import invoke_callback


class ResultsWorkspace(QWidget):
  """Tree-table showing samples, explicit All Events, and executed results."""

  _HEADERS = [
    "Sample / Population",
    "Events",
    "% Parent",
    "% Total",
    "Status",
  ]

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("resultsWorkspace")
    self._samples: list[tuple[str, str]] = []
    self._population_parents: dict[str, str | None] = {}
    self._population_names: dict[str, str] = {}
    self._report: ExecutionReport | None = None
    self._results_stale = False
    self._callbacks: list[Callable[[str, str, str], None]] = []

    self._tree = QTreeWidget()
    self._tree.setObjectName("resultsWorkspaceTree")
    self._tree.setColumnCount(len(self._HEADERS))
    self._tree.setHeaderLabels(self._HEADERS)
    self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    self._tree.currentItemChanged.connect(self._on_selection_changed)
    header = self._tree.header()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in range(1, len(self._HEADERS)):
      header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

    layout = QVBoxLayout(self)
    layout.addWidget(self._tree)

  def on_selection_changed(
    self, callback: Callable[[str, str, str], None]
  ) -> None:
    """Register ``(kind, stable_id, sample_id)`` selection callbacks."""
    self._callbacks.append(callback)

  def set_samples(self, samples: Sequence[tuple[str, str]]) -> None:
    self._samples = list(samples)
    self._rebuild()

  def set_population_hierarchy(
    self,
    parents: Mapping[str, str | None],
    names: Mapping[str, str] | None = None,
  ) -> None:
    self._population_parents = dict(parents)
    self._population_names = dict(names or {})
    self._rebuild()

  def set_report(self, report: ExecutionReport | None) -> None:
    self._report = report
    self._results_stale = False
    self._rebuild()

  def mark_results_stale(self) -> None:
    self._results_stale = True
    self._rebuild()

  def clear(self) -> None:
    self._report = None
    self._rebuild()

  def report(self) -> ExecutionReport | None:
    return self._report

  def tree(self) -> QTreeWidget:
    """Return the view tree for stable GUI tests and accessibility tooling."""
    return self._tree

  def _rebuild(self) -> None:
    blocked = self._tree.blockSignals(True)
    try:
      self._tree.clear()
      results = self._results_by_sample()
      statistics = self._statistics_by_sample_population()
      for sample_id, sample_name in self._samples:
        sample_item = QTreeWidgetItem([sample_name, "-", "-", "-", "sample"])
        self._set_identity(sample_item, "sample", sample_id, sample_id)
        self._tree.addTopLevelItem(sample_item)

        all_result = next(
          (value for value in results.get(sample_id, ())
           if value.population_id == "all_events"),
          None,
        )
        all_item = self._population_item(all_result, sample_id, "all_events")
        sample_item.addChild(all_item)
        self._add_population_children(
          all_item,
          results.get(sample_id, ()),
          statistics,
          sample_id,
        )
        sample_item.setExpanded(True)
        all_item.setExpanded(True)
    finally:
      self._tree.blockSignals(blocked)

  def _population_item(
    self,
    result: PopulationResult | None,
    sample_id: str,
    population_id: str,
  ) -> QTreeWidgetItem:
    if result is None:
      status = "stale" if self._results_stale else "not run"
      values = ["All Events", "-", "-", "-", status]
    else:
      status = "stale" if self._results_stale else "current"
      values = [
        self._population_names.get(population_id, population_id),
        str(result.event_count),
        self._format_frequency(result.frequency_of_parent),
        self._format_frequency(result.frequency_of_total),
        status,
      ]
    item = QTreeWidgetItem(values)
    self._set_identity(item, "population", population_id, sample_id)
    return item

  def _add_population_children(
    self,
    parent_item: QTreeWidgetItem,
    results: Sequence[PopulationResult],
    statistics: Mapping[tuple[str, str], Sequence[tuple[str, str, str, str]]],
    sample_id: str,
  ) -> None:
    parent_id = parent_item.data(0, Qt.UserRole)
    children = [
      value for value in results
      if (value.population_id != "all_events"
          and (self._population_parents.get(value.population_id) or "all_events")
          == parent_id)
    ]
    for result in children:
      item = self._population_item(result, sample_id, result.population_id)
      parent_item.addChild(item)
      for statistic_id, name, value, status in statistics.get(
        (sample_id, result.population_id), ()
      ):
        statistic_item = QTreeWidgetItem([name, "-", "-", value, status])
        self._set_identity(statistic_item, "statistic", statistic_id, sample_id)
        item.addChild(statistic_item)
      self._add_population_children(item, results, statistics, sample_id)

  def _results_by_sample(self) -> dict[str, tuple[PopulationResult, ...]]:
    if self._report is None:
      return {}
    result: dict[str, list[PopulationResult]] = {}
    for value in self._report.population_results:
      result.setdefault(value.sample_id, []).append(value)
    return {sample_id: tuple(values) for sample_id, values in result.items()}

  def _statistics_by_sample_population(
    self,
  ) -> dict[tuple[str, str], list[tuple[str, str, str, str]]]:
    if self._report is None:
      return {}
    result: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for value in self._report.statistic_results:
      result.setdefault((value.sample_id, value.population_id), []).append(
        (
          value.statistic_id,
          value.statistic_name or value.statistic_id,
          "-" if value.value is None else str(value.value),
          value.status,
        )
      )
    return result

  @staticmethod
  def _format_frequency(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"

  @staticmethod
  def _set_identity(
    item: QTreeWidgetItem,
    kind: str,
    stable_id: str,
    sample_id: str,
  ) -> None:
    item.setData(0, Qt.UserRole, stable_id)
    item.setData(0, Qt.UserRole + 1, kind)
    item.setData(0, Qt.UserRole + 2, sample_id)

  def _on_selection_changed(
    self, item: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
  ) -> None:
    if item is None:
      return
    stable_id = item.data(0, Qt.UserRole)
    kind = item.data(0, Qt.UserRole + 1)
    sample_id = item.data(0, Qt.UserRole + 2)
    if stable_id is None or kind is None or sample_id is None:
      return
    for callback in self._callbacks:
      invoke_callback(callback, str(kind), str(stable_id), str(sample_id))
