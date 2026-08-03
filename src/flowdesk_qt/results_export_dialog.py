"""Options dialog for the unified Results export."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFormLayout,
  QListWidget,
  QListWidgetItem,
  QWidget,
)


@dataclass(frozen=True)
class ResultsExportOptions:
  destination: str = "file"
  layout: str = "wide"
  include_population_metrics: bool = True
  include_custom_statistics: bool = True
  include_internal_ids: bool = False
  include_qc: bool = False
  population_ids: tuple[str, ...] | None = None


class ResultsExportDialog(QDialog):
  """Collect export choices without reading result table cells."""

  def __init__(
    self,
    parent: QWidget | None = None,
    population_options: tuple[tuple[str, str], ...] = (),
  ) -> None:
    super().__init__(parent)
    self.setObjectName("resultsExportDialog")
    self.setWindowTitle("Export Results")
    form = QFormLayout(self)

    self._layout = QComboBox(self)
    self._layout.setObjectName("resultsExportLayoutCombo")
    self._layout.addItem("Wide table", "wide")
    self._layout.addItem("Long detail table", "long")
    form.addRow("Layout:", self._layout)

    self._populations = QListWidget(self)
    self._populations.setObjectName("resultsExportPopulationList")
    self._populations.setSelectionMode(
      QListWidget.SelectionMode.NoSelection
    )
    self._populations.setToolTip(
      "Select the populations to include in the export"
    )
    for population_id, population_path in population_options:
      item = QListWidgetItem(population_path, self._populations)
      item.setData(Qt.ItemDataRole.UserRole, population_id)
      item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
      item.setCheckState(Qt.CheckState.Checked)
    form.addRow("Populations:", self._populations)

    self._destination = QComboBox(self)
    self._destination.setObjectName("resultsExportDestinationCombo")
    self._destination.addItem("File", "file")
    self._destination.addItem("Clipboard (TSV)", "clipboard")
    self._destination.setToolTip(
      "Copy tab-separated results for direct paste into Excel or Google Sheets"
    )
    form.insertRow(0, "Destination:", self._destination)

    self._population = QCheckBox("Population counts and frequencies", self)
    self._population.setObjectName("resultsExportPopulationCheck")
    self._population.setChecked(True)
    form.addRow(self._population)
    self._statistics = QCheckBox("Custom statistics", self)
    self._statistics.setObjectName("resultsExportStatisticsCheck")
    self._statistics.setChecked(True)
    form.addRow(self._statistics)
    self._internal_ids = QCheckBox(
      "Include internal IDs and hierarchy metadata", self
    )
    self._internal_ids.setObjectName("resultsExportInternalIdsCheck")
    form.addRow(self._internal_ids)
    self._qc = QCheckBox("Include status and QC metadata", self)
    self._qc.setObjectName("resultsExportQcCheck")
    form.addRow(self._qc)

    self._buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
      parent=self,
    )
    self._buttons.setObjectName("resultsExportDialogButtons")
    self._buttons.accepted.connect(self._accept_if_valid)
    self._buttons.rejected.connect(self.reject)
    form.addRow(self._buttons)

  def _accept_if_valid(self) -> None:
    if not self._population.isChecked() and not self._statistics.isChecked():
      self._population.setFocus()
      return
    if self._populations.count() and not self.population_ids():
      self._populations.setFocus()
      return
    self.accept()

  def population_ids(self) -> tuple[str, ...]:
    """Return checked stable population IDs in displayed order."""
    return tuple(
      str(item.data(Qt.ItemDataRole.UserRole))
      for index in range(self._populations.count())
      if (item := self._populations.item(index)).checkState()
      == Qt.CheckState.Checked
    )

  def options(self) -> ResultsExportOptions:
    return ResultsExportOptions(
      destination=str(self._destination.currentData()),
      layout=str(self._layout.currentData()),
      include_population_metrics=self._population.isChecked(),
      include_custom_statistics=self._statistics.isChecked(),
      include_internal_ids=self._internal_ids.isChecked(),
      include_qc=self._qc.isChecked(),
      population_ids=self.population_ids() or None,
    )
