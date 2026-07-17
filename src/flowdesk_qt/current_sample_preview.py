"""Presentation-only widget for non-authoritative current-sample preview data."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from flowdesk_core.preview import PreviewReport


class CurrentSamplePreview(QWidget):
  """Display preview provenance and values without performing calculations."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("currentSamplePreview")
    self._title = QLabel("Current Sample Preview")
    self._title.setObjectName("currentSamplePreviewTitle")
    self._title.setStyleSheet("QLabel { font-weight: bold; }")
    self._status = QLabel("Preview idle")
    self._status.setObjectName("currentSamplePreviewStatus")
    self._sample = QLabel("-")
    self._sample.setObjectName("currentSamplePreviewSample")
    self._population = QLabel("-")
    self._population.setObjectName("currentSamplePreviewPopulation")
    self._events = QLabel("-")
    self._events.setObjectName("currentSamplePreviewEvents")
    self._parent_frequency = QLabel("-")
    self._parent_frequency.setObjectName("currentSamplePreviewParentFrequency")
    self._total_frequency = QLabel("-")
    self._total_frequency.setObjectName("currentSamplePreviewTotalFrequency")
    self._statistics = QLabel("-")
    self._statistics.setObjectName("currentSamplePreviewStatistics")
    self._statistics.setWordWrap(True)

    form = QFormLayout()
    form.addRow("Sample", self._sample)
    form.addRow("Population", self._population)
    form.addRow("Events", self._events)
    form.addRow("% Parent", self._parent_frequency)
    form.addRow("% Total", self._total_frequency)
    form.addRow("Statistics", self._statistics)
    layout = QVBoxLayout(self)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.addWidget(self._title)
    layout.addWidget(self._status)
    layout.addLayout(form)

  def set_pending(
    self,
    sample_id: str,
    population_id: str,
    revision: int,
    *,
    batch_stale: bool,
  ) -> None:
    """Show that the requested preview has not completed yet."""
    self._sample.setText(sample_id)
    self._population.setText(population_id)
    self._status.setText(
      f"Preview — current sample only; recalculating (revision {revision})"
      + ("; Batch results stale" if batch_stale else "")
    )
    self._events.setText("-")
    self._parent_frequency.setText("-")
    self._total_frequency.setText("-")
    self._statistics.setText("-")

  def set_report(
    self,
    report: PreviewReport,
    *,
    batch_stale: bool,
    population_id: str | None = None,
  ) -> None:
    """Render a complete preview report with explicit provenance."""
    target_population_id = population_id or report.required_population_id
    result = next(
      (
        value for value in report.population_results
        if value.population_id == target_population_id
      ),
      None,
    )
    self._sample.setText(report.sample_id)
    self._population.setText(target_population_id)
    self._status.setText(
      f"Preview — current sample only; current (revision {report.revision})"
      + ("; Batch results stale" if batch_stale else "")
    )
    if result is None:
      self._events.setText("-")
      self._parent_frequency.setText("-")
      self._total_frequency.setText("-")
    else:
      self._events.setText(str(result.event_count))
      self._parent_frequency.setText(self._format_percent(result.frequency_of_parent))
      self._total_frequency.setText(self._format_percent(result.frequency_of_total))
    values = [
      f"{value.statistic_name or value.statistic_id}={value.value} ({value.status})"
      for value in report.statistic_results
      if value.population_id == target_population_id
    ]
    self._statistics.setText("; ".join(values) if values else "-")

  def set_stale(self, revision: int, population_id: str = "all_events") -> None:
    """Clear scientific values while retaining an explicit stale state."""
    self.set_pending(
      "-",
      population_id,
      revision,
      batch_stale=True,
    )
    self._status.setText(f"Preview stale (revision {revision}); Batch results stale")

  def set_error(self, message: str, revision: int) -> None:
    """Display a typed preview failure without changing authoritative results."""
    self._status.setText(f"Preview error (revision {revision}): {message}")

  def set_batch_current(self, sample_id: str | None, revision: int) -> None:
    """Show that the authoritative batch is current and preview is idle."""
    self._sample.setText(sample_id or "-")
    self._population.setText("-")
    self._events.setText("-")
    self._parent_frequency.setText("-")
    self._total_frequency.setText("-")
    self._statistics.setText("-")
    self._status.setText(
      f"Preview idle; Batch results current (revision {revision})"
    )

  @staticmethod
  def _format_percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100.0:.2f}%"
