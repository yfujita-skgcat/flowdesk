"""Population tree widget.

Displays the population hierarchy resulting from pipeline execution.
Data is received from ``ExecutionReport`` via ``flowdesk_core``.

This widget contains NO scientific execution logic.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_qt.diagnostics import invoke_callback

# ---------------------------------------------------------------------------
# PopulationTree widget
# ---------------------------------------------------------------------------


class PopulationTree(QWidget):
    """Table displaying population statistics from an execution report."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("populationTree")
        self._last_report: ExecutionReport | None = None
        self._population_parents: dict[str, str | None] = {}
        self._population_names: dict[str, str] = {}
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def set_report(self, report: ExecutionReport) -> None:
        """Populate the table from an ``ExecutionReport``."""
        self._last_report = report
        self._populate_table(report.population_results)
        self._populate_statistics(report.statistic_results)
        self._status_label.setText(
            f"Status: {report.status}  |  Populations: {len(report.population_results)}"
            + (
                f"  |  Statistics: {len(report.statistic_results)}"
                if report.statistic_results
                else ""
            )
        )

    def last_report(self) -> ExecutionReport | None:
        """Return the last loaded report."""
        return self._last_report

    def set_population_parents(self, parents: dict[str, str | None]) -> None:
        """Set display-only hierarchy metadata from the active gate strategy."""
        self._population_parents = dict(parents)

    def set_population_names(self, names: dict[str, str]) -> None:
        """Set display names for population IDs.

        Maps internal population IDs (e.g. ``gate_ab12``) to human-readable
        display names (e.g. ``CD45 positive``).  The root population
        ``all_events`` should map to ``All Events``.
        """
        self._population_names = dict(names)

    def get_selected_population_id(self) -> str | None:
        """Return the population ID of the currently selected row.

        Returns ``None`` if no row is selected.
        """
        selected = self._table.selectedItems()
        if not selected:
            return None
        row = self._table.row(selected[0])
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def get_selected_sample_id(self) -> str | None:
        """Return the sample ID stored on the selected population row."""
        selected = self._table.selectedItems()
        if not selected:
            return None
        item = self._table.item(self._table.row(selected[0]), 0)
        return None if item is None else item.data(Qt.UserRole + 1)

    def on_population_selected(
        self,
        callback: Callable[[str, str], None],
    ) -> None:
        """Register a callback for population selection changes.

        The callback receives ``(population_id: str, sample_id: str)``.
        When no row is selected the callback is *not* invoked.
        """
        self._selection_callbacks.append(callback)

    def on_add_statistic_requested(
        self,
        callback: Callable[[str], None],
    ) -> None:
        """Register a callback to create a statistic for the selected population."""
        self._add_statistic_callbacks.append(callback)

    def get_current_sample_id(self) -> str | None:
        """Return the sample_id associated with the current report data."""
        if self._last_report is None:
            return None
        results = self._last_report.population_results
        if not results:
            return None
        return results[0].sample_id

    def clear(self) -> None:
        """Clear all displayed data."""
        self._last_report = None
        self._population_names.clear()
        self._table.setRowCount(0)
        self._statistics_tree.clear()
        self._status_label.setText("No execution results")

    def mark_results_stale(self) -> None:
        """Display that results were discarded and require a pipeline rerun."""
        self._status_label.setText("Results stale; rerun pipeline")

    # -- private ------------------------------------------------------------

    def _populate_table(self, results: tuple[PopulationResult, ...]) -> None:
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            parent_id = self._population_parents.get(r.population_id)
            depth = self._population_depth(r.population_id)
            display_name = self._population_names.get(
                r.population_id, r.population_id
            )
            label = f"{'  ' * depth}{display_name}"
            pop_item = QTableWidgetItem(label)
            pop_item.setData(Qt.UserRole, r.population_id)
            pop_item.setData(Qt.UserRole + 1, r.sample_id)
            self._table.setItem(row, 0, pop_item)

            parent_display = self._population_names.get(parent_id, parent_id or "-")
            parent_item = QTableWidgetItem(parent_display)
            if parent_id is not None:
                parent_item.setData(Qt.UserRole, parent_id)
            self._table.setItem(row, 1, parent_item)

            self._table.setItem(row, 2, QTableWidgetItem(r.sample_id))
            self._table.setItem(row, 3, QTableWidgetItem(str(r.event_count)))
            freq_parent = (
                f"{r.frequency_of_parent:.4f}" if r.frequency_of_parent is not None else "-"
            )
            freq_total = f"{r.frequency_of_total:.4f}" if r.frequency_of_total is not None else "-"
            self._table.setItem(row, 4, QTableWidgetItem(freq_parent))
            self._table.setItem(row, 5, QTableWidgetItem(freq_total))

    def _populate_statistics(
        self, results: tuple[StatisticResult, ...]
    ) -> None:
        self._statistics_tree.clear()
        population_nodes: dict[tuple[str, str], QTreeWidgetItem] = {}
        for r in results:
            key = (r.sample_id, r.population_id)
            population_node = population_nodes.get(key)
            pop_display = self._population_names.get(
                r.population_id, r.population_id
            )
            if population_node is None:
                population_node = QTreeWidgetItem([pop_display, "", "", ""])
                population_node.setData(0, Qt.UserRole, r.population_id)
                population_node.setData(0, Qt.UserRole + 1, r.sample_id)
                population_nodes[key] = population_node
                self._statistics_tree.addTopLevelItem(population_node)

            value_str = "-"
            if r.value is not None:
                if isinstance(r.value, float):
                    value_str = f"{r.value:.6g}"
                else:
                    value_str = str(r.value)

            status_text = r.status
            if r.status == "undefined" and r.undefined_reason is not None:
                status_text = f"undefined ({r.undefined_reason})"
            statistic_item = QTreeWidgetItem(
                [
                    r.statistic_name or r.statistic_id,
                    r.metric,
                    value_str,
                    status_text,
                ]
            )
            statistic_item.setData(0, Qt.UserRole, r.statistic_id)
            if r.status == "ok":
                statistic_item.setForeground(3, Qt.GlobalColor.darkGreen)
            elif r.status in ("error", "undefined"):
                statistic_item.setForeground(3, Qt.GlobalColor.red)
            population_node.addChild(statistic_item)
        self._statistics_tree.expandAll()

    def _on_selection_changed(self) -> None:
        population_id = self.get_selected_population_id()
        if population_id is None:
            return
        sample_id = self.get_selected_sample_id() or ""
        for cb in self._selection_callbacks:
            invoke_callback(cb, population_id, sample_id)

    def _on_add_statistic_clicked(self) -> None:
        population_id = self.get_selected_population_id() or "all_events"
        for cb in self._add_statistic_callbacks:
            invoke_callback(cb, population_id)

    def _population_depth(self, population_id: str) -> int:
        depth = 0
        seen = {population_id}
        parent_id = self._population_parents.get(population_id)
        while parent_id and parent_id != "all_events" and parent_id not in seen:
            depth += 1
            seen.add(parent_id)
            parent_id = self._population_parents.get(parent_id)
        return depth + (1 if self._population_parents.get(population_id) else 0)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._selection_callbacks: list[Callable[[str, str], None]] = []
        self._add_statistic_callbacks: list[Callable[[str], None]] = []

        self._table = QTableWidget()
        self._table.setObjectName("populationResultsTable")
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            [
                "Population",
                "Parent",
                "Sample",
                "Events",
                "% of Parent",
                "% of Total",
            ]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._status_label = QLabel("No execution results")
        self._status_label.setObjectName("populationStatusLabel")

        box = QGroupBox("Population Results")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self._table)
        box_layout.addWidget(self._status_label)

        # --- Custom statistics grouped under their populations ---
        self._statistics_tree = QTreeWidget()
        self._statistics_tree.setObjectName("populationStatisticsTree")
        self._statistics_tree.setColumnCount(4)
        self._statistics_tree.setHeaderLabels(
            [
                "Population / Statistic",
                "Metric",
                "Value",
                "Status",
            ]
        )
        self._statistics_tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self._statistics_tree.header().setSectionResizeMode(
            QHeaderView.Stretch
        )

        stat_box = QGroupBox("Custom Statistics")
        stat_box_layout = QVBoxLayout(stat_box)
        stat_box_layout.addWidget(self._statistics_tree)
        self._add_statistic_button = QPushButton("Add Statistic")
        self._add_statistic_button.setObjectName(
            "addStatisticFromPopulationTreeButton"
        )
        self._add_statistic_button.setToolTip(
            "Create a statistic definition for the selected population"
        )
        self._add_statistic_button.clicked.connect(self._on_add_statistic_clicked)
        stat_box_layout.addWidget(self._add_statistic_button)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(stat_box)
