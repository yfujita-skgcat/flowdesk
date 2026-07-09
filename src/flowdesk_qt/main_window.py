"""Main window for Flowdesk.

Assembles the UI components and delegates all scientific computation to
``flowdesk_core.pipeline_runner``.  This module contains NO analysis logic.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction, QKeySequence
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
from flowdesk_qt.plot_widget import PlotWidget
from flowdesk_qt.population_tree import PopulationTree
from flowdesk_qt.sample_browser import SampleBrowser, _SampleInfo

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
        self.setWindowTitle("Flowdesk")
        self.resize(1400, 900)

        # Internal state
        self._event_data: dict[str, NDArray[np.float64]] = {}
        self._channel_names: list[str] = []
        self._current_sample_id: str | None = None
        self._worker: _PipelineWorker | None = None

        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._connect_signals()
        self._update_status("Ready")

    # -- public API ----------------------------------------------------------

    def load_samples_from_directory(self, directory: str | Path) -> int:
        """Load FCS samples from a directory."""
        return self._sample_browser.add_samples_from_directory(directory)

    # -- menu ----------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        action_open_dir = QAction("&Open Directory...", self)
        action_open_dir.setShortcut(QKeySequence.Open)
        action_open_dir.triggered.connect(self._on_open_directory)
        file_menu.addAction(action_open_dir)

        action_open_files = QAction("Open &Files...", self)
        action_open_files.setShortcut(QKeySequence("Ctrl+Shift+O"))
        action_open_files.triggered.connect(self._on_open_files)
        file_menu.addAction(action_open_files)

        file_menu.addSeparator()

        action_quit = QAction("E&xit", self)
        action_quit.setShortcut(QKeySequence.Quit)
        action_quit.triggered.connect(self.close)
        file_menu.addAction(action_quit)

        # Analysis menu
        analysis_menu = menubar.addMenu("&Analysis")

        action_run = QAction("&Run Pipeline", self)
        action_run.setShortcut(QKeySequence("Ctrl+R"))
        action_run.triggered.connect(self._on_run_pipeline)
        analysis_menu.addAction(action_run)

        analysis_menu.addSeparator()

        action_clear_gates = QAction("Clear &Gates", self)
        action_clear_gates.setShortcut(QKeySequence("Ctrl+G"))
        action_clear_gates.triggered.connect(self._on_clear_gates)
        analysis_menu.addAction(action_clear_gates)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        action_about = QAction("&About Flowdesk", self)
        action_about.triggered.connect(self._on_about)
        help_menu.addAction(action_about)

    # -- toolbar -------------------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        action_open = QAction("Open Samples", self)
        action_open.triggered.connect(self._on_open_directory)
        toolbar.addAction(action_open)

        toolbar.addSeparator()

        action_run = QAction("Run Pipeline", self)
        action_run.triggered.connect(self._on_run_pipeline)
        toolbar.addAction(action_run)

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
        splitter1.addWidget(self._sample_browser)
        splitter1.addWidget(center_widget)
        splitter1.setStretchFactor(0, 1)
        splitter1.setStretchFactor(1, 3)

        splitter2 = QSplitter(Qt.Horizontal)
        splitter2.addWidget(splitter1)
        splitter2.addWidget(right_widget)
        splitter2.setStretchFactor(0, 4)
        splitter2.setStretchFactor(1, 2)

        self.setCentralWidget(splitter2)

    def _create_center_pane(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._channel_selector)
        layout.addWidget(self._plot_widget)
        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
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

        # When channel selection changes, replot
        self._channel_selector.on_channel_changed(self._on_channel_changed)

        # When a gate is created, update plot overlays
        self._gate_editor.on_gate_selected(self._on_gate_selected)

    # -- sample handling -----------------------------------------------------

    def _on_sample_selected(self, sample: _SampleInfo) -> None:
        """Called when the user selects a sample in the browser."""
        self._current_sample_id = sample.id
        self._channel_names = [ch.name for ch in sample.info.channels]
        self._channel_selector.set_channels(self._channel_names)

        self._update_status(
            f"Selected: {sample.name}  ({sample.info.event_count} events, "
            f"{sample.info.channel_count} channels)"
        )

        # Load event data if not already loaded
        if sample.id not in self._event_data:
            self._load_sample_events(sample)

        # Replot with current channel selection
        self._replot()

    def _load_sample_events(self, sample: _SampleInfo) -> None:
        """Load FCS event data for a sample."""
        try:
            _, events = read_fcs_events(sample.path)
            self._event_data[sample.id] = events
            logger.info("Loaded %d events for sample %s", events.shape[0], sample.id)
        except Exception as exc:
            logger.error("Failed to load events for %s: %s", sample.id, exc)
            self._update_status(f"Error loading {sample.name}: {exc}")

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
        for gate in self._gate_editor.gates():
            self._plot_widget.add_gate_overlay(gate)

    def _get_channel_index(self, channel_name: str) -> int:
        """Get the column index for a channel name."""
        try:
            return self._channel_names.index(channel_name)
        except (ValueError, AttributeError):
            return -1

    # -- gate handling -------------------------------------------------------

    def _on_gate_selected(self, gate_index: int) -> None:
        """Called when a gate is selected in the gate editor."""
        # Could highlight the gate or show its properties
        pass

    def _on_clear_gates(self) -> None:
        """Clear all gates."""
        self._gate_editor.clear_gates()
        self._plot_widget.clear_gates()
        self._update_status("Gates cleared")

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
        from flowdesk_core.models import GatingStrategySpec

        samples = []
        for sid, _ in self._event_data.items():
            sample_info = self._sample_browser.selected_sample()
            if sample_info and sample_info.id == sid:
                samples.append(
                    {
                        "id": sid,
                        "name": sample_info.name,
                        "path": sample_info.path,
                    }
                )
            else:
                samples.append({"id": sid, "name": sid, "path": ""})

        gates_list = list(self._gate_editor.gates())

        strategy = GatingStrategySpec(
            id="default_strategy",
            name="Default Strategy",
            gates=tuple(gates_list),
            root_population_id="all_events",
        )

        project: dict[str, Any] = {
            "project_id": "flowdesk_session",
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
        }

        return project

    def _on_pipeline_finished(self) -> None:
        """Handle pipeline completion by retrieving results from the worker."""
        if self._worker is None:
            return

        if self._worker._error is not None:
            exc = self._worker._error
            logger.error("Pipeline execution failed: %s", exc)
            self._update_status(f"Pipeline error: {exc}")
            QMessageBox.critical(self, "Pipeline Error", str(exc))
            self._worker = None
            return

        report = self._worker._report
        if report is not None:
            self._population_tree.set_report(report)
            self._update_status(f"Pipeline complete: {report.summary}")
        else:
            self._update_status("Pipeline finished with no report")

        self._worker = None

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
