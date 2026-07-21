"""Excel-like, non-destructive sample title editor."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTableView, QVBoxLayout

from flowdesk_core.annotations import (
  resolve_sample_title,
  set_sample_title,
)
from flowdesk_core.models import AnnotationSpec


class SampleSheetModel(QAbstractTableModel):
  """Table model exposing stable sample identity and editable display title."""

  HEADERS = ("Sample ID", "File", "Sample name", "Title")

  def __init__(
    self,
    samples: Sequence[dict[str, Any]],
    annotations: Sequence[dict[str, Any] | AnnotationSpec],
    parent=None,
  ) -> None:
    super().__init__(parent)
    self._samples = tuple(dict(sample) for sample in samples)
    self._annotations = _to_specs(annotations)

  def rowCount(self, parent: QModelIndex | None = None) -> int:
    return 0 if parent is not None and parent.isValid() else len(self._samples)

  def columnCount(self, parent: QModelIndex | None = None) -> int:
    return 0 if parent is not None and parent.isValid() else len(self.HEADERS)

  def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
    if role != Qt.ItemDataRole.DisplayRole:
      return None
    if orientation == Qt.Orientation.Horizontal:
      return self.HEADERS[section]
    return section + 1

  def flags(self, index: QModelIndex):
    flags = super().flags(index)
    if index.isValid() and index.column() == 3:
      return flags | Qt.ItemFlag.ItemIsEditable
    return flags & ~Qt.ItemFlag.ItemIsEditable

  def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
    if not index.isValid() or not (0 <= index.row() < len(self._samples)):
      return None
    sample = self._samples[index.row()]
    title = resolve_sample_title(
      str(sample.get("id", "")),
      str(sample.get("name", "")),
      str(sample.get("path", "")),
      self._annotations,
    )
    values = (
      str(sample.get("id", "")),
      str(sample.get("path", "")),
      str(sample.get("name", "")),
      title,
    )
    if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
      return values[index.column()]
    if role == Qt.ItemDataRole.ToolTipRole and index.column() == 0:
      return "Stable sample identity; editing Title never changes this value."
    return None

  def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):
    if (
      role != Qt.ItemDataRole.EditRole
      or not index.isValid()
      or index.column() != 3
    ):
      return False
    sample_id = str(self._samples[index.row()].get("id", ""))
    self._annotations = set_sample_title(
      self._annotations, sample_id, str(value) if value is not None else ""
    )
    self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
    return True

  def annotations(self) -> list[dict[str, Any]]:
    return [
      {
        "sample_id": value.sample_id,
        "keyword": value.keyword,
        "value": value.value,
        "source": value.source,
      }
      for value in self._annotations
    ]


class SampleSheetDialog(QDialog):
  """Dialog for editing sample titles with a real Qt model/view table."""

  def __init__(
    self,
    samples: Sequence[dict[str, Any]],
    annotations: Sequence[dict[str, Any] | AnnotationSpec],
    parent=None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("sampleSheetDialog")
    self.setWindowTitle("Sample Sheet")
    self.resize(900, 480)
    self._model = SampleSheetModel(samples, annotations, self)
    self._table = QTableView()
    self._table.setObjectName("sampleSheetTable")
    self._table.setModel(self._model)
    self._table.setAlternatingRowColors(True)
    self._table.setSortingEnabled(False)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("sampleSheetDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    layout = QVBoxLayout(self)
    layout.addWidget(self._table)
    layout.addWidget(buttons)

  def annotations(self) -> list[dict[str, Any]]:
    return self._model.annotations()


def _to_specs(
  values: Iterable[dict[str, Any] | AnnotationSpec],
) -> tuple[AnnotationSpec, ...]:
  result: list[AnnotationSpec] = []
  for value in values:
    if isinstance(value, AnnotationSpec):
      result.append(value)
    else:
      result.append(
        AnnotationSpec(
          sample_id=str(value["sample_id"]),
          keyword=str(value["keyword"]),
          value=value.get("value"),
          source=value["source"],
        )
      )
  return tuple(result)
