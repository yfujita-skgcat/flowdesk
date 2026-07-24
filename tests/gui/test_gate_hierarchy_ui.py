"""Gate hierarchy and Boolean editor GUI regression tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDialog, QPushButton

from flowdesk_cli.main import run_project_command
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.gating_strategy import GatingStrategyError
from flowdesk_core.models import GateSpec, PopulationResult, StatisticResult
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_qt.gate_editor import GateEditor
from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.workspace_tree import WorkspaceTree
from flowdesk_storage.project import load_project

pytestmark = pytest.mark.gui


def _three_level_gates() -> list[GateSpec]:
    return [
        GateSpec(
            id="cells",
            name="Cells",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter="X",
            thresholds={"min": 1.0},
        ),
        GateSpec(
            id="singlets",
            name="Singlets",
            gate_type="range",
            parent_population_id="cells",
            x_parameter="Y",
            thresholds={"max": 8.0},
        ),
        GateSpec(
            id="positive",
            name="Positive",
            gate_type="range",
            parent_population_id="singlets",
            x_parameter="X",
            thresholds={"min": 5.0},
        ),
    ]


def test_hierarchy_tree_uses_ids_and_three_levels(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates(), notify=False)
        root = editor._tree_widget.topLevelItem(0)
        cells = root.child(0)
        singlets = cells.child(0)
        positive = singlets.child(0)
        assert root.data(0, Qt.UserRole) == "all_events"
        assert cells.data(0, Qt.UserRole) == "cells"
        assert singlets.data(0, Qt.UserRole) == "singlets"
        assert positive.data(0, Qt.UserRole) == "positive"
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_duplicate_names_remain_distinct_by_id(qapp) -> None:
    editor = GateEditor()
    gates = _three_level_gates()
    gates[1] = replace(gates[1], name="Cells")
    try:
        editor.set_gates(gates, notify=False)
        assert editor.select_gate("cells")
        assert editor.selected_gate().id == "cells"
        assert editor.select_gate("singlets")
        assert editor.selected_gate().id == "singlets"
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_population_color_is_display_only_and_has_color_column(qapp, monkeypatch) -> None:
  editor = GateEditor()
  gates = _three_level_gates()
  try:
    editor.set_gates(gates, notify=False)
    before = [(gate.id, gate.coordinates, gate.thresholds) for gate in editor.gates()]
    assert editor._tree_widget.columnCount() == 5
    assert editor._tree_widget.headerItem().text(4) == "Color"
    monkeypatch.setattr(
      "flowdesk_qt.gate_editor.QColorDialog.getColor",
      lambda *_args, **_kwargs: QColor("#123456"),
    )
    editor._choose_population_color("positive")
    assert editor.population_display_definitions()["positive"]["color"] == "#123456"
    after = [(gate.id, gate.coordinates, gate.thresholds) for gate in editor.gates()]
    assert before == after
  finally:
    editor.close()
    editor.deleteLater()
    qapp.processEvents()


def test_population_color_dialog_starts_with_visible_default(qapp, monkeypatch) -> None:
  editor = GateEditor()
  try:
    received = {}

    def fake_get_color(initial, *_args, **_kwargs):
      received["initial"] = initial
      return QColor()  # cancel; do not change the display definition

    monkeypatch.setattr("flowdesk_qt.gate_editor.QColorDialog.getColor", fake_get_color)
    editor._choose_population_color("positive")
    assert received["initial"].name() == "#d62728"
    assert editor.population_display_definitions() == {}
  finally:
    editor.close()
    editor.deleteLater()
    qapp.processEvents()


def test_selected_population_swatch_keeps_its_actual_color(qapp) -> None:
  editor = GateEditor()
  try:
    editor.set_gates(_three_level_gates(), notify=False)
    editor._population_display_colors["positive"] = "#800080"
    editor._refresh_hierarchy_tree("positive")
    item = editor._tree_items["positive"]
    editor._tree_widget.setCurrentItem(item)
    icon_image = item.icon(4).pixmap(12, 12).toImage()
    assert icon_image.pixelColor(6, 6).name() == "#800080"
  finally:
    editor.close()
    editor.deleteLater()
    qapp.processEvents()


def test_numeric_ellipse_gate_uses_command_stack_for_deletion(qapp, monkeypatch) -> None:
    editor = GateEditor()

    class AcceptedEllipseDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def name(self) -> str:
            return "Ellipse"

        def thresholds(self) -> dict[str, float]:
            return {
                "center_x": 10.0,
                "center_y": 20.0,
                "radius_x": 4.0,
                "radius_y": 6.0,
                "rotation": 0.0,
            }

        def coordinates(self) -> list[tuple[float, float]]:
            return []

    try:
        monkeypatch.setattr(
            "flowdesk_qt.gate_editor._GateDialog", AcceptedEllipseDialog
        )
        editor._type_combo.setCurrentText("ellipse")
        editor._create_gate_dialog()
        ellipse = editor.gates()[0]
        assert ellipse.gate_type == "ellipse"
        assert editor.select_gate(ellipse.id)
        editor._delete_selected_gate()
        assert editor.gates() == []
        assert editor.can_undo()
        assert editor.undo()
        assert [gate.id for gate in editor.gates()] == [ellipse.id]
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_all_events_root_clears_gate_definition_selection(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates(), notify=False)
        assert editor.select_gate("cells")
        assert editor.selected_gate() is not None
        editor._tree_widget.setCurrentItem(editor._tree_widget.topLevelItem(0))
        qapp.processEvents()
        assert editor.selected_gate() is None
        assert editor._list_widget.currentRow() == -1
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_hierarchy_selection_sets_gate_creation_parent_and_context(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates()[:1], notify=False)
        editor.set_current_sample_id("sample-1")
        editor.set_plot_channels("FSC-A", "SSC-A")
        editor.set_plot_scales("log10", "asinh")
        assert editor.select_gate("cells")
        context = editor._creation_banner.text()
        assert context == "Parent: Cells"
        details = editor._creation_banner.toolTip()
        assert "Cells [cells]" in details
        assert "sample-1" in details
        assert "FSC-A / SSC-A" in details
        assert "log10/asinh" in details
        editor._tree_widget.setCurrentItem(editor._tree_widget.topLevelItem(0))
        assert editor._creation_banner.text() == "Parent: All Events"
        assert editor.gates() == _three_level_gates()[:1]
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_create_gate_uses_selected_hierarchy_population_as_parent(qapp, monkeypatch) -> None:
    class AcceptedEllipseDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def name(self) -> str:
            return "Child ellipse"

        def thresholds(self) -> dict[str, float]:
            return {
                "center_x": 10.0,
                "center_y": 20.0,
                "radius_x": 4.0,
                "radius_y": 6.0,
                "rotation": 0.0,
            }

        def coordinates(self) -> list[tuple[float, float]]:
            return []

    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates()[:1], notify=False)
        editor.select_gate("cells")
        monkeypatch.setattr(
            "flowdesk_qt.gate_editor._GateDialog", AcceptedEllipseDialog
        )
        editor._type_combo.setCurrentText("ellipse")
        editor._create_gate_dialog()

        created = editor.gates()[-1]
        assert created.parent_population_id == "cells"
        assert editor.findChild(QPushButton, "createChildGateButton") is None
        assert editor.findChild(QComboBox, "parentPopulationCombo") is None
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_reparent_is_atomic_and_rejects_cycle(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates(), notify=False)
        before = editor.gates()
        with pytest.raises(GatingStrategyError, match="cycle"):
            editor.reparent_gate("cells", "positive")
        assert editor.gates() == before

        editor.reparent_gate("positive", "cells")
        updated = next(g for g in editor.gates() if g.id == "positive")
        assert updated.parent_population_id == "cells"
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_gate_mutations_route_through_undo_redo_commands(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates()[:1], notify=False)
        editor.duplicate_gate("cells", "cells-copy", name="Cells copy")
        assert editor.select_gate("cells-copy")
        assert editor.can_undo()
        assert editor.undo()
        assert not editor.select_gate("cells-copy")
        assert editor.redo()
        assert editor.select_gate("cells-copy")
        editor.copy_subtree(
            "cells",
            {"cells": "cells-subtree"},
            target_parent_id="all_events",
        )
        assert editor.select_gate("cells-subtree")
        assert editor.undo()
        assert not editor.select_gate("cells-subtree")
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_gate_preflight_reports_name_conflict_and_cycle_before_commit(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates()[:2], notify=False)
        assert editor.preflight_duplicate_gate("cells", name="Cells")
        assert editor.preflight_subtree_copy(
            "cells",
            {"cells": "cells-copy", "singlets": "singlets-copy"},
            target_parent_id="singlets",
        ) == ()
        before = editor.gates()
        with pytest.raises(GatingStrategyError, match="cycle"):
            editor.reparent_gate("cells", "singlets")
        assert editor.gates() == before
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_workspace_tree_unifies_sample_population_and_statistics(qapp) -> None:
    tree = WorkspaceTree()
    selected = []
    tree.on_selection_changed(
        lambda kind, stable_id, sample_id: selected.append(
            (kind, stable_id, sample_id)
        )
    )
    report = ExecutionReport(
        project_id="p",
        execution_profile_id="profile",
        pipeline_version="test",
        status="success",
        population_results=(
            PopulationResult("s1", "all_events", 10, None, 1.0),
            PopulationResult("s1", "positive", 4, 0.4, 0.4),
        ),
        statistic_results=(
            StatisticResult("s1", "stat-1", "positive", "count", 4, statistic_name="Count"),
        ),
    )
    try:
        tree.set_samples([("s1", "Sample 1")])
        tree.set_population_hierarchy(
            {"positive": "all_events"}, {"positive": "Positive"}
        )
        tree.set_report(report)
        assert tree.select("population", "positive")
        assert selected[-1] == ("population", "positive", "s1")
        item = tree._tree.topLevelItem(0)
        assert item.data(0, Qt.UserRole) == "s1"
        assert item.child(0).data(0, Qt.UserRole) == "positive"
        assert item.child(0).child(0).data(0, Qt.UserRole) == "stat-1"
    finally:
        tree.close()
        tree.deleteLater()
        qapp.processEvents()


def test_main_window_undo_action_marks_results_stale(qapp) -> None:
    window = MainWindow()
    gate = _three_level_gates()[0]
    try:
        window._results_stale = False
        window._gate_editor.add_gate(gate)
        assert window._results_stale
        window._results_stale = False
        assert window._gate_editor.undo()
        assert window._results_stale
        assert window.action_redo.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_boolean_update_validates_arity_sources_and_cycles(qapp) -> None:
    editor = GateEditor()
    boolean = GateSpec(
        id="combined",
        name="Combined",
        gate_type="boolean",
        parent_population_id="all_events",
        thresholds={"operation": "and", "source_ids": ["cells", "singlets"]},
    )
    try:
        editor.set_gates([*_three_level_gates()[:2], boolean], notify=False)
        editor.update_boolean_gate("combined", "not", ["cells"])
        updated = next(g for g in editor.gates() if g.id == "combined")
        assert updated.thresholds == {"operation": "not", "source_ids": ["cells"]}

        before = editor.gates()
        with pytest.raises(GatingStrategyError, match="invalid source count"):
            editor.update_boolean_gate("combined", "and", ["cells"])
        assert editor.gates() == before
        with pytest.raises(GatingStrategyError, match="cycle"):
            editor.update_boolean_gate("combined", "not", ["combined"])
        assert editor.gates() == before
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_show_gate_is_display_only(qapp) -> None:
    editor = GateEditor()
    shown: list[GateSpec] = []
    gate = GateSpec(
        id="log-gate",
        name="Log Gate",
        gate_type="rectangle",
        x_parameter="X",
        y_parameter="Y",
        thresholds={"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1},
    )
    try:
        editor.set_gates([gate], notify=False)
        editor.on_show_gate(shown.append)
        assert editor.select_gate("log-gate")
        before = editor.gates()
        editor._on_show_gate_clicked()
        assert shown == [gate]
        editor._emit_show_gate("log-gate")
        assert shown == [gate, gate]
        assert editor.gates() == before
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_nested_boolean_gui_manifest_matches_headless_after_roundtrip(
    qapp, tmp_path
) -> None:
    window = MainWindow()
    try:
        gates = [
            GateSpec(
                id="a", name="A", gate_type="range", x_parameter="X",
                thresholds={"min": 2.0, "max": 8.0},
            ),
            GateSpec(
                id="b", name="B", gate_type="range", x_parameter="Y",
                thresholds={"min": 5.0},
            ),
            GateSpec(
                id="nested", name="Nested", gate_type="boolean",
                thresholds={
                    "expression": {
                        "op": "or",
                        "children": [
                            {"op": "ref", "id": "a"},
                            {"op": "not", "child": {"op": "ref", "id": "b"}},
                        ],
                    }
                },
            ),
        ]
        window._gate_editor.set_gates(gates, notify=False)
        manifest = window._build_project_manifest()
        manifest["samples"] = [{"id": "sample", "path": "sample.fcs", "channels": []}]
        project_path = tmp_path / "nested.flowdesk"
        from flowdesk_storage.project import save_project

        save_project(project_path, manifest)
        manifest = load_project(project_path)
        data = np.array([
            [0.0, 1.0], [2.0, 9.0], [3.0, 7.0], [6.0, 6.0], [8.0, 10.0]
        ])
        report = PipelineRunner(manifest).run(
            ExecutionContext(), {"sample": data}, ["X", "Y"]
        )
        counts = {result.population_id: result.event_count for result in report.population_results}
        assert counts["all_events"] == 5
        assert counts["nested"] == 5
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_boolean_hierarchy_project_round_trip_and_cli(
    qapp, tmp_path
) -> None:
    fcs_path = tmp_path / "hierarchy.fcs"
    project_path = tmp_path / "hierarchy.flowdesk"
    output_path = tmp_path / "results.tsv"
    events = np.array([
        [0.0, 0.0], [2.0, 1.0], [4.0, 3.0], [6.0, 5.0]
    ])
    write_fcs_file(fcs_path, events, ["X", "Y"])
    gates = [
        GateSpec(
            id="x-positive",
            name="Positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter="X",
            thresholds={"min": 2.0},
        ),
        GateSpec(
            id="y-positive",
            name="Positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter="Y",
            thresholds={"min": 3.0},
        ),
        GateSpec(
            id="double-positive",
            name="Double Positive",
            gate_type="boolean",
            parent_population_id="x-positive",
            thresholds={
                "operation": "and",
                "source_ids": ["x-positive", "y-positive"],
            },
        ),
    ]
    window = MainWindow()
    try:
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        gates = [
            replace(gates[0], x_parameter=sample.info.channels[0].id),
            replace(gates[1], x_parameter=sample.info.channels[1].id),
            gates[2],
        ]
        window._gate_editor.set_gates(gates, notify=False)
        manifest = window._build_project_manifest()
        gui_report = PipelineRunner(manifest).run_samples(
            ExecutionContext(), tuple(window._sample_data.values())
        )
        window._save_project_to_path(project_path)

        saved = load_project(project_path)
        headless_report = PipelineRunner(saved).run_samples(
            ExecutionContext(), tuple(window._sample_data.values())
        )
        gui_counts = {
            result.population_id: result.event_count
            for result in gui_report.population_results
        }
        headless_counts = {
            result.population_id: result.event_count
            for result in headless_report.population_results
        }
        assert gui_counts == headless_counts
        assert headless_counts["double-positive"] == 2

        assert run_project_command(str(project_path), output=str(output_path)) == 0
        assert (
            "All Events/Positive/Double Positive\t2\t"
            in output_path.read_text(encoding="utf-8")
        )
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
