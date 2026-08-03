"""Channel and project-wide parameter display workspace."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
  QHBoxLayout,
  QLabel,
  QMenu,
  QTableWidget,
  QTableWidgetItem,
  QToolButton,
  QVBoxLayout,
  QWidget,
)

from flowdesk_core.parameter_catalog import ParameterCatalogEntry

_CHANNEL_COLUMNS = (
  ("id", "Stable ID"),
  ("name", "$PnN"),
  ("short_name", "$PnS"),
  ("detector", "Detector"),
  ("stain", "Stain"),
  ("unit", "Unit"),
  ("fcs_parameter_index", "FCS index"),
  ("gain", "Gain (PnG)"),
  ("exponent", "Exponent (PnE)"),
  ("range", "Range (PnR)"),
)
_DEFAULT_COLUMNS = {"name", "short_name", "detector", "stain", "fcs_parameter_index"}


class ChannelMetadataWorkspace(QWidget):
  """Show selected-sample parameters and edit project display labels."""

  project_mapping_changed = Signal(object)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("channelMetadataWorkspace")
    self._sample: Any | None = None
    self._sample_channels: dict[str, Any] = {}
    self._catalog: tuple[ParameterCatalogEntry, ...] = ()
    self._updating_project_table = False

    self._sample_label = QLabel("Sample: -")
    self._sample_label.setObjectName("channelMetadataSampleLabel")
    self._status_label = QLabel("Channel status: -")
    self._status_label.setObjectName("channelMetadataStatusLabel")
    self._file_label = QLabel("File: -")
    self._file_label.setObjectName("channelMetadataFileLabel")
    self._file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    self._table = QTableWidget()
    self._table.setObjectName("channelMetadataTable")
    self._table.setColumnCount(4)
    self._table.setHorizontalHeaderLabels(
      ["Actual parameter", "Plot display name", "Biological label / note", "Samples"]
    )
    self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
    self._table.setSortingEnabled(True)
    self._table.cellChanged.connect(self._on_project_mapping_cell_changed)

    self._column_button = QToolButton()
    self._column_button.setObjectName("channelColumnButton")
    self._column_button.setText("Columns")
    self._column_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    column_menu = QMenu(self._column_button)
    self._column_actions: dict[str, QAction] = {}
    for key, label in _CHANNEL_COLUMNS:
      action = QAction(label, column_menu)
      action.setObjectName(f"channelColumn_{key}")
      action.setCheckable(True)
      action.setChecked(key in _DEFAULT_COLUMNS)
      action.toggled.connect(
        lambda visible, column_key=key: self.set_column_visible(column_key, visible)
      )
      column_menu.addAction(action)
      self._column_actions[key] = action
    self._column_button.setMenu(column_menu)

    header = QHBoxLayout()
    header.addWidget(QLabel("Channel / Parameter Information"))
    header.addStretch(1)
    header.addWidget(self._column_button)

    info = QVBoxLayout()
    info.addWidget(self._sample_label)
    info.addWidget(self._status_label)
    info.addWidget(self._file_label)

    layout = QVBoxLayout(self)
    layout.addLayout(header)
    layout.addLayout(info)
    self._parameter_table = QTableWidget()
    self._parameter_table.setObjectName("parameterCatalogTable")
    self._parameter_table.setColumnCount(6 + len(_CHANNEL_COLUMNS))
    self._parameter_table.setHorizontalHeaderLabels(
      ["Parameter", "Type", "Source", "Expression", "Unit", "Status"]
      + [label for _, label in _CHANNEL_COLUMNS]
    )
    self._parameter_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self._parameter_table.setSortingEnabled(True)
    for key, _label in _CHANNEL_COLUMNS:
      self.set_column_visible(key, key in _DEFAULT_COLUMNS)
    layout.addWidget(QLabel("Selected sample parameters and FCS metadata (read-only)"))
    layout.addWidget(self._parameter_table)
    layout.addWidget(QLabel("Project-wide parameter display labels (editable)"))
    layout.addWidget(self._table)

  @property
  def table(self) -> QTableWidget:
    """Expose the table for accessibility and GUI regression tests."""
    return self._table

  @property
  def parameter_table(self) -> QTableWidget:
    """Expose the typed acquired-plus-derived parameter table for GUI tests."""
    return self._parameter_table

  def set_sample(self, sample: Any | None) -> None:
    """Display metadata for a SampleBrowser sample or clear the workspace."""
    self._sample = sample
    if sample is None:
      self._sample_label.setText("Sample: -")
      self._status_label.setText("Channel status: -")
      self._file_label.setText("File: -")
      self._sample_channels = {}
      self._table.setRowCount(0)
      self._parameter_table.setRowCount(0)
      return
    self._sample_label.setText(f"Sample: {sample.name} ({sample.id})")
    self._status_label.setText(
      f"Channel status: {getattr(sample, 'status', 'match')}"
    )
    self._file_label.setText(f"File: {sample.path or '-'}")
    self._sample_channels = {channel.id: channel for channel in sample.info.channels}
    self._populate_catalog()

  def set_parameter_catalog(self, catalog: tuple[ParameterCatalogEntry, ...]) -> None:
    """Display catalog provenance without evaluating parameter expressions in Qt."""
    self._catalog = tuple(catalog)
    self._populate_catalog()

  def set_project_parameter_mappings(
    self, mappings: tuple[dict[str, Any], ...] | list[dict[str, Any]],
  ) -> None:
    """Display project-wide label mappings and preserve stable parameter IDs."""
    self._updating_project_table = True
    try:
      self._table.setSortingEnabled(False)
      self._table.setRowCount(len(mappings))
      for row, mapping in enumerate(mappings):
        parameter_id = str(mapping.get("parameter_id", ""))
        actual = str(mapping.get("actual_parameter", parameter_id))
        values = (
          actual,
          str(mapping.get("plot_label", "")),
          str(mapping.get("annotation", "")),
          str(mapping.get("sample_count", "")),
        )
        for column, value in enumerate(values):
          item = QTableWidgetItem(value)
          if column == 0:
            item.setData(Qt.ItemDataRole.UserRole, parameter_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
          elif column == 3:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
          self._table.setItem(row, column, item)
    finally:
      self._updating_project_table = False
      self._table.setSortingEnabled(True)

  def _populate_catalog(self) -> None:
    catalog = self._catalog
    self._parameter_table.setSortingEnabled(False)
    self._parameter_table.setRowCount(len(catalog))
    for row, entry in enumerate(catalog):
      source = entry.source_stage
      if entry.definition_id:
        source = f"{source} ({entry.definition_id})"
      diagnostic_text = "; ".join(
        f"{diagnostic.code}: {diagnostic.message}"
        for diagnostic in entry.diagnostics
      )
      channel = self._sample_channels.get(entry.parameter_id)
      metadata = getattr(channel, "metadata", {}) if channel is not None else {}
      values = (
        entry.selector_label,
        entry.kind,
        source,
        entry.expression or "",
        entry.unit or "",
        entry.availability,
        entry.parameter_id,
        getattr(channel, "name", "") if channel is not None else "",
        getattr(channel, "short_name", "") if channel is not None else "",
        getattr(channel, "detector", "") if channel is not None else "",
        getattr(channel, "stain", "") if channel is not None else "",
        getattr(channel, "unit", "") if channel is not None else "",
        getattr(channel, "fcs_parameter_index", "") if channel is not None else "",
        metadata.get("png", ""), metadata.get("pne", ""), metadata.get("pnr", ""),
      )
      for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        if diagnostic_text:
          item.setToolTip(diagnostic_text)
        self._parameter_table.setItem(row, column, item)
    self._parameter_table.setSortingEnabled(True)

  def set_column_visible(self, key: str, visible: bool) -> None:
    """Show or hide one metadata column by stable key."""
    column = next(
      (index for index, (name, _label) in enumerate(_CHANNEL_COLUMNS) if name == key),
      -1,
    )
    if column < 0:
      raise KeyError(key)
    self._parameter_table.setColumnHidden(6 + column, not visible)
    action = self._column_actions.get(key)
    if action is not None and action.isChecked() != visible:
      action.setChecked(visible)

  def _on_project_mapping_cell_changed(self, row: int, column: int) -> None:
    if self._updating_project_table or column not in {1, 2}:
      return
    item = self._table.item(row, 0)
    edited = self._table.item(row, column)
    if item is None or edited is None:
      return
    self.project_mapping_changed.emit({
      "parameter_id": str(item.data(Qt.ItemDataRole.UserRole) or ""),
      "plot_label": self._table.item(row, 1).text().strip(),
      "annotation": self._table.item(row, 2).text().strip(),
    })
