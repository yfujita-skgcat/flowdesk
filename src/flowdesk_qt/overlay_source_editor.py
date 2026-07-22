"""Qt editor for persisted, display-only overlay source definitions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
  QCheckBox,
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QDoubleSpinBox,
  QFormLayout,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QListWidget,
  QListWidgetItem,
  QPushButton,
  QVBoxLayout,
  QWidget,
)

StatusResult = tuple[str, tuple[str, ...]]
StatusResolver = Callable[[list[dict[str, Any]]], dict[str, StatusResult]]


class OverlaySourceEditorDialog(QDialog):
  """Edit source list and basic per-source presentation without running analysis."""

  def __init__(
    self,
    samples: list[dict[str, Any]],
    population_ids: list[str] | tuple[str, ...],
    transforms: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    sources: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    status_resolver: StatusResolver | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("overlaySourceEditorDialog")
    self.setWindowTitle("Overlay Sources")
    self.resize(900, 560)
    self._samples = deepcopy(samples)
    self._population_ids = tuple(population_ids)
    self._transforms = deepcopy(list(transforms))
    self._sources = deepcopy(list(sources))
    self._status_resolver = status_resolver
    self._status_results: dict[str, StatusResult] = {}
    self._building = False
    self._build_ui()
    self._reload_list()
    if self._source_list.count():
      self._source_list.setCurrentRow(0)
    else:
      self._set_editor_enabled(False)
    self._resolve_statuses()

  def sources(self) -> list[dict[str, Any]]:
    """Return only display-definition data in stable list order."""
    result: list[dict[str, Any]] = []
    for order, source in enumerate(self._sources):
      value = deepcopy(source)
      value["order"] = order
      result.append(value)
    return result

  def status_results(self) -> dict[str, StatusResult]:
    return deepcopy(self._status_results)

  def _build_ui(self) -> None:
    root = QVBoxLayout(self)
    content = QHBoxLayout()
    root.addLayout(content, 1)

    left = QVBoxLayout()
    self._source_list = QListWidget()
    self._source_list.setObjectName("overlaySourceList")
    self._source_list.currentRowChanged.connect(self._on_row_changed)
    left.addWidget(self._source_list, 1)
    list_buttons = QHBoxLayout()
    self._add_button = QPushButton("Add")
    self._add_button.setObjectName("addOverlaySourceButton")
    self._add_button.clicked.connect(self._add_source)
    self._remove_button = QPushButton("Remove")
    self._remove_button.setObjectName("removeOverlaySourceButton")
    self._remove_button.clicked.connect(self._remove_source)
    self._up_button = QPushButton("Up")
    self._up_button.setObjectName("moveOverlaySourceUpButton")
    self._up_button.clicked.connect(lambda: self._move_source(-1))
    self._down_button = QPushButton("Down")
    self._down_button.setObjectName("moveOverlaySourceDownButton")
    self._down_button.clicked.connect(lambda: self._move_source(1))
    for button in (self._add_button, self._remove_button, self._up_button, self._down_button):
      list_buttons.addWidget(button)
    left.addLayout(list_buttons)
    content.addLayout(left, 1)

    form_widget = QWidget()
    form_widget.setObjectName("overlaySourceDetails")
    form = QFormLayout(form_widget)
    self._sample_combo = QComboBox()
    self._sample_combo.setObjectName("overlaySourceSampleCombo")
    self._sample_combo.currentIndexChanged.connect(self._on_sample_changed)
    form.addRow("Sample:", self._sample_combo)
    self._population_combo = QComboBox()
    self._population_combo.setObjectName("overlaySourcePopulationCombo")
    form.addRow("Population ID/path:", self._population_combo)
    self._x_combo = QComboBox()
    self._x_combo.setObjectName("overlaySourceXParameterCombo")
    form.addRow("X parameter:", self._x_combo)
    self._y_combo = QComboBox()
    self._y_combo.setObjectName("overlaySourceYParameterCombo")
    form.addRow("Y parameter:", self._y_combo)
    self._x_transform_combo = QComboBox()
    self._x_transform_combo.setObjectName("overlaySourceXTransformCombo")
    form.addRow("X transform:", self._x_transform_combo)
    self._y_transform_combo = QComboBox()
    self._y_transform_combo.setObjectName("overlaySourceYTransformCombo")
    form.addRow("Y transform:", self._y_transform_combo)
    self._legend_edit = QLineEdit()
    self._legend_edit.setObjectName("overlaySourceLegendEdit")
    form.addRow("Legend label:", self._legend_edit)
    self._color_edit = QLineEdit()
    self._color_edit.setObjectName("overlaySourceColorEdit")
    self._color_edit.setPlaceholderText("#RRGGBB")
    form.addRow("Color:", self._color_edit)
    self._alpha_spin = QDoubleSpinBox()
    self._alpha_spin.setObjectName("overlaySourceAlphaSpinBox")
    self._alpha_spin.setRange(0.0, 1.0)
    self._alpha_spin.setSingleStep(0.05)
    self._alpha_spin.setDecimals(2)
    form.addRow("Alpha:", self._alpha_spin)
    self._visible_check = QCheckBox("Visible")
    self._visible_check.setObjectName("overlaySourceVisibilityCheckBox")
    form.addRow("Display:", self._visible_check)
    self._status_label = QLabel("Status: -")
    self._status_label.setObjectName("overlaySourceCompatibilityLabel")
    self._status_label.setWordWrap(True)
    form.addRow("Compatibility:", self._status_label)
    content.addWidget(form_widget, 2)

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("overlaySourceDialogButtons")
    buttons.accepted.connect(self._accept)
    buttons.rejected.connect(self.reject)
    root.addWidget(buttons)

    for widget in (
      self._population_combo, self._x_combo, self._y_combo,
      self._x_transform_combo, self._y_transform_combo, self._legend_edit,
      self._color_edit, self._alpha_spin, self._visible_check,
    ):
      if isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(self._write_current_source)
      elif isinstance(widget, QCheckBox):
        widget.toggled.connect(self._write_current_source)
      elif isinstance(widget, QDoubleSpinBox):
        widget.valueChanged.connect(self._write_current_source)
      else:
        widget.textChanged.connect(self._write_current_source)
    self._populate_static_combos()

  def _populate_static_combos(self) -> None:
    self._sample_combo.clear()
    for sample in self._samples:
      self._sample_combo.addItem(
        f"{sample.get('name', sample['id'])} [{sample['id']}]", sample["id"]
      )
    self._population_combo.clear()
    self._population_combo.addItems(list(self._population_ids))
    self._x_transform_combo.clear()
    self._x_transform_combo.addItem("(none)", None)
    self._y_transform_combo.clear()
    self._y_transform_combo.addItem("(none)", None)
    for transform in self._transforms:
      label = f"{transform.get('name', transform['id'])} [{transform['id']}]"
      self._x_transform_combo.addItem(label, transform["id"])
      self._y_transform_combo.addItem(label, transform["id"])

  def _sample_channels(self, sample_id: str) -> list[dict[str, Any]]:
    sample = next((item for item in self._samples if item.get("id") == sample_id), None)
    return [] if sample is None else list(sample.get("channels", []))

  def _populate_channel_combos(
    self,
    sample_id: str,
    x_id: str | None = None,
    y_id: str | None = None,
  ) -> None:
    self._building = True
    try:
      for combo, include_none in ((self._x_combo, False), (self._y_combo, True)):
        previous = x_id if combo is self._x_combo else y_id
        combo.clear()
        if include_none:
          combo.addItem("(none)", None)
        for channel in self._sample_channels(sample_id):
          label = channel.get("name", channel["id"])
          combo.addItem(f"{label} [{channel['id']}]", channel["id"])
        if previous:
          index = combo.findData(previous)
          if index >= 0:
            combo.setCurrentIndex(index)
    finally:
      self._building = False

  def _reload_list(self, selected_row: int | None = None) -> None:
    self._building = True
    try:
      self._source_list.clear()
      for source in self._sources:
        status = self._status_results.get(source.get("source_id", ""), ("unresolved", ()))[0]
        visible = "visible" if source.get("visible", True) else "hidden"
        item = QListWidgetItem(
          f"[{status}] {source.get('display_name', source.get('source_id', ''))} "
          f"({source.get('sample_id', 'template')}; {visible})"
        )
        item.setData(Qt.ItemDataRole.UserRole, source.get("source_id"))
        self._source_list.addItem(item)
    finally:
      self._building = False
    if self._source_list.count():
      self._source_list.setCurrentRow(
        max(0, min(selected_row if selected_row is not None else 0, self._source_list.count() - 1))
      )

  def _current_index(self) -> int:
    return self._source_list.currentRow()

  def _current_source(self) -> dict[str, Any] | None:
    index = self._current_index()
    return self._sources[index] if 0 <= index < len(self._sources) else None

  def _on_row_changed(self, row: int) -> None:
    source = self._sources[row] if 0 <= row < len(self._sources) else None
    self._set_editor_enabled(source is not None)
    if source is None:
      return
    self._building = True
    try:
      self._sample_combo.setCurrentIndex(self._sample_combo.findData(source.get("sample_id")))
      self._population_combo.setCurrentIndex(
        self._population_combo.findText(source.get("population_id", ""))
      )
      self._populate_channel_combos(
        str(source.get("sample_id", "")),
        source.get("x_parameter_id"), source.get("y_parameter_id"),
      )
      self._set_data(self._x_combo, source.get("x_parameter_id"))
      self._set_data(self._y_combo, source.get("y_parameter_id"))
      self._set_data(self._x_transform_combo, source.get("x_transform_id"))
      self._set_data(self._y_transform_combo, source.get("y_transform_id"))
      style = source.get("style") or {}
      self._legend_edit.setText(str(style.get("legend_label", source.get("display_name", ""))))
      self._color_edit.setText(str(style.get("color", "#4c78a8")))
      self._alpha_spin.setValue(float(style.get("alpha", 1.0)))
      self._visible_check.setChecked(bool(source.get("visible", True)))
    finally:
      self._building = False
    self._update_status_label()

  @staticmethod
  def _set_data(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)

  def _set_editor_enabled(self, enabled: bool) -> None:
    for widget in (
      self._population_combo, self._x_combo, self._y_combo,
      self._x_transform_combo, self._y_transform_combo, self._legend_edit,
      self._color_edit, self._alpha_spin, self._visible_check,
    ):
      widget.setEnabled(enabled)
    self._remove_button.setEnabled(enabled)
    self._up_button.setEnabled(enabled)
    self._down_button.setEnabled(enabled)

  def _add_source(self) -> None:
    if not self._samples:
      self._status_label.setText("Status: missing — no sample is available")
      return
    sample = self._samples[0]
    channels = self._sample_channels(str(sample["id"]))
    if not channels:
      self._status_label.setText("Status: missing — selected sample has no channels")
      return
    source_id = f"source-{uuid.uuid4().hex[:10]}"
    self._sources.append({
      "source_id": source_id,
      "sample_id": sample["id"],
      "population_id": self._population_ids[0] if self._population_ids else "all_events",
      "display_name": str(sample.get("name", sample["id"])),
      "x_parameter_id": channels[0]["id"],
      "y_parameter_id": channels[1]["id"] if len(channels) > 1 else None,
      "x_transform_id": None,
      "y_transform_id": None,
      "visible": True,
      "order": len(self._sources),
      "style": {
        "source_id": source_id,
        "legend_label": str(sample.get("name", sample["id"])),
        "color": "#4c78a8",
        "alpha": 1.0,
        "manual_fields": [],
      },
    })
    self._resolve_statuses()
    self._reload_list(len(self._sources) - 1)

  def _remove_source(self) -> None:
    index = self._current_index()
    if 0 <= index < len(self._sources):
      self._sources.pop(index)
      self._resolve_statuses()
      self._reload_list(max(0, index - 1))
    else:
      self._set_editor_enabled(False)

  def _move_source(self, offset: int) -> None:
    index = self._current_index()
    target = index + offset
    if not (0 <= index < len(self._sources) and 0 <= target < len(self._sources)):
      return
    self._sources[index], self._sources[target] = self._sources[target], self._sources[index]
    self._reload_list(target)

  def _write_current_source(self, *_args: Any) -> None:
    if self._building:
      return
    source = self._current_source()
    if source is None:
      return
    source["sample_id"] = self._sample_combo.currentData()
    source["population_id"] = self._population_combo.currentText() or None
    source["x_parameter_id"] = self._x_combo.currentData()
    source["y_parameter_id"] = self._y_combo.currentData()
    source["x_transform_id"] = self._x_transform_combo.currentData()
    source["y_transform_id"] = self._y_transform_combo.currentData()
    source["visible"] = self._visible_check.isChecked()
    style = source.setdefault("style", {"source_id": source["source_id"]})
    style["source_id"] = source["source_id"]
    style["legend_label"] = self._legend_edit.text()
    style["color"] = self._color_edit.text().strip()
    style["alpha"] = self._alpha_spin.value()
    style["manual_fields"] = ["legend_label", "color", "alpha"]
    self._resolve_statuses()
    self._reload_list(self._current_index())

  def _resolve_statuses(self) -> None:
    if self._status_resolver is not None:
      self._status_results = self._status_resolver(self.sources())
    self._update_status_label()

  def _update_status_label(self) -> None:
    source = self._current_source()
    if source is None:
      self._status_label.setText("Status: -")
      return
    status, details = self._status_results.get(source["source_id"], ("unresolved", ()))
    text = f"Status: {status}"
    if details:
      text += "\n" + "\n".join(details)
    self._status_label.setText(text)

  def _on_sample_changed(self, _index: int) -> None:
    if self._building:
      return
    source = self._current_source()
    if source is None:
      return
    self._populate_channel_combos(str(self._sample_combo.currentData()))
    self._write_current_source()

  def _accept(self) -> None:
    try:
      for source in self.sources():
        if not source.get("sample_id") and not source.get("template_source_role"):
          raise ValueError(f"source {source.get('source_id')!r} has no sample")
        if not source.get("population_id") and not source.get("template_population_path"):
          raise ValueError(f"source {source.get('source_id')!r} has no population")
        if not source.get("x_parameter_id"):
          raise ValueError(f"source {source.get('source_id')!r} has no X parameter")
        status, details = self._status_results.get(
          str(source.get("source_id")), ("unresolved", ())
        )
        if source.get("visible", True) and status != "compatible":
          detail = "; ".join(details) if details else status
          raise ValueError(
            f"visible source {source.get('source_id')!r} is {status}: {detail}"
          )
    except ValueError as exc:
      self._status_label.setText(f"Status: error — {exc}")
      return
    self.accept()
