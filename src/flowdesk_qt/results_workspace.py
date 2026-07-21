"""Executed-results workspace for sample and population navigation.

The widget is a view over ``ExecutionReport``.  It does not calculate
membership, counts, frequencies, or statistic values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
  QAbstractItemView,
  QComboBox,
  QHeaderView,
  QToolButton,
  QTreeWidget,
  QTreeWidgetItem,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_qt.diagnostics import invoke_callback
from flowdesk_qt.results_state import (
  ResultRowState,
  RuntimeResultState,
)


class ResultsWorkspace(QWidget):
  """Tree-table showing samples, explicit All Events, and executed results."""

  _STATUS_COLORS = {
    "current": "#2e7d32",
    "zero events": "#c47f00",
    "recalculating": "#b58900",
    "stale": "#c62828",
    "error": "#b71c1c",
    "undefined": "#6a1b9a",
    "missing": "#757575",
    "not run": "#757575",
  }

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
    self._result_state: RuntimeResultState | None = None
    self._results_stale = False
    self._force_all_stale = False
    self._mode = "Hierarchy"
    self._callbacks: list[Callable[[str, str, str], None]] = []
    self._add_statistic_callbacks: list[Callable[[str], None]] = []

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
    self._mode_selector = QComboBox()
    self._mode_selector.setObjectName("resultsViewModeSelector")
    self._mode_selector.addItems(["Hierarchy", "Flat table"])
    self._mode_selector.currentTextChanged.connect(self.set_mode)
    layout.addWidget(self._mode_selector)
    self._add_statistic_button = QToolButton()
    self._add_statistic_button.setObjectName("resultsAddStatisticButton")
    self._add_statistic_button.setText("Add Statistic...")
    self._add_statistic_button.clicked.connect(self._on_add_statistic)
    layout.addWidget(self._add_statistic_button)
    layout.addWidget(self._tree)

  def on_selection_changed(
    self, callback: Callable[[str, str, str], None]
  ) -> None:
    """Register ``(kind, stable_id, sample_id)`` selection callbacks."""
    self._callbacks.append(callback)

  def on_add_statistic_requested(self, callback: Callable[[str], None]) -> None:
    """Register the Results entry point for persisted statistic definitions."""
    self._add_statistic_callbacks.append(callback)

  def _on_add_statistic(self) -> None:
    item = self._tree.currentItem()
    population_id = "all_events"
    if item is not None and item.data(0, Qt.UserRole + 1) in {"population", "statistic"}:
      population_id = str(item.data(0, Qt.UserRole))
      if item.data(0, Qt.UserRole + 1) == "statistic":
        population_id = self._statistic_population_id_from_item(item) or "all_events"
    for callback in self._add_statistic_callbacks:
      invoke_callback(callback, population_id)

  def _statistic_population_id_from_item(self, item: QTreeWidgetItem) -> str | None:
    sample_id = item.data(0, Qt.UserRole + 2)
    statistic_id = item.data(0, Qt.UserRole)
    if self._result_state is None:
      return None
    for row in self._result_state.rows():
      if row.key.sample_id == sample_id and row.key.result_id == statistic_id:
        return self._statistic_population_id(row)
    return None

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
    statistic_definitions = () if report is None else tuple(
      (value.statistic_id, value.population_id)
      for value in report.statistic_results
    )
    self._result_state = RuntimeResultState(
      report,
      authoritative_revision=0 if report is not None else None,
      sample_ids=tuple(sample_id for sample_id, _name in self._samples),
      population_ids=tuple(self._population_parents),
      statistic_definitions=statistic_definitions,
    )
    self._results_stale = False
    self._force_all_stale = False
    self._rebuild()

  def set_result_state(self, state: RuntimeResultState | None) -> None:
    """Render one merged authoritative/preview runtime state snapshot."""
    self._result_state = state
    self._report = None if state is None else state.authoritative_report
    self._results_stale = False if state is None else state.batch_stale
    self._force_all_stale = False
    self._rebuild()

  def mark_results_stale(self) -> None:
    self._results_stale = True
    self._force_all_stale = True
    self._rebuild()

  def clear(self) -> None:
    self._report = None
    self._result_state = None
    self._force_all_stale = False
    self._rebuild()

  def report(self) -> ExecutionReport | None:
    return self._report

  def mode(self) -> str:
    return self._mode

  def set_mode(self, mode: str) -> None:
    if mode not in {"Hierarchy", "Flat table"}:
      raise ValueError(f"unknown Results workspace mode: {mode!r}")
    self._mode = mode
    self._rebuild()

  def tree(self) -> QTreeWidget:
    """Return the view tree for stable GUI tests and accessibility tooling."""
    return self._tree

  def _rebuild(self) -> None:
    blocked = self._tree.blockSignals(True)
    try:
      self._tree.clear()
      results = self._results_by_sample()
      statistics = self._statistics_by_sample_population()
      if self._mode == "Flat table":
        self._rebuild_flat(results)
        return
      self._tree.setColumnCount(len(self._HEADERS))
      self._tree.setHeaderLabels(self._HEADERS)
      header = self._tree.header()
      header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
      for column in range(1, len(self._HEADERS)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
      for sample_id, sample_name in self._samples:
        sample_item = QTreeWidgetItem([sample_name, "-", "-", "-", "sample"])
        self._set_identity(sample_item, "sample", sample_id, sample_id)
        self._tree.addTopLevelItem(sample_item)

        all_result = next(
          (value for value in results.get(sample_id, ())
           if value.key.result_id == "all_events"),
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

  def _rebuild_flat(
    self, results: Mapping[str, Sequence[ResultRowState]]
  ) -> None:
    self._tree.setColumnCount(7)
    self._tree.setHeaderLabels([
      "Sample",
      "Population",
      "Parent",
      "Events",
      "% Parent",
      "% Total",
      "Status",
    ])
    sample_names = dict(self._samples)
    result_by_sample = {
      sample_id: tuple(values) for sample_id, values in results.items()
    }
    sample_ids = [sample_id for sample_id, _name in self._samples]
    for sample_id in result_by_sample:
      if sample_id not in sample_ids:
        sample_ids.append(sample_id)
    for sample_id in sample_ids:
      values = result_by_sample.get(sample_id, ())
      result_by_id = {value.key.result_id: value for value in values}
      population_ids = ["all_events"]
      population_ids.extend(
        population_id for population_id in self._population_parents
        if population_id != "all_events"
      )
      population_ids.extend(
        value.key.result_id for value in values
        if value.key.result_id not in population_ids
      )
      for population_id in population_ids:
        value = result_by_id.get(population_id)
        parent_id = self._population_parents.get(population_id)
        result = None if value is None else value.result
        status = self._row_status(value, result)
        item = QTreeWidgetItem([
          sample_names.get(sample_id, sample_id),
          self._population_names.get(population_id, population_id),
          self._population_names.get(parent_id, parent_id or "-"),
          "-" if not isinstance(result, PopulationResult) else str(result.event_count),
          "-" if not isinstance(result, PopulationResult)
          else self._format_frequency(result.frequency_of_parent),
          "-" if not isinstance(result, PopulationResult)
          else self._format_frequency(result.frequency_of_total),
          status,
        ])
        self._set_identity(item, "population", population_id, sample_id, value)
        self._set_status_color(item, status, 6)
        self._tree.addTopLevelItem(item)
    header = self._tree.header()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for column in range(2, 7):
      header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

  def _population_item(
    self,
    row: ResultRowState | None,
    sample_id: str,
    population_id: str,
  ) -> QTreeWidgetItem:
    result = None if row is None else row.result
    population_result = result if isinstance(result, PopulationResult) else None
    status = self._row_status(row, population_result)
    values = [
      self._population_names.get(
        population_id,
        "All Events" if population_id == "all_events" else population_id,
      ),
      "-" if population_result is None else str(population_result.event_count),
      "-" if population_result is None
      else self._format_frequency(population_result.frequency_of_parent),
      "-" if population_result is None
      else self._format_frequency(population_result.frequency_of_total),
      status,
    ]
    item = QTreeWidgetItem(values)
    self._set_identity(item, "population", population_id, sample_id, row)
    self._set_status_color(item, status, 4)
    return item

  def _add_population_children(
    self,
    parent_item: QTreeWidgetItem,
    results: Sequence[ResultRowState],
    statistics: Mapping[tuple[str, str], Sequence[ResultRowState]],
    sample_id: str,
  ) -> None:
    parent_id = parent_item.data(0, Qt.UserRole)
    child_ids = [
      population_id for population_id, value in self._population_parents.items()
      if population_id != "all_events"
      and (value or "all_events") == parent_id
    ]
    for value in results:
      if value.key.result_id != "all_events" and (
        self._population_parents.get(value.key.result_id) or "all_events"
      ) == parent_id and value.key.result_id not in child_ids:
        child_ids.append(value.key.result_id)
    result_by_id = {value.key.result_id: value for value in results}
    for population_id in child_ids:
      result = result_by_id.get(population_id)
      item = self._population_item(result, sample_id, population_id)
      parent_item.addChild(item)
      for statistic_row in statistics.get((sample_id, population_id), ()):
        statistic = statistic_row.result
        statistic_result = statistic if isinstance(statistic, StatisticResult) else None
        statistic_name = (
          statistic_result.statistic_name or statistic_result.statistic_id
          if statistic_result is not None else statistic_row.key.result_id
        )
        statistic_value = (
          "-" if statistic_result is None or statistic_result.value is None
          else str(statistic_result.value)
        )
        statistic_item = QTreeWidgetItem(
          [
            statistic_name,
            "-",
            "-",
            statistic_value,
            self._row_status(statistic_row, statistic_result),
          ]
        )
        self._set_identity(
          statistic_item, "statistic", statistic_row.key.result_id, sample_id,
          statistic_row,
        )
        self._set_status_color(
          statistic_item,
          self._row_status(statistic_row, statistic_result),
          4,
        )
        if statistic_result is not None:
          statistic_item.setToolTip(
            0,
            "unit=" + str(statistic_result.unit or "")
            + "; undefined_reason=" + str(statistic_result.undefined_reason or "")
            + "; revision=" + str(statistic_row.revision),
          )
        item.addChild(statistic_item)
      self._add_population_children(item, results, statistics, sample_id)

  def _results_by_sample(self) -> dict[str, tuple[ResultRowState, ...]]:
    if self._result_state is None:
      return {}
    result: dict[str, list[ResultRowState]] = {}
    for row in self._result_state.rows():
      if row.key.kind == "population":
        result.setdefault(row.key.sample_id, []).append(row)
    return {sample_id: tuple(values) for sample_id, values in result.items()}

  def _statistics_by_sample_population(
    self,
  ) -> dict[tuple[str, str], list[ResultRowState]]:
    if self._result_state is None:
      return {}
    result: dict[tuple[str, str], list[ResultRowState]] = {}
    for row in self._result_state.rows():
      if row.key.kind != "statistic":
        continue
      population_id = self._statistic_population_id(row)
      if population_id is not None:
        result.setdefault((row.key.sample_id, population_id), []).append(row)
    return result

  def _statistic_population_id(self, row: ResultRowState) -> str | None:
    result = row.result
    if isinstance(result, StatisticResult):
      return result.population_id
    if self._result_state is None:
      return None
    for definition_id, population_id in self._result_state.statistic_definitions.items():
      if definition_id == row.key.result_id:
        return population_id
    return None

  def _row_status(
    self,
    row: ResultRowState | None,
    result: PopulationResult | StatisticResult | None,
  ) -> str:
    if self._force_all_stale:
      return "stale"
    if row is None:
      return "not run" if self._report is None else "missing"
    if row.freshness != "current":
      return row.freshness
    if isinstance(result, StatisticResult) and result.status != "ok":
      return result.status
    if isinstance(result, PopulationResult) and result.event_count == 0:
      return "zero events"
    return "current"

  @staticmethod
  def _format_frequency(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"

  @classmethod
  def _set_status_color(
    cls, item: QTreeWidgetItem, status: str, column: int
  ) -> None:
    """Color only the status text; values and status semantics remain unchanged."""
    color = cls._STATUS_COLORS.get(status)
    if color is not None:
      item.setForeground(column, QBrush(QColor(color)))

  @staticmethod
  def _set_identity(
    item: QTreeWidgetItem,
    kind: str,
    stable_id: str,
    sample_id: str,
    row: ResultRowState | None = None,
  ) -> None:
    item.setData(0, Qt.UserRole, stable_id)
    item.setData(0, Qt.UserRole + 1, kind)
    item.setData(0, Qt.UserRole + 2, sample_id)
    if row is not None:
      item.setData(0, Qt.UserRole + 3, row.revision)
      item.setData(0, Qt.UserRole + 4, row.source)
      item.setToolTip(
        0,
        f"source={row.source}; revision={row.revision}; freshness={row.freshness}",
      )

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
