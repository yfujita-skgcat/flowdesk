"""GUI consumers of the shared acquired-plus-derived Parameter Catalog."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.parameter_catalog import (
  ParameterCatalogDiagnostic,
  ParameterCatalogEntry,
)
from flowdesk_qt.channel_metadata import ChannelMetadataWorkspace
from flowdesk_qt.channel_selector import ChannelSelector
from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.statistics_editor import StatisticsEditorDialog
from flowdesk_qt.transform_editor import TransformEditorDialog

pytestmark = pytest.mark.gui


def _catalog() -> tuple[ParameterCatalogEntry, ...]:
  return (
    ParameterCatalogEntry(
      parameter_id="FL1-A", display_name="FL1-A", kind="acquired", unit="a.u.",
      source_stage="raw",
    ),
    ParameterCatalogEntry(
      parameter_id="ratio", display_name="FL1 / FL2", kind="derived", unit="ratio",
      source_stage="compensated", definition_id="ratio-definition",
      expression="FL1-A / FL2-A", input_parameter_ids=("FL1-A", "FL2-A"),
      availability="not_run",
    ),
    ParameterCatalogEntry(
      parameter_id="broken", display_name="Broken", kind="derived", unit=None,
      source_stage="compensated", definition_id="broken-definition",
      expression="FL1-A / missing", availability="missing_input",
      diagnostics=(ParameterCatalogDiagnostic(
        code="unknown_derived_input", message="missing input: missing"
      ),),
    ),
  )


def _item_enabled(combo: QComboBox, parameter_id: str) -> bool:
  index = combo.findData(parameter_id)
  assert index >= 0
  item = combo.model().item(index)
  assert item is not None
  return item.isEnabled()


def test_catalog_is_visible_but_derived_axes_wait_for_processed_display(qapp) -> None:
  selector = ChannelSelector()
  try:
    selector.set_parameter_catalog(_catalog())
    assert selector._x_combo.findData("ratio") >= 0
    assert not _item_enabled(selector._x_combo, "ratio")
    assert not _item_enabled(selector._x_combo, "broken")
    assert "not_run" in selector._x_combo.itemData(
      selector._x_combo.findData("ratio"), 3
    )
  finally:
    selector.close()
    selector.deleteLater()


def test_transform_and_statistics_can_define_valid_derived_parameter(qapp) -> None:
  transform = TransformEditorDialog([], _catalog())
  statistics = StatisticsEditorDialog([], _catalog(), ("all_events",))
  try:
    assert _item_enabled(transform._parameter_combo, "ratio")
    assert not _item_enabled(transform._parameter_combo, "broken")
    assert _item_enabled(statistics._parameter_combo, "ratio")
    assert not _item_enabled(statistics._parameter_combo, "broken")
  finally:
    transform.close()
    transform.deleteLater()
    statistics.close()
    statistics.deleteLater()


def test_parameter_information_shows_catalog_provenance_and_status(qapp) -> None:
  workspace = ChannelMetadataWorkspace()
  try:
    workspace.set_parameter_catalog(_catalog())
    table = workspace.parameter_table
    assert table.rowCount() == 3
    assert table.item(1, 0).text() == "FL1 / FL2 [ratio] (Derived)"
    assert table.item(1, 1).text() == "derived"
    assert table.item(1, 3).text() == "FL1-A / FL2-A"
    assert table.item(1, 5).text() == "not_run"
    assert "unknown_derived_input" in table.item(2, 5).toolTip()
  finally:
    workspace.close()
    workspace.deleteLater()


def test_main_window_plots_derived_parameter_from_canonical_result(qapp, tmp_path) -> None:
  path = tmp_path / "ratio.fcs"
  write_fcs_file(
    path,
    np.array([[2.0, 1.0], [8.0, 2.0]], dtype=np.float64),
    ["X", "Y"],
  )
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    x_id, y_id = (channel.id for channel in sample.info.channels)
    window._derived_parameters = [{
      "id": "ratio-definition",
      "name": "Ratio",
      "output_channel_id": "ratio",
      "expression": f"{x_id} / {y_id}",
      "input_parameters": [x_id, y_id],
      "source_stage": "raw",
    }]
    window._refresh_parameter_catalog()
    selector = window._channel_selector
    assert _item_enabled(selector._x_combo, "ratio")
    selector.set_selected_channels("ratio", y_id)
    for _ in range(100):
      if not any(
        result.x_parameter_id == "ratio"
        for result in window._processed_display_cache.values()
      ):
        QTest.qWait(5)
        continue
      break
    assert window._plot_widget._scatter is not None
    np.testing.assert_allclose(window._plot_widget._rendered_x, [2.0, 4.0])
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_simple_overlay_uses_the_same_derived_parameter_id(qapp, tmp_path) -> None:
  first = tmp_path / "ratio-active.fcs"
  second = tmp_path / "ratio-overlay.fcs"
  write_fcs_file(first, np.array([[2.0, 1.0], [8.0, 2.0]]), ["X", "Y"])
  write_fcs_file(second, np.array([[3.0, 1.0], [9.0, 3.0]]), ["X", "Y"])
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(first), str(second)]) == 2
    active, overlay = window._sample_browser.samples()
    x_id, y_id = (channel.id for channel in active.info.channels)
    window._derived_parameters = [{
      "id": "ratio-definition", "name": "Ratio", "output_channel_id": "ratio",
      "expression": f"{x_id} / {y_id}", "input_parameters": [x_id, y_id],
      "source_stage": "raw",
    }]
    window._refresh_parameter_catalog()
    assert window._sample_browser.select_sample(active.id)
    assert window._current_sample_id == active.id
    window._channel_selector.set_selected_channels("ratio", y_id)
    source = [{
      "source_id": f"manual:{overlay.id}", "sample_id": overlay.id,
      "population_id": "all_events", "display_name": overlay.id,
      "x_parameter_id": "ratio", "y_parameter_id": y_id,
    }]
    assert window._overlay_status_resolver(source)[f"manual:{overlay.id}"][0] == "compatible"
    window._sample_browser._set_manual_overlay(overlay.id, True)
    assert overlay.id in window._sample_browser.overlay_state()["manual_overlay_sample_ids"]
    window._render_manual_overlays("ratio", y_id)
    QTest.qWait(20)
    banner = window._plot_widget.findChild(
      type(window._plot_widget._status_banner), "plotStatusBanner"
    )
    assert banner.text() == ""
    assert len(window._plot_widget._overlay_scatter_items) == 1
    overlay_x, overlay_y = window._plot_widget._overlay_scatter_items[0].getData()
    np.testing.assert_allclose(overlay_x, [3.0, 3.0])
    np.testing.assert_allclose(overlay_y, [1.0, 3.0])
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_axis_transform_selector_creates_one_persisted_log_definition(qapp, tmp_path) -> None:
  path = tmp_path / "transform.fcs"
  write_fcs_file(path, np.array([[1.0, 2.0], [10.0, 3.0]]), ["X", "Y"])
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    parameter_id = sample.info.channels[0].id
    combo = window.findChild(QComboBox, "xAnalysisTransformCombo")
    assert combo is not None
    combo.setCurrentIndex(combo.findData("log"))
    assert len(window._transforms) == 1
    transform = window._transforms[0]
    assert transform["parameter"] == parameter_id
    assert transform["transform_type"] == "log"
    assert transform["settings"]["base"] == 10.0
    assert window._transform_for_parameter(parameter_id).id == transform["id"]
    assert window._gate_editor._x_transform_id == transform["id"]
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_derived_parameter_deletion_lists_all_persisted_references(qapp) -> None:
  window = MainWindow()
  try:
    window._derived_parameters = [{
      "id": "ratio-definition", "name": "Ratio", "output_channel_id": "ratio",
      "input_parameters": ["X", "Y"],
    }]
    window._transforms = [{"id": "ratio-log", "name": "Ratio log", "parameter": "ratio"}]
    window._statistics = [{"id": "ratio-mean", "name": "Ratio mean", "parameter_id": "ratio"}]
    window._plot_views = [{"id": "ratio-view", "name": "Ratio view", "x_parameter": "ratio"}]
    references = window._derived_parameter_references({"ratio"})
    assert references == [
      "transform Ratio log",
      "statistic Ratio mean",
      "plot view Ratio view",
    ]
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
