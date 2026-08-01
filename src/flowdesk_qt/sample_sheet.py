"""Excel-like, non-destructive sample title editor."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import (
  QAbstractTableModel,
  QModelIndex,
  QSortFilterProxyModel,
  Qt,
)
from PySide6.QtWidgets import (
  QApplication,
  QDialog,
  QDialogButtonBox,
  QFileDialog,
  QHBoxLayout,
  QInputDialog,
  QLineEdit,
  QMessageBox,
  QPushButton,
  QTableView,
  QVBoxLayout,
)

from flowdesk_core.annotations import (
  annotation_columns,
  annotation_table,
  parse_annotation_csv,
  resolve_sample_title,
  set_sample_title,
)
from flowdesk_core.models import AnnotationSpec

logger = logging.getLogger(__name__)


class SampleSheetModel(QAbstractTableModel):
  """One non-destructive sheet for titles and workspace annotations."""

  BASE_HEADERS = ("Sample ID", "File", "Sample name", "Title")

  def __init__(
    self,
    samples: Sequence[dict[str, Any]],
    annotations: Sequence[dict[str, Any] | AnnotationSpec],
    parent=None,
  ) -> None:
    super().__init__(parent)
    self._samples = tuple(dict(sample) for sample in samples)
    self._annotations = _to_specs(annotations)
    self._annotation_columns = tuple(
      value for value in annotation_columns(self._annotations)
      if value != "sample_title"
    )
    self._undo: list[tuple[AnnotationSpec, ...]] = []
    self._redo: list[tuple[AnnotationSpec, ...]] = []

  def rowCount(self, parent: QModelIndex | None = None) -> int:
    return 0 if parent is not None and parent.isValid() else len(self._samples)

  def columnCount(self, parent: QModelIndex | None = None) -> int:
    return 0 if parent is not None and parent.isValid() else len(self.headers)

  @property
  def headers(self) -> tuple[str, ...]:
    return self.BASE_HEADERS + self._annotation_columns

  def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
    if role != Qt.ItemDataRole.DisplayRole:
      return None
    if orientation == Qt.Orientation.Horizontal:
      return self.headers[section]
    return section + 1

  def flags(self, index: QModelIndex):
    flags = super().flags(index)
    if index.isValid() and index.column() == 3:
      return flags | Qt.ItemFlag.ItemIsEditable
    if index.isValid() and index.column() >= len(self.BASE_HEADERS):
      keyword = self.headers[index.column()]
      sample_id = str(self._samples[index.row()].get("id", ""))
      if not self._has_fcs_value(sample_id, keyword):
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
    values: tuple[Any, ...] = (
      str(sample.get("id", "")),
      str(sample.get("path", "")),
      str(sample.get("name", "")),
      title,
    ) + tuple(
      self._annotation_value(str(sample.get("id", "")), keyword)
      for keyword in self._annotation_columns
    )
    if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
      return values[index.column()]
    if role == Qt.ItemDataRole.ToolTipRole:
      if index.column() == 0:
        return "Stable sample identity; editing Title never changes this value."
      if index.column() >= len(self.BASE_HEADERS):
        keyword = self.headers[index.column()]
        sample_id = str(sample.get("id", ""))
        if self._has_fcs_value(sample_id, keyword):
          return "FCS-derived keyword (read-only). Add a workspace column to override it."
    return None

  def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):
    if (
      role != Qt.ItemDataRole.EditRole
      or not index.isValid()
      or index.column() < 3
    ):
      return False
    sample_id = str(self._samples[index.row()].get("id", ""))
    self._remember()
    if index.column() == 3:
      self._annotations = set_sample_title(
        self._annotations, sample_id, str(value) if value is not None else ""
      )
    else:
      keyword = self.headers[index.column()]
      self._annotations = tuple(
        item for item in self._annotations
        if not (
          item.sample_id == sample_id
          and item.keyword == keyword
          and item.source == "workspace"
        )
      ) + (AnnotationSpec(sample_id, keyword, value, "workspace"),)
    self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
    return True

  def paste_tsv(self, text: str, start_row: int = 0) -> None:
    """Paste a two-column Excel/TSV selection into the title column.

    The first column may contain a stable sample ID or an exact, unique sample
    name; the second column is the title. Rows are validated before any
    mutation so a malformed paste cannot shift or partially overwrite later
    rows.
    """
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
      return
    if len(rows[0]) >= 2 and rows[0][0].strip().lower() in {
      "sample id", "sample_id", "sample name", "sample_name", "name",
    }:
      rows = rows[1:]
    known_ids = {str(sample.get("id", "")) for sample in self._samples}
    names: dict[str, list[str]] = {}
    for sample in self._samples:
      name = str(sample.get("name", "")).strip()
      if name:
        names.setdefault(name, []).append(str(sample.get("id", "")))
    updates: list[tuple[str, str]] = []
    for row_index, row in enumerate(rows, start=1):
      if len(row) < 2 or not row[0].strip():
        raise ValueError(f"paste row {row_index} must contain sample ID and title")
      key = row[0].strip()
      if key in known_ids:
        sample_id = key
      elif len(names.get(key, [])) == 1:
        sample_id = names[key][0]
      elif names.get(key):
        raise ValueError(f"paste row {row_index} references ambiguous sample name {key!r}")
      else:
        raise ValueError(f"paste row {row_index} references unknown sample ID or name {key!r}")
      updates.append((sample_id, row[1]))
    if len({sample_id for sample_id, _title in updates}) != len(updates):
      raise ValueError("paste contains duplicate sample IDs")
    self._remember()
    self.beginResetModel()
    for sample_id, title in updates:
      self._annotations = set_sample_title(self._annotations, sample_id, title)
    self.endResetModel()

  def fill_title_series(self, prefix: str, start: int, step: int = 1) -> None:
    """Set deterministic titles such as ``prefix 1``, ``prefix 2``."""
    self._remember()
    self.beginResetModel()
    for index, sample in enumerate(self._samples):
      self._annotations = set_sample_title(
        self._annotations,
        str(sample.get("id", "")),
        f"{prefix}{start + index * step}",
      )
    self.endResetModel()

  def import_csv_text(self, text: str) -> None:
    """Validate and merge CSV annotations before changing the table state."""
    imported = parse_annotation_csv(text)
    known = {str(sample.get("id", "")) for sample in self._samples}
    unknown = sorted({item.sample_id for item in imported} - known)
    if unknown:
      raise ValueError(f"CSV references unknown samples: {unknown!r}")
    self.beginResetModel()
    self._remember()
    self._annotations = self._annotations + tuple(imported)
    self._annotation_columns = tuple(
      value for value in annotation_columns(self._annotations)
      if value != "sample_title"
      )
    self.endResetModel()

  def replace_text(self, old: str, new: str) -> None:
    """Replace text in editable titles/annotations as one undoable change."""
    if not old:
      return
    self._remember()
    self.beginResetModel()
    self._annotations = tuple(
      AnnotationSpec(
        sample_id=item.sample_id,
        keyword=item.keyword,
        value=(
          str(item.value).replace(old, new)
          if item.source != "fcs" and item.value is not None
          else item.value
        ),
        source=item.source,
      )
      for item in self._annotations
    )
    self.endResetModel()

  def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
    """Sort rows by display value while retaining stable IDs and annotations."""
    if column < 0 or column >= len(self.headers):
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
    self.beginResetModel()
    self._annotations = self._undo.pop()
    self.endResetModel()
    return True

  def redo(self) -> bool:
    if not self._redo:
      return False
    self._undo.append(self._annotations)
    self.beginResetModel()
    self._annotations = self._redo.pop()
    self.endResetModel()
    return True

  def data_for_sample(self, sample: dict[str, Any], column: int) -> str:
    values: tuple[Any, ...] = (
      str(sample.get("id", "")),
      str(sample.get("path", "")),
      str(sample.get("name", "")),
      resolve_sample_title(
        str(sample.get("id", "")), str(sample.get("name", "")),
        str(sample.get("path", "")), self._annotations,
      ),
    ) + tuple(
      self._annotation_value(str(sample.get("id", "")), keyword)
      for keyword in self._annotation_columns
    )
    return str(values[column])

  def add_annotation_column(self, keyword: str) -> None:
    """Add an editable workspace/imported annotation column without FCS mutation."""
    normalized = keyword.strip()
    if not normalized:
      raise ValueError("annotation column name must be non-empty")
    if normalized in self.headers:
      raise ValueError(f"annotation column already exists: {normalized!r}")
    self.beginResetModel()
    self._annotation_columns += (normalized,)
    self.endResetModel()

  def _annotation_value(self, sample_id: str, keyword: str) -> Any:
    rows = annotation_table((sample_id,), self._annotations)
    return rows[0].get(keyword) if rows else None

  def _has_fcs_value(self, sample_id: str, keyword: str) -> bool:
    return any(
      item.sample_id == sample_id and item.keyword == keyword and item.source == "fcs"
      for item in self._annotations
    )

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
    add_column = QPushButton("Add Annotation Column…")
    add_column.setObjectName("sampleSheetAddAnnotationColumnButton")
    add_column.clicked.connect(self._on_add_annotation_column)
    self._columns_button = add_column
    paste = QPushButton("Paste")
    paste.setObjectName("sampleSheetPasteButton")
    paste.clicked.connect(self._on_paste)
    import_csv = QPushButton("Import CSV…")
    import_csv.setObjectName("sampleSheetImportCsvButton")
    import_csv.clicked.connect(self._on_import_csv)
    fill = QPushButton("Fill Titles…")
    fill.setObjectName("sampleSheetFillSeriesButton")
    fill.clicked.connect(self._on_fill_titles)
    replace = QPushButton("Find/Replace…")
    replace.setObjectName("sampleSheetFindReplaceButton")
    replace.clicked.connect(self._on_replace)
    undo = QPushButton("Undo")
    undo.setObjectName("sampleSheetUndoButton")
    undo.clicked.connect(self._model.undo)
    redo = QPushButton("Redo")
    redo.setObjectName("sampleSheetRedoButton")
    redo.clicked.connect(self._model.redo)
    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("sampleSheetDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    layout = QVBoxLayout(self)
    layout.addWidget(self._filter_edit)
    actions = QHBoxLayout()
    actions.addWidget(add_column)
    actions.addWidget(paste)
    actions.addWidget(import_csv)
    actions.addWidget(fill)
    actions.addWidget(replace)
    actions.addWidget(undo)
    actions.addWidget(redo)
    actions.addStretch(1)
    layout.addLayout(actions)
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

  def _on_add_annotation_column(self) -> None:
    keyword, accepted = QInputDialog.getText(
      self, "Add Annotation Column", "Column name:"
    )
    if not accepted:
      return
    try:
      self._model.add_annotation_column(keyword)
    except ValueError:
      return

  def _on_paste(self) -> None:
    clipboard = QApplication.clipboard()
    try:
      mime = clipboard.mimeData()
      text = clipboard.text()
      logger.info(
        "Sample Sheet paste requested: formats=%s text_length=%d lines=%d",
        list(mime.formats()) if mime is not None else [],
        len(text),
        text.count("\n") + (1 if text else 0),
      )
      self._model.paste_tsv(text)
    except Exception as exc:
      logger.exception("Sample Sheet paste failed")
      QMessageBox.warning(self, "Paste failed", str(exc))

  def _on_import_csv(self) -> None:
    path, _ = QFileDialog.getOpenFileName(
      self, "Import Sample Annotations", "", "CSV files (*.csv);;All files (*)"
    )
    if not path:
      return
    with open(path, encoding="utf-8", newline="") as handle:
      self._model.import_csv_text(handle.read())

  def _on_fill_titles(self) -> None:
    prefix, accepted = QInputDialog.getText(self, "Fill Titles", "Prefix:")
    if accepted and prefix:
      self._model.fill_title_series(prefix, 1)

  def _on_replace(self) -> None:
    old, accepted = QInputDialog.getText(self, "Find/Replace", "Find:")
    if not accepted or not old:
      return
    new, accepted = QInputDialog.getText(self, "Find/Replace", "Replace with:")
    if accepted:
      self._model.replace_text(old, new)


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
