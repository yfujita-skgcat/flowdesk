"""Qt editor for the typed, display-only plot presentation definition."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

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

from flowdesk_core.models import (
  FontSpec,
  PlotPresentationSpec,
  SourceStyleSpec,
)
from flowdesk_core.plot_presentation import (
  SUPPORTED_STYLE_FIELDS,
  PresentationValidationError,
  validate_presentation,
)

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT_FIELDS = ("title", "axis_label", "tick", "legend")


class PlotStyleEditorDialog(QDialog):
  """Edit presentation values and reject unsupported style fields explicitly."""

  def __init__(
    self,
    plot_type: str,
    presentation: dict[str, Any] | None,
    source_ids: tuple[str, ...] | list[str] = (),
    project_defaults: dict[str, Any] | None = None,
    global_defaults: dict[str, Any] | None = None,
    parent: QWidget | None = None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("plotStyleEditorDialog")
    self.setWindowTitle("Plot Presentation")
    self.resize(820, 760)
    self._plot_type = plot_type
    self._presentation = deepcopy(presentation or {})
    self._source_ids = tuple(source_ids)
    self._project_defaults = deepcopy(project_defaults or {})
    self._global_defaults = deepcopy(global_defaults or {})
    self._source_styles = self._normalise_source_styles()
    self._building = False
    self._build_ui()
    self._load_presentation()

  def presentation(self) -> dict[str, Any]:
    """Return JSON-compatible presentation state only."""
    self._write_source_style()
    result = deepcopy(self._presentation)
    result.update({
      "title": self._title_edit.text(),
      "subtitle": self._subtitle_edit.text(),
      "x_axis_display_label": self._x_label_edit.text() or None,
      "y_axis_display_label": self._y_label_edit.text() or None,
      "background_color": self._background_edit.text().strip(),
      "legend_visible": self._legend_visible_check.isChecked(),
      "legend_position": self._legend_position_combo.currentData(),
      "legend_source_ids": [
        self._legend_list.item(index).data(0x0100)
        for index in range(self._legend_list.count())
      ],
      "gate_outline_color": self._gate_color_edit.text().strip(),
      "gate_outline_width": self._gate_width_spin.value(),
      "gate_outline_style": self._gate_style_combo.currentData(),
      "colormap": self._colormap_edit.text().strip() or None,
      "automatic_style_policy": self._presentation.get(
        "automatic_style_policy", "palette.v1"
      ),
      "source_styles": deepcopy(self._source_styles),
    })
    for field_name in _FONT_FIELDS:
      result[f"{field_name}_font"] = self._font_mapping(field_name)
    return result

  def _normalise_source_styles(self) -> list[dict[str, Any]]:
    existing = {
      str(style.get("source_id")): deepcopy(style)
      for style in self._presentation.get("source_styles", [])
      if isinstance(style, dict) and style.get("source_id")
    }
    styles: list[dict[str, Any]] = []
    for source_id in self._source_ids:
      style = existing.get(source_id, {"source_id": source_id})
      style.setdefault("source_id", source_id)
      style.setdefault("legend_label", None)
      style.setdefault("color", None)
      style.setdefault("alpha", 1.0)
      style.setdefault("marker_shape", None)
      style.setdefault("marker_size", 4.0)
      style.setdefault("line_color", None)
      style.setdefault("line_width", 1.5)
      style.setdefault("line_style", "solid")
      style.setdefault("histogram_fill_color", None)
      style.setdefault("histogram_outline_color", None)
      style.setdefault("histogram_alpha", 0.35)
      style["manual_fields"] = list(style.get("manual_fields", []))
      style.setdefault("provenance", {})
      styles.append(style)
    return styles

  def _build_ui(self) -> None:
    root = QVBoxLayout(self)
    form_widget = QWidget()
    form = QFormLayout(form_widget)
    self._title_edit = QLineEdit()
    self._title_edit.setObjectName("plotTitleEdit")
    form.addRow("Title:", self._title_edit)
    self._subtitle_edit = QLineEdit()
    self._subtitle_edit.setObjectName("plotSubtitleEdit")
    form.addRow("Subtitle/annotation:", self._subtitle_edit)
    self._x_label_edit = QLineEdit()
    self._x_label_edit.setObjectName("plotXAxisDisplayLabelEdit")
    form.addRow("X axis display label:", self._x_label_edit)
    self._y_label_edit = QLineEdit()
    self._y_label_edit.setObjectName("plotYAxisDisplayLabelEdit")
    form.addRow("Y axis display label:", self._y_label_edit)
    self._legend_visible_check = QCheckBox("Show legend")
    self._legend_visible_check.setObjectName("plotLegendVisibleCheckBox")
    form.addRow("Legend:", self._legend_visible_check)
    self._legend_position_combo = QComboBox()
    self._legend_position_combo.setObjectName("plotLegendPositionCombo")
    for value in ("right", "left", "top", "bottom", "inside"):
      self._legend_position_combo.addItem(value, value)
    form.addRow("Legend position:", self._legend_position_combo)

    legend_widget = QWidget()
    legend_layout = QHBoxLayout(legend_widget)
    legend_layout.setContentsMargins(0, 0, 0, 0)
    self._legend_list = QListWidget()
    self._legend_list.setObjectName("plotLegendOrderList")
    legend_layout.addWidget(self._legend_list, 1)
    legend_buttons = QVBoxLayout()
    self._legend_up_button = QPushButton("Up")
    self._legend_up_button.setObjectName("moveLegendSourceUpButton")
    self._legend_up_button.clicked.connect(lambda: self._move_legend(-1))
    self._legend_down_button = QPushButton("Down")
    self._legend_down_button.setObjectName("moveLegendSourceDownButton")
    self._legend_down_button.clicked.connect(lambda: self._move_legend(1))
    legend_buttons.addWidget(self._legend_up_button)
    legend_buttons.addWidget(self._legend_down_button)
    legend_layout.addLayout(legend_buttons)
    form.addRow("Legend order:", legend_widget)

    self._background_edit = QLineEdit()
    self._background_edit.setObjectName("plotBackgroundColorEdit")
    form.addRow("Plot background:", self._background_edit)
    self._gate_color_edit = QLineEdit()
    self._gate_color_edit.setObjectName("plotGateOutlineColorEdit")
    form.addRow("Gate outline color:", self._gate_color_edit)
    self._gate_width_spin = self._spin(0.1, 100.0, 1.5)
    self._gate_width_spin.setObjectName("plotGateOutlineWidthSpinBox")
    form.addRow("Gate outline width:", self._gate_width_spin)
    self._gate_style_combo = self._line_style_combo("plotGateOutlineStyleCombo")
    form.addRow("Gate outline style:", self._gate_style_combo)
    self._colormap_edit = QLineEdit()
    self._colormap_edit.setObjectName("plotColormapEdit")
    self._colormap_edit.setPlaceholderText("e.g. viridis")
    form.addRow("Colormap:", self._colormap_edit)
    root.addWidget(form_widget)

    source_form = QWidget()
    source_layout = QFormLayout(source_form)
    self._source_combo = QComboBox()
    self._source_combo.setObjectName("plotStyleSourceCombo")
    self._source_combo.currentIndexChanged.connect(self._on_source_changed)
    source_layout.addRow("Source:", self._source_combo)
    self._source_status_label = QLabel("Automatic style")
    self._source_status_label.setObjectName("plotStyleSourceProvenanceLabel")
    source_layout.addRow("Provenance:", self._source_status_label)
    self._marker_shape_combo = QComboBox()
    self._marker_shape_combo.setObjectName("plotMarkerShapeCombo")
    self._marker_shape_combo.addItem("Automatic", None)
    for value in ("circle", "square", "triangle", "cross", "plus"):
      self._marker_shape_combo.addItem(value.title(), value)
    source_layout.addRow("Marker shape:", self._marker_shape_combo)
    self._marker_size_spin = self._spin(0.1, 100.0, 4.0)
    self._marker_size_spin.setObjectName("plotMarkerSizeSpinBox")
    source_layout.addRow("Marker size:", self._marker_size_spin)
    self._source_color_edit = QLineEdit()
    self._source_color_edit.setObjectName("plotSourceColorEdit")
    source_layout.addRow("Source color:", self._source_color_edit)
    self._source_alpha_spin = self._spin(0.0, 1.0, 1.0, 0.05)
    self._source_alpha_spin.setObjectName("plotSourceAlphaSpinBox")
    source_layout.addRow("Source alpha:", self._source_alpha_spin)
    self._line_color_edit = QLineEdit()
    self._line_color_edit.setObjectName("plotSourceLineColorEdit")
    source_layout.addRow("Line color:", self._line_color_edit)
    self._line_width_spin = self._spin(0.1, 100.0, 1.5)
    self._line_width_spin.setObjectName("plotSourceLineWidthSpinBox")
    source_layout.addRow("Line width:", self._line_width_spin)
    self._line_style_combo = self._line_style_combo("plotSourceLineStyleCombo")
    source_layout.addRow("Line style:", self._line_style_combo)
    self._hist_fill_edit = QLineEdit()
    self._hist_fill_edit.setObjectName("plotHistogramFillColorEdit")
    source_layout.addRow("Histogram fill:", self._hist_fill_edit)
    self._hist_outline_edit = QLineEdit()
    self._hist_outline_edit.setObjectName("plotHistogramOutlineColorEdit")
    source_layout.addRow("Histogram outline:", self._hist_outline_edit)
    self._hist_alpha_spin = self._spin(0.0, 1.0, 0.35, 0.05)
    self._hist_alpha_spin.setObjectName("plotHistogramAlphaSpinBox")
    source_layout.addRow("Histogram alpha:", self._hist_alpha_spin)
    self._reset_source_button = QPushButton("Reset source to automatic")
    self._reset_source_button.setObjectName("resetSourceStyleButton")
    self._reset_source_button.clicked.connect(self._reset_source)
    source_layout.addRow("Overrides:", self._reset_source_button)
    reset_defaults = QWidget()
    reset_layout = QHBoxLayout(reset_defaults)
    reset_layout.setContentsMargins(0, 0, 0, 0)
    self._reset_project_button = QPushButton("Project default")
    self._reset_project_button.setObjectName("resetSourceToProjectDefaultButton")
    self._reset_project_button.clicked.connect(self._reset_source_to_project)
    self._reset_global_button = QPushButton("Global default")
    self._reset_global_button.setObjectName("resetSourceToGlobalDefaultButton")
    self._reset_global_button.clicked.connect(self._reset_source_to_global)
    reset_layout.addWidget(self._reset_project_button)
    reset_layout.addWidget(self._reset_global_button)
    source_layout.addRow("Resolve default:", reset_defaults)
    root.addWidget(source_form)

    font_form = QWidget()
    fonts = QFormLayout(font_form)
    self._font_controls: dict[str, tuple[QLineEdit, QDoubleSpinBox, QComboBox]] = {}
    for field_name, label in (
      ("title", "Title font"), ("axis_label", "Axis label font"),
      ("tick", "Tick font"), ("legend", "Legend font"),
    ):
      row = QWidget()
      row_layout = QHBoxLayout(row)
      row_layout.setContentsMargins(0, 0, 0, 0)
      family = QLineEdit()
      family.setObjectName(f"{field_name}FontFamilyEdit")
      size = self._spin(1.0, 96.0, 10.0)
      size.setObjectName(f"{field_name}FontSizeSpinBox")
      weight = QComboBox()
      weight.setObjectName(f"{field_name}FontWeightCombo")
      weight.addItems(["normal", "bold", "light"])
      row_layout.addWidget(family, 2)
      row_layout.addWidget(size, 1)
      row_layout.addWidget(weight, 1)
      fonts.addRow(label, row)
      self._font_controls[field_name] = (family, size, weight)
    root.addWidget(font_form)

    self._status_label = QLabel("Status: ready")
    self._status_label.setObjectName("plotStyleValidationLabel")
    self._status_label.setWordWrap(True)
    root.addWidget(self._status_label)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("plotStyleDialogButtons")
    buttons.accepted.connect(self._accept)
    buttons.rejected.connect(self.reject)
    root.addWidget(buttons)

    self._source_controls = (
      self._marker_shape_combo, self._marker_size_spin, self._source_color_edit,
      self._source_alpha_spin, self._line_color_edit, self._line_width_spin,
      self._line_style_combo, self._hist_fill_edit, self._hist_outline_edit,
      self._hist_alpha_spin,
    )
    for field_name, widget in zip(
      (
        "marker_shape", "marker_size", "color", "alpha", "line_color",
        "line_width", "line_style", "histogram_fill_color",
        "histogram_outline_color", "histogram_alpha",
      ),
      self._source_controls,
      strict=True,
    ):
      if isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(
          lambda _index, name=field_name: self._mark_current_field(name)
        )
      elif isinstance(widget, QDoubleSpinBox):
        widget.valueChanged.connect(
          lambda _value, name=field_name: self._mark_current_field(name)
        )
      else:
        widget.textChanged.connect(
          lambda _text, name=field_name: self._mark_current_field(name)
        )

  @staticmethod
  def _spin(minimum: float, maximum: float, value: float, step: float = 1.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    return spin

  @staticmethod
  def _line_style_combo(object_name: str) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName(object_name)
    for value in ("solid", "dashed", "dotted", "dashdot"):
      combo.addItem(value.title(), value)
    return combo

  def _load_presentation(self) -> None:
    self._building = True
    try:
      self._title_edit.setText(str(self._presentation.get("title", "")))
      self._subtitle_edit.setText(str(self._presentation.get("subtitle", "")))
      self._x_label_edit.setText(str(self._presentation.get("x_axis_display_label") or ""))
      self._y_label_edit.setText(str(self._presentation.get("y_axis_display_label") or ""))
      self._legend_visible_check.setChecked(bool(self._presentation.get("legend_visible", True)))
      self._set_data(
        self._legend_position_combo,
        self._presentation.get("legend_position", "right"),
      )
      self._background_edit.setText(str(self._presentation.get("background_color", "#ffffff")))
      self._gate_color_edit.setText(str(self._presentation.get("gate_outline_color", "#555555")))
      self._gate_width_spin.setValue(float(self._presentation.get("gate_outline_width", 1.5)))
      self._set_data(self._gate_style_combo, self._presentation.get("gate_outline_style", "solid"))
      self._colormap_edit.setText(str(self._presentation.get("colormap") or ""))
      self._legend_list.clear()
      legend_ids = list(self._presentation.get("legend_source_ids", self._source_ids))
      legend_ids.extend(source_id for source_id in self._source_ids if source_id not in legend_ids)
      for source_id in legend_ids:
        item = QListWidgetItem(source_id)
        item.setData(0x0100, source_id)
        self._legend_list.addItem(item)
      self._source_combo.clear()
      self._source_combo.addItems(list(self._source_ids))
      for field_name in _FONT_FIELDS:
        value = self._presentation.get(f"{field_name}_font", {})
        family, size, weight = self._font_controls[field_name]
        family.setText(str(value.get("family", "DejaVu Sans")))
        size.setValue(float(value.get("size", 10.0)))
        weight.setCurrentText(str(value.get("weight", "normal")))
    finally:
      self._building = False
    if self._source_combo.count():
      self._source_combo.setCurrentIndex(0)
    self._update_support_state()

  @staticmethod
  def _set_data(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)

  def _font_mapping(self, field_name: str) -> dict[str, Any]:
    family, size, weight = self._font_controls[field_name]
    return {
      "family": family.text(), "size": size.value(),
      "weight": weight.currentText(), "italic": False,
    }

  def _style(self) -> dict[str, Any] | None:
    index = self._source_combo.currentIndex()
    return self._source_styles[index] if 0 <= index < len(self._source_styles) else None

  def _on_source_changed(self, _index: int) -> None:
    self._building = True
    try:
      style = self._style()
      if style is None:
        return
      self._set_data(self._marker_shape_combo, style.get("marker_shape"))
      self._marker_size_spin.setValue(float(style.get("marker_size", 4.0)))
      self._source_color_edit.setText(str(style.get("color") or ""))
      self._source_alpha_spin.setValue(float(style.get("alpha", 1.0)))
      self._line_color_edit.setText(str(style.get("line_color") or ""))
      self._line_width_spin.setValue(float(style.get("line_width", 1.5)))
      self._set_data(self._line_style_combo, style.get("line_style", "solid"))
      self._hist_fill_edit.setText(str(style.get("histogram_fill_color") or ""))
      self._hist_outline_edit.setText(str(style.get("histogram_outline_color") or ""))
      self._hist_alpha_spin.setValue(float(style.get("histogram_alpha", 0.35)))
      fields = style.get("manual_fields", [])
      self._source_status_label.setText(
        "Manual override: " + ", ".join(fields)
        if fields else "Resolved: " + ", ".join(
          sorted(set(style.get("provenance", {}).values()))
        ) if style.get("provenance") else "Automatic style"
      )
    finally:
      self._building = False
    self._update_support_state()

  def _mark_current_field(self, field_name: str | None = None) -> None:
    if self._building:
      return
    self._write_source_style()
    if field_name is not None:
      style = self._style()
      if style is not None:
        fields = set(style.get("manual_fields", []))
        fields.add(field_name)
        style["manual_fields"] = sorted(fields)
        provenance = dict(style.get("provenance", {}))
        provenance[field_name] = "manual"
        style["provenance"] = provenance
    self._update_support_state()

  def _write_source_style(self) -> None:
    style = self._style()
    if style is None or self._building:
      return
    style.update({
      "marker_shape": self._marker_shape_combo.currentData(),
      "marker_size": self._marker_size_spin.value(),
      "color": self._source_color_edit.text().strip() or None,
      "alpha": self._source_alpha_spin.value(),
      "line_color": self._line_color_edit.text().strip() or None,
      "line_width": self._line_width_spin.value(),
      "line_style": self._line_style_combo.currentData(),
      "histogram_fill_color": self._hist_fill_edit.text().strip() or None,
      "histogram_outline_color": self._hist_outline_edit.text().strip() or None,
      "histogram_alpha": self._hist_alpha_spin.value(),
    })

  def _reset_source(self) -> None:
    self._reset_source_to({
      "marker_shape": None, "marker_size": 4.0, "color": None,
      "alpha": 1.0, "line_color": None, "line_width": 1.5,
      "line_style": "solid", "histogram_fill_color": None,
      "histogram_outline_color": None, "histogram_alpha": 0.35,
    }, "view_default")

  def _reset_source_to_project(self) -> None:
    self._reset_source_to(
      self._default_source_style(self._project_defaults), "project_default"
    )

  def _reset_source_to_global(self) -> None:
    self._reset_source_to(
      self._default_source_style(self._global_defaults), "global_default"
    )

  @staticmethod
  def _default_source_style(defaults: dict[str, Any]) -> dict[str, Any]:
    styles = defaults.get("source_styles", [])
    if isinstance(styles, list) and styles and isinstance(styles[0], dict):
      return deepcopy(styles[0])
    return {}

  def _reset_source_to(self, values: dict[str, Any], provenance: str) -> None:
    style = self._style()
    if style is None:
      return
    style.update(deepcopy(values))
    style["manual_fields"] = []
    style["provenance"] = {"style": provenance}
    self._on_source_changed(self._source_combo.currentIndex())

  def _move_legend(self, offset: int) -> None:
    row = self._legend_list.currentRow()
    target = row + offset
    if not (0 <= row < self._legend_list.count() and 0 <= target < self._legend_list.count()):
      return
    item = self._legend_list.takeItem(row)
    self._legend_list.insertItem(target, item)
    self._legend_list.setCurrentRow(target)

  def _update_support_state(self) -> None:
    supported = SUPPORTED_STYLE_FIELDS.get(self._plot_type, frozenset())
    mapping = {
      "marker_shape": self._marker_shape_combo, "marker_size": self._marker_size_spin,
      "color": self._source_color_edit, "alpha": self._source_alpha_spin,
      "line_color": self._line_color_edit, "line_width": self._line_width_spin,
      "line_style": self._line_style_combo, "histogram_fill_color": self._hist_fill_edit,
      "histogram_outline_color": self._hist_outline_edit, "histogram_alpha": self._hist_alpha_spin,
    }
    for field_name, widget in mapping.items():
      enabled = field_name in supported
      widget.setEnabled(enabled)
      widget.setToolTip(
        "Supported for this plot type"
        if enabled else f"Unsupported for {self._plot_type}"
      )
    colormap_enabled = "colormap" in supported
    self._colormap_edit.setEnabled(colormap_enabled)
    self._colormap_edit.setToolTip(
      "Supported for this plot type"
      if colormap_enabled else f"Unsupported for {self._plot_type}"
    )

  def _typed_presentation(self) -> PlotPresentationSpec:
    source_styles = tuple(SourceStyleSpec(**{
      **style, "manual_fields": tuple(style.get("manual_fields", [])),
    }) for style in self.presentation()["source_styles"])
    result = self.presentation()
    return PlotPresentationSpec(
      title=str(result["title"]), subtitle=str(result["subtitle"]),
      x_axis_display_label=result["x_axis_display_label"],
      y_axis_display_label=result["y_axis_display_label"],
      background_color=str(result["background_color"]),
      legend_visible=bool(result["legend_visible"]),
      legend_position=str(result["legend_position"]),
      legend_source_ids=tuple(result["legend_source_ids"]),
      title_font=FontSpec(**result["title_font"]),
      axis_label_font=FontSpec(**result["axis_label_font"]),
      tick_font=FontSpec(**result["tick_font"]),
      legend_font=FontSpec(**result["legend_font"]),
      gate_outline_color=str(result["gate_outline_color"]),
      gate_outline_width=float(result["gate_outline_width"]),
      gate_outline_style=str(result["gate_outline_style"]),
      colormap=result["colormap"],
      automatic_style_policy=str(result["automatic_style_policy"]),
      source_styles=source_styles,
    )

  def _accept(self) -> None:
    try:
      typed = self._typed_presentation()
      validate_presentation(self._plot_type, typed)  # type: ignore[arg-type]
    except (PresentationValidationError, ValueError) as exc:
      self._status_label.setText(f"Status: unsupported/invalid — {exc}")
      return
    self._status_label.setText("Status: valid display presentation")
    self.accept()
