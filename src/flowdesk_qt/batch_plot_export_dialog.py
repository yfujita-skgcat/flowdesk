"""Qt-only editor for persisted batch plot export definitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QFileDialog,
  QFormLayout,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QListWidget,
  QListWidgetItem,
  QMessageBox,
  QPushButton,
  QSpinBox,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.plot_export import resolve_export_canvas


@dataclass(frozen=True)
class BatchPlotExportRequest:
  """Serializable dialog output; it contains no loaded event data."""

  definition: dict[str, Any]
  output_dir: str
  run: bool


class BatchPlotExportDialog(QDialog):
  """Edit a ``BatchPlotExportSpec`` and select a session output directory."""

  _OUTPUT_DIRECTORY_KEY = "batch_plot_export/output_directory"

  def __init__(
    self,
    definitions: Sequence[Mapping[str, Any]],
    samples: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    plot_views: Sequence[Mapping[str, Any]],
    current_view_id: str,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("batchPlotExportDialog")
    self.setWindowTitle("Batch Plot Export")
    self.resize(620, 760)
    self._definitions = [dict(item) for item in definitions]
    self._samples = [dict(item) for item in samples]
    self._groups = [dict(item) for item in groups]
    self._views = [dict(item) for item in plot_views]
    self._run = False

    self._definition = QComboBox()
    self._definition.setObjectName("batchPlotDefinitionCombo")
    self._definition.addItem("New definition", "")
    for item in self._definitions:
      self._definition.addItem(
        str(item.get("name") or item.get("id") or "Unnamed"),
        str(item.get("id", "")),
      )
    self._definition.currentIndexChanged.connect(self._load_selected_definition)
    new_button = QPushButton("New")
    new_button.setObjectName("batchPlotNewDefinitionButton")
    new_button.clicked.connect(lambda: self._definition.setCurrentIndex(0))

    self._name = QLineEdit()
    self._name.setObjectName("batchPlotNameLineEdit")
    self._target = QComboBox()
    self._target.setObjectName("batchPlotTargetCombo")
    self._target.addItem("All samples", "all")
    self._target.addItem("Explicit samples", "explicit")
    self._target.addItem("Sample group", "group")
    self._target.currentIndexChanged.connect(self._update_target_widgets)
    self._sample_list = QListWidget()
    self._sample_list.setObjectName("batchPlotSampleList")
    self._sample_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
    for sample in self._samples:
      item = QListWidgetItem(str(sample.get("name") or sample.get("id")))
      item.setData(32, str(sample.get("id", "")))
      self._sample_list.addItem(item)
    self._group = QComboBox()
    self._group.setObjectName("batchPlotGroupCombo")
    for group in self._groups:
      self._group.addItem(
        str(group.get("name") or group.get("id")), str(group.get("id", ""))
      )
    self._view = QComboBox()
    self._view.setObjectName("batchPlotViewCombo")
    view_items = self._views or [{"id": current_view_id, "name": "Current view"}]
    for view in view_items:
      self._view.addItem(
        str(view.get("name") or view.get("id") or "View"),
        str(view.get("id", "")),
      )
    index = self._view.findData(current_view_id)
    if index >= 0:
      self._view.setCurrentIndex(index)

    self._formats: dict[str, QCheckBox] = {}
    format_layout = QHBoxLayout()
    for value, label in (("png", "PNG"), ("jpg", "JPEG"), ("svg", "SVG"), ("pdf", "PDF")):
      check = QCheckBox(label)
      check.setObjectName(f"batchPlotFormat{value.upper()}CheckBox")
      self._formats[value] = check
      format_layout.addWidget(check)

    self._width = self._spin("batchPlotWidthSpinBox", 1, 20000, 800)
    self._height = self._spin("batchPlotHeightSpinBox", 1, 20000, 600)
    self._dpi = self._spin("batchPlotDPISpinBox", 1, 1200, 96)
    self._resolution_mode = QComboBox()
    self._resolution_mode.setObjectName("batchPlotRasterResolutionModeCombo")
    self._resolution_mode.addItem("Legacy pixel dimensions", "legacy_pixel_dimensions")
    self._resolution_mode.addItem("Scale pixels by DPI", "dpi_scaled")
    self._resolution_preview = QLabel()
    self._resolution_preview.setObjectName("batchPlotResolutionPreviewLabel")
    self._resolution_preview.setWordWrap(True)
    for widget in (self._width, self._height, self._dpi):
      widget.valueChanged.connect(self._update_resolution_preview)
    self._resolution_mode.currentIndexChanged.connect(self._update_resolution_preview)
    for check in self._formats.values():
      check.toggled.connect(self._update_resolution_preview)
    self._aspect = self._check("1:1 aspect", "batchPlotAspectCheckBox")
    self._layout_policy = QComboBox()
    self._layout_policy.setObjectName("batchPlotLayoutPolicyCombo")
    self._layout_policy.addItem("Current view", "current_view")
    self._layout_policy.addItem("Shared ranges", "shared_ranges")

    self._visibility: dict[str, QCheckBox] = {}
    for key, label, checked in (
      ("include_title", "Title", True),
      ("include_axis_labels", "Axis labels", True),
      ("include_ticks", "Ticks", True),
      ("include_gates", "Gates", True),
      ("include_legend", "Legend", True),
      ("include_status_banner", "Status banner", False),
    ):
      self._visibility[key] = self._check(label, f"batchPlot{key}CheckBox", checked)

    self._template = QLineEdit()
    self._template.setObjectName("batchPlotFilenameTemplateLineEdit")
    self._collision = QComboBox()
    self._collision.setObjectName("batchPlotCollisionPolicyCombo")
    self._collision.addItem("Fail on collision", "fail")
    self._collision.addItem("Replace existing", "replace")
    self._collision.addItem("Add suffix", "suffix")
    self._strict = self._check("Strict export", "batchPlotStrictCheckBox", True)
    self._output = QLineEdit()
    self._output.setObjectName("batchPlotOutputDirectoryLineEdit")
    browse = QPushButton("Browse…")
    browse.setObjectName("batchPlotBrowseOutputButton")
    browse.clicked.connect(self._browse_output)

    form = QFormLayout()
    definition_row = QHBoxLayout()
    definition_row.addWidget(self._definition)
    definition_row.addWidget(new_button)
    form.addRow("Definition", definition_row)
    form.addRow("Name", self._name)
    form.addRow("Target", self._target)
    form.addRow("Samples", self._sample_list)
    form.addRow("Group", self._group)
    form.addRow("Plot view", self._view)
    form.addRow("Formats", format_layout)
    form.addRow("Canvas width (logical px @ 96 DPI)", self._width)
    form.addRow("Canvas height (logical px @ 96 DPI)", self._height)
    form.addRow("Raster DPI", self._dpi)
    form.addRow("Raster resolution", self._resolution_mode)
    form.addRow("Effective output", self._resolution_preview)
    form.addRow("Aspect", self._aspect)
    form.addRow("Layout", self._layout_policy)
    form.addRow("Visibility", self._visibility["include_title"])
    for key in (
      "include_axis_labels", "include_ticks", "include_gates", "include_legend",
      "include_status_banner",
    ):
      form.addRow("", self._visibility[key])
    form.addRow("Filename template", self._template)
    form.addRow("Collision", self._collision)
    form.addRow("", self._strict)
    output_row = QHBoxLayout()
    output_row.addWidget(self._output)
    output_row.addWidget(browse)
    form.addRow("Output directory", output_row)
    self._output.setText(
      str(QSettings().value(self._OUTPUT_DIRECTORY_KEY, "", type=str) or "")
    )

    save = QPushButton("Save Definition")
    save.setObjectName("batchPlotSaveDefinitionButton")
    save.clicked.connect(self._accept_save)
    run = QPushButton("Run Export")
    run.setObjectName("batchPlotRunExportButton")
    run.clicked.connect(self._accept_run)
    cancel = QPushButton("Cancel")
    cancel.setObjectName("batchPlotCancelButton")
    cancel.clicked.connect(self.reject)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    buttons.addWidget(save)
    buttons.addWidget(run)
    buttons.addWidget(cancel)

    layout = QVBoxLayout(self)
    layout.addWidget(QLabel("Create or update a reusable export definition."))
    layout.addLayout(form)
    layout.addLayout(buttons)
    self._load_selected_definition(0)

  @staticmethod
  def _spin(name: str, minimum: int, maximum: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setObjectName(name)
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin

  @staticmethod
  def _check(label: str, name: str, checked: bool = False) -> QCheckBox:
    check = QCheckBox(label)
    check.setObjectName(name)
    check.setChecked(checked)
    return check

  def _browse_output(self) -> None:
    path = QFileDialog.getExistingDirectory(self, "Select batch plot output directory")
    if path:
      self._output.setText(path)

  def _update_target_widgets(self) -> None:
    target = str(self._target.currentData())
    self._sample_list.setEnabled(target == "explicit")
    self._group.setEnabled(target == "group")
    self._update_resolution_preview()

  def _load_selected_definition(self, _index: int) -> None:
    definition_id = str(self._definition.currentData() or "")
    value = next(
      (item for item in self._definitions if str(item.get("id", "")) == definition_id),
      {},
    )
    defaults: dict[str, Any] = {
      "name": "Batch export",
      "target": "all",
      "sample_ids": [],
      "group_id": None,
      "plot_view_id": self._view.currentData() or "main-view",
      "formats": ["png"],
      "width": 800,
      "height": 600,
      "dpi": 96,
      "raster_resolution_mode": "dpi_scaled",
      "aspect_1_to_1": False,
      "layout_policy": "current_view",
      "include_title": True,
      "include_axis_labels": True,
      "include_ticks": True,
      "include_gates": True,
      "include_legend": True,
      "include_status_banner": False,
      "filename_template": "{sample_title}_{sample_id}_{plot_id}",
      "collision_policy": "fail",
      "strict": True,
    }
    defaults.update(value)
    if value and "raster_resolution_mode" not in value:
      defaults["raster_resolution_mode"] = "legacy_pixel_dimensions"
    self._name.setText(str(defaults["name"]))
    target_index = self._target.findData(defaults["target"])
    self._target.setCurrentIndex(max(0, target_index))
    selected = {str(item) for item in defaults.get("sample_ids", [])}
    for index in range(self._sample_list.count()):
      item = self._sample_list.item(index)
      item.setSelected(str(item.data(32)) in selected)
    group_index = self._group.findData(defaults.get("group_id"))
    if group_index >= 0:
      self._group.setCurrentIndex(group_index)
    view_index = self._view.findData(defaults.get("plot_view_id"))
    if view_index >= 0:
      self._view.setCurrentIndex(view_index)
    formats = {str(item).lower() for item in defaults.get("formats", [])}
    for key, check in self._formats.items():
      check.setChecked(key in formats)
    self._width.setValue(int(defaults["width"]))
    self._height.setValue(int(defaults["height"]))
    self._dpi.setValue(int(defaults["dpi"]))
    resolution_index = self._resolution_mode.findData(defaults["raster_resolution_mode"])
    self._resolution_mode.setCurrentIndex(max(0, resolution_index))
    self._aspect.setChecked(bool(defaults["aspect_1_to_1"]))
    layout_index = self._layout_policy.findData(defaults["layout_policy"])
    if layout_index >= 0:
      self._layout_policy.setCurrentIndex(layout_index)
    for key, check in self._visibility.items():
      check.setChecked(bool(defaults[key]))
    self._template.setText(str(defaults["filename_template"]))
    collision_index = self._collision.findData(defaults["collision_policy"])
    if collision_index >= 0:
      self._collision.setCurrentIndex(collision_index)
    self._strict.setChecked(bool(defaults["strict"]))
    self._update_target_widgets()
    self._update_resolution_preview()

  def _update_resolution_preview(self) -> None:
    options = {
      "width": self._width.value(),
      "height": self._height.value(),
      "dpi": self._dpi.value(),
      "raster_resolution_mode": self._resolution_mode.currentData(),
      "aspect_1_to_1": self._aspect.isChecked(),
    }
    from flowdesk_core.models import BatchPlotExportSpec
    try:
      spec = BatchPlotExportSpec(
        id="preview", name="preview", target="all", sample_ids=(),
        group_id=None, plot_view_id="preview", formats=("png",),
        width=options["width"], height=options["height"], dpi=options["dpi"],
        raster_resolution_mode=options["raster_resolution_mode"],
        aspect_1_to_1=options["aspect_1_to_1"],
      )
      canvas = resolve_export_canvas(spec)
      raster = (
        f"{canvas.raster_width} × {canvas.raster_height} px "
        f"({canvas.physical_width_in:.2f} × {canvas.physical_height_in:.2f} in)"
      )
      vector = any(self._formats[key].isChecked() for key in ("svg", "pdf"))
      raster_selected = any(self._formats[key].isChecked() for key in ("png", "jpg"))
      if vector and not raster_selected:
        self._resolution_preview.setText("DPI not applicable to vector geometry")
      elif vector:
        self._resolution_preview.setText(f"Raster: {raster}; vector: DPI not applicable")
      else:
        self._resolution_preview.setText(raster)
    except (TypeError, ValueError):
      self._resolution_preview.clear()

  def _accept_save(self) -> None:
    self._run = False
    if self._validate(False):
      self.accept()

  def _accept_run(self) -> None:
    self._run = True
    if self._validate(True):
      self.accept()

  def _validate(self, require_output: bool) -> bool:
    if not self._name.text().strip():
      QMessageBox.warning(self, "Invalid batch export", "A definition name is required.")
      return False
    if not any(check.isChecked() for check in self._formats.values()):
      QMessageBox.warning(self, "Invalid batch export", "Select at least one format.")
      return False
    if require_output and not self._output.text().strip():
      QMessageBox.warning(self, "Invalid batch export", "Select an output directory.")
      return False
    return True

  def request(self) -> BatchPlotExportRequest:
    output_dir = self._output.text().strip()
    if output_dir:
      settings = QSettings()
      settings.setValue(self._OUTPUT_DIRECTORY_KEY, output_dir)
      settings.sync()
    return BatchPlotExportRequest(self.definition_mapping(), output_dir, self._run)

  def definition_mapping(self) -> dict[str, Any]:
    definition_id = str(self._definition.currentData() or "")
    return {
      "id": definition_id,
      "name": self._name.text().strip(),
      "target": self._target.currentData(),
      "sample_ids": [str(item.data(32)) for item in self._sample_list.selectedItems()],
      "group_id": self._group.currentData() if self._target.currentData() == "group" else None,
      "plot_view_id": self._view.currentData(),
      "formats": [key for key, check in self._formats.items() if check.isChecked()],
      "width": self._width.value(),
      "height": self._height.value(),
      "dpi": self._dpi.value(),
      "raster_resolution_mode": self._resolution_mode.currentData(),
      "aspect_1_to_1": self._aspect.isChecked(),
      "layout_policy": self._layout_policy.currentData(),
      **{key: check.isChecked() for key, check in self._visibility.items()},
      "filename_template": self._template.text().strip(),
      "collision_policy": self._collision.currentData(),
      "strict": self._strict.isChecked(),
    }
