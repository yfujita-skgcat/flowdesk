from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
  QComboBox,
  QLabel,
  QLineEdit,
  QPlainTextEdit,
  QPushButton,
)

from flowdesk_core.derived_parameters import DerivedParameterPreview
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import ChannelSpec, GateSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.sample import SampleData
from flowdesk_qt.derived_parameter_editor import DerivedParameterEditorDialog
from flowdesk_qt.main_window import MainWindow

pytestmark = pytest.mark.gui


def _line_edit(dialog: DerivedParameterEditorDialog, name: str) -> QLineEdit:
  widget = dialog.findChild(QLineEdit, name)
  assert widget is not None
  return widget


def test_editor_starts_empty_and_generates_draft_ids(qapp) -> None:
  dialog = DerivedParameterEditorDialog(
    [],
    (ChannelSpec(id="signal", name="Signal"),),
  )
  try:
    assert dialog.definitions() == []
    assert dialog._definition_list.count() == 0

    dialog._new_button.click()
    assert dialog._id_edit.text() == "derived_parameter_compensated_expression"
    assert dialog._output_id_edit.text() == "expression"

    dialog._name_edit.setText("Ratio")
    dialog._source_combo.setCurrentText("raw")
    dialog._expression_edit.setPlainText("signal / 2")
    assert dialog._id_edit.text() == "ratio_raw_signal_over_2"
    assert dialog._output_id_edit.text() == "signal_over_2"
    assert "Ratio | raw | signal / 2 => signal_over_2" == (
      dialog._definition_list.item(0).text()
    )
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_referenced_derived_ids_are_read_only_after_reopen(qapp) -> None:
  definition = {
    "id": "stable_definition",
    "name": "Ratio",
    "expression": "signal / 2",
    "output_channel_id": "stable_output",
    "source_stage": "compensated",
    "input_parameters": ["signal"],
    "invalid_value_policy": "emit_nan_with_warning",
  }
  dialog = DerivedParameterEditorDialog(
    [definition],
    (ChannelSpec(id="signal", name="Signal"),),
    fixed_definition_ids=("stable_definition",),
    fixed_output_channel_ids=("stable_output",),
  )
  try:
    assert dialog._id_edit.isReadOnly()
    assert dialog._output_id_edit.isReadOnly()
    dialog._name_edit.setText("Renamed")
    dialog._source_combo.setCurrentText("raw")
    dialog._expression_edit.setPlainText("signal")
    assert dialog._id_edit.text() == "stable_definition"
    assert dialog._output_id_edit.text() == "stable_output"
    assert dialog.definitions()[0]["id"] == "stable_definition"
    assert dialog.definitions()[0]["output_channel_id"] == "stable_output"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_generated_ids_use_collision_suffixes(qapp) -> None:
  definitions = [{
    "id": "ratio_compensated_signal_over_2",
    "name": "Ratio",
    "expression": "signal / 2",
    "output_channel_id": "signal_over_2",
    "source_stage": "compensated",
    "input_parameters": ["signal"],
    "invalid_value_policy": "emit_nan_with_warning",
  }]
  dialog = DerivedParameterEditorDialog(
    definitions,
    (ChannelSpec(id="signal", name="Signal"),),
  )
  try:
    dialog._new_button.click()
    dialog._name_edit.setText("Ratio")
    dialog._expression_edit.setPlainText("signal / 2")
    assert dialog._id_edit.text() == "ratio_compensated_signal_over_2_2"
    assert dialog._output_id_edit.text() == "signal_over_2_2"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_persists_all_fields_and_inserts_parameter(qapp) -> None:
  channels = (
    ChannelSpec(id="signal", name="Signal"),
    ChannelSpec(id="reference", name="Reference"),
  )
  dialog = DerivedParameterEditorDialog([], channels)
  try:
    dialog._new_button.click()
    expression = dialog.findChild(
      QPlainTextEdit, "derivedParameterExpressionEdit"
    )
    assert expression is not None
    expression.setPlainText(" / reference")
    _line_edit(dialog, "derivedParameterNameEdit").setText("Signal ratio")
    _line_edit(dialog, "derivedParameterUnitEdit").setText("ratio")
    expression.moveCursor(QTextCursor.Start)
    parameter_combo = dialog.findChild(
      QComboBox, "derivedParameterInsertParameterCombo"
    )
    assert parameter_combo is not None
    parameter_combo.setCurrentIndex(parameter_combo.findData("signal"))
    insert_button = dialog.findChild(
      QPushButton, "derivedParameterInsertParameterButton"
    )
    assert insert_button is not None
    insert_button.click()
    _line_edit(dialog, "derivedParameterOutputIdEdit").setText("signal_ratio")
    detected_inputs = dialog.findChild(
      QLabel, "derivedParameterDetectedInputsLabel"
    )
    assert detected_inputs is not None
    assert detected_inputs.text() == "Signal [signal], Reference [reference]"
    source = dialog.findChild(QComboBox, "derivedParameterSourceStageCombo")
    policy = dialog.findChild(QComboBox, "derivedParameterPolicyCombo")
    assert source is not None and policy is not None
    source.setCurrentText("raw")
    policy.setCurrentText("fail_run")
    _line_edit(dialog, "derivedParameterDefinitionIdEdit").setText("ratio_def")
    _line_edit(dialog, "derivedParameterOutputIdEdit").setText("signal_ratio")

    definitions = dialog.definitions()

    assert definitions == [{
      "id": "ratio_def",
      "name": "Signal ratio",
      "expression": "signal / reference",
      "output_channel_id": "signal_ratio",
      "output_label": None,
      "unit": "ratio",
      "source_stage": "raw",
      "input_parameters": ["signal", "reference"],
      "invalid_value_policy": "fail_run",
      "non_finite_policy": "strict",
      "notes": "",
    }]
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_replaces_detected_inputs_when_expression_changes(qapp) -> None:
  dialog = DerivedParameterEditorDialog(
    [],
    (
      ChannelSpec(id="signal", name="Signal"),
      ChannelSpec(id="reference", name="Reference"),
    ),
  )
  try:
    dialog._new_button.click()
    expression = dialog.findChild(
      QPlainTextEdit, "derivedParameterExpressionEdit"
    )
    detected_inputs = dialog.findChild(
      QLabel, "derivedParameterDetectedInputsLabel"
    )
    assert expression is not None and detected_inputs is not None

    expression.setPlainText("signal")
    assert dialog.definitions()[0]["input_parameters"] == ["signal"]
    assert detected_inputs.text() == "Signal [signal]"

    expression.setPlainText("reference")
    assert dialog.definitions()[0]["input_parameters"] == ["reference"]
    assert detected_inputs.text() == "Reference [reference]"

    expression.setPlainText("signal /")
    assert dialog.definitions()[0]["input_parameters"] == []
    assert detected_inputs.text() == "Invalid or incomplete expression"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_reports_core_syntax_code_and_position(qapp) -> None:
  dialog = DerivedParameterEditorDialog(
    [], (ChannelSpec(id="signal", name="Signal"),)
  )
  try:
    dialog._new_button.click()
    _line_edit(dialog, "derivedParameterDefinitionIdEdit").setText("bad")
    _line_edit(dialog, "derivedParameterNameEdit").setText("Bad")
    _line_edit(dialog, "derivedParameterOutputIdEdit").setText("bad_output")
    expression = dialog.findChild(
      QPlainTextEdit, "derivedParameterExpressionEdit"
    )
    validate = dialog.findChild(
      QPushButton, "derivedParameterValidateButton"
    )
    diagnostic = dialog.findChild(QLabel, "derivedParameterDiagnosticLabel")
    assert expression is not None and validate is not None and diagnostic is not None
    expression.setPlainText("signal /")

    validate.click()

    assert "invalid_derived_expression" in diagnostic.text()
    assert "line 1" in diagnostic.text()
    assert "column" in diagnostic.text()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_can_delete_the_last_definition(qapp) -> None:
  dialog = DerivedParameterEditorDialog(
    [{
      "id": "copy",
      "name": "Copy",
      "expression": "signal",
      "output_channel_id": "copy_output",
      "unit": None,
      "source_stage": "raw",
      "input_parameters": ["signal"],
      "invalid_value_policy": "fail_run",
    }],
    (ChannelSpec(id="signal", name="Signal"),),
  )
  try:
    delete = dialog.findChild(QPushButton, "derivedParameterDeleteButton")
    assert delete is not None
    delete.click()

    assert dialog.definitions() == []
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_preview_delegates_to_bounded_core_result(qapp) -> None:
  calls: list[tuple[list[dict], str]] = []

  def preview_callback(definitions: list[dict], output_id: str):
    calls.append((definitions, output_id))
    values = np.array([2.0, np.nan], dtype=np.float64)
    values.setflags(write=False)
    return DerivedParameterPreview(
      values=values,
      channel=ChannelSpec(id="ratio", name="Ratio"),
      source_event_count=500,
      preview_event_count=2,
      diagnostics=(),
    )

  dialog = DerivedParameterEditorDialog(
    [],
    (
      ChannelSpec(id="signal", name="Signal"),
      ChannelSpec(id="reference", name="Reference"),
    ),
    preview_callback=preview_callback,
  )
  try:
    dialog._new_button.click()
    expression = dialog.findChild(
      QPlainTextEdit, "derivedParameterExpressionEdit"
    )
    assert expression is not None
    expression.setPlainText("signal / reference")
    _line_edit(dialog, "derivedParameterDefinitionIdEdit").setText("ratio_def")
    _line_edit(dialog, "derivedParameterNameEdit").setText("Ratio")
    preview = dialog.findChild(QPushButton, "derivedParameterPreviewButton")
    result = dialog.findChild(QLabel, "derivedParameterPreviewLabel")
    assert expression is not None and preview is not None and result is not None
    _line_edit(dialog, "derivedParameterOutputIdEdit").setText("ratio")

    preview.click()

    assert calls[0][1] == "ratio"
    assert calls[0][0][0]["expression"] == "signal / reference"
    assert "2 / 500 events" in result.text()
    assert "NaN: 1" in result.text()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_preview_surfaces_core_nonfinite_diagnostic(qapp) -> None:
  sample = SampleData(
    "s1",
    np.array([[0.0], [1.0], [-2.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"),),
  )

  def preview_callback(definitions: list[dict], output_id: str):
    runner = PipelineRunner({"derived_parameters": definitions})
    return runner.preview_derived_parameter(sample, output_id)

  dialog = DerivedParameterEditorDialog(
    [], (ChannelSpec(id="signal", name="Signal"),),
    preview_callback=preview_callback,
  )
  try:
    dialog._new_button.click()
    expression = dialog.findChild(QPlainTextEdit, "derivedParameterExpressionEdit")
    assert expression is not None
    expression.setPlainText("log(signal)")
    _line_edit(dialog, "derivedParameterDefinitionIdEdit").setText("log_def")
    _line_edit(dialog, "derivedParameterNameEdit").setText("Log signal")
    _line_edit(dialog, "derivedParameterOutputIdEdit").setText("log_signal")
    preview = dialog.findChild(QPushButton, "derivedParameterPreviewButton")
    result = dialog.findChild(QLabel, "derivedParameterPreviewLabel")
    assert expression is not None and preview is not None and result is not None
    expression.setPlainText("log(signal)")
    preview.click()
    assert "NaN: 2" in result.text()
    assert "derived_parameter_nonfinite_values" in result.text()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_main_window_derived_definitions_survive_project_save_load(
  qapp,
  tmp_path: Path,
) -> None:
  definition = {
    "id": "ratio_def",
    "name": "Ratio",
    "expression": "signal / reference",
    "output_channel_id": "ratio",
    "output_label": None,
    "unit": "ratio",
    "source_stage": "raw",
    "input_parameters": ["signal", "reference"],
    "invalid_value_policy": "fail_run",
    "notes": "",
  }
  first = MainWindow()
  second = MainWindow()
  bundle = tmp_path / "derived.flowdesk"
  try:
    assert first.action_derived_parameters.objectName() == "actionDerivedParameters"
    first._derived_parameters = [definition]
    first._save_project_to_path(bundle)
    second._load_project_from_path(bundle)

    assert second._build_project_manifest()["derived_parameters"] == [definition]
  finally:
    first.close()
    second.close()
    first.deleteLater()
    second.deleteLater()
    qapp.processEvents()


def test_gui_derived_definition_matches_headless_gate_count(
  qapp,
  tmp_path: Path,
) -> None:
  fcs_path = tmp_path / "derived-gui.fcs"
  write_fcs_file(
    fcs_path,
    np.array([[2.0, 1.0], [1.0, 2.0], [6.0, 3.0]], dtype=np.float64),
    ["Signal", "Reference"],
  )
  window = MainWindow()
  try:
    window._sample_browser.add_samples_from_paths([str(fcs_path)])
    sample_info = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample_info.id)
    signal_id, reference_id = [channel.id for channel in sample_info.info.channels]
    window._derived_parameters = [{
      "id": "ratio_definition",
      "name": "Ratio",
      "expression": f"{signal_id} / {reference_id}",
      "output_channel_id": "ratio",
      "output_label": None,
      "unit": "ratio",
      "source_stage": "raw",
      "input_parameters": [signal_id, reference_id],
      "invalid_value_policy": "fail_run",
      "notes": "",
    }]
    window._gate_editor.set_gates([GateSpec(
      id="ratio_positive",
      name="Ratio positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter="ratio",
      thresholds={"min": 1.5},
    )])
    manifest = window._build_project_manifest()
    typed_samples = tuple(window._sample_data.values())

    window._on_run_pipeline()
    worker = window._worker
    assert worker is not None
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    qapp.processEvents()

    gui_report = window._population_tree.last_report()
    assert gui_report is not None
    headless_report = PipelineRunner(manifest).run_samples(
      ExecutionContext(), typed_samples
    )
    gui_counts = {
      result.population_id: result.event_count
      for result in gui_report.population_results
    }
    headless_counts = {
      result.population_id: result.event_count
      for result in headless_report.population_results
    }
    assert gui_counts == headless_counts == {
      "all_events": 3,
      "ratio_positive": 2,
    }
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
