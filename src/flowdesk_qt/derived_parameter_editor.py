"""Qt project-state editor for headless derived parameter definitions."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

import numpy as np
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
  QPlainTextEdit,
  QPushButton,
  QSplitter,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.derived_parameters import (
  DerivedParameterPlanningError,
  DerivedParameterPreview,
  ExpressionError,
  extract_parameter_references,
  plan_derived_parameters,
)
from flowdesk_core.models import ChannelSpec, DerivedParameterSpec

PreviewCallback = Callable[[list[dict[str, Any]], str], DerivedParameterPreview]


class DerivedParameterEditorDialog(QDialog):
  """Edit persisted definitions and preview them through a core callback."""

  def __init__(
    self,
    definitions: Sequence[dict[str, Any]],
    available_channels: Sequence[ChannelSpec],
    *,
    preview_callback: PreviewCallback | None = None,
    fixed_definition_ids: Sequence[str] = (),
    fixed_output_channel_ids: Sequence[str] = (),
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("derivedParameterEditorDialog")
    self.setWindowTitle("Derived Parameters")
    self.resize(920, 620)
    self._definitions = deepcopy(list(definitions))
    self._available_channels = tuple(available_channels)
    self._preview_callback = preview_callback
    self._fixed_definition_ids = {str(value) for value in fixed_definition_ids}
    self._fixed_output_channel_ids = {
      str(value) for value in fixed_output_channel_ids
    }
    self._loading = False
    self._current_row = -1
    self._build_ui()
    self._refresh_definition_list(len(self._definitions) - 1)

  def definitions(self) -> list[dict[str, Any]]:
    """Return a deep copy of the current persisted project definitions."""
    self._commit_current()
    return deepcopy(self._definitions)

  def _build_ui(self) -> None:
    outer = QVBoxLayout(self)
    splitter = QSplitter(Qt.Orientation.Horizontal)

    left = QWidget()
    left_layout = QVBoxLayout(left)
    self._definition_list = QListWidget()
    self._definition_list.setObjectName("derivedParameterDefinitionList")
    left_layout.addWidget(self._definition_list)
    list_buttons = QHBoxLayout()
    self._new_button = QPushButton("New")
    self._new_button.setObjectName("derivedParameterNewButton")
    self._delete_button = QPushButton("Delete")
    self._delete_button.setObjectName("derivedParameterDeleteButton")
    list_buttons.addWidget(self._new_button)
    list_buttons.addWidget(self._delete_button)
    left_layout.addLayout(list_buttons)

    right = QWidget()
    right_layout = QVBoxLayout(right)
    form = QFormLayout()
    self._id_edit = QLineEdit()
    self._id_edit.setObjectName("derivedParameterDefinitionIdEdit")
    self._name_edit = QLineEdit()
    self._name_edit.setObjectName("derivedParameterNameEdit")
    self._output_id_edit = QLineEdit()
    self._output_id_edit.setObjectName("derivedParameterOutputIdEdit")
    self._unit_edit = QLineEdit()
    self._unit_edit.setObjectName("derivedParameterUnitEdit")
    self._source_combo = QComboBox()
    self._source_combo.setObjectName("derivedParameterSourceStageCombo")
    self._source_combo.addItems(["compensated", "raw"])
    if any(
      definition.get("source_stage") == "transformed"
      for definition in self._definitions
    ):
      self._source_combo.addItem("transformed")
    self._policy_combo = QComboBox()
    self._policy_combo.setObjectName("derivedParameterPolicyCombo")
    self._policy_combo.addItems([
      "emit_nan_with_warning",
      "fail_sample",
      "fail_run",
    ])
    self._nonfinite_combo = QComboBox()
    self._nonfinite_combo.setObjectName("derivedParameterNonFinitePolicyCombo")
    self._nonfinite_combo.addItem("Strict (report invalid events)", "strict")
    self._nonfinite_combo.addItem(
      "Exclude invalid values explicitly", "exclude_invalid"
    )
    form.addRow("Definition ID:", self._id_edit)
    form.addRow("Name:", self._name_edit)
    form.addRow("Output channel ID:", self._output_id_edit)
    form.addRow("Unit:", self._unit_edit)
    form.addRow("Source stage:", self._source_combo)
    form.addRow("Failure policy:", self._policy_combo)
    form.addRow("Non-finite policy:", self._nonfinite_combo)

    self._expression_edit = QPlainTextEdit()
    self._expression_edit.setObjectName("derivedParameterExpressionEdit")
    self._expression_edit.setPlaceholderText("signal / reference")
    form.addRow("Expression:", self._expression_edit)

    self._detected_inputs_label = QLabel("No input parameters detected")
    self._detected_inputs_label.setObjectName(
      "derivedParameterDetectedInputsLabel"
    )
    self._detected_inputs_label.setWordWrap(True)
    form.addRow("Expression inputs:", self._detected_inputs_label)

    insertion = QHBoxLayout()
    self._insert_parameter_combo = QComboBox()
    self._insert_parameter_combo.setObjectName(
      "derivedParameterInsertParameterCombo"
    )
    self._insert_parameter_button = QPushButton("Insert parameter")
    self._insert_parameter_button.setObjectName(
      "derivedParameterInsertParameterButton"
    )
    insertion.addWidget(self._insert_parameter_combo)
    insertion.addWidget(self._insert_parameter_button)
    form.addRow("Insert parameter:", insertion)
    right_layout.addLayout(form)

    actions = QHBoxLayout()
    self._validate_button = QPushButton("Validate")
    self._validate_button.setObjectName("derivedParameterValidateButton")
    self._preview_button = QPushButton("Preview")
    self._preview_button.setObjectName("derivedParameterPreviewButton")
    actions.addWidget(self._validate_button)
    actions.addWidget(self._preview_button)
    actions.addStretch(1)
    right_layout.addLayout(actions)
    self._diagnostic_label = QLabel("Not validated")
    self._diagnostic_label.setObjectName("derivedParameterDiagnosticLabel")
    self._diagnostic_label.setWordWrap(True)
    self._preview_label = QLabel("No preview")
    self._preview_label.setObjectName("derivedParameterPreviewLabel")
    self._preview_label.setWordWrap(True)
    right_layout.addWidget(self._diagnostic_label)
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
    buttons.setObjectName("derivedParameterDialogButtons")
    outer.addWidget(buttons)

    self._definition_list.currentRowChanged.connect(self._on_row_changed)
    self._new_button.clicked.connect(self._add_definition)
    self._delete_button.clicked.connect(self._delete_definition)
    self._insert_parameter_button.clicked.connect(self._insert_parameter)
    self._expression_edit.textChanged.connect(self._refresh_detected_inputs)
    self._name_edit.textChanged.connect(self._update_generated_ids)
    self._source_combo.currentTextChanged.connect(self._update_generated_ids)
    self._expression_edit.textChanged.connect(self._update_generated_ids)
    self._id_edit.editingFinished.connect(self._commit_current)
    self._output_id_edit.editingFinished.connect(self._commit_current)
    self._validate_button.clicked.connect(self._validate_current)
    self._preview_button.clicked.connect(self._preview_current)
    buttons.accepted.connect(self._accept_if_valid)
    buttons.rejected.connect(self.reject)

  @staticmethod
  def _empty_definition() -> dict[str, Any]:
    return {
      "id": "",
      "name": "",
      "expression": "",
      "output_channel_id": "",
      "output_label": None,
      "unit": None,
      "source_stage": "compensated",
      "input_parameters": [],
      "invalid_value_policy": "emit_nan_with_warning",
      "non_finite_policy": "strict",
      "notes": "",
    }

  def _parameter_choices(self) -> list[tuple[str, str]]:
    labels: dict[str, str] = {}
    for channel in self._available_channels:
      display_name = channel.short_name or channel.name
      if channel.short_name and channel.short_name != channel.name:
        display_name = f"{display_name} [{channel.name}]"
      labels[channel.id] = display_name
    for definition in self._definitions:
      output_id = str(definition.get("output_channel_id", ""))
      if output_id:
        name = str(definition.get("name", "Derived"))
        labels.setdefault(output_id, f"{name} [{output_id}]")
    return list(labels.items())

  @staticmethod
  def _expression_token(expression: str) -> str:
    """Create a short, readable identifier fragment from an expression."""
    text = expression.strip().lower()
    if not text:
      return "expression"
    for operator, word in (
      ("**", "_power_"),
      ("/", "_over_"),
      ("*", "_times_"),
      ("+", "_plus_"),
      ("-", "_minus_"),
    ):
      text = text.replace(operator, word)
    token = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    token = re.sub(r"_+", "_", token)
    return (token or "expression")[:48].rstrip("_")

  @staticmethod
  def _id_token(value: object, fallback: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip()).strip("_")
    return token.lower() or fallback

  def _definition_id_base(self, definition: dict[str, Any]) -> str:
    name = self._id_token(definition.get("name"), "derived_parameter")
    source = self._id_token(definition.get("source_stage"), "compensated")
    expression = self._expression_token(str(definition.get("expression", "")))
    return f"{name}_{source}_{expression}"

  def _output_id_base(self, definition: dict[str, Any]) -> str:
    return self._expression_token(str(definition.get("expression", "")))

  def _unique_id(
    self, base: str, values: Sequence[str], *, exclude: str = "",
  ) -> str:
    used = {str(value) for value in values if str(value) and str(value) != exclude}
    candidate = base
    suffix = 2
    while candidate in used:
      candidate = f"{base}_{suffix}"
      suffix += 1
    return candidate

  def _generated_definition_id(self, definition: dict[str, Any]) -> str:
    used = [str(value.get("id", "")) for value in self._definitions]
    return self._unique_id(
      self._definition_id_base(definition), used,
      exclude=str(definition.get("id", "")),
    )

  def _generated_output_id(self, definition: dict[str, Any]) -> str:
    used = [channel.id for channel in self._available_channels]
    used.extend(str(value.get("output_channel_id", "")) for value in self._definitions)
    return self._unique_id(
      self._output_id_base(definition), used,
      exclude=str(definition.get("output_channel_id", "")),
    )

  def _refresh_parameter_widgets(self) -> None:
    choices = self._parameter_choices()
    self._insert_parameter_combo.clear()
    for parameter_id, label in choices:
      self._insert_parameter_combo.addItem(label, parameter_id)

  def _detected_input_parameters(self, expression: str) -> tuple[str, ...] | None:
    try:
      return extract_parameter_references(
        expression,
        (parameter_id for parameter_id, _label in self._parameter_choices()),
      )
    except (DerivedParameterPlanningError, ExpressionError):
      return None

  def _refresh_detected_inputs(self) -> None:
    if self._loading:
      return
    references = self._detected_input_parameters(
      self._expression_edit.toPlainText().strip()
    )
    if references is None:
      self._detected_inputs_label.setText("Invalid or incomplete expression")
      return
    labels = dict(self._parameter_choices())
    if not references:
      self._detected_inputs_label.setText("No input parameters detected")
      return
    self._detected_inputs_label.setText(
      ", ".join(labels[parameter_id] for parameter_id in references)
    )

  def _refresh_definition_list(self, selected_row: int) -> None:
    self._loading = True
    try:
      self._definition_list.clear()
      for definition in self._definitions:
        self._definition_list.addItem(self._definition_summary(definition))
      if self._definitions:
        self._definition_list.setCurrentRow(
          min(max(selected_row, 0), len(self._definitions) - 1)
        )
    finally:
      self._loading = False
    if self._definitions:
      self._load_row(self._definition_list.currentRow())
    else:
      self._clear_fields()

  def _definition_summary(self, definition: dict[str, Any]) -> str:
    label = str(definition.get("name") or definition.get("id") or "New definition")
    source = str(definition.get("source_stage") or "compensated")
    expression = str(definition.get("expression") or "(empty)").replace("\n", " ")
    if len(expression) > 40:
      expression = expression[:37] + "..."
    output_id = str(definition.get("output_channel_id") or "unset")
    return f"{label} | {source} | {expression} => {output_id}"

  def _clear_fields(self) -> None:
    self._loading = True
    try:
      self._current_row = -1
      self._id_edit.clear()
      self._name_edit.clear()
      self._output_id_edit.clear()
      self._unit_edit.clear()
      self._expression_edit.clear()
      self._insert_parameter_combo.clear()
      self._detected_inputs_label.setText("No input parameters detected")
      self._diagnostic_label.setText("No definitions")
      self._preview_label.setText("No preview")
    finally:
      self._loading = False

  def _load_row(self, row: int) -> None:
    if row < 0 or row >= len(self._definitions):
      return
    self._loading = True
    try:
      definition = self._definitions[row]
      self._current_row = row
      self._id_edit.setText(str(definition.get("id", "")))
      self._id_edit.setReadOnly(
        str(definition.get("id", "")) in self._fixed_definition_ids
      )
      self._name_edit.setText(str(definition.get("name", "")))
      self._output_id_edit.setText(
        str(definition.get("output_channel_id", definition.get("id", "")))
      )
      self._output_id_edit.setReadOnly(
        str(definition.get("output_channel_id", definition.get("id", "")))
        in self._fixed_output_channel_ids
      )
      self._unit_edit.setText(str(definition.get("unit") or ""))
      self._source_combo.setCurrentText(
        str(definition.get("source_stage", "compensated"))
      )
      self._policy_combo.setCurrentText(
        str(definition.get("invalid_value_policy", "emit_nan_with_warning"))
      )
      policy_index = self._nonfinite_combo.findData(
        definition.get("non_finite_policy", "strict")
      )
      self._nonfinite_combo.setCurrentIndex(max(0, policy_index))
      self._expression_edit.setPlainText(str(definition.get("expression", "")))
      self._refresh_parameter_widgets()
      self._diagnostic_label.setText("Not validated")
      self._preview_label.setText("No preview")
    finally:
      self._loading = False
    self._refresh_detected_inputs()

  def _update_generated_ids(self, *_args: object) -> None:
    """Update only IDs that are still editable draft identities."""
    if self._loading or not (0 <= self._current_row < len(self._definitions)):
      return
    self._commit_current()
    definition = self._definitions[self._current_row]
    definition_id = str(definition.get("id", ""))
    output_id = str(definition.get("output_channel_id", ""))
    if definition_id not in self._fixed_definition_ids:
      definition["id"] = self._generated_definition_id(definition)
      self._id_edit.setText(definition["id"])
    if output_id not in self._fixed_output_channel_ids:
      definition["output_channel_id"] = self._generated_output_id(definition)
      self._output_id_edit.setText(definition["output_channel_id"])
    item = self._definition_list.item(self._current_row)
    if item is not None:
      item.setText(self._definition_summary(definition))

  def _commit_current(self) -> None:
    if self._loading or not (0 <= self._current_row < len(self._definitions)):
      return
    original = self._definitions[self._current_row]
    expression = self._expression_edit.toPlainText().strip()
    references = self._detected_input_parameters(expression)
    definition_id = self._id_edit.text().strip()
    if str(original.get("id", "")) in self._fixed_definition_ids:
      definition_id = str(original.get("id", ""))
    output_channel_id = self._output_id_edit.text().strip()
    if str(original.get("output_channel_id", "")) in self._fixed_output_channel_ids:
      output_channel_id = str(original.get("output_channel_id", ""))
    original.update({
      "id": definition_id,
      "name": self._name_edit.text().strip(),
      "expression": expression,
      "output_channel_id": output_channel_id,
      "output_label": original.get("output_label"),
      "unit": self._unit_edit.text().strip() or None,
      "source_stage": self._source_combo.currentText(),
      "input_parameters": list(references or ()),
      "invalid_value_policy": self._policy_combo.currentText(),
      "non_finite_policy": self._nonfinite_combo.currentData() or "strict",
      "notes": str(original.get("notes", "")),
    })
    if original["source_stage"] != "transformed":
      original.pop("legacy_source_stage_policy", None)

  def _on_row_changed(self, row: int) -> None:
    if self._loading:
      return
    self._commit_current()
    self._load_row(row)

  def _add_definition(self) -> None:
    self._commit_current()
    definition = self._empty_definition()
    self._definitions.append(definition)
    definition["id"] = self._generated_definition_id(definition)
    definition["output_channel_id"] = self._generated_output_id(definition)
    self._refresh_definition_list(len(self._definitions) - 1)

  def _delete_definition(self) -> None:
    if not (0 <= self._current_row < len(self._definitions)):
      return
    self._definitions.pop(self._current_row)
    self._refresh_definition_list(min(self._current_row, len(self._definitions) - 1))

  def _insert_parameter(self) -> None:
    parameter_id = self._insert_parameter_combo.currentData()
    if parameter_id:
      self._expression_edit.insertPlainText(str(parameter_id))

  @staticmethod
  def _spec_from_mapping(definition: dict[str, Any]) -> DerivedParameterSpec:
    return DerivedParameterSpec(
      id=definition["id"],
      name=definition["name"],
      expression=definition["expression"],
      source_stage=definition["source_stage"],
      input_parameters=tuple(definition["input_parameters"]),
      output_channel_id=definition["output_channel_id"],
      output_label=definition.get("output_label"),
      unit=definition.get("unit"),
      invalid_value_policy=definition["invalid_value_policy"],
      non_finite_policy=definition.get("non_finite_policy", "strict"),
      legacy_source_stage_policy=definition.get("legacy_source_stage_policy"),
      notes=definition.get("notes", ""),
    )

  def _validated_specs(self) -> tuple[DerivedParameterSpec, ...]:
    self._commit_current()
    specs = tuple(self._spec_from_mapping(value) for value in self._definitions)
    plan_derived_parameters(
      specs,
      (channel.id for channel in self._available_channels),
    )
    return specs

  def _show_validation_error(self, error: Exception) -> None:
    code = getattr(error, "code", None)
    if code is None and ":" in str(error):
      candidate = str(error).split(":", 1)[0]
      if candidate.replace("_", "").isalnum():
        code = candidate
    code = code or "invalid_derived_parameter_definition"
    line = getattr(error, "line", None)
    column = getattr(error, "column", None)
    location = ""
    if line is not None:
      location = f" (line {line}, column {column or 1})"
    self._diagnostic_label.setText(f"{code}: {error}{location}")

  def _validate_current(self) -> bool:
    try:
      self._validated_specs()
    except (DerivedParameterPlanningError, KeyError, TypeError, ValueError) as exc:
      self._show_validation_error(exc)
      return False
    self._diagnostic_label.setText("valid")
    return True

  def _preview_current(self) -> None:
    if not self._validate_current():
      return
    if self._preview_callback is None:
      self._preview_label.setText("Preview unavailable: no sample is selected")
      return
    output_id = self._output_id_edit.text().strip()
    try:
      preview = self._preview_callback(self.definitions(), output_id)
    except Exception as exc:
      self._show_validation_error(exc)
      self._preview_label.setText(f"Preview failed: {exc}")
      return
    finite = preview.values[np.isfinite(preview.values)]
    nan_count = int(np.isnan(preview.values).sum())
    summary = (
      f"{preview.preview_event_count} / {preview.source_event_count} events; "
      f"NaN: {nan_count}"
    )
    if finite.size:
      summary += f"; min={finite.min():.6g}, max={finite.max():.6g}"
    shown = ["NaN" if np.isnan(value) else f"{value:.6g}" for value in preview.values[:5]]
    if shown:
      summary += "; values: " + ", ".join(shown)
    if preview.diagnostics:
      summary += "; diagnostics: " + ", ".join(
        diagnostic.code for diagnostic in preview.diagnostics
      )
    self._preview_label.setText(summary)

  def _accept_if_valid(self) -> None:
    if self._validate_current():
      self.accept()
