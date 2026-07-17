"""Read-only channel metadata workspace for the selected sample."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
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
  """Inspect channel identity and FCS metadata without editing analysis state."""

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("channelMetadataWorkspace")
    self._sample: Any | None = None

    self._sample_label = QLabel("Sample: -")
    self._sample_label.setObjectName("channelMetadataSampleLabel")
    self._status_label = QLabel("Channel status: -")
    self._status_label.setObjectName("channelMetadataStatusLabel")
    self._file_label = QLabel("File: -")
    self._file_label.setObjectName("channelMetadataFileLabel")
    self._file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    self._table = QTableWidget()
    self._table.setObjectName("channelMetadataTable")
    self._table.setColumnCount(len(_CHANNEL_COLUMNS))
    self._table.setHorizontalHeaderLabels([label for _, label in _CHANNEL_COLUMNS])
    self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self._table.setSortingEnabled(True)

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
    for key, _label in _CHANNEL_COLUMNS:
      self.set_column_visible(key, key in _DEFAULT_COLUMNS)

    header = QHBoxLayout()
    header.addWidget(QLabel("Channel Metadata"))
    header.addStretch(1)
    header.addWidget(self._column_button)

    info = QVBoxLayout()
    info.addWidget(self._sample_label)
    info.addWidget(self._status_label)
    info.addWidget(self._file_label)

    layout = QVBoxLayout(self)
    layout.addLayout(header)
    layout.addLayout(info)
    layout.addWidget(self._table)

  @property
  def table(self) -> QTableWidget:
    """Expose the table for accessibility and GUI regression tests."""
    return self._table

  def set_sample(self, sample: Any | None) -> None:
    """Display metadata for a SampleBrowser sample or clear the workspace."""
    self._sample = sample
    if sample is None:
      self._sample_label.setText("Sample: -")
      self._status_label.setText("Channel status: -")
      self._file_label.setText("File: -")
      self._table.setRowCount(0)
      return
    self._sample_label.setText(f"Sample: {sample.name} ({sample.id})")
    self._status_label.setText(f"Channel status: {sample.status}")
    self._file_label.setText(f"File: {sample.path or '-'}")
    self._populate(sample.info)

  def set_column_visible(self, key: str, visible: bool) -> None:
    """Show or hide one metadata column by stable key."""
    column = next(
      (index for index, (name, _label) in enumerate(_CHANNEL_COLUMNS) if name == key),
      -1,
    )
    if column < 0:
      raise KeyError(key)
    self._table.setColumnHidden(column, not visible)
    action = self._column_actions.get(key)
    if action is not None and action.isChecked() != visible:
      action.setChecked(visible)

  def _populate(self, info: Any) -> None:
    self._table.setSortingEnabled(False)
    self._table.setRowCount(len(info.channels))
    for row, channel in enumerate(info.channels):
      values = (
        channel.id,
        channel.name,
        channel.short_name,
        channel.detector,
        channel.stain,
        channel.unit,
        channel.fcs_parameter_index,
        channel.metadata.get("png", ""),
        channel.metadata.get("pne", ""),
        channel.metadata.get("pnr", ""),
      )
      for column, value in enumerate(values):
        self._table.setItem(
          row,
          column,
          QTableWidgetItem("" if value is None else str(value)),
        )
    self._table.setSortingEnabled(True)
