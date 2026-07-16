"""Unified sample, population, and statistic navigation tree."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult


class WorkspaceTree(QWidget):
  """Display-only hierarchy with stable IDs for workspace navigation."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("workspaceTree")
    self._population_parents: dict[str, str | None] = {}
    self._population_names: dict[str, str] = {}
    self._samples: list[tuple[str, str]] = []
    self._report: ExecutionReport | None = None
    self._callbacks: list[Callable[[str, str, str], None]] = []
    self._tree = QTreeWidget()
    self._tree.setObjectName("workspaceHierarchyTree")
    self._tree.setHeaderLabels(["Workspace", "Type", "Value", "Status"])
    self._tree.currentItemChanged.connect(self._on_selection_changed)
    layout = QVBoxLayout(self)
    layout.addWidget(self._tree)

  def on_selection_changed(self, callback: Callable[[str, str, str], None]) -> None:
    """Register ``(kind, stable_id, sample_id)`` selection callbacks."""
    self._callbacks.append(callback)

  def set_samples(self, samples: Sequence[tuple[str, str]]) -> None:
    values = list(samples)
    if values == self._samples:
      return
    self._samples = values
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
    self._rebuild()

  def select(self, kind: str, stable_id: str) -> bool:
    iterator = self._tree.findItems(
      "", Qt.MatchContains | Qt.MatchRecursive, 0
    )
    for item in iterator:
      if item.data(0, Qt.UserRole) == stable_id and item.data(0, Qt.UserRole + 1) == kind:
        self._tree.setCurrentItem(item)
        return True
    return False

  def _rebuild(self) -> None:
    self._tree.clear()
    results = self._results_by_sample()
    stats = self._statistics_by_sample_population()
    for sample_id, sample_name in self._samples:
      sample_item = QTreeWidgetItem([sample_name, "sample", sample_id, ""])
      sample_item.setData(0, Qt.UserRole, sample_id)
      sample_item.setData(0, Qt.UserRole + 1, "sample")
      self._tree.addTopLevelItem(sample_item)
      sample_results = results.get(sample_id, ())
      by_parent: dict[str | None, list[PopulationResult]] = {}
      for result in sample_results:
        by_parent.setdefault(self._population_parents.get(result.population_id), []).append(result)
      self._add_populations(sample_item, by_parent, "all_events", stats, sample_id)
      sample_item.setExpanded(True)

  def _add_populations(
    self,
    parent_item: QTreeWidgetItem,
    by_parent: dict[str | None, list[PopulationResult]],
    parent_id: str,
    stats: dict[tuple[str, str], list[tuple[str, str, str, str]]],
    sample_id: str,
  ) -> None:
    for result in by_parent.get(parent_id, ()):
      name = self._population_names.get(result.population_id, result.population_id)
      population_item = QTreeWidgetItem(
        [name, "population", str(result.event_count), "ok"]
      )
      population_item.setData(0, Qt.UserRole, result.population_id)
      population_item.setData(0, Qt.UserRole + 1, "population")
      population_item.setData(0, Qt.UserRole + 2, sample_id)
      parent_item.addChild(population_item)
      for stat_id, name, value, status in stats.get((sample_id, result.population_id), ()):
        statistic_item = QTreeWidgetItem([name, "statistic", value, status])
        statistic_item.setData(0, Qt.UserRole, stat_id)
        statistic_item.setData(0, Qt.UserRole + 1, "statistic")
        statistic_item.setData(0, Qt.UserRole + 2, sample_id)
        population_item.addChild(statistic_item)
      self._add_populations(
        population_item, by_parent, result.population_id, stats, sample_id
      )

  def _results_by_sample(self) -> dict[str, tuple[PopulationResult, ...]]:
    if self._report is None:
      return {}
    result: dict[str, list[PopulationResult]] = {}
    for population in self._report.population_results:
      result.setdefault(population.sample_id, []).append(population)
    return {sample_id: tuple(values) for sample_id, values in result.items()}

  def _statistics_by_sample_population(
    self,
  ) -> dict[tuple[str, str], list[tuple[str, str, str, str]]]:
    if self._report is None:
      return {}
    result: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for statistic in self._report.statistic_results:
      value = "-" if statistic.value is None else str(statistic.value)
      result.setdefault((statistic.sample_id, statistic.population_id), []).append(
        (
          statistic.statistic_id,
          statistic.statistic_name or statistic.statistic_id,
          value,
          statistic.status,
        )
      )
    return result

  def _on_selection_changed(self, item: QTreeWidgetItem | None, _previous) -> None:
    if item is None:
      return
    stable_id = item.data(0, Qt.UserRole)
    kind = item.data(0, Qt.UserRole + 1)
    if stable_id is None or kind is None:
      return
    sample_id = item.data(0, Qt.UserRole + 2) or (
      stable_id if kind == "sample" else ""
    )
    for callback in self._callbacks:
      callback(str(kind), str(stable_id), str(sample_id))
