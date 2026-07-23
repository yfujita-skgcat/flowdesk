"""Read-only GUI presentation of structured pipeline diagnostics."""

from __future__ import annotations

import pytest

from flowdesk_core.execution_report import ExecutionDiagnostic, ExecutionReport
from flowdesk_qt.diagnostics_panel import DiagnosticsPanel

pytestmark = pytest.mark.gui


def test_diagnostics_panel_displays_execution_report_diagnostics(qapp) -> None:
  panel = DiagnosticsPanel()
  message = "A long diagnostic message that should remain available in full."
  report = ExecutionReport(
    project_id="project",
    execution_profile_id="default",
    pipeline_version="0.1",
    status="partial_success",
    diagnostics=(
      ExecutionDiagnostic(
        code="derived_parameter_evaluation_failed",
        message=message,
        severity="warning",
        stage="derived_parameters",
        sample_id="sample-1",
      ),
    ),
  )

  panel.set_report(report)

  assert panel._table.rowCount() == 1
  assert [panel._table.item(0, column).text() for column in range(5)] == [
    "warning",
    "derived_parameter_evaluation_failed",
    "derived_parameters",
    "sample-1",
    message,
  ]
  assert panel._table.item(0, 4).toolTip() == message
  assert panel._detail_edit.toPlainText() == message
  assert panel._status_label.text() == "Diagnostics: 1 (partial_success)"


def test_diagnostics_panel_discards_old_rows_when_stale(qapp) -> None:
  panel = DiagnosticsPanel()
  panel.set_report(
    ExecutionReport(
      project_id="project",
      execution_profile_id="default",
      pipeline_version="0.1",
      status="success",
      diagnostics=(
        ExecutionDiagnostic(
          code="test_diagnostic",
          message="Old result",
          severity="info",
          stage="test",
        ),
      ),
    )
  )

  panel.clear(stale=True)

  assert panel._table.rowCount() == 0
  assert panel._detail_edit.toPlainText() == ""
  assert panel._status_label.text() == "Diagnostics stale; rerun pipeline"
