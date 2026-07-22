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
  QMenu,
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
    "disabled": "#9e9e9e",
  }

  _HEADERS = [
    "Sample / Population",
    "Events",
    "% Parent",
    "% Total",
  ]
  _STATUS_HEADER = "Population Status"

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
    self._statistic_columns: list[str] = []
    self._display_statistic_columns: list[str] = []
    self._statistic_names: dict[str, str] = {}
    self._statistic_headers: dict[str, str] = {}
    self._statistic_header_tooltips: dict[str, str] = {}
    self._visible_statistic_ids: set[str] | None = None
    self._statistic_column_order: list[str] = []
    self._statistic_column_widths: dict[str, int] = {}
    self._callbacks: list[Callable[[str, str, str], None]] = []
    self._add_statistic_callbacks: list[Callable[[str], None]] = []
    self._manage_statistic_callbacks: list[Callable[[], None]] = []

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
    self._mode_selector.addItem("Statistics detail")
    self._mode_selector.currentTextChanged.connect(self.set_mode)
    layout.addWidget(self._mode_selector)
    self._add_statistic_button = QToolButton()
    self._add_statistic_button.setObjectName("resultsAddStatisticButton")
    self._add_statistic_button.setText("Add Statistic...")
    self._add_statistic_button.clicked.connect(self._on_add_statistic)
    layout.addWidget(self._add_statistic_button)
    self._manage_statistics_button = QToolButton()
    self._manage_statistics_button.setObjectName("resultsManageStatisticsButton")
    self._manage_statistics_button.setText("Manage Statistics...")
    self._manage_statistics_button.clicked.connect(self._on_manage_statistics)
    layout.addWidget(self._manage_statistics_button)
    self._column_button = QToolButton()
    self._column_button.setObjectName("resultsStatisticColumnsButton")
    self._column_button.setText("Columns...")
    self._column_menu = QMenu(self._column_button)
    self._column_button.setMenu(self._column_menu)
    self._column_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    layout.addWidget(self._column_button)
    layout.addWidget(self._tree)

  def on_selection_changed(
    self, callback: Callable[[str, str, str], None]
  ) -> None:
    """Register ``(kind, stable_id, sample_id)`` selection callbacks."""
    self._callbacks.append(callback)

  def on_add_statistic_requested(self, callback: Callable[[str], None]) -> None:
    """Register the Results entry point for persisted statistic definitions."""
    self._add_statistic_callbacks.append(callback)

  def on_manage_statistics_requested(self, callback: Callable[[], None]) -> None:
    """Register the shared editor entry point for existing definitions."""
    self._manage_statistic_callbacks.append(callback)

  def _on_manage_statistics(self) -> None:
    for callback in self._manage_statistic_callbacks:
      invoke_callback(callback)

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
    if mode not in {"Hierarchy", "Flat table", "Statistics detail"}:
      raise ValueError(f"unknown Results workspace mode: {mode!r}")
    self._mode = mode
    self._rebuild()

  def tree(self) -> QTreeWidget:
    """Return the view tree for stable GUI tests and accessibility tooling."""
    return self._tree

  def statistic_column_visibility(self) -> dict[str, bool]:
    """Return display-only visibility for dynamic statistic columns."""
    visible = self._visible_statistic_ids
    return {
      statistic_id: visible is None or statistic_id in visible
      for statistic_id in self._statistic_columns
    }

  def set_statistic_column_visibility(self, visibility: Mapping[str, bool]) -> None:
    """Set display-only visibility without changing analysis definitions."""
    self._visible_statistic_ids = {
      statistic_id for statistic_id, is_visible in visibility.items()
      if is_visible
    }
    self._rebuild()

  def statistic_column_order(self) -> tuple[str, ...]:
    return tuple(self._statistic_column_order)

  def set_statistic_column_order(self, order: Sequence[str]) -> None:
    self._statistic_column_order = list(dict.fromkeys(str(value) for value in order))
    self._rebuild()

  def statistic_column_widths(self) -> dict[str, int]:
    return dict(self._statistic_column_widths)

  def set_statistic_column_widths(self, widths: Mapping[str, int]) -> None:
    self._statistic_column_widths = {
      str(statistic_id): int(width)
      for statistic_id, width in widths.items()
      if int(width) > 0
    }
    self._apply_statistic_column_widths()

  def _rebuild(self) -> None:
    blocked = self._tree.blockSignals(True)
    try:
      self._tree.clear()
      results = self._results_by_sample()
      self._configure_statistic_columns()
      self._refresh_column_menu()
      if self._mode == "Statistics detail":
        self._rebuild_statistics_detail()
        return
      if self._mode == "Flat table":
        self._rebuild_flat(results)
        return
      headers = self._result_headers()
      self._tree.setColumnCount(len(headers))
      self._tree.setHeaderLabels(headers)
      self._set_header_tooltips()
      header = self._tree.header()
      header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
      for column in range(1, len(headers)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
      self._apply_statistic_column_widths()
      for sample_id, sample_name in self._samples:
        sample_item = QTreeWidgetItem(
          [sample_name, "-", "-", "-"]
          + ["-" for _ in self._display_statistic_columns]
          + ["sample"]
        )
        self._set_identity(sample_item, "sample", sample_id, sample_id)
        self._tree.addTopLevelItem(sample_item)

        all_result = next(
          (value for value in results.get(sample_id, ())
           if value.key.result_id == "all_events"),
          None,
        )
        all_item = self._population_item(
          all_result, sample_id, "all_events", results.get(sample_id, ())
        )
        sample_item.addChild(all_item)
        self._add_population_children(
          all_item,
          results.get(sample_id, ()),
          sample_id,
        )
        sample_item.setExpanded(True)
        all_item.setExpanded(True)
    finally:
      self._tree.blockSignals(blocked)

  def _rebuild_flat(
    self, results: Mapping[str, Sequence[ResultRowState]]
  ) -> None:
    headers = [
      "Sample",
      "Population",
      "Parent",
      "Events",
      "% Parent",
      "% Total",
    ] + [self._statistic_headers[stat_id] for stat_id in self._display_statistic_columns] + [
      self._STATUS_HEADER,
    ]
    self._tree.setColumnCount(len(headers))
    self._tree.setHeaderLabels(headers)
    self._set_header_tooltips(base_column=6)
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
        ] + self._statistic_values(sample_id, population_id, values) + [status])
        self._set_identity(item, "population", population_id, sample_id, value)
        self._set_status_color(
          item, status, len(self._display_statistic_columns) + 6
        )
        self._apply_statistic_cell_state(item, sample_id, population_id)
        self._tree.addTopLevelItem(item)
    header = self._tree.header()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for column in range(2, len(headers)):
      header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    self._apply_statistic_column_widths(base_column=6)

  def _population_item(
    self,
    row: ResultRowState | None,
    sample_id: str,
    population_id: str,
    results: Sequence[ResultRowState] = (),
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
    ] + self._statistic_values(sample_id, population_id, results) + [status]
    item = QTreeWidgetItem(values)
    self._set_identity(item, "population", population_id, sample_id, row)
    self._set_status_color(
      item, status, len(self._display_statistic_columns) + len(self._HEADERS)
    )
    self._apply_statistic_cell_state(item, sample_id, population_id)
    return item

  def _add_population_children(
    self,
    parent_item: QTreeWidgetItem,
    results: Sequence[ResultRowState],
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
      item = self._population_item(result, sample_id, population_id, results)
      parent_item.addChild(item)
      self._add_population_children(item, results, sample_id)

  def _results_by_sample(self) -> dict[str, tuple[ResultRowState, ...]]:
    if self._result_state is None:
      return {}
    result: dict[str, list[ResultRowState]] = {}
    for row in self._result_state.rows():
      if row.key.kind == "population":
        result.setdefault(row.key.sample_id, []).append(row)
    return {sample_id: tuple(values) for sample_id, values in result.items()}

  def _configure_statistic_columns(self) -> None:
    """Build deterministic dynamic columns from the shared result snapshot."""
    names: dict[str, str] = {}
    order: list[str] = []
    if self._report is not None:
      for result in self._report.statistic_results:
        if result.statistic_id not in names:
          names[result.statistic_id] = (
            result.statistic_name or result.statistic_id
          )
          order.append(result.statistic_id)
    if self._result_state is not None:
      for statistic_id in self._result_state.statistic_definitions:
        if statistic_id not in names:
          names[statistic_id] = statistic_id
          order.append(statistic_id)
      self._statistic_rows = {
        (row.key.sample_id, row.key.result_id, row.key.population_id): row
        for row in self._result_state.rows()
        if row.key.kind == "statistic" and row.key.population_id
      }
    else:
      self._statistic_rows = {}
    self._statistic_columns = order
    if self._statistic_column_order:
      ordered = [
        statistic_id for statistic_id in self._statistic_column_order
        if statistic_id in order
      ]
      order = ordered + [statistic_id for statistic_id in order if statistic_id not in ordered]
      self._statistic_columns = order
    self._display_statistic_columns = [
      statistic_id for statistic_id in order
      if self._visible_statistic_ids is None
      or statistic_id in self._visible_statistic_ids
    ]
    self._statistic_names = names
    self._statistic_headers = {
      statistic_id: names[statistic_id] for statistic_id in order
    }
    self._statistic_header_tooltips = {}
    if self._report is not None:
      for result in self._report.statistic_results:
        self._statistic_header_tooltips.setdefault(
          result.statistic_id,
          "statistic_id=" + result.statistic_id
          + "; metric=" + result.metric
          + "; unit=" + str(result.unit or ""),
        )

  def _set_header_tooltips(self, *, base_column: int = len(_HEADERS)) -> None:
    header = self._tree.headerItem()
    for offset, statistic_id in enumerate(self._display_statistic_columns):
      header.setToolTip(
        base_column + offset,
        self._statistic_header_tooltips.get(
          statistic_id, "statistic_id=" + statistic_id
        ),
      )

  def _result_headers(self) -> list[str]:
    return self._HEADERS + [
      self._statistic_headers[statistic_id]
      for statistic_id in self._display_statistic_columns
    ] + [self._STATUS_HEADER]

  def _statistic_values(
    self,
    sample_id: str,
    population_id: str,
    _population_results: Sequence[ResultRowState],
  ) -> list[str]:
    """Render statistic cells without calculating or formatting core values."""
    values: list[str] = []
    for _offset, statistic_id in enumerate(self._display_statistic_columns):
      row = self._statistic_rows.get((sample_id, statistic_id, population_id))
      result = None if row is None else row.result
      statistic_result = result if isinstance(result, StatisticResult) else None
      value = (
        "-" if statistic_result is None or statistic_result.value is None
        else str(statistic_result.value)
      )
      values.append(value)
    return values

  def _apply_statistic_cell_state(
    self, item: QTreeWidgetItem, sample_id: str, population_id: str
  ) -> None:
    for offset, statistic_id in enumerate(self._display_statistic_columns):
      row = self._statistic_rows.get((sample_id, statistic_id, population_id))
      result = None if row is None else row.result
      statistic_result = result if isinstance(result, StatisticResult) else None
      status = self._row_status(row, statistic_result)
      column = len(self._HEADERS) + offset
      self._set_status_color(item, status, column)
      if row is None:
        continue
      item.setToolTip(
        column,
        f"statistic_id={statistic_id}; status={status}; "
        + "unit=" + str(statistic_result.unit if statistic_result else "")
        + "; undefined_reason=" + str(
          statistic_result.undefined_reason if statistic_result else ""
        )
        + "; n_total=" + str(
          statistic_result.n_total if statistic_result else ""
        )
        + "; n_valid=" + str(
          statistic_result.n_valid if statistic_result else ""
        )
        + "; n_invalid=" + str(
          statistic_result.n_invalid if statistic_result else ""
        )
        + "; invalid_fraction=" + str(
          statistic_result.invalid_fraction if statistic_result else ""
        )
        + "; non_finite_policy=" + str(
          statistic_result.non_finite_policy if statistic_result else ""
        )
        + f"; revision={row.revision}; source={row.source}",
      )

  def _refresh_column_menu(self) -> None:
    self._column_menu.clear()
    for statistic_id in self._statistic_columns:
      action = self._column_menu.addAction(self._statistic_headers[statistic_id])
      action.setCheckable(True)
      action.setChecked(
        self._visible_statistic_ids is None
        or statistic_id in self._visible_statistic_ids
      )
      action.setData(statistic_id)
      action.triggered.connect(self._on_statistic_column_toggled)
    self._column_button.setEnabled(bool(self._statistic_columns))

  def _on_statistic_column_toggled(self, checked: bool) -> None:
    action = self.sender()
    statistic_id = action.data() if action is not None else None
    if not isinstance(statistic_id, str):
      return
    visible = set(self._statistic_columns)
    if self._visible_statistic_ids is not None:
      visible = set(self._visible_statistic_ids)
    if checked:
      visible.add(statistic_id)
    else:
      visible.discard(statistic_id)
    self._visible_statistic_ids = visible
    self._rebuild()

  def _apply_statistic_column_widths(self, *, base_column: int = len(_HEADERS)) -> None:
    for offset, statistic_id in enumerate(self._display_statistic_columns):
      width = self._statistic_column_widths.get(statistic_id)
      if width is not None:
        self._tree.setColumnWidth(base_column + offset, width)

  def _rebuild_statistics_detail(self) -> None:
    headers = [
      "Sample", "Population", "Statistic", "Value", "Unit", "Status",
      "n valid", "n total", "Reason", "Revision",
    ]
    self._tree.setColumnCount(len(headers))
    self._tree.setHeaderLabels(headers)
    self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    for column in range(3, len(headers)):
      self._tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    if self._result_state is None:
      return
    sample_names = dict(self._samples)
    rows = sorted(
      (
        row for row in self._result_state.rows()
        if row.key.kind == "statistic"
      ),
      key=lambda row: (row.key.sample_id, row.key.population_id, row.key.result_id),
    )
    for row in rows:
      result = row.result if isinstance(row.result, StatisticResult) else None
      status = self._row_status(row, result)
      item = QTreeWidgetItem([
        sample_names.get(row.key.sample_id, row.key.sample_id),
        self._population_names.get(row.key.population_id, row.key.population_id),
        result.statistic_name if result is not None else row.key.result_id,
        "-" if result is None or result.value is None else str(result.value),
        "" if result is None else str(result.unit or ""),
        status,
        "" if result is None or result.n_valid is None else str(result.n_valid),
        "" if result is None or result.n_total is None else str(result.n_total),
        "" if result is None else str(result.undefined_reason or ""),
        "" if row.revision is None else str(row.revision),
      ])
      self._set_identity(item, "statistic", row.key.result_id, row.key.sample_id, row)
      self._set_status_color(item, status, 5)
      self._tree.addTopLevelItem(item)

  def _statistic_population_id(self, row: ResultRowState) -> str | None:
    result = row.result
    if isinstance(result, StatisticResult):
      return result.population_id
    if row.key.population_id:
      return row.key.population_id
    if self._result_state is None:
      return None
    for definition_id, population_ids in self._result_state.statistic_definitions.items():
      if definition_id == row.key.result_id:
        if len(population_ids) == 1:
          return population_ids[0]
        return None
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
