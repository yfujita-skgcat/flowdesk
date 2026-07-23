"""Display structured pipeline diagnostics without performing analysis."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
  QAbstractItemView,
  QGroupBox,
  QHeaderView,
  QLabel,
  QPlainTextEdit,
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
        if column == 4:
          # Keep the table compact while making the complete diagnostic available
          # without relying on the column width.
          item.setToolTip(value)
        if diagnostic.severity == "error":
          item.setForeground(Qt.GlobalColor.red)
        elif diagnostic.severity == "warning":
          item.setForeground(Qt.GlobalColor.darkYellow)
        self._table.setItem(row, column, item)
    if report.diagnostics:
      self._table.selectRow(0)
    self._status_label.setText(
      f"Diagnostics: {len(report.diagnostics)} ({report.status})"
    )

  def clear(self, *, stale: bool = False) -> None:
    """Discard displayed diagnostics when their pipeline result is stale."""
    self._table.setRowCount(0)
    self._detail_edit.clear()
    self._detail_edit.setPlaceholderText("Select a diagnostic to view its full message")
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
    self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    self._table.itemSelectionChanged.connect(self._show_selected_message)
    self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    self._detail_label = QLabel("Selected diagnostic message")
    self._detail_label.setObjectName("pipelineDiagnosticsDetailLabel")
    self._detail_edit = QPlainTextEdit()
    self._detail_edit.setObjectName("pipelineDiagnosticsDetailEdit")
    self._detail_edit.setReadOnly(True)
    self._detail_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    self._detail_edit.setMinimumHeight(64)
    self._detail_edit.setMaximumHeight(160)
    self._detail_edit.setPlaceholderText("Select a diagnostic to view its full message")

    self._status_label = QLabel("No diagnostics")
    self._status_label.setObjectName("pipelineDiagnosticsStatusLabel")

    group = QGroupBox("Pipeline Diagnostics")
    group_layout = QVBoxLayout(group)
    group_layout.addWidget(self._table)
    group_layout.addWidget(self._detail_label)
    group_layout.addWidget(self._detail_edit)
    group_layout.addWidget(self._status_label)

    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(group)

  def _show_selected_message(self) -> None:
    row = self._table.currentRow()
    item = self._table.item(row, 4) if row >= 0 else None
    if item is None:
      self._detail_edit.clear()
      self._detail_edit.setPlaceholderText("Select a diagnostic to view its full message")
      return
    self._detail_edit.setPlaceholderText("")
    self._detail_edit.setPlainText(item.text())
