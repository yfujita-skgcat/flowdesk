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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult
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
        self._status_label.setText(
            f"Status: {report.status}  |  Populations: {len(report.population_results)}"
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
        self._status_label.setText("No execution results")

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

    def _on_selection_changed(self) -> None:
        population_id = self.get_selected_population_id()
        if population_id is None:
            return
        sample_id = self.get_selected_sample_id() or ""
        for cb in self._selection_callbacks:
            invoke_callback(cb, population_id, sample_id)

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

        layout = QVBoxLayout(self)
        layout.addWidget(box)
