"""Qt editor for project-side sample annotations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtWidgets import (
  QDialog,
  QDialogButtonBox,
  QTableWidget,
  QTableWidgetItem,
  QVBoxLayout,
)

from flowdesk_core.annotations import (
  annotation_columns,
  annotation_table,
  fill_annotation_series,
  parse_annotation_csv,
  replace_annotation_values,
)
from flowdesk_core.models import AnnotationSpec


class AnnotationEditorDialog(QDialog):
  """Edit annotations as a sample-by-keyword table."""

  def __init__(
    self,
    sample_ids: Sequence[str],
    annotations: Sequence[dict[str, Any]],
    parent=None,
  ) -> None:
    super().__init__(parent)
    self.setObjectName("annotationEditorDialog")
    self.setWindowTitle("Sample Annotations")
    self.resize(720, 420)
    self._sample_ids = tuple(sample_ids)
    self._annotations = _to_specs(annotations)
    self._table = QTableWidget()
    self._table.setObjectName("annotationTable")
    self._table.itemChanged.connect(self._on_item_changed)
    self._build_table()

    buttons = QDialogButtonBox(
      QDialogButtonBox.StandardButton.Ok
      | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.setObjectName("annotationDialogButtons")
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    layout = QVBoxLayout(self)
    layout.addWidget(self._table)
    layout.addWidget(buttons)

  def annotations(self) -> list[dict[str, Any]]:
    """Return serializable annotation definitions."""
    return [
      {
        "sample_id": item.sample_id,
        "keyword": item.keyword,
        "value": item.value,
        "source": item.source,
      }
      for item in self._annotations
    ]

  def import_csv_text(self, text: str) -> None:
    """Import CSV text through the same typed core parser used by CLI code."""
    self._annotations = list(self._annotations) + list(parse_annotation_csv(text))
    self._build_table()

  def replace_value(self, keyword: str, old: Any, new: Any) -> None:
    self._annotations = list(
      replace_annotation_values(self._annotations, keyword, old, new)
    )
    self._build_table()

  def fill_series(self, keyword: str, start: float, step: float = 1) -> None:
    self._annotations = list(self._annotations) + list(
      fill_annotation_series(self._sample_ids, keyword, start, step)
    )
    self._build_table()

  def _build_table(self) -> None:
    columns = annotation_columns(self._annotations)
    rows = annotation_table(self._sample_ids, self._annotations)
    self._table.blockSignals(True)
    self._table.setRowCount(len(rows))
    self._table.setColumnCount(len(columns) + 1)
    self._table.setHorizontalHeaderLabels(["sample_id", *columns])
    for row_index, row in enumerate(rows):
      sample_item = QTableWidgetItem(str(row["sample_id"]))
      sample_item.setFlags(sample_item.flags() & ~sample_item.flags().ItemIsEditable)
      self._table.setItem(row_index, 0, sample_item)
      for column_index, keyword in enumerate(columns, start=1):
        value = row.get(keyword)
        self._table.setItem(
          row_index,
          column_index,
          QTableWidgetItem("" if value is None else str(value)),
        )
    self._table.blockSignals(False)

  def _on_item_changed(self, item: QTableWidgetItem) -> None:
    if item.column() == 0:
      return
    keyword = self._table.horizontalHeaderItem(item.column()).text()
    sample_id = self._table.item(item.row(), 0).text()
    value = item.text()
    self._annotations.append(AnnotationSpec(sample_id, keyword, value, "workspace"))


def _to_specs(values: Sequence[dict[str, Any]]) -> tuple[AnnotationSpec, ...]:
  return tuple(
    AnnotationSpec(
      sample_id=str(value["sample_id"]),
      keyword=str(value["keyword"]),
      value=value.get("value"),
      source=value["source"],
    )
    for value in values
  )
