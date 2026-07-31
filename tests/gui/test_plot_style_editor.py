from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
  QComboBox,
  QDoubleSpinBox,
  QLineEdit,
  QPushButton,
  QTabWidget,
)

from flowdesk_qt.plot_style_editor import PlotStyleEditorDialog

pytestmark = pytest.mark.gui


def test_style_editor_round_trips_plot_and_source_presentation(qapp) -> None:
  dialog = PlotStyleEditorDialog(
    "histogram",
    {
      "title": "Before", "x_axis_display_label": "CD3", "legend_visible": True,
      "legend_position": "right", "source_styles": [{
        "source_id": "source-a", "legend_label": "A",
        "histogram_fill_color": "#112233", "histogram_alpha": 0.4,
        "manual_fields": ["legend_label", "histogram_fill_color", "histogram_alpha"],
      }],
    },
    ("source-a", "source-b"),
  )
  try:
    dialog._title_edit.setText("After")
    dialog._title_mode_combo.setCurrentIndex(
      dialog._title_mode_combo.findData("overlay_sample_titles")
    )
    dialog._subtitle_edit.setText("annotation")
    dialog._x_label_edit.setText("Publication CD3")
    dialog._legend_position_combo.setCurrentText("bottom")
    dialog._legend_visible_check.setChecked(False)
    dialog._source_combo.setCurrentIndex(0)
    dialog._hist_fill_edit.setText("#ff0000")
    dialog._hist_alpha_spin.setValue(0.6)
    dialog._accept()

    result = dialog.presentation()
    assert result["title"] == "After"
    assert result["title_mode"] == "overlay_sample_titles"
    assert result["subtitle"] == "annotation"
    assert result["x_axis_display_label"] == "Publication CD3"
    assert result["legend_visible"] is False
    assert result["legend_position"] == "bottom"
    assert result["source_styles"][0]["histogram_fill_color"] == "#ff0000"
    assert result["source_styles"][0]["histogram_alpha"] == 0.6
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_reset_removes_manual_source_overrides(qapp) -> None:
  dialog = PlotStyleEditorDialog(
    "scatter",
    {"source_styles": [{
      "source_id": "source-a", "marker_shape": "square", "marker_size": 12,
      "manual_fields": ["marker_shape", "marker_size"],
    }]},
    ("source-a",),
  )
  try:
    dialog._reset_source_button.click()
    style = dialog.presentation()["source_styles"][0]
    assert style["manual_fields"] == []
    assert style["marker_shape"] is None
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_rejects_unsupported_source_style(qapp) -> None:
  dialog = PlotStyleEditorDialog(
    "histogram",
    {"source_styles": [{
      "source_id": "source-a", "marker_shape": "circle",
      "manual_fields": ["marker_shape"],
    }]},
    ("source-a",),
  )
  try:
    dialog._accept()
    assert "unsupported" in dialog._status_label.text()
    assert dialog.result() == 0
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_distinguishes_project_and_global_default_resolution(qapp) -> None:
  dialog = PlotStyleEditorDialog(
    "scatter",
    {"source_styles": [{"source_id": "source-a", "manual_fields": ["color"]}]},
    ("source-a",),
    {"source_styles": [{"source_id": "source-a", "color": "#112233"}]},
    {"source_styles": [{"source_id": "source-a", "color": "#445566"}]},
  )
  try:
    dialog._reset_project_button.click()
    project_style = dialog.presentation()["source_styles"][0]
    assert project_style["color"] == "#112233"
    assert project_style["provenance"]["style"] == "project_default"
    dialog._reset_global_button.click()
    global_style = dialog.presentation()["source_styles"][0]
    assert global_style["color"] == "#445566"
    assert global_style["provenance"]["style"] == "global_default"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_uses_compact_pages_for_small_monitors(qapp) -> None:
  dialog = PlotStyleEditorDialog("scatter", {}, ())
  try:
    pages = dialog.findChild(QTabWidget, "plotAppearancePages")
    assert dialog.width() <= 560
    assert dialog.height() <= 520
    assert pages is not None
    assert dialog.findChild(QComboBox, "plotTitleModeCombo") is not None
    assert pages.count() == 3
    assert [pages.tabText(i) for i in range(pages.count())] == [
      "General", "Sources", "Fonts"
    ]
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_persists_single_sample_density_coloring(qapp) -> None:
  dialog = PlotStyleEditorDialog("scatter", {}, ())
  restored: PlotStyleEditorDialog | None = None
  try:
    selector = dialog.findChild(QComboBox, "plotColormapEdit")
    assert selector is not None
    selector.setCurrentIndex(selector.findData("density"))
    assert dialog.presentation()["colormap"] == "density"
    restored = PlotStyleEditorDialog("scatter", {"colormap": "density"}, ())
    selector = restored.findChild(QComboBox, "plotColormapEdit")
    assert selector is not None
    assert selector.currentData() == "density"
  finally:
    dialog.close()
    dialog.deleteLater()
    if restored is not None:
      restored.close()
      restored.deleteLater()
      qapp.processEvents()


def test_style_editor_single_color_has_palette_and_density_disables_it(qapp, monkeypatch) -> None:
  dialog = PlotStyleEditorDialog("scatter", {}, ())
  try:
    button = dialog.findChild(QPushButton, "plotSingleColorButton")
    edit = dialog.findChild(QLineEdit, "plotSingleColorEdit")
    selector = dialog.findChild(QComboBox, "plotColormapEdit")
    assert button is not None and edit is not None and selector is not None
    assert edit.isEnabled()
    monkeypatch.setattr(
      "flowdesk_qt.plot_style_editor.QColorDialog.getColor",
      lambda *_args: QColor("#A1B2C3"),
    )
    button.click()
    assert edit.text() == "#a1b2c3"
    assert dialog.presentation()["single_color"] == "#a1b2c3"
    size = dialog.findChild(QDoubleSpinBox, "plotSingleDotSizeSpinBox")
    assert size is not None
    size.setValue(3.5)
    assert dialog.presentation()["single_dot_size"] == 3.5
    selector.setCurrentIndex(selector.findData("density"))
    assert not edit.isEnabled()
    selector.setCurrentIndex(selector.findData(None))
    assert edit.isEnabled()
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_color_button_uses_palette_and_normalizes_hex(qapp, monkeypatch) -> None:
  dialog = PlotStyleEditorDialog(
    "histogram",
    {"background_color": "#010203", "source_styles": [{"source_id": "source-a"}]},
    ("source-a",),
  )
  try:
    button = dialog.findChild(QPushButton, "plotBackgroundColorButton")
    edit = dialog.findChild(QLineEdit, "plotBackgroundColorEdit")
    assert button is not None
    assert edit is not None
    monkeypatch.setattr(
      "flowdesk_qt.plot_style_editor.QColorDialog.getColor",
      lambda *_args: QColor("#A1B2C3"),
    )
    button.click()
    assert edit.text() == "#a1b2c3"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_style_editor_color_button_cancel_keeps_value(qapp, monkeypatch) -> None:
  dialog = PlotStyleEditorDialog("scatter", {"background_color": "#123456"}, ())
  try:
    button = dialog.findChild(QPushButton, "plotBackgroundColorButton")
    edit = dialog.findChild(QLineEdit, "plotBackgroundColorEdit")
    assert button is not None
    assert edit is not None
    monkeypatch.setattr(
      "flowdesk_qt.plot_style_editor.QColorDialog.getColor",
      lambda *_args: QColor(),
    )
    button.click()
    assert edit.text() == "#123456"
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()
