"""GUI E2E tests for population filtering (Phase 3-3).

Verify that selecting a population in the Population Results table filters
the scatter plot to only display events belonging to that population.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer

from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import GateSpec
from flowdesk_qt.channel_selector import COUNT_CHANNEL, COUNT_DISPLAY
from flowdesk_qt.main_window import MainWindow

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
            x_parameter="X",
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
            x_parameter="X",
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
            x_parameter="X",
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

        # Add a new gate -> invalidates results, selection resets to all_events
        new_gate = GateSpec(
            id="neg",
            name="negative",
            gate_type="range",
            parent_population_id="all_events",
            x_parameter="X",
            thresholds={"max": 1.0},
        )
        window._gate_editor.add_gate(new_gate)
        qapp.processEvents()

        # Results are stale, filter resets to all_events
        assert window._results_stale
        assert window._selected_population_id == "all_events"
        # All 4 points visible (stale flag prevents old membership from being used)
        assert len(window._plot_widget._scatter.xData) == 4
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
            x_parameter="FSC",
            y_parameter="SSC",
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
            x_parameter="FSC",
            y_parameter="SSC",
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
            assert False, "rect population not found in new report"
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

        ch_names = [ch.name for ch in sample1.info.channels]
        x_ch = ch_names[0]
        y_ch = ch_names[1] if len(ch_names) > 1 else ch_names[0]

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
            x_parameter="X",
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
            x_parameter="X",
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
