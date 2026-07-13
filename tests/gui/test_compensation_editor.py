"""GUI tests for the compensation matrix editor dialog."""

from __future__ import annotations

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
