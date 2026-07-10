"""Population tree widget.

Displays the population hierarchy resulting from pipeline execution.
Data is received from ``ExecutionReport`` via ``flowdesk_core``.

This widget contains NO scientific execution logic.
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# PopulationTree widget
# ---------------------------------------------------------------------------


class PopulationTree(QWidget):
    """Table displaying population statistics from an execution report."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._last_report: ExecutionReport | None = None
        self._population_parents: dict[str, str | None] = {}
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

    def clear(self) -> None:
        """Clear all displayed data."""
        self._last_report = None
        self._table.setRowCount(0)
        self._status_label.setText("No execution results")

    # -- private ------------------------------------------------------------

    def _populate_table(self, results: tuple[PopulationResult, ...]) -> None:
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            parent_id = self._population_parents.get(r.population_id)
            depth = self._population_depth(r.population_id)
            label = f"{'  ' * depth}{r.population_id}"
            self._table.setItem(row, 0, QTableWidgetItem(label))
            self._table.setItem(row, 1, QTableWidgetItem(parent_id or "-"))
            self._table.setItem(row, 2, QTableWidgetItem(r.sample_id))
            self._table.setItem(row, 3, QTableWidgetItem(str(r.event_count)))
            freq_parent = (
                f"{r.frequency_of_parent:.4f}" if r.frequency_of_parent is not None else "-"
            )
            freq_total = f"{r.frequency_of_total:.4f}" if r.frequency_of_total is not None else "-"
            self._table.setItem(row, 4, QTableWidgetItem(freq_parent))
            self._table.setItem(row, 5, QTableWidgetItem(freq_total))

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
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            [
                "Population",
                "Parent",
                "Sample",
                "Events",
                "Freq. of Parent",
                "Freq. of Total",
            ]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self._status_label = QLabel("No execution results")

        box = QGroupBox("Population Results")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self._table)
        box_layout.addWidget(self._status_label)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
