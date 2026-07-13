"""Qt editor for persisted, GUI-independent analysis transforms."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
  QComboBox,
  QDialog,
  QDialogButtonBox,
  QFormLayout,
  QHBoxLayout,
  QLabel,
  QLineEdit,
  QListWidget,
  QMessageBox,
  QPushButton,
  QSplitter,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.models import ChannelSpec, TransformSpec
from flowdesk_core.transforms import (
  LOGICLE_IMPLEMENTATION_VERSION,
  TransformError,
  apply_transform,
  inverse_transform,
  validate_transform,
)

_DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
  "linear": {"scale": 1.0, "offset": 0.0},
  "log": {"base": 10.0, "invalid_value_policy": "to_nan"},
  "asinh": {"cofactor": 1.0},
  "logicle": {
    "T": 262144.0,
    "W": 0.5,
    "M": 4.5,
    "A": 0.0,
    "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
  },
  "legacy_logicle_approximation": {"w": 0.25, "td": 1e6, "tn": 1e4},
}


class TransformEditorDialog(QDialog):
  """Edit complete transform definitions and preview core round trips."""

  def __init__(
    self,
    transforms: Sequence[dict[str, Any]],
    available_channels: Sequence[ChannelSpec],
    *,
    preview_values: dict[str, NDArray[np.float64]] | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("transformEditorDialog")
    self.setWindowTitle("Analysis Transforms")
    self.resize(850, 560)
    self._transforms = deepcopy(list(transforms))
    self._channels = tuple(available_channels)
    self._preview_values = preview_values or {}
    self._current_row = -1
    self._loading = False
    self._build_ui()
    if not self._transforms:
      self._transforms.append(self._empty_transform())
    self._refresh_list(0)

  def transforms(self) -> list[dict[str, Any]]:
    """Return validated persisted mappings without sharing mutable state."""
    self._commit_current()
    self._validate_all()
    return deepcopy(self._transforms)

  def _build_ui(self) -> None:
    outer = QVBoxLayout(self)
    splitter = QSplitter(Qt.Orientation.Horizontal)
    left = QWidget()
    left_layout = QVBoxLayout(left)
    self._list = QListWidget()
    self._list.setObjectName("transformDefinitionList")
    left_layout.addWidget(self._list)
    row = QHBoxLayout()
    self._new_button = QPushButton("New")
    self._new_button.setObjectName("transformNewButton")
    self._delete_button = QPushButton("Delete")
    self._delete_button.setObjectName("transformDeleteButton")
    row.addWidget(self._new_button)
    row.addWidget(self._delete_button)
    left_layout.addLayout(row)

    right = QWidget()
    right_layout = QVBoxLayout(right)
    form = QFormLayout()
    self._id_edit = QLineEdit()
    self._id_edit.setObjectName("transformIdEdit")
    self._name_edit = QLineEdit()
    self._name_edit.setObjectName("transformNameEdit")
    self._parameter_combo = QComboBox()
    self._parameter_combo.setObjectName("transformParameterCombo")
    for channel in self._channels:
      self._parameter_combo.addItem(f"{channel.name} [{channel.id}]", channel.id)
    self._type_combo = QComboBox()
    self._type_combo.setObjectName("transformTypeCombo")
    self._type_combo.addItems(["linear", "log", "asinh", "logicle"])
    if any(
      value.get("transform_type") == "legacy_logicle_approximation"
      for value in self._transforms
    ):
      self._type_combo.addItem("legacy_logicle_approximation")
    form.addRow("Transform ID:", self._id_edit)
    form.addRow("Name:", self._name_edit)
    form.addRow("Parameter:", self._parameter_combo)
    form.addRow("Type:", self._type_combo)

    self._setting_rows: dict[str, tuple[QLabel, QWidget]] = {}
    self._setting_edits: dict[str, QWidget] = {}
    for name in ("scale", "offset", "base", "cofactor", "T", "W", "M", "A", "w", "td", "tn"):
      edit = QLineEdit()
      edit.setObjectName(f"transformSetting{name}Edit")
      label = QLabel(f"{name}:")
      form.addRow(label, edit)
      self._setting_rows[name] = (label, edit)
      self._setting_edits[name] = edit
    policy = QComboBox()
    policy.setObjectName("transformInvalidValuePolicyCombo")
    policy.addItems(["to_nan", "to_zero", "clip_to_one"])
    policy_label = QLabel("invalid_value_policy:")
    form.addRow(policy_label, policy)
    self._setting_rows["invalid_value_policy"] = (policy_label, policy)
    self._setting_edits["invalid_value_policy"] = policy
    version = QLineEdit(LOGICLE_IMPLEMENTATION_VERSION)
    version.setObjectName("transformImplementationVersionEdit")
    version.setReadOnly(True)
    version_label = QLabel("implementation_version:")
    form.addRow(version_label, version)
    self._setting_rows["implementation_version"] = (version_label, version)
    self._setting_edits["implementation_version"] = version
    right_layout.addLayout(form)

    actions = QHBoxLayout()
    self._preview_button = QPushButton("Preview")
    self._preview_button.setObjectName("transformPreviewButton")
    actions.addWidget(self._preview_button)
    actions.addStretch(1)
    right_layout.addLayout(actions)
    self._preview_label = QLabel("No preview")
    self._preview_label.setObjectName("transformPreviewLabel")
    self._preview_label.setWordWrap(True)
    right_layout.addWidget(self._preview_label)
    right_layout.addStretch(1)

    splitter.addWidget(left)
    splitter.addWidget(right)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 3)
    outer.addWidget(splitter)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok
      | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("transformDialogButtons")
    outer.addWidget(buttons)

    self._list.currentRowChanged.connect(self._on_row_changed)
    self._new_button.clicked.connect(self._add_transform)
    self._delete_button.clicked.connect(self._delete_transform)
    self._type_combo.currentTextChanged.connect(self._update_setting_visibility)
    self._preview_button.clicked.connect(self._preview_current)
    buttons.accepted.connect(self._accept_if_valid)
    buttons.rejected.connect(self.reject)

  @staticmethod
  def _empty_transform() -> dict[str, Any]:
    return {
      "id": "",
      "name": "",
      "transform_type": "logicle",
      "parameter": "",
      "settings": deepcopy(_DEFAULT_SETTINGS["logicle"]),
      "role": "analysis",
      "notes": "",
    }

  def _visible_setting_names(self) -> tuple[str, ...]:
    return tuple(_DEFAULT_SETTINGS[self._type_combo.currentText()])

  def _update_setting_visibility(self) -> None:
    visible = set(self._visible_setting_names())
    for name, (label, widget) in self._setting_rows.items():
      label.setVisible(name in visible)
      widget.setVisible(name in visible)
    if not self._loading:
      defaults = _DEFAULT_SETTINGS[self._type_combo.currentText()]
      for name, value in defaults.items():
        widget = self._setting_edits[name]
        if isinstance(widget, QLineEdit) and not widget.text():
          widget.setText(str(value))

  def _refresh_list(self, selected_row: int) -> None:
    self._loading = True
    try:
      self._list.clear()
      for transform in self._transforms:
        label = transform.get("name") or transform.get("id") or "New transform"
        self._list.addItem(f"{label} [{transform.get('parameter') or 'unset'}]")
      if self._transforms:
        self._list.setCurrentRow(min(selected_row, len(self._transforms) - 1))
    finally:
      self._loading = False
    if self._transforms:
      self._load_row(self._list.currentRow())

  def _load_row(self, row: int) -> None:
    if row < 0 or row >= len(self._transforms):
      return
    self._loading = True
    try:
      self._current_row = row
      value = self._transforms[row]
      self._id_edit.setText(str(value.get("id", "")))
      self._name_edit.setText(str(value.get("name", "")))
      parameter = str(value.get("parameter", ""))
      index = self._parameter_combo.findData(parameter)
      if index >= 0:
        self._parameter_combo.setCurrentIndex(index)
      transform_type = str(value.get("transform_type", "logicle"))
      self._type_combo.setCurrentText(transform_type)
      settings = value.get("settings", {})
      defaults = _DEFAULT_SETTINGS[transform_type]
      for name, widget in self._setting_edits.items():
        setting = settings.get(name, defaults.get(name, ""))
        if isinstance(widget, QComboBox):
          widget.setCurrentText(str(setting))
        else:
          widget.setText(str(setting))
      self._preview_label.setText("No preview")
      self._update_setting_visibility()
    finally:
      self._loading = False

  def _build_current_spec(self) -> TransformSpec:
    settings: dict[str, Any] = {}
    for name in self._visible_setting_names():
      widget = self._setting_edits[name]
      if isinstance(widget, QComboBox):
        settings[name] = widget.currentText()
      elif name == "implementation_version":
        settings[name] = widget.text()
      else:
        settings[name] = float(widget.text())
    return TransformSpec(
      id=self._id_edit.text().strip(),
      name=self._name_edit.text().strip(),
      transform_type=self._type_combo.currentText(),  # type: ignore[arg-type]
      parameter=str(self._parameter_combo.currentData() or ""),
      settings=settings,
    )

  def _commit_current(self) -> None:
    if self._current_row < 0 or self._current_row >= len(self._transforms):
      return
    self._transforms[self._current_row] = asdict(self._build_current_spec())

  def _validate_all(self) -> None:
    ids: set[str] = set()
    parameters: set[str] = set()
    for mapping in self._transforms:
      spec = TransformSpec(**mapping)
      if not spec.id or not spec.name or not spec.parameter:
        raise ValueError("transform ID, name, and parameter are required")
      if spec.id in ids:
        raise ValueError(f"duplicate transform ID: {spec.id}")
      if spec.parameter in parameters:
        raise ValueError(f"parameter already has an analysis transform: {spec.parameter}")
      validate_transform(spec)
      ids.add(spec.id)
      parameters.add(spec.parameter)

  def _preview_current(self) -> None:
    try:
      spec = self._build_current_spec()
      validate_transform(spec)
      values = np.asarray(
        self._preview_values.get(spec.parameter, np.array([], dtype=np.float64)),
        dtype=np.float64,
      )
      values = values[np.isfinite(values)][:200]
      if values.size == 0:
        self._preview_label.setText("Valid definition; no loaded preview events")
        return
      transformed = apply_transform(spec, values)
      restored = inverse_transform(spec, transformed)
      error = float(np.max(np.abs(restored - values)))
      self._preview_label.setText(
        f"{values.size} finite events; inverse round-trip max absolute error: {error:.6g}"
      )
    except (TransformError, ValueError, OverflowError) as exc:
      self._preview_label.setText(f"Preview error: {exc}")

  def _on_row_changed(self, row: int) -> None:
    if self._loading:
      return
    try:
      self._commit_current()
    except (ValueError, TransformError):
      pass
    self._load_row(row)

  def _add_transform(self) -> None:
    try:
      self._commit_current()
    except (ValueError, TransformError):
      pass
    self._transforms.append(self._empty_transform())
    self._refresh_list(len(self._transforms) - 1)

  def _delete_transform(self) -> None:
    row = self._list.currentRow()
    if row < 0:
      return
    self._transforms.pop(row)
    self._current_row = -1
    self._refresh_list(max(0, row - 1))

  def _accept_if_valid(self) -> None:
    try:
      self.transforms()
    except (ValueError, TransformError) as exc:
      QMessageBox.warning(self, "Invalid transform", str(exc))
      return
    self.accept()
