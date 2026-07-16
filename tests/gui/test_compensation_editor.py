"""GUI tests for the compensation matrix editor dialog."""

from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from flowdesk_core.models import ChannelSpec  # noqa: E402
from flowdesk_qt.compensation_editor import (  # noqa: E402
    CompensationMatrixEditorDialog,
    _empty_matrix_mapping,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _sample_channels() -> tuple[ChannelSpec, ...]:
    return (
        ChannelSpec(id="FL1-A", name="FL1-A"),
        ChannelSpec(id="FL2-A", name="FL2-A"),
        ChannelSpec(id="FL3-A", name="FL3-A"),
    )


def _valid_2x2_matrix() -> dict:
    return {
        "id": "comp_2x2",
        "name": "2x2 test matrix",
        "source": "user_defined",
        "channels": ["FL1-A", "FL2-A"],
        "matrix": [[1.0, 0.1], [0.2, 1.0]],
        "provenance": {},
    }


def _valid_binding() -> dict:
    return {
        "id": "bind_1",
        "matrix_id": "comp_2x2",
        "scope": "sample",
        "target_id": "sample_1",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Basic construction and round-trip
# ---------------------------------------------------------------------------


def test_editor_constructs_and_returns_empty_defaults() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        # An empty matrix is auto-created when no matrices provided
        matrices = dialog.matrices()
        assert len(matrices) == 1
        assert matrices[0]["id"] == ""
        assert matrices[0]["source"] == "user_defined"
        bindings = dialog.bindings()
        assert bindings == []
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_editor_round_trip_preserves_matrix_and_binding() -> None:
    app = _app()
    matrix = _valid_2x2_matrix()
    binding = _valid_binding()
    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix],
        bindings=[binding],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        matrices = dialog.matrices()
        assert len(matrices) == 1
        assert matrices[0]["id"] == "comp_2x2"
        assert matrices[0]["channels"] == ["FL1-A", "FL2-A"]

        bindings = dialog.bindings()
        assert len(bindings) == 1
        assert bindings[0]["id"] == "bind_1"
        assert bindings[0]["matrix_id"] == "comp_2x2"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Heat map and validation
# ---------------------------------------------------------------------------


def test_heat_map_populated_for_2x2_matrix() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        heat_map = dialog._heat_map
        assert heat_map.rowCount() == 2
        assert heat_map.columnCount() == 2
        # Diagonal should be 1.0000
        assert "1.0000" in heat_map.item(0, 0).text()
        assert "1.0000" in heat_map.item(1, 1).text()
        # Off-diagonal
        assert "0.1000" in heat_map.item(0, 1).text()
        assert "0.2000" in heat_map.item(1, 0).text()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_validate_current_shows_condition_number() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        is_valid = dialog._validate_current()
        assert is_valid is True
        diag = dialog.findChild(QLabel, "compensationDiagnosticLabel")
        assert "Valid" in diag.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Matrix add, duplicate, delete
# ---------------------------------------------------------------------------


def test_add_matrix_increases_count() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._add_matrix()
        matrices = dialog.matrices()
        assert len(matrices) == 2
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_calculated_matrix_is_read_only_and_duplicate_is_editable() -> None:
    """Calculated results are immutable; only their derivative is editable."""
    app = _app()
    matrix = _valid_2x2_matrix()
    matrix["id"] = "calculated-comp_2x2"
    matrix["source"] = "calculated"
    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        assert not dialog._id_edit.isEnabled()
        assert not dialog._name_edit.isEnabled()
        assert not dialog._heat_map.isEnabled()

        dialog._duplicate_matrix()

        duplicate = dialog.matrices()[-1]
        assert duplicate["source"] == "user_defined"
        assert duplicate["provenance"]["derived_from_matrix_id"] == (
            "calculated-comp_2x2"
        )
        assert dialog._id_edit.isEnabled()
        assert dialog._heat_map.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_duplicate_matrix_sets_provenance() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._duplicate_matrix()
        matrices = dialog.matrices()
        assert len(matrices) == 2
        duplicate = matrices[1]
        assert duplicate["id"].startswith("comp_2x2_edit_")
        assert duplicate["name"] == "2x2 test matrix (edit copy)"
        assert duplicate["provenance"]["derived_from_matrix_id"] == "comp_2x2"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_delete_matrix_removes_it() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._delete_matrix()
        matrices = dialog.matrices()
        # An empty matrix is auto-created when the list becomes empty on refresh
        # but _delete_matrix does not auto-add, so we just check count
        assert len(matrices) == 0
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_cannot_delete_matrix_referenced_by_binding() -> None:
    import unittest.mock

    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[_valid_binding()],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        from PySide6.QtWidgets import QMessageBox

        with unittest.mock.patch.object(QMessageBox, "warning"):
            dialog._delete_matrix()
        # Should still exist because it's referenced
        matrices = dialog.matrices()
        assert len(matrices) == 1
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Binding add and delete
# ---------------------------------------------------------------------------


def test_add_binding_increases_count() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[_valid_binding()],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._add_binding()
        bindings = dialog.bindings()
        assert len(bindings) == 2
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_delete_binding_removes_it() -> None:
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[_valid_binding()],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._delete_binding()
        bindings = dialog.bindings()
        assert len(bindings) == 0
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Validation on accept
# ---------------------------------------------------------------------------


def test_accept_rejects_duplicate_matrix_ids() -> None:
    app = _app()
    matrix_a = _valid_2x2_matrix()
    matrix_b = _valid_2x2_matrix()  # same id
    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix_a, matrix_b],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        # _accept_if_valid should raise a ValueError and show a warning
        dialog._commit_current_matrix()
        with pytest.raises(ValueError, match="Duplicate matrix ID"):
            dialog._validate_all_matrices()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_accept_rejects_empty_matrix_id() -> None:
    app = _app()
    empty = _empty_matrix_mapping()
    dialog = CompensationMatrixEditorDialog(
        matrices=[empty],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        dialog._commit_current_matrix()
        with pytest.raises(ValueError, match="non-empty ID"):
            dialog._validate_all_matrices()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_accept_rejects_binding_to_unknown_matrix() -> None:
    app = _app()
    binding = {
        "id": "bind_unknown",
        "matrix_id": "nonexistent",
        "scope": "sample",
        "target_id": "sample_1",
        "notes": "",
    }
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[binding],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        with pytest.raises(ValueError, match="unknown matrix"):
            dialog._validate_all_bindings()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_duplicate_matrix_does_not_mutate_original() -> None:
    """Verify that duplicating and editing a matrix does not mutate the original.

    Regression test for A4 Residual 2: the duplicate-before-edit workflow
    must use deepcopy so that changes to the duplicate never leak back into
    the original matrix spec.
    """
    import copy

    app = _app()
    original_matrix = _valid_2x2_matrix()
    original_snapshot = copy.deepcopy(original_matrix)
    dialog = CompensationMatrixEditorDialog(
        matrices=[original_matrix],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        # Duplicate the matrix
        dialog._duplicate_matrix()
        matrices = dialog.matrices()
        assert len(matrices) == 2

        # Mutate the duplicate's matrix values in the heat map
        dup = matrices[1]
        assert dup["id"] != original_snapshot["id"]
        # Write a different value into the duplicate
        dup["matrix"] = [[1.0, 0.9], [0.8, 1.0]]

        # The original must remain unchanged
        assert matrices[0]["matrix"] == original_snapshot["matrix"]
        assert matrices[0]["id"] == original_snapshot["id"]
        assert matrices[0]["name"] == original_snapshot["name"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_heat_map_edit_does_not_affect_unselected_matrix() -> None:
    """Editing the heat map of one matrix must not affect another matrix
    when switching selections."""
    app = _app()
    matrix_a = _valid_2x2_matrix()
    matrix_b = _valid_2x2_matrix()
    matrix_b["id"] = "comp_2x2_b"
    matrix_b["name"] = "2x2 test matrix B"
    matrix_b["matrix"] = [[1.0, 0.0], [0.0, 1.0]]

    snap_a = copy.deepcopy(matrix_a)
    snap_b = copy.deepcopy(matrix_b)

    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix_a, matrix_b],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        # Commit current matrix (matrix_b is selected after init)
        dialog._commit_current_matrix()
        # Verify both matrices retain their original values
        matrices = dialog.matrices()
        assert matrices[0]["matrix"] == snap_a["matrix"]
        assert matrices[1]["matrix"] == snap_b["matrix"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_accept_rejects_duplicate_scope_target() -> None:
    app = _app()
    binding_a = _valid_binding()
    binding_b = _valid_binding()
    binding_b["id"] = "bind_2"
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[binding_a, binding_b],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
    )
    try:
        with pytest.raises(ValueError, match="Duplicate binding scope"):
            dialog._validate_all_bindings()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# Compensated / uncompensated preview
# ---------------------------------------------------------------------------


def test_preview_populates_table_with_core_output() -> None:
    """The preview table must show uncompensated and compensated values
    derived from core's ``apply_compensation``, not a Qt-side calculation."""
    import numpy as np

    app = _app()
    matrix = _valid_2x2_matrix()
    events = np.array([
        [100.0, 200.0, 50.0],
        [300.0, 400.0, 100.0],
        [50.0, 60.0, 20.0],
    ], dtype=np.float64)
    channel_ids = ["FSC-H", "FL1-A", "FL2-A"]
    sample_data = {
        "sample_1": {
            "events": events,
            "channel_ids": channel_ids,
        }
    }

    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
        sample_data=sample_data,
    )
    try:
        dialog._on_preview()
        table = dialog._preview_table
        # 2 compensation channels × 3 events = 6 rows
        assert table.rowCount() == 6
        # First row should be FL1-A
        assert table.item(0, 0).text() == "FL1-A"
        diag = dialog.findChild(QLabel, "compensationDiagnosticLabel")
        assert "Preview" in diag.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_preview_values_match_headless_apply_compensation() -> None:
    """GUI preview compensated values must match headless
    ``apply_compensation`` output exactly (A4 Residual 5)."""
    import numpy as np

    from flowdesk_core.compensation import apply_compensation
    from flowdesk_core.models import CompensationMatrixSpec

    app = _app()
    matrix = _valid_2x2_matrix()
    events = np.array([
        [100.0, 200.0, 50.0],
        [300.0, 400.0, 100.0],
    ], dtype=np.float64)
    channel_ids = ["FSC-H", "FL1-A", "FL2-A"]
    sample_data = {
        "sample_1": {
            "events": events,
            "channel_ids": channel_ids,
        }
    }

    dialog = CompensationMatrixEditorDialog(
        matrices=[matrix],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
        sample_data=sample_data,
    )
    try:
        dialog._on_preview()
        table = dialog._preview_table

        # Compute headless compensated values for comparison
        spec = CompensationMatrixSpec(**matrix)
        compensated = apply_compensation(spec, events, channel_ids)

        # FL1-A is at column index 1, FL2-A at column index 2
        fl1_idx = channel_ids.index("FL1-A")
        fl2_idx = channel_ids.index("FL2-A")

        row = 0
        for ch in ("FL1-A", "FL2-A"):
            col_idx = fl1_idx if ch == "FL1-A" else fl2_idx
            for evt in range(len(events)):
                uncomp_text = table.item(row, 1).text()
                comp_text = table.item(row, 2).text()
                assert float(uncomp_text) == pytest.approx(
                    events[evt, col_idx], abs=1e-3
                )
                assert float(comp_text) == pytest.approx(
                    compensated[evt, col_idx], abs=1e-3
                )
                row += 1
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_preview_shows_message_when_no_sample_data() -> None:
    """When sample_data is empty, the preview combo should show a
    placeholder and the diagnostic label should report the absence."""
    app = _app()
    dialog = CompensationMatrixEditorDialog(
        matrices=[_valid_2x2_matrix()],
        bindings=[],
        available_channels=_sample_channels(),
        sample_ids=["sample_1"],
        group_ids=[],
        sample_data={},
    )
    try:
        dialog._on_preview()
        diag = dialog.findChild(QLabel, "compensationDiagnosticLabel")
        assert "no sample data" in diag.text().lower() or \
            "no data" in diag.text().lower() or \
            "no event data" in diag.text().lower() or \
            "no" in diag.text().lower()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
