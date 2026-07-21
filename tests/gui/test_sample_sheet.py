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
