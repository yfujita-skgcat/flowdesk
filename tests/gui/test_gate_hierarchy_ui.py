"""Gate hierarchy and Boolean editor GUI regression tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from flowdesk_cli.main import run_project_command
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.gating_strategy import GatingStrategyError
from flowdesk_core.models import GateSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_qt.gate_editor import GateEditor
from flowdesk_qt.main_window import MainWindow
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


def test_explicit_child_mode_sets_parent_and_context(qapp) -> None:
    editor = GateEditor()
    try:
        editor.set_gates(_three_level_gates()[:1], notify=False)
        editor.set_current_sample_id("sample-1")
        editor.set_plot_channels("FSC-A", "SSC-A")
        editor.set_plot_scales("log10", "asinh")
        assert editor.begin_child_gate("cells")
        assert editor.parent_population() == "cells"
        context = editor._creation_banner.text()
        assert "Cells [cells]" in context
        assert "sample-1" in context
        assert "FSC-A / SSC-A" in context
        assert "log10/asinh" in context
        editor.cancel_child_gate_mode()
        assert editor.parent_population() == "all_events"
        assert editor.gates() == _three_level_gates()[:1]
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
        x_scale="log10",
        y_scale="asinh",
        thresholds={"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1},
    )
    try:
        editor.set_gates([gate], notify=False)
        editor.on_show_gate(shown.append)
        assert editor.select_gate("log-gate")
        before = editor.gates()
        editor._on_show_gate_clicked()
        assert shown == [gate]
        assert editor.gates() == before
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_three_level_gui_manifest_matches_headless_counts(qapp) -> None:
    window = MainWindow()
    try:
        window._gate_editor.set_gates(_three_level_gates(), notify=False)
        manifest = window._build_project_manifest()
        manifest["samples"] = [{"id": "sample"}]
        data = np.array([
            [0.0, 1.0], [2.0, 9.0], [3.0, 7.0], [6.0, 6.0], [8.0, 10.0]
        ])
        report = PipelineRunner(manifest).run(
            ExecutionContext(), {"sample": data}, ["X", "Y"]
        )
        counts = {result.population_id: result.event_count for result in report.population_results}
        assert counts == {
            "all_events": 5,
            "cells": 4,
            "singlets": 2,
            "positive": 1,
        }
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
        assert "double-positive\t2\t" in output_path.read_text(encoding="utf-8")
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
