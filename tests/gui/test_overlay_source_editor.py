from __future__ import annotations

from copy import deepcopy

import pytest

from flowdesk_qt.overlay_source_editor import OverlaySourceEditorDialog

pytestmark = pytest.mark.gui


def _samples() -> list[dict[str, object]]:
  return [{
    "id": "s1", "name": "Sample 1", "channels": [
      {"id": "x", "name": "X"}, {"id": "y", "name": "Y"},
    ],
  }, {
    "id": "s2", "name": "Sample 2", "channels": [
      {"id": "y", "name": "Y"}, {"id": "x", "name": "X"},
    ],
  }]


def test_editor_add_reorder_visibility_and_basic_style(qapp) -> None:
  statuses: list[list[dict[str, object]]] = []

  def resolve(sources: list[dict[str, object]]) -> dict[str, tuple[str, tuple[str, ...]]]:
    statuses.append(deepcopy(sources))
    return {
      str(source["source_id"]): ("compatible", ())
      for source in sources
    }

  dialog = OverlaySourceEditorDialog(
    _samples(), ("all_events", "cd3"),
    ({"id": "linear-x", "name": "Linear X", "parameter": "x"},),
    status_resolver=resolve,
  )
  try:
    dialog._add_button.click()
    assert dialog._source_list.count() == 1
    dialog._legend_edit.setText("Control")
    dialog._color_edit.setText("#ff0000")
    dialog._alpha_spin.setValue(0.4)
    dialog._visible_check.setChecked(False)
    assert dialog._accept() is None
    assert dialog.sources()[0]["visible"] is False
    assert dialog.sources()[0]["style"]["legend_label"] == "Control"
    assert dialog.sources()[0]["style"]["alpha"] == 0.4
    assert statuses
    assert dialog._status_label.text().startswith("Status: compatible")
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_editor_keeps_hidden_invalid_source_for_repair(qapp) -> None:
  source = {
    "source_id": "missing", "sample_id": "not-loaded", "population_id": "cd3",
    "display_name": "Missing", "x_parameter_id": "x", "order": 0,
    "visible": False,
  }
  dialog = OverlaySourceEditorDialog(
    _samples(), ("all_events",), (), (source,),
    status_resolver=lambda _sources: {"missing": ("missing", ("sample is missing",))},
  )
  try:
    assert dialog._source_list.item(0).text().startswith("[missing]")
    assert "sample is missing" in dialog._status_label.text()
    assert dialog.sources()[0]["visible"] is False
  finally:
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()
