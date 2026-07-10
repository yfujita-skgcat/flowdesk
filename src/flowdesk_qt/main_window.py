"""Main window for Flowdesk.

Assembles the UI components and delegates all scientific computation to
``flowdesk_core.pipeline_runner``.  This module contains NO analysis logic.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QWidget,
)

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import read_fcs_events
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_qt.channel_selector import ChannelSelector
from flowdesk_qt.gate_editor import GateEditor
from flowdesk_qt.plot_toolbar import PlotToolbar
from flowdesk_qt.plot_widget import PlotWidget
from flowdesk_qt.population_tree import PopulationTree
from flowdesk_qt.sample_browser import SampleBrowser, _SampleInfo
from flowdesk_storage.project import load_project, resolve_sample_paths, save_project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background worker for pipeline execution
# ---------------------------------------------------------------------------


class _PipelineWorker(QThread):
    """Runs pipeline execution in a background thread.

    The resulting ``ExecutionReport`` (or exception) is stored as an
    instance attribute so the GUI thread can retrieve it after
    ``finished`` is emitted.
    """

    def __init__(
        self,
        project: dict[str, Any],
        event_data: dict[str, NDArray[np.float64]],
        channel_names: list[str],
        profile_id: str = "default",
    ) -> None:
        super().__init__()
        self._project = project
        self._event_data = event_data
        self._channel_names = channel_names
        self._profile_id = profile_id
        self._report: Any = None
        self._error: Exception | None = None

    def run(self) -> None:
        try:
            runner = PipelineRunner(self._project)
            ctx = ExecutionContext(execution_profile_id=self._profile_id)
            self._report = runner.run(ctx, self._event_data, self._channel_names)
            logger.info("Pipeline completed: %s", self._report.summary)
        except Exception as exc:
            self._error = exc
            logger.error("Pipeline failed: %s", exc)
        # QThread.finished is emitted automatically when run() returns.


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """Main application window.

    Layout:
      - Left: SampleBrowser
      - Center: PlotWidget with ChannelSelector above
      - Right: GateEditor above PopulationTree
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("flowdeskMainWindow")
        self.setWindowTitle("Flowdesk")
        self.resize(1400, 900)

        # Internal state
        self._event_data: dict[str, NDArray[np.float64]] = {}
        self._channel_names: list[str] = []
        self._current_sample_id: str | None = None
        self._worker: _PipelineWorker | None = None
        self._results_stale = False
        self._project_id = "flowdesk_session"
        self._project_path: Path | None = None

        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._connect_signals()
        self._update_status("Ready")

    # -- public API ----------------------------------------------------------

    def load_samples_from_directory(self, directory: str | Path) -> int:
        """Load FCS samples from a directory."""
        return self._sample_browser.add_samples_from_directory(directory)

    def debug_state(self) -> dict[str, object]:
        """Return JSON-serializable GUI state without raw event arrays."""
        worker = self._worker
        report = self._population_tree.last_report()
        worker_error = None if worker is None else worker._error
        return {
            "application": {"name": "Flowdesk", "version": "0.1.0"},
            "window": {
                "title": self.windowTitle(),
                "visible": self.isVisible(),
                "enabled": self.isEnabled(),
            },
            "project": {
                "id": self._project_id,
                "path": None if self._project_path is None else str(self._project_path),
            },
            "current_sample_id": self._current_sample_id,
            "samples": [
                {
                    "id": sample.id,
                    "name": sample.name,
                    "path": sample.path,
                    "event_count": sample.info.event_count,
                    "channel_count": sample.info.channel_count,
                }
                for sample in self._sample_browser.samples()
            ],
            "axes": {
                "x_channel": self._channel_selector.x_channel(),
                "y_channel": self._channel_selector.y_channel(),
                "x_transform": self._channel_selector.x_transform(),
                "y_transform": self._channel_selector.y_transform(),
            },
            "plot": {
                "range_mode": self._plot_widget.range_mode(),
                "view_range": self._plot_widget.view_range(),
                "active_gate_creation": self._plot_widget._active_gate_creation,
            },
            "gates": [asdict(gate) for gate in self._gate_editor.gates()],
            "gate_editor": {
                "selected_row": self._gate_editor._list_widget.currentRow(),
                "status": self._gate_editor._status_label.text(),
            },
            "pipeline": {
                "worker_present": worker is not None,
                "running": worker is not None and worker.isRunning(),
                "error_type": None if worker_error is None else type(worker_error).__name__,
                "error_message": None if worker_error is None else str(worker_error),
            },
            "population_report": {
                "status": None if report is None else report.status,
                "counts": {}
                if report is None
                else {
                    result.population_id: result.event_count
                    for result in report.population_results
                },
            },
            "results_stale": self._results_stale,
            "status": self.statusBar().currentMessage(),
        }

    # -- menu ----------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        self.action_open_directory = QAction("&Open Directory...", self)
        self.action_open_directory.setObjectName("actionOpenDirectory")
        self.action_open_directory.setShortcut(QKeySequence.Open)
        self.action_open_directory.triggered.connect(self._on_open_directory)
        file_menu.addAction(self.action_open_directory)

        self.action_open_files = QAction("Open &Files...", self)
        self.action_open_files.setObjectName("actionOpenFiles")
        self.action_open_files.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.action_open_files.triggered.connect(self._on_open_files)
        file_menu.addAction(self.action_open_files)

        self.action_open_project = QAction("Open &Project...", self)
        self.action_open_project.setObjectName("actionOpenProject")
        self.action_open_project.triggered.connect(self._on_open_project)
        file_menu.addAction(self.action_open_project)

        self.action_save_project = QAction("&Save Project...", self)
        self.action_save_project.setObjectName("actionSaveProject")
        self.action_save_project.setShortcut(QKeySequence.Save)
        self.action_save_project.triggered.connect(self._on_save_project)
        file_menu.addAction(self.action_save_project)

        file_menu.addSeparator()

        self.action_export_results = QAction("Export Population &Results...", self)
        self.action_export_results.setObjectName("actionExportResults")
        self.action_export_results.triggered.connect(self._on_export_population_results)
        file_menu.addAction(self.action_export_results)

        file_menu.addSeparator()

        self.action_quit = QAction("E&xit", self)
        self.action_quit.setObjectName("actionQuit")
        self.action_quit.setShortcut(QKeySequence.Quit)
        self.action_quit.triggered.connect(self.close)
        file_menu.addAction(self.action_quit)

        # Analysis menu
        analysis_menu = menubar.addMenu("&Analysis")

        self.action_run_pipeline = QAction("&Run Pipeline", self)
        self.action_run_pipeline.setObjectName("actionRunPipeline")
        self.action_run_pipeline.setShortcut(QKeySequence("Ctrl+R"))
        self.action_run_pipeline.triggered.connect(self._on_run_pipeline)
        analysis_menu.addAction(self.action_run_pipeline)

        analysis_menu.addSeparator()

        self.action_clear_gates = QAction("Clear &Gates", self)
        self.action_clear_gates.setObjectName("actionClearGates")
        self.action_clear_gates.setShortcut(QKeySequence("Ctrl+G"))
        self.action_clear_gates.triggered.connect(self._on_clear_gates)
        analysis_menu.addAction(self.action_clear_gates)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        action_about = QAction("&About Flowdesk", self)
        action_about.triggered.connect(self._on_about)
        help_menu.addAction(action_about)

    # -- toolbar -------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        action_open = QAction("Open Samples", self)
        action_open.triggered.connect(self._on_open_directory)
        toolbar.addAction(action_open)

        toolbar.addSeparator()

        action_run = QAction("Run Pipeline", self)
        action_run.triggered.connect(self._on_run_pipeline)
        toolbar.addAction(action_run)

        toolbar.addSeparator()

        action_export_results = QAction("Export Results", self)
        action_export_results.triggered.connect(self._on_export_population_results)
        toolbar.addAction(action_export_results)

    # -- central widget ------------------------------------------------------

    def _build_central_widget(self) -> None:
        # --- Left pane: sample browser ---
        self._sample_browser = SampleBrowser()

        # --- Center pane: channel selector + plot ---
        self._channel_selector = ChannelSelector()
        self._plot_widget = PlotWidget()
        self._plot_widget.set_downsample(1)

        center_widget = self._create_center_pane()

        # --- Right pane: gate editor + population tree ---
        self._gate_editor = GateEditor()
        self._population_tree = PopulationTree()

        right_widget = self._create_right_pane()

        # --- Assemble with splitters ---
        splitter1 = QSplitter(Qt.Horizontal)
        splitter1.setObjectName("mainContentSplitter")
        splitter1.addWidget(self._sample_browser)
        splitter1.addWidget(center_widget)
        splitter1.setStretchFactor(0, 1)
        splitter1.setStretchFactor(1, 3)

        splitter2 = QSplitter(Qt.Horizontal)
        splitter2.setObjectName("mainOuterSplitter")
        splitter2.addWidget(splitter1)
        splitter2.addWidget(right_widget)
        splitter2.setStretchFactor(0, 4)
        splitter2.setStretchFactor(1, 2)

        self.setCentralWidget(splitter2)
        self.statusBar().setObjectName("mainStatusBar")

    def _create_center_pane(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        self._plot_toolbar = PlotToolbar()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._channel_selector)
        layout.addWidget(self._plot_toolbar)
        layout.addWidget(self._plot_widget)
        layout.setStretch(0, 0)
        layout.setStretch(1, 0)
        layout.setStretch(2, 1)
        return widget

    def _create_right_pane(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._gate_editor)
        layout.addWidget(self._population_tree)
        layout.setStretch(0, 1)
        layout.setStretch(1, 1)
        return widget

    # -- signal connections --------------------------------------------------

    def _connect_signals(self) -> None:
        # When a sample is selected, load its channels and plot
        self._sample_browser.on_sample_selected(self._on_sample_selected)

        # When a sample is removed, clean up its associated state
        self._sample_browser.on_sample_removed(self._on_sample_removed)

        # When channel selection changes, replot
        self._channel_selector.on_channel_changed(self._on_channel_changed)

        # When a gate is selected, update highlight
        self._gate_editor.on_gate_selected(self._on_gate_selected)

        # When the gate list changes (add/delete/clear), refresh overlays and invalidate results
        self._gate_editor.on_gates_changed(self._on_gates_changed)

        # Interactive gate creation starts from the gate editor.
        self._gate_editor.on_interactive_gate_requested(self._on_interactive_gate_requested)

        # Plot toolbar callbacks
        self._plot_toolbar.on_reset_robust(self._on_reset_robust)
        self._plot_toolbar.on_reset_full(self._on_reset_full)
        self._plot_toolbar.on_export_png(self._on_export_png)

        # Connect plot mouse events to gate creation
        self._plot_widget.on_mouse_clicked(self._on_plot_mouse_clicked)
        self._plot_widget.on_gate_geometry_changed(self._on_gate_geometry_changed)

    # -- sample handling -----------------------------------------------------

    def _on_sample_selected(self, sample: _SampleInfo) -> None:
        """Called when the user selects a sample in the browser."""
        previous_x = self._channel_selector.x_channel()
        previous_y = self._channel_selector.y_channel()
        self._current_sample_id = sample.id
        self._channel_names = [ch.name for ch in sample.info.channels]
        x_preserved, y_preserved = self._channel_selector.set_channels(self._channel_names)

        status = (
            f"Selected: {sample.name}  ({sample.info.event_count} events, "
            f"{sample.info.channel_count} channels)"
        )
        if previous_x and not x_preserved:
            status += f" | X fallback: {previous_x} not in sample"
        if previous_y and not y_preserved:
            status += f" | Y fallback: {previous_y} not in sample"
        self._update_status(status)

        # Load event data if not already loaded
        if sample.id not in self._event_data:
            self._load_sample_events(sample)

        # Replot with current channel selection
        self._replot()

    def _on_sample_removed(self, sample: _SampleInfo) -> None:
        """Called when a sample is removed from the browser."""
        # Remove event data for this sample
        self._event_data.pop(sample.id, None)
        self._mark_results_stale(f"Removed: {sample.name}")

        # If the removed sample was the currently selected one, clear UI state
        if self._current_sample_id == sample.id:
            self._current_sample_id = None
            self._channel_names = []
            self._channel_selector.set_channels([])
            self._plot_widget.clear_plot()

    def _load_sample_events(self, sample: _SampleInfo) -> None:
        """Load FCS event data for a sample."""
        try:
            _, events = read_fcs_events(sample.path)
            self._event_data[sample.id] = events
            logger.info("Loaded %d events for sample %s", events.shape[0], sample.id)
        except Exception as exc:
            logger.error("Failed to load events for %s: %s", sample.id, exc)
            self._update_status(f"Error loading {sample.name}: {exc}")

    def _on_gates_changed(self) -> None:
        """Called when the gate list changes (add/delete/clear).

        Refresh overlays and invalidate cached population results.
        """
        self._population_tree.set_population_parents(self._population_parent_map())
        self._mark_results_stale("Gates changed")
        self._replot()

    # -- channel selection ---------------------------------------------------

    def _on_channel_changed(self, x_name: str, y_name: str) -> None:
        """Called when X or Y channel selection changes."""
        self._replot()

    def _replot(self) -> None:
        """Replot the current sample with current channel selection and axis transforms."""
        if self._current_sample_id is None:
            return

        data = self._event_data.get(self._current_sample_id)
        if data is None or not self._channel_names:
            return

        x_name = self._channel_selector.x_channel()
        y_name = self._channel_selector.y_channel()

        # Sync gate editor with current channels
        self._gate_editor.set_plot_channels(x_name, y_name)

        x_idx = self._get_channel_index(x_name)
        y_idx = self._get_channel_index(y_name)

        if x_idx < 0 or y_idx < 0:
            return

        x_data = data[:, x_idx]
        y_data = data[:, y_idx]

        # Apply axis transform settings to the plot widget.
        x_transform = self._channel_selector.x_transform()
        y_transform = self._channel_selector.y_transform()
        self._plot_widget.set_axis_transforms(x_transform, y_transform)

        self._plot_widget.plot_events(x_data, y_data, x_label=x_name, y_label=y_name)

        # Refresh gate overlays
        self._plot_widget.clear_gates()
        for idx, gate in enumerate(self._gate_editor.gates()):
            if gate.x_parameter == x_name and gate.y_parameter == y_name:
                self._plot_widget.add_gate_overlay(gate, idx)

    def _get_channel_index(self, channel_name: str) -> int:
        """Get the column index for a channel name."""
        try:
            return self._channel_names.index(channel_name)
        except (ValueError, AttributeError):
            return -1

    # -- gate handling -------------------------------------------------------

    def _on_gate_selected(self, gate_index: int) -> None:
        """Called when a gate is selected in the gate editor."""
        # Highlight the selected gate overlay with a solid pen
        self._plot_widget.highlight_gate_index(gate_index)

    def _on_clear_gates(self) -> None:
        """Clear all gates."""
        self._plot_widget.clear_gate_creation()
        self._gate_editor.cancel_polygon()
        self._gate_editor.clear_gates()
        self._plot_widget.clear_gates()
        self._mark_results_stale("Gates cleared")

    # -- pipeline execution --------------------------------------------------

    def _on_run_pipeline(self) -> None:
        """Run the analysis pipeline on loaded samples."""
        if not self._event_data:
            QMessageBox.information(
                self,
                "No samples",
                "No samples loaded. Open a directory or files first.",
            )
            return

        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Pipeline running",
                "A pipeline execution is already in progress. Please wait.",
            )
            return

        if not self._all_loaded_samples_share_channels():
            QMessageBox.critical(
                self,
                "Channel mismatch",
                "Loaded samples have different channel names. Run Pipeline is blocked "
                "until per-sample channel mapping is implemented.",
            )
            return

        project = self._build_project_manifest()
        self._update_status("Running pipeline...")
        self._worker = _PipelineWorker(
            project,
            self._event_data,
            self._channel_names,
        )
        self._worker.finished.connect(self._on_pipeline_finished)
        self._worker.start()

    def _build_project_manifest(self) -> dict[str, Any]:
        """Build a project manifest from current UI state.

        This constructs a minimal project dictionary that the PipelineRunner
        can consume.  Gate definitions from the gate editor are included.
        """
        samples = []
        sample_lookup = {sample.id: sample for sample in self._sample_browser.samples()}
        for sid in self._event_data:
            sample_info = sample_lookup.get(sid)
            if sample_info is None:
                samples.append({"id": sid, "name": sid, "path": ""})
                continue
            samples.append(
                {
                    "id": sid,
                    "name": sample_info.name,
                    "path": sample_info.path,
                }
            )

        gates_list = list(self._gate_editor.gates())

        strategy = {
            "id": "default_strategy",
            "name": "Default Strategy",
            "gates": [asdict(gate) for gate in gates_list],
            "root_population_id": "all_events",
            "notes": "",
        }

        project: dict[str, Any] = {
            "project_id": self._project_id,
            "project_version": "1.0.0",
            "pipeline_version": "0.1",
            "samples": samples,
            "execution_profiles": [
                {
                    "id": "default",
                    "name": "Default Profile",
                    "sample_selector": "all",
                    "gating_strategy_id": "default_strategy",
                }
            ],
            "gating_strategies_data": {
                "default_strategy": strategy,
            },
            "derived_parameters": [],
            "transforms": [],
            "compensation_matrices": [],
            "sample_path_resolution_policy": "relative_to_project_or_absolute",
            "plot_display_settings": {
                "selected_sample_id": self._current_sample_id,
                "x_channel": self._channel_selector.x_channel(),
                "y_channel": self._channel_selector.y_channel(),
                "x_scale": self._channel_selector.x_transform(),
                "y_scale": self._channel_selector.y_transform(),
            },
        }

        return project

    def _on_pipeline_finished(self) -> None:
        """Handle pipeline completion by retrieving results from the worker."""
        if self._worker is None:
            return

        worker = self._worker
        if worker._error is not None:
            exc = worker._error
            logger.error("Pipeline execution failed: %s", exc)
            self._update_status(f"Pipeline error: {exc}")
            QMessageBox.critical(self, "Pipeline Error", str(exc))
            self._release_pipeline_worker(worker)
            return

        report = worker._report
        if report is not None:
            self._population_tree.set_population_names(self._population_name_map())
            self._population_tree.set_report(report)
            self._results_stale = False
            self._update_status(f"Pipeline complete: {report.summary}")
        else:
            self._update_status("Pipeline finished with no report")

        self._release_pipeline_worker(worker)

    def _release_pipeline_worker(self, worker: _PipelineWorker) -> None:
        """Disconnect and schedule a completed worker for Qt-owned deletion."""
        try:
            worker.finished.disconnect(self._on_pipeline_finished)
        except (RuntimeError, TypeError):
            pass
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Do not destroy the window while its pipeline thread is running."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait()
        if worker is not None:
            self._release_pipeline_worker(worker)
        super().closeEvent(event)

    # -- file handling -------------------------------------------------------

    def _on_open_directory(self) -> None:
        """Open a directory dialog and load FCS files."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select directory containing FCS files",
            "",
        )
        if not directory:
            return

        count = self._sample_browser.add_samples_from_directory(directory)
        self._update_status(f"Loaded {count} samples from {directory}")

    def _on_open_files(self) -> None:
        """Open a file dialog and load selected FCS files."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select FCS files",
            "",
            "FCS files (*.fcs);;All files (*)",
        )
        if not paths:
            return

        count = self._sample_browser.add_samples_from_paths(paths)
        self._update_status(f"Loaded {count} samples")

    def _on_save_project(self) -> None:
        """Save current analysis and display state as a project bundle."""
        initial = str(self._project_path or Path.cwd())
        path_str = QFileDialog.getExistingDirectory(
            self,
            "Select project bundle directory",
            initial,
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix != ".flowdesk":
            path = path.with_suffix(".flowdesk")
        try:
            self._save_project_to_path(path)
            self._update_status(f"Project saved to {path}")
        except Exception as exc:
            logger.error("Project save failed: %s", exc)
            QMessageBox.critical(self, "Project Save Error", str(exc))

    def _save_project_to_path(self, path: str | Path) -> None:
        """Save current project state through the storage API."""
        project_path = Path(path)
        save_project(project_path, self._build_project_manifest())
        self._project_path = project_path

    def _on_open_project(self) -> None:
        path_str = QFileDialog.getExistingDirectory(
            self,
            "Open Flowdesk Project",
            str(self._project_path or Path.cwd()),
        )
        if not path_str:
            return
        try:
            self._load_project_from_path(path_str)
            self._update_status(f"Project loaded from {path_str}")
        except Exception as exc:
            logger.error("Project load failed: %s", exc)
            QMessageBox.critical(self, "Project Load Error", str(exc))

    def _load_project_from_path(self, path: str | Path) -> None:
        """Load saved samples, gates, and display-only plot settings."""
        project_path = Path(path)
        manifest = load_project(project_path)
        strategy_data = manifest.get("gating_strategies_data", {}).get(
            "default_strategy",
            {"id": "default_strategy", "name": "Default Strategy", "gates": []},
        )
        strategy = PipelineRunner._strategy_from_mapping(strategy_data)

        self._sample_browser.clear_samples()
        self._event_data.clear()
        self._current_sample_id = None
        self._channel_names = []
        self._gate_editor.set_gates(list(strategy.gates), notify=False)
        self._population_tree.set_population_parents(self._population_parent_map())

        resolved_samples = resolve_sample_paths(manifest, project_path)
        self._sample_browser.add_samples_from_paths(
            [str(sample["path"]) for sample in resolved_samples]
        )
        display = manifest.get("plot_display_settings", {})
        self._channel_selector.set_x_transform(display.get("x_scale", "linear"))
        self._channel_selector.set_y_transform(display.get("y_scale", "linear"))

        selected_id = display.get("selected_sample_id")
        if selected_id is None and resolved_samples:
            selected_id = resolved_samples[0].get("id")
        if selected_id is not None:
            self._sample_browser.select_sample(str(selected_id))
            self._channel_selector.set_selected_channels(
                str(display.get("x_channel", "")),
                str(display.get("y_channel", "")),
            )

        self._project_id = str(manifest["project_id"])
        self._project_path = project_path
        self._mark_results_stale("Project loaded")

    def _population_parent_map(self) -> dict[str, str | None]:
        parents = {"all_events": None}
        parents.update(
            {gate.id: gate.parent_population_id for gate in self._gate_editor.gates()}
        )
        return parents

    def _population_name_map(self) -> dict[str, str]:
        """Build a mapping from population ID to human-readable display name."""
        names = {"all_events": "All Events"}
        names.update({gate.id: gate.name for gate in self._gate_editor.gates()})
        return names

    # -- plot mouse handlers -------------------------------------------------

    def _on_plot_mouse_clicked(
        self,
        data_x: float,
        data_y: float,
        is_double_click: bool,
        dragging: bool = False,
        rect_end_x: float | None = None,
        rect_end_y: float | None = None,
    ) -> None:
        """Handle mouse clicks on the plot for gate creation."""
        # Rectangle gate completion (drag release)
        if not dragging and rect_end_x is not None and rect_end_y is not None:
            self._create_rectangle_gate(data_x, data_y, rect_end_x, rect_end_y)
            self._plot_widget.clear_gate_creation()
            return

        # Polygon vertex collection
        if self._gate_editor.is_collecting_polygon():
            if is_double_click:
                # Double-click marks the final vertex and finishes the polygon.
                self._gate_editor.receive_polygon_vertex(data_x, data_y)
                self._plot_widget.add_polygon_preview_vertex(data_x, data_y)
                self._gate_editor.finish_polygon_gate()
                self._plot_widget.clear_gate_creation()
                self._update_status("Polygon gate completed")
            else:
                # Single click adds a vertex
                self._gate_editor.receive_polygon_vertex(data_x, data_y)
                self._plot_widget.add_polygon_preview_vertex(data_x, data_y)
            return

    def _create_rectangle_gate(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """Create a rectangle gate from two drag endpoints."""
        from flowdesk_core.models import GateSpec

        x_min = min(x1, x2)
        x_max = max(x1, x2)
        y_min = min(y1, y2)
        y_max = max(y1, y2)

        # Avoid degenerate rectangles
        if abs(x_max - x_min) < 1e-10 or abs(y_max - y_min) < 1e-10:
            return

        x_name = self._channel_selector.x_channel()
        y_name = self._channel_selector.y_channel()

        import uuid

        gate = GateSpec(
            id=f"gate_{uuid.uuid4().hex[:8]}",
            name=f"rect_{len(self._gate_editor.gates()) + 1}",
            gate_type="rectangle",
            parent_population_id=self._gate_editor.parent_population(),
            x_parameter=x_name,
            y_parameter=y_name,
            thresholds={
                "x_min": x_min,
                "x_max": x_max,
                "y_min": y_min,
                "y_max": y_max,
            },
        )
        self._gate_editor.add_gate(gate)
        self._update_status(f"Rectangle gate created: {gate.name}")

    def _on_gate_geometry_changed(self, gate_index: int, gate) -> None:
        """Persist interactive ROI edits back into the gate editor and invalidate results."""
        self._gate_editor.update_gate(gate_index, gate, notify=True)
        self._mark_results_stale(f"Gate updated: {gate.name}")

    # -- plot toolbar handlers -----------------------------------------------

    def _on_interactive_gate_requested(self, gate_type: str) -> bool:
        """Start plot-based gate creation from the gate editor."""
        if self._current_sample_id is None:
            QMessageBox.information(
                self,
                "No sample",
                "Load and select a sample before creating a gate.",
            )
            return False

        if gate_type == "rectangle":
            self._gate_editor.cancel_polygon()
            self._plot_widget.begin_gate_creation("rectangle")
            self._update_status("Drag on the plot to create a rectangle gate.")
            return True

        if gate_type == "polygon":
            self._plot_widget.begin_gate_creation("polygon")
            self._gate_editor.start_polygon_collection()
            self._update_status("Click polygon vertices on the plot. Double-click to finish.")
            return True

        return False

    def _on_reset_robust(self) -> None:
        """Reset viewport to robust auto-range."""
        self._plot_widget.set_robust_range()
        self._update_status("Viewport reset to robust range")

    def _on_reset_full(self) -> None:
        """Reset viewport to full data range."""
        self._plot_widget.set_full_range()
        self._update_status("Viewport reset to full range")

    def _on_export_png(self) -> None:
        """Export current plot view to PNG."""
        path_str = QFileDialog.getSaveFileName(
            self,
            "Export Plot as PNG",
            "",
            "PNG files (*.png)",
        )[0]
        if not path_str:
            return
        try:
            self._plot_widget.export_png(path_str)
            self._update_status(f"Plot exported to {path_str}")
        except Exception as exc:
            logger.error("PNG export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_export_population_results(self) -> None:
        """Export population statistics from the latest non-stale report."""
        report = self._population_tree.last_report()
        if report is None or not report.population_results:
            QMessageBox.information(
                self,
                "No results",
                "Run Pipeline before exporting Population Results.",
            )
            return
        if self._results_stale:
            QMessageBox.information(
                self,
                "Results stale",
                "Population Results are stale. Run Pipeline again before exporting.",
            )
            return

        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Population Results",
            "",
            "TSV files (*.tsv);;CSV files (*.csv);;All files (*)",
        )
        if not path_str:
            return
        delimiter = "," if selected_filter.startswith("CSV") or path_str.endswith(".csv") else "\t"
        try:
            self._export_population_results_to_path(path_str, delimiter=delimiter)
            self._update_status(f"Population Results exported to {path_str}")
        except Exception as exc:
            logger.error("Population Results export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_population_results_to_path(
        self,
        path: str | Path,
        delimiter: str = "\t",
    ) -> None:
        """Write current non-stale population results using core export helpers."""
        if self._results_stale:
            raise RuntimeError("Population Results are stale; rerun pipeline before export")
        report = self._population_tree.last_report()
        if report is None or not report.population_results:
            raise RuntimeError("No Population Results available for export")

        from flowdesk_core.export import write_population_results

        write_population_results(list(report.population_results), path, delimiter=delimiter)

    def _mark_results_stale(self, reason: str) -> None:
        self._results_stale = True
        self._population_tree.clear()
        self._update_status(f"{reason} (results stale; rerun pipeline)")

    def _all_loaded_samples_share_channels(self) -> bool:
        samples = [
            sample
            for sample in self._sample_browser.samples()
            if sample.id in self._event_data
        ]
        if not samples:
            return True
        first = [ch.name for ch in samples[0].info.channels]
        return all([ch.name for ch in sample.info.channels] == first for sample in samples)

    # -- help ----------------------------------------------------------------

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Flowdesk",
            "Flowdesk\n\n"
            "Linux-first FlowJo-like flow cytometry analysis application.\n"
            "Version 0.1.0",
        )

    # -- status bar ----------------------------------------------------------

    def _update_status(self, message: str) -> None:
        """Update the status bar."""
        self.statusBar().showMessage(message)
