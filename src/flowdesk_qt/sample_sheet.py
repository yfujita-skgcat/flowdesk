"""Excel-like, non-destructive sample title editor."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import (
  QAbstractTableModel,
  QModelIndex,
  QSortFilterProxyModel,
  Qt,
)
from PySide6.QtWidgets import (
  QDialog,
  QDialogButtonBox,
  QLineEdit,
  QTableView,
  QVBoxLayout,
)

from flowdesk_core.annotations import (
  parse_annotation_csv,
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
    self._undo: list[tuple[AnnotationSpec, ...]] = []
    self._redo: list[tuple[AnnotationSpec, ...]] = []

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
    self._remember()
    self._annotations = set_sample_title(
      self._annotations, sample_id, str(value) if value is not None else ""
    )
    self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
    return True

  def paste_tsv(self, text: str, start_row: int = 0) -> None:
    """Paste a two-column Excel/TSV selection into the title column.

    The first column must be a known stable sample ID and the second column is
    the title.  Rows are validated before any mutation so a malformed paste
    cannot shift or partially overwrite later rows.
    """
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
      return
    if len(rows[0]) >= 2 and rows[0][0].strip().lower() in {"sample id", "sample_id"}:
      rows = rows[1:]
    known = {str(sample.get("id", "")): index for index, sample in enumerate(self._samples)}
    updates: list[tuple[str, str]] = []
    for row_index, row in enumerate(rows, start=1):
      if len(row) < 2 or not row[0].strip():
        raise ValueError(f"paste row {row_index} must contain sample ID and title")
      sample_id = row[0].strip()
      if sample_id not in known:
        raise ValueError(f"paste row {row_index} references unknown sample {sample_id!r}")
      updates.append((sample_id, row[1]))
    if len({sample_id for sample_id, _title in updates}) != len(updates):
      raise ValueError("paste contains duplicate sample IDs")
    self._remember()
    for sample_id, title in updates:
      self._annotations = set_sample_title(self._annotations, sample_id, title)
    self.layoutChanged.emit()

  def fill_title_series(self, prefix: str, start: int, step: int = 1) -> None:
    """Set deterministic titles such as ``prefix 1``, ``prefix 2``."""
    self._remember()
    for index, sample in enumerate(self._samples):
      self._annotations = set_sample_title(
        self._annotations,
        str(sample.get("id", "")),
        f"{prefix}{start + index * step}",
      )
    self.layoutChanged.emit()

  def import_csv_text(self, text: str) -> None:
    """Validate and merge CSV annotations before changing the table state."""
    imported = parse_annotation_csv(text)
    known = {str(sample.get("id", "")) for sample in self._samples}
    unknown = sorted({item.sample_id for item in imported} - known)
    if unknown:
      raise ValueError(f"CSV references unknown samples: {unknown!r}")
    self._remember()
    self._annotations = self._annotations + tuple(imported)
    self.layoutChanged.emit()

  def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
    """Sort rows by display value while retaining stable IDs and annotations."""
    if column < 0 or column >= len(self.HEADERS):
      return
    reverse = order == Qt.SortOrder.DescendingOrder
    self.layoutAboutToBeChanged.emit()
    self._samples = tuple(sorted(
      self._samples,
      key=lambda sample: str(self.data_for_sample(sample, column)).casefold(),
      reverse=reverse,
    ))
    self.layoutChanged.emit()

  def undo(self) -> bool:
    if not self._undo:
      return False
    self._redo.append(self._annotations)
    self._annotations = self._undo.pop()
    self.layoutChanged.emit()
    return True

  def redo(self) -> bool:
    if not self._redo:
      return False
    self._undo.append(self._annotations)
    self._annotations = self._redo.pop()
    self.layoutChanged.emit()
    return True

  def data_for_sample(self, sample: dict[str, Any], column: int) -> str:
    return (
      str(sample.get("id", "")),
      str(sample.get("path", "")),
      str(sample.get("name", "")),
      resolve_sample_title(
        str(sample.get("id", "")), str(sample.get("name", "")),
        str(sample.get("path", "")), self._annotations,
      ),
    )[column]

  def _remember(self) -> None:
    self._undo.append(self._annotations)
    self._redo.clear()

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
    self._filter_edit = QLineEdit()
    self._filter_edit.setObjectName("sampleSheetFilterEdit")
    self._filter_edit.setPlaceholderText("Filter samples...")
    self._table = QTableView()
    self._table.setObjectName("sampleSheetTable")
    self._proxy = QSortFilterProxyModel(self)
    self._proxy.setSourceModel(self._model)
    self._proxy.setFilterKeyColumn(-1)
    self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    self._table.setModel(self._proxy)
    self._table.setAlternatingRowColors(True)
    self._table.setSortingEnabled(True)
    self._table.horizontalHeader().setSortIndicatorShown(True)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("sampleSheetDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    layout = QVBoxLayout(self)
    layout.addWidget(self._filter_edit)
    layout.addWidget(self._table)
    layout.addWidget(buttons)
    self._filter_edit.textChanged.connect(self._proxy.setFilterFixedString)

  def annotations(self) -> list[dict[str, Any]]:
    return self._model.annotations()

  def paste_clipboard_text(self, text: str) -> None:
    self._model.paste_tsv(text)

  def fill_title_series(self, prefix: str, start: int, step: int = 1) -> None:
    self._model.fill_title_series(prefix, start, step)

  def import_csv_text(self, text: str) -> None:
    self._model.import_csv_text(text)

  def undo(self) -> bool:
    return self._model.undo()

  def redo(self) -> bool:
    return self._model.redo()


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
