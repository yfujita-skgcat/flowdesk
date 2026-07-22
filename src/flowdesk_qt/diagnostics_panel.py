"""Display structured pipeline diagnostics without performing analysis."""

from __future__ import annotations

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


class DiagnosticsPanel(QWidget):
  """Read-only presentation of ``ExecutionReport.diagnostics``."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("diagnosticsPanel")
    self._build_ui()

  def set_report(self, report: ExecutionReport) -> None:
    """Display diagnostics from one completed headless pipeline run."""
    self._table.setRowCount(len(report.diagnostics))
    for row, diagnostic in enumerate(report.diagnostics):
      values = (
        diagnostic.severity,
        diagnostic.code,
        diagnostic.stage,
        diagnostic.sample_id or "",
        diagnostic.message,
      )
      for column, value in enumerate(values):
        item = QTableWidgetItem(value)
        if diagnostic.severity == "error":
          item.setForeground(Qt.GlobalColor.red)
        elif diagnostic.severity == "warning":
          item.setForeground(Qt.GlobalColor.darkYellow)
        self._table.setItem(row, column, item)
    self._status_label.setText(
      f"Diagnostics: {len(report.diagnostics)} ({report.status})"
    )

  def clear(self, *, stale: bool = False) -> None:
    """Discard displayed diagnostics when their pipeline result is stale."""
    self._table.setRowCount(0)
    self._status_label.setText(
      "Diagnostics stale; rerun pipeline" if stale else "No diagnostics"
    )

  def _build_ui(self) -> None:
    self._table = QTableWidget()
    self._table.setObjectName("pipelineDiagnosticsTable")
    self._table.setColumnCount(5)
    self._table.setHorizontalHeaderLabels(
      ["Severity", "Code", "Stage", "Sample", "Message"]
    )
    self._table.setEditTriggers(QTableWidget.NoEditTriggers)
    self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

    self._status_label = QLabel("No diagnostics")
    self._status_label.setObjectName("pipelineDiagnosticsStatusLabel")

    group = QGroupBox("Pipeline Diagnostics")
    group_layout = QVBoxLayout(group)
    group_layout.addWidget(self._table)
    group_layout.addWidget(self._status_label)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(group)
