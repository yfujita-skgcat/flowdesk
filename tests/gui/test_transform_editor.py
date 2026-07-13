"""GUI tests for versioned analysis transform editing and preview."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit  # noqa: E402

from flowdesk_core.models import ChannelSpec  # noqa: E402
from flowdesk_qt.transform_editor import TransformEditorDialog  # noqa: E402


def _app() -> QApplication:
  return QApplication.instance() or QApplication([])


def test_transform_editor_edits_logicle_parameters_and_round_trip_preview() -> None:
  app = _app()
  dialog = TransformEditorDialog(
    [],
    (ChannelSpec(id="signal", name="Signal"),),
    preview_values={"signal": np.array([-100.0, 0.0, 100.0, 262144.0])},
  )
  try:
    dialog.findChild(QLineEdit, "transformIdEdit").setText("logicle_signal")
    dialog.findChild(QLineEdit, "transformNameEdit").setText("Signal Logicle")
    dialog._parameter_combo.setCurrentIndex(0)
    dialog._type_combo.setCurrentText("logicle")
    dialog._setting_edits["T"].setText("262144")
    dialog._setting_edits["W"].setText("0.5")
    dialog._setting_edits["M"].setText("4.5")
    dialog._setting_edits["A"].setText("0")

    dialog._preview_current()

    preview = dialog.findChild(QLabel, "transformPreviewLabel").text()
    assert "inverse round-trip" in preview
    assert "4 finite events" in preview
    definitions = dialog.transforms()
    assert definitions[0]["transform_type"] == "logicle"
    assert definitions[0]["settings"]["T"] == 262144.0
    assert definitions[0]["settings"]["implementation_version"].startswith(
      "logicle-gml2"
    )
  finally:
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_transform_editor_exposes_complete_settings_for_each_new_type() -> None:
  app = _app()
  dialog = TransformEditorDialog(
    [], (ChannelSpec(id="signal", name="Signal"),)
  )
  try:
    expected = {
      "linear": {"scale", "offset"},
      "log": {"base", "invalid_value_policy"},
      "asinh": {"cofactor"},
      "logicle": {"T", "W", "M", "A", "implementation_version"},
    }
    for transform_type, setting_names in expected.items():
      dialog._type_combo.setCurrentText(transform_type)
      assert set(dialog._visible_setting_names()) == setting_names
  finally:
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
