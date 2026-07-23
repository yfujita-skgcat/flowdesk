"""GUI E2E tests for population filtering (Phase 3-3).

Verify that selecting a population in the Population Results table filters
the scatter plot to only display events belonging to that population.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer

from flowdesk_cli.run_project import run_project_command
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import GateSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_qt.channel_selector import COUNT_CHANNEL
from flowdesk_qt.main_window import MainWindow
from flowdesk_storage.project import save_project

pytestmark = [pytest.mark.gui, pytest.mark.gui_e2e]


def _wait_for_worker(window: MainWindow) -> None:
    """Block until the background pipeline worker finishes.

    The worker C++ object may be deleted by _release_pipeline_worker before
    this function returns.  We guard against that with a try/except.
    """
    worker = window._worker
    assert worker is not None
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    try:
        assert worker.isRunning() is False
    except RuntimeError:
        # C++ object already deleted by _release_pipeline_worker;
        # worker is no longer running either way.
        pass


# ---------------------------------------------------------------------------
# 3-3a: Basic population filtering
# ---------------------------------------------------------------------------


def test_population_filter_reduces_scatter_points(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """4 events, range gate selects 3 -> scatter shows 3 after population selection."""
    fcs_path = tmp_path / "filter.fcs"
    events = np.array(
        [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        assert window._event_data[sample.id].shape == (4, 2)

        # Range gate: X >= 2.0 selects events [2,3,4] -> 3 events
        gate = GateSpec(
            id="pos",
            name="positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"min": 2.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        report = window._population_tree.last_report()
        assert report is not None
        gui_counts = {
            r.population_id: r.event_count for r in report.population_results
        }
        assert gui_counts == {"all_events": 4, "pos": 3}

        # all_events shows 4 points
        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 4

        # Changing one display scale must not recalculate the linear gate.
        window._channel_selector.set_analysis_transform_choice("x", "log")
        window._on_axis_analysis_transform_requested("x", "log")
        assert not window._results_stale
        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 4

        # Select gate population -> 3 points
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()
        # _replot() creates a new scatter object; re-fetch the reference
        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 3

        # Select all_events -> 4 points
        table.selectRow(0)
        qapp.processEvents()
        assert len(window._plot_widget._scatter.xData) == 4
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_show_gate_restores_both_axis_transforms_by_id(qapp) -> None:
    window = MainWindow()
    gate = GateSpec(
        id="transformed-gate",
        name="Transformed gate",
        gate_type="rectangle",
        x_parameter="X",
        y_parameter="Y",
        x_transform_id="transform-x-log",
        y_transform_id="transform-y-asinh",
        thresholds={"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
    )
    try:
        window._channel_selector.set_channels(["X", "Y"])
        window._transforms = [
            {
                "id": "transform-x-log",
                "name": "X log",
                "transform_type": "log",
                "parameter": "X",
                "settings": {"base": 10.0},
            },
            {
                "id": "transform-y-asinh",
                "name": "Y asinh",
                "transform_type": "asinh",
                "parameter": "Y",
                "settings": {"cofactor": 1.0},
            },
        ]
        window._replot = lambda: None

        window._on_show_gate(gate)

        assert window._channel_selector.x_channel_id() == "X"
        assert window._channel_selector.y_channel_id() == "Y"
        assert window._channel_selector._x_analysis_transform_combo.currentData() == "log"
        assert window._channel_selector._y_analysis_transform_combo.currentData() == "asinh"
        assert window._plot_transform_overrides == {
            "X": "transform-x-log",
            "Y": "transform-y-asinh",
        }

        window._on_axis_analysis_transform_requested("x", "linear")
        assert window._plot_transform_overrides["X"] is None
        assert {value["id"] for value in window._transforms} == {
            "transform-x-log",
            "transform-y-asinh",
        }
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3b: Membership mask persists across channel switches
# ---------------------------------------------------------------------------


def test_population_filter_persists_across_channel_switch(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Population membership mask follows X/Y channel changes."""
    fcs_path = tmp_path / "channelswitch.fcs"
    events = np.array(
        [[0.0, 0.0, 10.0], [2.0, 1.0, 20.0], [3.0, 2.0, 30.0], [4.0, 3.0, 40.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y", "Z"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)

        gate = GateSpec(
            id="pos",
            name="positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"min": 2.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        # Select gate population
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 3

        # Selecting the gate definition is independent from the displayed
        # population.  The filtered result remains visible for this test.
        window._on_gate_selected(0)
        assert window.selected_gate_id == "pos"
        assert window.display_population_id == "pos"
        assert len(window._plot_widget._scatter.xData) == 3

        # Show Gate displays the parent population for editing, while the
        # explicit Show Population action displays the gate result.
        window._on_show_gate(gate)
        assert window.display_population_id == "all_events"
        window._on_show_population(gate)
        assert window.display_population_id == "pos"
        assert len(window._plot_widget._scatter.xData) == 3

        # Returning to All Events changes the display only; it must not move
        # the gate editing target.
        window._on_population_selected("all_events", sample.id)
        assert window.display_population_id == "all_events"
        assert window.selected_gate_id == "pos"
        assert len(window._plot_widget._scatter.xData) == 4

        window._on_population_selected("pos", sample.id)
        assert window.display_population_id == "pos"

        # Switch X/Y to different channels, membership still 3
        window._channel_selector.set_selected_channels("X", "Z")
        qapp.processEvents()
        assert len(window._plot_widget._scatter.xData) == 3

        window._channel_selector.set_selected_channels("Z", "Y")
        qapp.processEvents()
        assert len(window._plot_widget._scatter.xData) == 3
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3c: Gate edit invalidates membership display
# ---------------------------------------------------------------------------


def test_gate_edit_invalidates_population_filter(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """After gate edit, stale membership is not used for display."""
    fcs_path = tmp_path / "invalidate.fcs"
    events = np.array(
        [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)

        gate = GateSpec(
            id="pos",
            name="positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"min": 2.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        # Select gate population (3 points)
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()
        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 3

        # Add a new gate -> retain the displayed population while recalculating.
        new_gate = GateSpec(
            id="neg",
            name="negative",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"max": 1.0},
        )
        window._gate_editor.add_gate(new_gate)
        qapp.processEvents()

        # The previous membership remains visible with explicit provenance.
        assert window._results_stale
        assert window._selected_population_id == "pos"
        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == 3
        assert window._plot_widget._status_banner.text() == (
            "Recalculating — displayed events are from the previous revision"
        )
        window._on_population_selected("pos", sample.id)
        assert window._selected_population_id == "pos"
        assert len(window._plot_widget._scatter.xData) == 3

        # The newly defined gate has no previous membership; selecting it must
        # not fabricate the old ``pos`` mask.
        window._on_population_selected("neg", sample.id)
        assert window._selected_population_id == "neg"
        assert len(window._plot_widget._scatter.xData) == 4
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3e: Gate edits invalidate and refresh persisted statistics
# ---------------------------------------------------------------------------


def test_gate_edit_stales_then_refreshes_statistics(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """A rerun replaces stale statistic results with PipelineRunner results."""
    fcs_path = tmp_path / "statistics-invalidation.fcs"
    events = np.array(
        [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        x_channel_id = sample.info.channels[0].id
        window._statistics = [
            {
                "id": "positive_count",
                "name": "Positive count",
                "population_id": "positive",
                "metric": "count",
                "source_stage": "compensated",
                "value_policy": "full_events",
            },
            {
                "id": "positive_mean_x",
                "name": "Positive mean X",
                "population_id": "positive",
                "parameter_id": x_channel_id,
                "metric": "mean",
                "source_stage": "compensated",
                "value_policy": "full_events",
            },
        ]
        window._gate_editor.set_gates([
            GateSpec(
                id="positive",
                name="positive",
                gate_type="range",
                parent_population_id="all_events",
                x_parameter=x_channel_id,
                thresholds={"min": 2.0},
            ),
        ])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        first_report = window._population_tree.last_report()
        assert first_report is not None
        first_values = {
            result.statistic_id: result.value
            for result in first_report.statistic_results
        }
        assert first_values == {
            "positive_count": 3,
            "positive_mean_x": pytest.approx(3.0),
        }

        window._gate_editor.set_gates([
            GateSpec(
                id="positive",
                name="positive",
                gate_type="range",
                parent_population_id="all_events",
                x_parameter=x_channel_id,
                thresholds={"min": 3.0},
            ),
        ])
        qapp.processEvents()
        assert window._results_stale is True
        assert window._population_tree.last_report() is None

        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        refreshed_report = window._population_tree.last_report()
        assert refreshed_report is not None
        refreshed_values = {
            result.statistic_id: result.value
            for result in refreshed_report.statistic_results
        }
        assert refreshed_values == {
            "positive_count": 2,
            "positive_mean_x": pytest.approx(3.5),
        }
        assert window._results_stale is False
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3f: GUI, headless API, and CLI statistic values agree
# ---------------------------------------------------------------------------


def test_gui_statistics_match_headless_api_and_cli_export(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """All frontends consume the same persisted statistic definitions."""
    fcs_path = tmp_path / "statistics-consistency.fcs"
    events = np.array(
        [[0.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample_info = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample_info.id)
        x_channel_id = sample_info.info.channels[0].id
        y_channel_id = sample_info.info.channels[1].id
        window._gate_editor.set_gates([
            GateSpec(
                id="positive",
                name="positive",
                gate_type="range",
                parent_population_id="all_events",
                x_parameter=x_channel_id,
                thresholds={"min": 2.0},
            ),
        ])
        window._statistics = [
            {
                "id": "positive_count",
                "name": "Positive count",
                "population_id": "positive",
                "metric": "count",
                "source_stage": "compensated",
                "value_policy": "full_events",
            },
            {
                "id": "positive_mean_y",
                "name": "Positive mean Y",
                "population_id": "positive",
                "parameter_id": y_channel_id,
                "metric": "mean",
                "source_stage": "compensated",
                "value_policy": "full_events",
            },
        ]
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        gui_report = window._population_tree.last_report()
        assert gui_report is not None
        gui_results = {
            result.statistic_id: result
            for result in gui_report.statistic_results
        }
        assert {
            statistic_id: result.value
            for statistic_id, result in gui_results.items()
        } == {
            "positive_count": 3,
            "positive_mean_y": pytest.approx(30.0),
        }

        statistics_tree = window._population_tree._statistics_tree
        gui_table = {
            statistics_tree.topLevelItem(population_row).child(statistic_row).data(
                0, 0x0100
            ): (
                statistics_tree.topLevelItem(population_row).child(statistic_row).text(2),
                statistics_tree.topLevelItem(population_row).child(statistic_row).text(3),
            )
            for population_row in range(statistics_tree.topLevelItemCount())
            for statistic_row in range(
                statistics_tree.topLevelItem(population_row).childCount()
            )
        }
        assert gui_table == {
            "positive_count": ("3", "ok"),
            "positive_mean_y": ("30", "ok"),
        }

        project = window._build_project_manifest()
        api_report = PipelineRunner(project).run_samples(
            ExecutionContext(), tuple(window._sample_data.values())
        )
        api_results = {
            result.statistic_id: result
            for result in api_report.statistic_results
        }
        assert {
            statistic_id: (result.value, result.status)
            for statistic_id, result in api_results.items()
        } == {
            statistic_id: (result.value, result.status)
            for statistic_id, result in gui_results.items()
        }

        project_path = tmp_path / "statistics-consistency.flowdesk"
        save_project(project_path, project)
        cli_path = tmp_path / "statistics.tsv"
        assert run_project_command(
            str(project_path), statistics_output=str(cli_path)
        ) == 0
        with cli_path.open(encoding="utf-8") as fh:
            cli_rows = {
                row["statistic_id"]: row
                for row in csv.DictReader(fh, delimiter="\t")
            }

        assert set(cli_rows) == set(gui_results)
        for statistic_id, result in gui_results.items():
            assert float(cli_rows[statistic_id]["value"]) == pytest.approx(
                result.value
            )
            assert cli_rows[statistic_id]["status"] == result.status
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3d: GUI count matches headless runner count
# ---------------------------------------------------------------------------


def test_gui_population_count_matches_headless(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """GUI scatter point count matches membership mask sum."""
    fcs_path = tmp_path / "headlessmatch.fcs"
    np.random.seed(42)
    events = np.column_stack([
        np.random.exponential(100, 1000),
        np.random.exponential(50, 1000),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)

        # Rectangle gate
        gate = GateSpec(
            id="rect",
            name="rectangle",
            gate_type="rectangle",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            y_parameter=sample.info.channels[1].id,
            thresholds={"x_min": 50.0, "x_max": 200.0, "y_min": 20.0, "y_max": 100.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        report = window._population_tree.last_report()
        assert report is not None

        # Get headless membership mask sum for "rect"
        rect_mask = None
        for m in report.population_membership:
            if m.population_id == "rect" and m.sample_id == sample.id:
                rect_mask = m.mask
                break
        assert rect_mask is not None
        headless_count = int(rect_mask.sum())

        # Select gate population in GUI
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        assert window._plot_widget._scatter is not None
        gui_count = len(window._plot_widget._scatter.xData)
        assert gui_count == headless_count
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3e: Display downsampling does not change headless counts
# ---------------------------------------------------------------------------


def test_downsampling_does_not_change_headless_count(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Changing display downsample factor must not alter headless population counts."""
    fcs_path = tmp_path / "downsample.fcs"
    np.random.seed(99)
    events = np.column_stack([
        np.random.exponential(100, 500),
        np.random.exponential(50, 500),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)

        gate = GateSpec(
            id="rect",
            name="rectangle",
            gate_type="rectangle",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            y_parameter=sample.info.channels[1].id,
            thresholds={
                "x_min": 50.0,
                "x_max": 200.0,
                "y_min": 20.0,
                "y_max": 100.0,
            },
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        report = window._population_tree.last_report()
        assert report is not None

        headless_count = None
        for r in report.population_results:
            if r.population_id == "rect":
                headless_count = r.event_count
                break
        assert headless_count is not None

        # Select gate population, then change downsample factor
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        window._plot_widget.set_downsample(10)
        window._replot()
        qapp.processEvents()

        # Re-run pipeline: headless count must be unchanged
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        new_report = window._population_tree.last_report()
        assert new_report is not None
        for r in new_report.population_results:
            if r.population_id == "rect":
                assert r.event_count == headless_count
                break
        else:
            raise AssertionError("rect population not found in new report")
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 3-3f: Real FCS multi-sample membership switching
# ---------------------------------------------------------------------------


def test_real_fcs_multi_sample_membership_switch(
    qapp,
    gui_artifact_widgets: list[object],
) -> None:
    """Each sample uses its own membership mask when switching samples."""
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    fcs_files = sorted(data_dir.glob("*.fcs"))

    if len(fcs_files) < 2:
        pytest.skip("Need at least 2 real FCS files in data/")

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        loaded = window._sample_browser.add_samples_from_paths(
            [str(fcs_files[0]), str(fcs_files[1])]
        )
        assert loaded == 2

        samples = window._sample_browser.samples()
        sample1 = samples[0]
        sample2 = samples[1]

        # Select first sample (loads its events)
        assert window._sample_browser.select_sample(sample1.id)
        qapp.processEvents()

        # Pre-load sample 2 events so pipeline processes both samples
        window._load_sample_events(sample2)
        qapp.processEvents()

        channel_ids = [ch.id for ch in sample1.info.channels]
        x_ch = channel_ids[0]
        y_ch = channel_ids[1] if len(channel_ids) > 1 else channel_ids[0]

        data1 = window._event_data[sample1.id]
        mid_x = float(data1[:, 0].mean())
        gate = GateSpec(
            id="rect",
            name="rectangle",
            gate_type="rectangle",
            parent_population_id="all_events",
            x_parameter=x_ch,
            y_parameter=y_ch,
            thresholds={
                "x_min": mid_x,
                "x_max": mid_x * 3,
                "y_min": 0.0,
                "y_max": float(data1[:, 1].max() * 2),
            },
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        report = window._population_tree.last_report()
        assert report is not None

        # Verify membership exists for both samples
        membership_map = {}
        for m in report.population_membership:
            if m.population_id == "rect":
                membership_map[m.sample_id] = m

        assert sample1.id in membership_map
        assert sample2.id in membership_map

        count1 = int(membership_map[sample1.id].mask.sum())
        count2 = int(membership_map[sample2.id].mask.sum())

        # Select gate population on sample 1
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        assert window._plot_widget._scatter is not None
        assert len(window._plot_widget._scatter.xData) == count1

        # Switch to sample 2 — membership for sample 2 should be used
        assert window._sample_browser.select_sample(sample2.id)
        qapp.processEvents()

        assert len(window._plot_widget._scatter.xData) == count2
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# Phase 4: 1D histogram display (Count mode)
# ---------------------------------------------------------------------------


def test_count_mode_shows_histogram_not_scatter(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Setting Y axis to Count renders a histogram, not a scatter plot."""
    fcs_path = tmp_path / "histogram.fcs"
    np.random.seed(7)
    events = np.column_stack([
        np.random.exponential(100, 500),
        np.random.exponential(50, 500),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Initially in scatter mode
        assert window._plot_widget._scatter is not None
        assert window._plot_widget._is_histogram_mode is False

        # Switch Y to Count -> histogram mode
        window._channel_selector.set_selected_channels("FSC", COUNT_CHANNEL)
        qapp.processEvents()

        assert window._channel_selector.is_count_mode()
        assert window._plot_widget._is_histogram_mode is True
        # Scatter must be cleared in histogram mode
        assert window._plot_widget._scatter is None
        # Histogram item must exist
        assert window._plot_widget._histogram_item is not None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_histogram_bin_count_sum_matches_population(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Histogram bin heights sum to the population event count."""
    fcs_path = tmp_path / "histcount.fcs"
    np.random.seed(13)
    n_events = 1000
    events = np.column_stack([
        np.random.normal(50, 10, n_events),
        np.random.normal(30, 5, n_events),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Switch to histogram mode
        window._channel_selector.set_selected_channels("FSC", COUNT_CHANNEL)
        qapp.processEvents()

        assert window._plot_widget._is_histogram_mode
        hist_item = window._plot_widget._histogram_item
        assert hist_item is not None

        # BarGraphItem stores heights; sum of heights should equal event count
        heights = np.asarray(hist_item.opts.get("height", []))
        total = int(np.sum(heights))
        assert total == n_events
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_switching_back_from_count_restores_scatter(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Switching Y from Count back to a real channel restores scatter plot."""
    fcs_path = tmp_path / "restorescatter.fcs"
    np.random.seed(21)
    events = np.column_stack([
        np.random.exponential(100, 500),
        np.random.exponential(50, 500),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Go to histogram mode
        window._channel_selector.set_selected_channels("FSC", COUNT_CHANNEL)
        qapp.processEvents()
        assert window._plot_widget._is_histogram_mode is True
        assert window._plot_widget._scatter is None

        # Switch back to normal scatter
        window._channel_selector.set_selected_channels("FSC", "SSC")
        qapp.processEvents()

        assert window._plot_widget._is_histogram_mode is False
        assert window._plot_widget._scatter is not None
        assert window._plot_widget._histogram_item is None
        assert len(window._plot_widget._scatter.xData) == 500
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_count_mode_y_transform_disabled(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Y transform combo box is disabled in Count mode."""
    fcs_path = tmp_path / "ydisabled.fcs"
    events = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Y transform enabled in scatter mode
        assert window._channel_selector._y_transform_combo.isEnabled()

        # Switch to Count mode
        window._channel_selector.set_selected_channels("FSC", COUNT_CHANNEL)
        qapp.processEvents()
        assert not window._channel_selector._y_transform_combo.isEnabled()

        # Switch back to scatter mode
        window._channel_selector.set_selected_channels("FSC", "SSC")
        qapp.processEvents()
        assert window._channel_selector._y_transform_combo.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_count_mode_with_population_filter(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Histogram respects population membership filter."""
    fcs_path = tmp_path / "histpop.fcs"
    events = np.array(
        [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Range gate: X >= 2.0 selects 3 events
        gate = GateSpec(
            id="pos",
            name="positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"min": 2.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        # Switch to histogram mode
        window._channel_selector.set_selected_channels("X", COUNT_CHANNEL)
        qapp.processEvents()

        # all_events histogram: 4 events
        hist_item = window._plot_widget._histogram_item
        assert hist_item is not None
        heights_all = np.asarray(hist_item.opts.get("height", []))
        assert int(np.sum(heights_all)) == 4

        # Select gate population -> histogram shows only 3 events
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        hist_item = window._plot_widget._histogram_item
        assert hist_item is not None
        heights_filtered = np.asarray(hist_item.opts.get("height", []))
        assert int(np.sum(heights_filtered)) == 3
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# Phase 5: Marginal histograms
# ---------------------------------------------------------------------------


def test_marginal_histograms_toggle(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Toggling marginal histograms on and off works correctly."""
    fcs_path = tmp_path / "marginal.fcs"
    np.random.seed(42)
    events = np.column_stack([
        np.random.exponential(100, 500),
        np.random.exponential(50, 500),
    ]).astype(np.float64)
    write_fcs_file(fcs_path, events, ["FSC", "SSC"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Marginal histograms disabled by default
        assert window._plot_widget.is_marginal_enabled() is False
        assert window._plot_toolbar.is_marginal_enabled() is False

        # Enable marginal histograms
        window._plot_widget.set_marginal_enabled(True)
        window._plot_toolbar.set_marginal_enabled(True)
        window._replot()
        qapp.processEvents()

        assert window._plot_widget.is_marginal_enabled() is True
        assert window._plot_toolbar.is_marginal_enabled() is True

        # Marginal plots should exist
        assert window._plot_widget._marginal_x_plot is not None
        assert window._plot_widget._marginal_y_plot is not None

        # Disable marginal histograms
        window._plot_widget.set_marginal_enabled(False)
        window._plot_toolbar.set_marginal_enabled(False)
        window._replot()
        qapp.processEvents()

        assert window._plot_widget.is_marginal_enabled() is False
        assert window._plot_toolbar.is_marginal_enabled() is False
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_marginal_histograms_respect_population_filter(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Marginal histograms respect population membership filter."""
    fcs_path = tmp_path / "marginalpop.fcs"
    events = np.array(
        [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
        dtype=np.float64,
    )
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Range gate: X >= 2.0 selects 3 events
        gate = GateSpec(
            id="pos",
            name="positive",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter=sample.info.channels[0].id,
            thresholds={"min": 2.0},
        )
        window._gate_editor.set_gates([gate])
        window._on_run_pipeline()
        _wait_for_worker(window)
        qapp.processEvents()

        # Enable marginal histograms
        window._plot_widget.set_marginal_enabled(True)
        window._replot()
        qapp.processEvents()

        # all_events: marginal histograms should have 4 events
        assert window._plot_widget._marginal_x_plot is not None
        assert window._plot_widget._marginal_y_plot is not None

        # Select gate population -> marginal histograms show 3 events
        table = window._population_tree._table
        table.selectRow(1)
        qapp.processEvents()

        # Scatter shows 3 events
        assert len(window._plot_widget._scatter.xData) == 3
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_marginal_histogram_toolbar_checkbox(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """The toolbar checkbox toggles marginal histograms via callback."""
    fcs_path = tmp_path / "marginalcb.fcs"
    events = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Check that the checkbox exists
        assert window._plot_toolbar._marginal_checkbox is not None
        assert window._plot_toolbar._marginal_checkbox.isChecked() is False

        # Check the checkbox programmatically
        window._plot_toolbar._marginal_checkbox.setChecked(True)
        qapp.processEvents()

        assert window._plot_toolbar.is_marginal_enabled() is True
        assert window._plot_widget.is_marginal_enabled() is True
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_marginal_histograms_persist_in_debug_state(
    qapp,
    tmp_path: Path,
    gui_artifact_widgets: list[object],
) -> None:
    """Marginal histogram state is included in debug state dump."""
    fcs_path = tmp_path / "debugstate.fcs"
    events = np.array([[1.0, 2.0]], dtype=np.float64)
    write_fcs_file(fcs_path, events, ["X", "Y"])

    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        window.show()
        assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
        sample = window._sample_browser.samples()[0]
        assert window._sample_browser.select_sample(sample.id)
        qapp.processEvents()

        # Enable marginal
        window._plot_widget.set_marginal_enabled(True)
        qapp.processEvents()

        debug_state = window.debug_state()
        assert debug_state["plot"]["marginal_enabled"] is True

        # Disable marginal
        window._plot_widget.set_marginal_enabled(False)
        qapp.processEvents()

        debug_state = window.debug_state()
        assert debug_state["plot"]["marginal_enabled"] is False
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_histogram_log10_excludes_nonpositive_once(
    qapp,
    gui_artifact_widgets: list[object],
) -> None:
    """Log histogram keeps every finite positive event and remains JSON-safe."""
    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        plot = window._plot_widget
        plot.set_axis_transforms("log10", "linear")
        plot.plot_histogram(
            np.array([-1.0, 0.0, 0.1, 1.0, 10.0, np.nan]),
            x_label="X",
        )
        heights = np.asarray(plot._histogram_item.opts["height"])
        assert int(heights.sum()) == 3
        assert plot.display_state()["excluded_event_count"] == 3
        json.dumps(window.debug_state())
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_marginal_control_and_right_histogram_orientation(
    qapp,
    gui_artifact_widgets: list[object],
) -> None:
    """Marginal control is stable and the right histogram extends horizontally."""
    window = MainWindow()
    gui_artifact_widgets.append(window)
    try:
        button = window._plot_toolbar._marginal_checkbox
        assert button.objectName() == "toggleMarginalHistogramsButton"
        window._plot_widget.set_marginal_enabled(True)
        window._plot_widget.plot_events(
            np.array([1.0, 2.0, 3.0]),
            np.array([4.0, 5.0, 6.0]),
        )
        opts = window._plot_widget._marginal_y_item.opts
        assert "y" in opts
        assert "width" in opts
        assert np.asarray(opts["width"]).sum() == 3

        window._plot_widget.plot_histogram(np.array([1.0, 2.0, 3.0]))
        assert window._plot_widget._marginal_x_plot is None
        assert window._plot_widget._marginal_y_plot is None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
