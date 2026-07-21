from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from flowdesk_qt.sample_sheet import SampleSheetDialog, SampleSheetModel

pytestmark = pytest.mark.gui


def test_sample_sheet_model_edits_only_workspace_title(qapp) -> None:
  model = SampleSheetModel(
    [
      {"id": "s1", "name": "Original", "path": "/tmp/one.fcs"},
      {"id": "s2", "name": "Second", "path": "/tmp/two.fcs"},
    ],
    [{"sample_id": "s1", "keyword": "Condition", "value": "treated", "source": "fcs"}],
  )
  assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "Original"
  assert model.setData(model.index(0, 3), "Treatment A")
  assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "Treatment A"
  values = model.annotations()
  assert any(item["keyword"] == "Condition" for item in values)
  assert any(
    item["keyword"] == "sample_title" and item["value"] == "Treatment A"
    for item in values
  )


def test_sample_sheet_dialog_cancel_keeps_original_annotations(qapp) -> None:
  original = [{
    "sample_id": "s1",
    "keyword": "sample_title",
    "value": "Before",
    "source": "workspace",
  }]
  dialog = SampleSheetDialog(
    [{"id": "s1", "name": "Sample", "path": "/tmp/sample.fcs"}], original
  )
  dialog._model.setData(dialog._model.index(0, 3), "After")
  assert original[0]["value"] == "Before"
  dialog.reject()


def test_sample_sheet_paste_fill_sort_and_undo(qapp) -> None:
  model = SampleSheetModel(
    [
      {"id": "s1", "name": "B", "path": "/tmp/b.fcs"},
      {"id": "s2", "name": "A", "path": "/tmp/a.fcs"},
    ], [],
  )
  model.paste_tsv("Sample ID\tTitle\ns1\tOne\ns2\tTwo\n")
  assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "One"
  model.fill_title_series("Rep ", 1)
  assert model.data(model.index(1, 3), Qt.ItemDataRole.DisplayRole) == "Rep 2"
  assert model.undo()
  assert model.data(model.index(1, 3), Qt.ItemDataRole.DisplayRole) == "Two"
  model.sort(2, Qt.SortOrder.AscendingOrder)
  assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "s2"
  with pytest.raises(ValueError, match="unknown sample"):
    model.paste_tsv("s3\tBad\n")


def test_sample_sheet_csv_preview_validates_sample_ids(qapp) -> None:
  dialog = SampleSheetDialog(
    [{"id": "s1", "name": "Sample", "path": "/tmp/sample.fcs"}], [],
  )
  dialog.import_csv_text("sample_id,Condition\ns1,treated\n")
  assert any(item["keyword"] == "Condition" for item in dialog.annotations())
  with pytest.raises(ValueError, match="unknown samples"):
    dialog.import_csv_text("sample_id,Condition\ns2,bad\n")
  dialog.reject()


def test_sample_sheet_filter_is_case_insensitive_and_non_destructive(qapp) -> None:
  dialog = SampleSheetDialog(
    [
      {"id": "s1", "name": "Control", "path": "/tmp/control.fcs"},
      {"id": "s2", "name": "Treated", "path": "/tmp/treated.fcs"},
    ], [],
  )
  dialog._filter_edit.setText("treated")
  assert dialog._proxy.rowCount() == 1
  assert dialog._proxy.data(dialog._proxy.index(0, 0)) == "s2"
  assert len(dialog.annotations()) == 0
  dialog.reject()
