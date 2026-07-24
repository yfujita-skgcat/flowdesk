"""Display-only options for current plot image export."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFormLayout,
  QSpinBox,
  QWidget,
)


@dataclass(frozen=True)
class PlotExportRequest:
  """A GUI request; scientific analysis state is intentionally absent."""

  format_name: str
  width: int = 800
  height: int = 600
  aspect_1_to_1: bool = False
  include_title: bool = True
  include_axis_labels: bool = True
  include_ticks: bool = True
  include_gates: bool = True
  include_legend: bool = True
  include_status_banner: bool = False
  layout_policy: str = "current_view"

  def metadata(self) -> dict[str, object]:
    return {
      "format": self.format_name,
      "width": self.width,
      "height": self.height,
      "aspect_1_to_1": self.aspect_1_to_1,
      "include_title": self.include_title,
      "include_axis_labels": self.include_axis_labels,
      "include_ticks": self.include_ticks,
      "include_gates": self.include_gates,
      "include_legend": self.include_legend,
      "include_status_banner": self.include_status_banner,
      "layout_policy": self.layout_policy,
    }


class PlotExportDialog(QDialog):
  """Collect export-layer visibility options without changing the view."""

  def __init__(self, format_name: str, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("plotExportOptionsDialog")
    self.setWindowTitle("Plot Export Options")
    self._format = QComboBox()
    self._format.setObjectName("plotExportFormatCombo")
    self._format.addItems(["PNG", "JPEG", "SVG", "PDF"])
    self._format.setCurrentText(format_name)
    self._width = QSpinBox()
    self._width.setObjectName("plotExportWidthSpinBox")
    self._width.setRange(1, 20_000)
    self._width.setValue(800)
    self._height = QSpinBox()
    self._height.setObjectName("plotExportHeightSpinBox")
    self._height.setRange(1, 20_000)
    self._height.setValue(600)
    self._aspect = QCheckBox("1:1 aspect")
    self._aspect.setObjectName("plotExportAspectCheckBox")
    self._title = self._check("Include title", "plotExportIncludeTitleCheckBox", True)
    self._labels = self._check(
      "Include axis labels", "plotExportIncludeAxisLabelsCheckBox", True
    )
    self._ticks = self._check("Include ticks", "plotExportIncludeTicksCheckBox", True)
    self._gates = self._check("Include gates", "plotExportIncludeGatesCheckBox", True)
    self._legend = self._check("Include legend", "plotExportIncludeLegendCheckBox", True)
    self._status = self._check(
      "Include status banner", "plotExportIncludeStatusCheckBox", False
    )
    form = QFormLayout(self)
    form.addRow("Format", self._format)
    form.addRow("Width", self._width)
    form.addRow("Height", self._height)
    form.addRow("Aspect", self._aspect)
    for widget in (
      self._title, self._labels, self._ticks, self._gates, self._legend, self._status
    ):
      form.addRow(widget)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("plotExportDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    form.addRow(buttons)

  @staticmethod
  def _check(label: str, object_name: str, checked: bool) -> QCheckBox:
    widget = QCheckBox(label)
    widget.setObjectName(object_name)
    widget.setChecked(checked)
    return widget

  def request(self) -> PlotExportRequest:
    return PlotExportRequest(
      format_name=self._format.currentText(),
      width=self._width.value(),
      height=self._height.value(),
      aspect_1_to_1=self._aspect.isChecked(),
      include_title=self._title.isChecked(),
      include_axis_labels=self._labels.isChecked(),
      include_ticks=self._ticks.isChecked(),
      include_gates=self._gates.isChecked(),
      include_legend=self._legend.isChecked(),
      include_status_banner=self._status.isChecked(),
    )
