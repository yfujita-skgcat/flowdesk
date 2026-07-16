"""Main window for Flowdesk.

Assembles the UI components and delegates all scientific computation to
``flowdesk_core.pipeline_runner``.  This module contains NO analysis logic.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QWidget,
)

from flowdesk_core.compensation import (
    inspect_compensation_matrix,
    resolve_compensation_binding,
)
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.gate_transform_migration import preview_gate_transform_migration
from flowdesk_core.models import CompensationMatrixSpec, TransformSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.sample import SampleData
from flowdesk_qt.channel_selector import ChannelSelector
from flowdesk_qt.diagnostics_panel import DiagnosticsPanel
from flowdesk_qt.gate_editor import GateEditor
from flowdesk_qt.group_panel import GroupPanel
from flowdesk_qt.plot_toolbar import PlotToolbar
from flowdesk_qt.plot_widget import PlotWidget
from flowdesk_qt.population_tree import PopulationTree
from flowdesk_qt.sample_browser import SampleBrowser, _SampleInfo
from flowdesk_qt.workspace_tree import WorkspaceTree
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import load_project, resolve_sample_paths, save_project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compensation status indicator
# ---------------------------------------------------------------------------


class _CompensationStatusIndicator(QWidget):
    """Persistent status-bar widget showing compensation matrix status.

    Displays a badge indicating:
    - 🟢 Valid matrix applied
    - 🟡 Ill-conditioned matrix applied (warning)
    - 🔴 No matrix applied or invalid matrix
    - ⚠️ Results stale
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compensationStatusIndicator")
        self._label = QLabel()
        self._label.setObjectName("compensationStatusLabel")
        self._label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 2px 6px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addWidget(self._label)
        self._set_state("none", "", stale=False)

    def _set_state(
        self,
        status: Literal["valid", "warning", "none", "error"],
        matrix_name: str,
        stale: bool = False,
    ) -> None:
        icon_map = {
            "valid": "🟢",
            "warning": "🟡",
            "none": "🔴",
            "error": "⚠️",
        }
        icon = icon_map.get(status, "⚠️")
        stale_marker = " (stale)" if stale else ""
        if matrix_name:
            text = f"{icon} Comp: {matrix_name}{stale_marker}"
        else:
            text = f"{icon} Comp: none{stale_marker}"
        self._label.setText(text)

    def set_valid(self, matrix_name: str, stale: bool = False) -> None:
        self._set_state("valid", matrix_name, stale)

    def set_warning(self, matrix_name: str, condition_number: float, stale: bool = False) -> None:
        text = f"Comp: {matrix_name} (cond={condition_number:.0e})"
        self._set_state("warning", text, stale)

    def set_none(self, stale: bool = False) -> None:
        self._set_state("none", "", stale)

    def set_error(self, message: str, stale: bool = False) -> None:
        self._set_state("error", message, stale)

    def mark_stale(self) -> None:
        """Re-render with stale flag."""
        current = self._label.text()
        if " (stale)" not in current:
            self._label.setText(current + " (stale)")

    def clear_stale(self) -> None:
        """Remove stale marker."""
        current = self._label.text()
        if " (stale)" in current:
            self._label.setText(current.replace(" (stale)", ""))


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
        samples: tuple[SampleData, ...],
        profile_id: str = "default",
    ) -> None:
        super().__init__()
        self._project = project
        self._samples = samples
        self._profile_id = profile_id
        self._report: Any = None
        self._error: Exception | None = None

    def run(self) -> None:
        try:
            runner = PipelineRunner(self._project)
            ctx = ExecutionContext(execution_profile_id=self._profile_id)
            self._report = runner.run_samples(ctx, self._samples)
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
        self._sample_data: dict[str, SampleData] = {}
        self._channel_names: list[str] = []
        self._current_sample_id: str | None = None
        self._worker: _PipelineWorker | None = None
        self._results_stale = False
        self._project_dirty = False
        self._project_id = "flowdesk_session"
        self._project_path: Path | None = None
        self._derived_parameters: list[dict[str, Any]] = []
        self._compensation_matrices: list[dict[str, Any]] = []
        self._compensation_bindings: list[dict[str, Any]] = []
        self._compensation_calculations: list[dict[str, Any]] = []
        self._transforms: list[dict[str, Any]] = []
        self._statistics: list[dict[str, Any]] = []
        self._default_compensation_matrix_id: str | None = None
        self._migration_diagnostics: list[dict[str, Any]] = []
        self._advanced_groups_enabled = False
        self._sample_groups: list[dict[str, Any]] = []
        self._group_strategy_bindings: list[dict[str, Any]] = []
        self._annotations: list[dict[str, Any]] = []
        # Display-only: selected population for plot filtering.
        self._selected_population_id: str = "all_events"

        self._compensation_status_indicator = _CompensationStatusIndicator()
        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._connect_signals()
        self._update_status("Ready")
        self._update_compensation_status()
        self._update_undo_actions()

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
                **self._plot_widget.display_state(),
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
            "population_filter": {
                "selected_population_id": self._selected_population_id,
                "memberships": []
                if report is None
                else [
                    {
                        "sample_id": membership.sample_id,
                        "population_id": membership.population_id,
                        "mask_length": int(membership.mask.size),
                        "event_count": membership.event_count,
                    }
                    for membership in report.population_membership
                ],
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

        self.action_export_statistics = QAction("Export &Statistics...", self)
        self.action_export_statistics.setObjectName("actionExportStatistics")
        self.action_export_statistics.triggered.connect(self._on_export_statistics)
        file_menu.addAction(self.action_export_statistics)

        file_menu.addSeparator()

        self.action_quit = QAction("E&xit", self)
        self.action_quit.setObjectName("actionQuit")
        self.action_quit.setShortcut(QKeySequence.Quit)
        self.action_quit.triggered.connect(self.close)
        file_menu.addAction(self.action_quit)

        edit_menu = menubar.addMenu("&Edit")
        self.action_undo = QAction("&Undo Gate Change", self)
        self.action_undo.setObjectName("actionUndoGateChange")
        self.action_undo.setShortcut(QKeySequence.Undo)
        self.action_undo.triggered.connect(self._on_undo)
        edit_menu.addAction(self.action_undo)
        self.action_redo = QAction("&Redo Gate Change", self)
        self.action_redo.setObjectName("actionRedoGateChange")
        self.action_redo.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.action_redo.triggered.connect(self._on_redo)
        edit_menu.addAction(self.action_redo)

        # Analysis menu
        analysis_menu = menubar.addMenu("&Analysis")

        self.action_run_pipeline = QAction("&Run Pipeline", self)
        self.action_run_pipeline.setObjectName("actionRunPipeline")
        self.action_run_pipeline.setShortcut(QKeySequence("Ctrl+R"))
        self.action_run_pipeline.triggered.connect(self._on_run_pipeline)
        analysis_menu.addAction(self.action_run_pipeline)

        analysis_menu.addSeparator()

        self.action_derived_parameters = QAction("Derived &Parameters...", self)
        self.action_derived_parameters.setObjectName("actionDerivedParameters")
        self.action_derived_parameters.triggered.connect(
            self._on_edit_derived_parameters
        )
        analysis_menu.addAction(self.action_derived_parameters)

        self.action_compensation = QAction("&Compensation...", self)
        self.action_compensation.setObjectName("actionCompensation")
        self.action_compensation.triggered.connect(self._on_edit_compensation)
        analysis_menu.addAction(self.action_compensation)

        self.action_compensation_calculations = QAction(
            "Compensation &Calculations...", self
        )
        self.action_compensation_calculations.setObjectName(
            "actionCompensationCalculations"
        )
        self.action_compensation_calculations.triggered.connect(
            self._on_edit_compensation_calculations
        )
        analysis_menu.addAction(self.action_compensation_calculations)

        self.action_transforms = QAction("Analysis &Transforms...", self)
        self.action_transforms.setObjectName("actionTransforms")
        self.action_transforms.triggered.connect(self._on_edit_transforms)
        analysis_menu.addAction(self.action_transforms)

        self.action_statistics = QAction("Population &Statistics...", self)
        self.action_statistics.setObjectName("actionStatistics")
        self.action_statistics.triggered.connect(self._on_edit_statistics)
        analysis_menu.addAction(self.action_statistics)

        self.action_annotations = QAction("Sample &Annotations...", self)
        self.action_annotations.setObjectName("actionAnnotations")
        self.action_annotations.triggered.connect(self._on_edit_annotations)
        analysis_menu.addAction(self.action_annotations)

        analysis_menu.addSeparator()
        self.action_advanced_groups = QAction(
            "Use Multiple Analysis Groups", self
        )
        self.action_advanced_groups.setObjectName("actionAdvancedGroups")
        self.action_advanced_groups.setCheckable(True)
        self.action_advanced_groups.setChecked(False)
        self.action_advanced_groups.setToolTip(
            "Show Group assignments for different panels, controls, or QC samples. "
            "Treatment/control comparison samples normally stay in one Group."
        )
        self.action_advanced_groups.toggled.connect(
            self._set_advanced_groups_enabled
        )
        analysis_menu.addAction(self.action_advanced_groups)

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
        self._group_panel = GroupPanel()
        self._group_panel.setVisible(False)
        self._population_tree = PopulationTree()
        self._workspace_tree = WorkspaceTree()
        self._diagnostics_panel = DiagnosticsPanel()
        self._workspace_navigation = self._create_workspace_navigation()

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
        self.statusBar().addPermanentWidget(self._compensation_status_indicator)

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
        layout.addWidget(self._workspace_navigation)
        layout.addWidget(self._gate_editor)
        layout.addWidget(self._group_panel)
        layout.addWidget(self._workspace_tree)
        layout.addWidget(self._population_tree)
        layout.addWidget(self._diagnostics_panel)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)
        layout.setStretch(2, 1)
        layout.setStretch(3, 1)
        return widget

    def _create_workspace_navigation(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("workspaceNavigationBar")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self._breadcrumb_label = QLabel("All Events")
        self._breadcrumb_label.setObjectName("workspaceBreadcrumbLabel")
        self._breadcrumb_label.setWordWrap(True)
        self._parent_navigation_button = QPushButton("Parent")
        self._parent_navigation_button.setObjectName("workspaceParentButton")
        self._parent_navigation_button.clicked.connect(self._navigate_to_parent)
        self._previous_sample_button = QPushButton("Previous Sample")
        self._previous_sample_button.setObjectName("previousSampleButton")
        self._previous_sample_button.clicked.connect(
            lambda: self._navigate_sample(-1)
        )
        self._next_sample_button = QPushButton("Next Sample")
        self._next_sample_button.setObjectName("nextSampleButton")
        self._next_sample_button.clicked.connect(lambda: self._navigate_sample(1))
        layout.addWidget(self._breadcrumb_label, 1)
        layout.addWidget(self._parent_navigation_button)
        layout.addWidget(self._previous_sample_button)
        layout.addWidget(self._next_sample_button)
        return widget

    def _set_advanced_groups_enabled(self, enabled: bool) -> None:
        """Toggle only Group visibility; never delete or merge project state."""
        self._advanced_groups_enabled = bool(enabled)
        self._group_panel.setVisible(self._advanced_groups_enabled)
        if enabled:
            self._update_status(
                "Advanced Group mode: comparison samples should normally share one strategy"
            )
        else:
            self._update_status("Simple mode: All Samples × Default Strategy")

    def _on_groups_changed(self, groups: list[dict[str, Any]]) -> None:
        """Persist Group edits in project state and invalidate analysis."""
        self._sample_groups = deepcopy(groups)
        self._mark_results_stale("Sample Groups changed")

    # -- signal connections --------------------------------------------------

    def _connect_signals(self) -> None:
        # When a sample is selected, load its channels and plot
        self._sample_browser.on_sample_selected(self._on_sample_selected)

        # When a sample is removed, clean up its associated state
        self._sample_browser.on_sample_removed(self._on_sample_removed)
        self._sample_browser.on_sample_reconnected(self._on_sample_reconnected)

        # When channel selection changes, replot
        self._channel_selector.on_channel_changed(self._on_channel_changed)

        # When a gate is selected, update highlight
        self._gate_editor.on_gate_selected(self._on_gate_selected)

        # When the gate list changes (add/delete/clear), refresh overlays and invalidate results
        self._gate_editor.on_gates_changed(self._on_gates_changed)

        # Interactive gate creation starts from the gate editor.
        self._gate_editor.on_interactive_gate_requested(self._on_interactive_gate_requested)
        self._gate_editor.on_show_gate(self._on_show_gate)
        self._gate_editor.on_migrate_gate(self._on_migrate_gate)

        # Plot toolbar callbacks
        self._plot_toolbar.on_reset_robust(self._on_reset_robust)
        self._plot_toolbar.on_reset_full(self._on_reset_full)
        self._plot_toolbar.on_export_png(self._on_export_png)
        self._plot_toolbar.on_add_statistic(self._on_add_statistic_from_graph)
        self._plot_toolbar.on_marginal_toggled(self._on_marginal_toggled)
        self._group_panel.groups_changed.connect(self._on_groups_changed)

        # Population selection (display-only filter)
        self._population_tree.on_population_selected(self._on_population_selected)
        self._population_tree.on_add_statistic_requested(
            self._on_add_statistic_from_population_tree
        )
        self._workspace_tree.on_selection_changed(self._on_workspace_tree_selected)

        # Connect plot mouse events to gate creation
        self._plot_widget.on_mouse_clicked(self._on_plot_mouse_clicked)
        self._plot_widget.on_gate_geometry_changed(self._on_gate_geometry_changed)

    # -- sample handling -----------------------------------------------------

    def _on_sample_selected(self, sample: _SampleInfo) -> None:
        """Called when the user selects a sample in the browser."""
        previous_x = self._channel_selector.x_channel()
        previous_y = self._channel_selector.y_channel()
        self._current_sample_id = sample.id
        self._gate_editor.set_current_sample_id(sample.id)
        self._group_panel.set_sample_ids(
            [item.id for item in self._sample_browser.samples()]
        )
        self._workspace_tree.set_samples(
            [(item.id, item.name) for item in self._sample_browser.samples()]
        )
        self._workspace_tree.select("sample", sample.id)
        self._update_workspace_navigation()
        report = self._population_tree.last_report()
        if report is not None and not self._results_stale:
            self._validate_population_selection(report)
        self._channel_names = [ch.name for ch in sample.info.channels]
        x_preserved, y_preserved = self._channel_selector.set_channel_specs(sample.info.channels)

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
        sample_status = getattr(sample, "status", "match")
        if sample_status in {"missing", "fingerprint mismatch"}:
            self._update_status(f"{sample.name}: {sample_status}; reconnect before analysis")
            self._plot_widget.clear_plot()
            return
        if sample.id not in self._sample_data:
            self._load_sample_events(sample)

        # Replot with current channel selection
        self._replot()
        self._update_compensation_status()

    def _on_sample_removed(self, sample: _SampleInfo) -> None:
        """Called when a sample is removed from the browser."""
        # Remove event data for this sample
        self._event_data.pop(sample.id, None)
        self._sample_data.pop(sample.id, None)
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
            _, typed_sample = read_fcs_sample(sample.path, sample.id)
            self._sample_data[sample.id] = typed_sample
            self._event_data[sample.id] = typed_sample.events
            logger.info("Loaded %d events for sample %s", typed_sample.event_count, sample.id)
        except Exception as exc:
            logger.error("Failed to load events for %s: %s", sample.id, exc)
            self._update_status(f"Error loading {sample.name}: {exc}")

    def _on_sample_reconnected(self, sample: _SampleInfo) -> None:
        """Invalidate prior raw view and reload an explicitly accepted reconnect."""
        self._sample_data.pop(sample.id, None)
        self._event_data.pop(sample.id, None)
        self._mark_results_stale(f"Reconnected: {sample.name}")
        if self._current_sample_id == sample.id:
            self._on_sample_selected(sample)

    def _on_gates_changed(self) -> None:
        """Called when the gate list changes (add/delete/clear).

        Refresh overlays and invalidate cached population results.
        """
        self._population_tree.set_population_parents(self._population_parent_map())
        self._workspace_tree.set_population_hierarchy(
            self._population_parent_map(), self._population_name_map()
        )
        self._mark_results_stale("Gates changed")
        self._project_dirty = True
        self._update_undo_actions()
        self._replot()

    def _on_undo(self) -> None:
        if self._gate_editor.undo():
            self._update_undo_actions()

    def _on_redo(self) -> None:
        if self._gate_editor.redo():
            self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        self.action_undo.setEnabled(self._gate_editor.can_undo())
        self.action_redo.setEnabled(self._gate_editor.can_redo())

    # -- channel selection ---------------------------------------------------

    def _on_channel_changed(self, x_name: str, y_name: str) -> None:
        """Called when X or Y channel selection changes."""
        self._replot()

    def _on_population_selected(self, population_id: str, sample_id: str) -> None:
        """Called when the user selects a population in the results table.

        This is a display-only change; it does not modify gates or analysis state.
        """
        if sample_id and sample_id != self._current_sample_id:
            self._sample_browser.select_sample(sample_id)
        self._selected_population_id = population_id
        self._update_workspace_navigation()
        if population_id != "all_events":
            self._gate_editor.select_gate(population_id)
            self._workspace_tree.select("population", population_id)
        self._replot()

    def _update_workspace_navigation(self) -> None:
        sample = self._sample_browser.selected_sample()
        sample_name = sample.name if sample is not None else "-"
        population_id = self._selected_population_id or "all_events"
        names = self._population_name_map()
        chain: list[str] = []
        current = population_id
        parents = self._population_parent_map()
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            chain.append(names.get(current, current))
            current = parents.get(current) or ""
        self._breadcrumb_label.setText(
            f"{sample_name} / " + " / ".join(reversed(chain or ["All Events"]))
        )
        self._parent_navigation_button.setEnabled(population_id != "all_events")
        index = -1 if sample is None else self._sample_browser.samples().index(sample)
        samples = self._sample_browser.samples()
        self._previous_sample_button.setEnabled(index > 0)
        self._next_sample_button.setEnabled(0 <= index < len(samples) - 1)

    def _navigate_to_parent(self) -> None:
        population_id = self._selected_population_id or "all_events"
        parent_id = self._population_parent_map().get(population_id) or "all_events"
        self._on_population_selected(parent_id, self._current_sample_id or "")

    def _navigate_sample(self, offset: int) -> None:
        samples = self._sample_browser.samples()
        current = self._sample_browser.selected_sample()
        if current is None:
            return
        index = samples.index(current) + offset
        if 0 <= index < len(samples):
            self._sample_browser.select_sample(samples[index].id)

    def _on_workspace_tree_selected(
        self, kind: str, stable_id: str, sample_id: str
    ) -> None:
        """Bridge unified workspace selection to existing display navigation."""
        if kind == "sample":
            self._sample_browser.select_sample(stable_id)
        elif kind == "population":
            self._on_population_selected(stable_id, sample_id)

    def _replot(self) -> None:
        """Replot the current sample with current channel selection and axis transforms.

        When Y channel is set to the Count option, renders a 1D histogram instead
        of a 2D scatter plot (Phase 4).
        """
        if self._current_sample_id is None:
            return

        data = self._event_data.get(self._current_sample_id)
        if data is None or not self._channel_names:
            return

        x_name = self._channel_selector.x_channel()
        y_name = self._channel_selector.y_channel()
        x_id = self._channel_selector.x_channel_id()
        y_id = self._channel_selector.y_channel_id()

        x_spec = self._transform_for_parameter(x_id)
        y_spec = None if self._channel_selector.is_count_mode() else (
            self._transform_for_parameter(y_id)
        )
        self._channel_selector.set_analysis_transform_bound(
            x_spec is not None, y_spec is not None
        )
        self._plot_widget.set_axis_transform_specs(x_spec, y_spec)

        # Sync gate editor with current channels
        self._gate_editor.set_plot_channels(x_id, y_id)
        self._gate_editor.set_plot_scales(
            self._channel_selector.x_transform(),
            self._channel_selector.y_transform(),
        )
        self._gate_editor.set_plot_transforms(
            None if x_spec is None else x_spec.id,
            None if y_spec is None else y_spec.id,
        )

        x_idx = self._get_channel_index(x_id)
        if x_idx < 0:
            return

        x_data = data[:, x_idx]

        # Determine if we are in histogram (Count) mode.
        is_histogram = self._channel_selector.is_count_mode()
        self._plot_toolbar.set_marginal_available(not is_histogram)

        if is_histogram:
            # 1D histogram: only X channel data is needed.
            x_data, _ = self._apply_population_filter(x_data, x_data)

            x_transform = self._channel_selector.x_transform()
            self._plot_widget.set_axis_transforms(x_transform, "linear")
            self._plot_widget.plot_histogram(x_data, x_label=x_name)

            # No 2D gate overlays in histogram mode.
            self._plot_widget.clear_gates()
        else:
            # 2D scatter plot.
            y_idx = self._get_channel_index(y_id)

            if y_idx < 0:
                return

            y_data = data[:, y_idx]

            # Apply population membership mask (display filter, Phase 3).
            x_data, y_data = self._apply_population_filter(x_data, y_data)

            # For marginal histograms, use unfiltered data (or population-filtered if preferred).
            # Use the same filtered data for marginal histograms.
            marginal_x = x_data
            marginal_y = y_data

            # Apply axis transform settings to the plot widget.
            x_transform = self._channel_selector.x_transform()
            y_transform = self._channel_selector.y_transform()
            self._plot_widget.set_axis_transforms(x_transform, y_transform)

            self._plot_widget.plot_events(
                x_data, y_data,
                x_label=x_name, y_label=y_name,
                marginal_x_data=marginal_x,
                marginal_y_data=marginal_y,
            )

            # Refresh gate overlays
            self._plot_widget.clear_gates()
            for idx, gate in enumerate(self._gate_editor.gates()):
                if gate.x_parameter == x_id and gate.y_parameter == y_id:
                    self._plot_widget.add_gate_overlay(gate, idx)
            self._gate_editor.set_overlay_status(
                self._plot_widget.display_state()["hidden_gate_reasons"]
            )

    def _get_channel_index(self, channel_id: str) -> int:
        """Get a column index by stable ID for the current sample."""
        sample = self._sample_data.get(self._current_sample_id or "")
        if sample is not None:
            try:
                return sample.channel_index(channel_id)
            except Exception:
                return -1
        selected = self._sample_browser.selected_sample()
        if selected is not None:
            for index, channel in enumerate(selected.info.channels):
                if channel.id == channel_id or channel.name == channel_id:
                    return index
        try:
            return self._channel_names.index(channel_id)
        except (ValueError, AttributeError):
            return -1

    def _get_population_mask(self) -> NDArray[np.bool_] | None:
        """Return the membership boolean mask for the current sample and selected population.

        Returns ``None`` when no valid membership data is available (stale results,
        no report, or missing population/sample).  In that case the caller should
        fall back to displaying all events.
        """
        report = self._population_tree.last_report()
        if report is None:
            return None
        if self._results_stale:
            return None
        if not hasattr(report, "population_membership") or not report.population_membership:
            return None

        sample_id = self._current_sample_id
        population_id = self._selected_population_id

        # all_events is always valid: no filter needed
        if population_id == "all_events":
            return None

        # Find matching membership entry for (sample_id, population_id)
        for membership in report.population_membership:
            if membership.sample_id == sample_id and membership.population_id == population_id:
                return membership.mask

        # Selected population does not exist for this sample; fall back to all events
        return None

    def _apply_population_filter(
        self,
        x_data: NDArray[np.float64],
        y_data: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Apply the currently selected population membership mask to X/Y data.

        If no valid mask is available, the original data is returned unchanged.
        """
        mask = self._get_population_mask()
        if mask is None:
            return x_data, y_data

        return x_data[mask], y_data[mask]

    # -- gate handling -------------------------------------------------------

    def _on_gate_selected(self, gate_index: int) -> None:
        """Called when a gate is selected in the gate editor."""
        # Highlight the selected gate overlay with a solid pen
        self._plot_widget.highlight_gate_index(gate_index)
        gates = self._gate_editor.gates()
        if 0 <= gate_index < len(gates):
            self._selected_population_id = gates[gate_index].id
            self._workspace_tree.select("population", gates[gate_index].id)
            self._update_workspace_navigation()

    def _on_show_gate(self, gate) -> None:
        """Navigate display controls to a gate without changing analysis state."""
        if gate.x_parameter:
            y_parameter = gate.y_parameter or self._channel_selector.y_channel_id()
            self._channel_selector.set_selected_channels(
                gate.x_parameter, y_parameter
            )
        if gate.x_transform_id or gate.transform_id:
            self._channel_selector.set_x_transform("linear")
        else:
            self._channel_selector.set_x_transform(gate.x_scale)
        if gate.y_transform_id:
            self._channel_selector.set_y_transform("linear")
        else:
            self._channel_selector.set_y_transform(gate.y_scale)
        self._replot()
        self._update_status(
            f"Showing gate: {gate.name} [{gate.id}] on "
            f"{gate.x_transform_id or gate.x_scale}/"
            f"{gate.y_transform_id or gate.y_scale}"
        )

    def _transform_specs(self) -> tuple[TransformSpec, ...]:
        return tuple(
            TransformSpec(
                id=value["id"],
                name=value.get("name", value["id"]),
                transform_type=value["transform_type"],
                parameter=value["parameter"],
                settings=value.get("settings", {}),
                role=value.get("role", "analysis"),
                notes=value.get("notes", ""),
            )
            for value in self._transforms
        )

    def _transform_for_parameter(self, parameter: str) -> TransformSpec | None:
        matches = [
            transform for transform in self._transform_specs()
            if transform.parameter == parameter
        ]
        if len(matches) > 1:
            logger.error("Ambiguous analysis transforms for parameter %s", parameter)
            return None
        return matches[0] if matches else None

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
        for sample in self._sample_browser.samples():
            if (
                getattr(sample, "status", "match")
                not in {"missing", "fingerprint mismatch"}
                and sample.id not in self._sample_data
            ):
                self._load_sample_events(sample)
        if not self._sample_data:
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
            tuple(self._sample_data.values()),
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
        sample_ids = list(sample_lookup)
        sample_ids.extend(sid for sid in self._sample_data if sid not in sample_lookup)
        for sid in sample_ids:
            sample_info = sample_lookup.get(sid)
            if sample_info is None:
                samples.append({"id": sid, "name": sid, "path": "", "channels": []})
                continue
            sample_mapping = {
                "id": sid,
                "name": sample_info.name,
                "path": sample_info.path,
                "channels": [asdict(channel) for channel in sample_info.info.channels],
            }
            fingerprint = getattr(sample_info, "fingerprint", None)
            if fingerprint is not None:
                sample_mapping["fingerprint"] = fingerprint.to_mapping()
            samples.append(sample_mapping)

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
            "project_version": CURRENT_PROJECT_VERSION,
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
            "advanced_groups_enabled": self._advanced_groups_enabled,
            "sample_groups": deepcopy(self._sample_groups) or [
                {
                    "id": "all-samples",
                    "name": "All Samples",
                    "role": "all_samples",
                    "sample_ids": [],
                    "membership_rule": {"all": []},
                }
            ],
            "group_strategy_bindings": deepcopy(self._group_strategy_bindings) or [
                {
                    "id": "all-samples-default-strategy",
                    "group_id": "all-samples",
                    "gating_strategy_id": "default_strategy",
                    "statistic_ids": [],
                }
            ],
            "annotations": deepcopy(self._annotations),
            "derived_parameters": deepcopy(self._derived_parameters),
            "transforms": deepcopy(self._transforms),
            "compensation_matrices": deepcopy(self._compensation_matrices),
            "compensation_bindings": deepcopy(self._compensation_bindings),
            "compensation_calculations": deepcopy(
                self._compensation_calculations
            ),
            "statistics": deepcopy(self._statistics),
            "default_compensation_matrix_id": self._default_compensation_matrix_id,
            "migration_diagnostics": deepcopy(self._migration_diagnostics),
            "sample_path_resolution_policy": "relative_to_project_or_absolute",
            "plot_display_settings": {
                "selected_sample_id": self._current_sample_id,
                "x_channel": self._channel_selector.x_channel_id(),
                "y_channel": self._channel_selector.y_channel_id(),
                "x_scale": self._channel_selector.x_transform(),
                "y_scale": self._channel_selector.y_transform(),
                "marginal_enabled": self._plot_widget.is_marginal_enabled(),
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
            self._workspace_tree.set_report(report)
            self._diagnostics_panel.set_report(report)
            self._gate_editor.set_population_results(report.population_results)
            self._results_stale = False
            self._compensation_status_indicator.clear_stale()
            self._validate_population_selection(report)
            self._update_status(f"Pipeline complete: {report.summary}")
            # Replot to apply the now-valid population membership mask.
            self._replot()
            self._update_compensation_status()
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
        self._project_dirty = False
        self._gate_editor.mark_undo_clean()
        self._update_undo_actions()

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
        self._sample_data.clear()
        self._current_sample_id = None
        self._channel_names = []
        self._gate_editor.set_gates(list(strategy.gates), notify=False)
        self._gate_editor.mark_undo_clean()
        self._project_dirty = False
        self._update_undo_actions()
        self._population_tree.set_population_parents(self._population_parent_map())
        self._workspace_tree.set_population_hierarchy(
            self._population_parent_map(), self._population_name_map()
        )

        self._derived_parameters = deepcopy(manifest.get("derived_parameters", []))
        self._transforms = deepcopy(manifest.get("transforms", []))
        self._compensation_matrices = deepcopy(
            manifest.get("compensation_matrices", [])
        )
        self._compensation_bindings = deepcopy(
            manifest.get("compensation_bindings", [])
        )
        self._compensation_calculations = deepcopy(
            manifest.get("compensation_calculations", [])
        )
        self._statistics = deepcopy(manifest.get("statistics", []))
        self._sample_groups = deepcopy(manifest.get("sample_groups", []))
        self._group_strategy_bindings = deepcopy(
            manifest.get("group_strategy_bindings", [])
        )
        self._annotations = deepcopy(manifest.get("annotations", []))
        self._group_panel.set_groups(self._sample_groups)
        self.action_advanced_groups.setChecked(
            bool(manifest.get("advanced_groups_enabled", False))
        )

        resolved_samples = resolve_sample_paths(manifest, project_path)
        self._sample_browser.add_project_samples(resolved_samples)
        self._group_panel.set_sample_ids(
            [item.id for item in self._sample_browser.samples()]
        )
        display = manifest.get("plot_display_settings", {})
        self._channel_selector.set_x_transform(display.get("x_scale", "linear"))
        self._channel_selector.set_y_transform(display.get("y_scale", "linear"))
        marginal = bool(display.get("marginal_enabled", False))
        self._plot_widget.set_marginal_enabled(marginal)
        self._plot_toolbar.set_marginal_enabled(marginal)

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
        self._default_compensation_matrix_id = manifest.get(
            "default_compensation_matrix_id"
        )
        self._migration_diagnostics = deepcopy(
            manifest.get("migration_diagnostics", [])
        )
        self._mark_results_stale("Project loaded")

    def _on_edit_derived_parameters(self) -> None:
        """Edit project definitions; preview delegates to PipelineRunner."""
        from flowdesk_qt.derived_parameter_editor import (
            DerivedParameterEditorDialog,
        )

        channels_by_id = {}
        current = self._sample_data.get(self._current_sample_id or "")
        if current is not None:
            channels_by_id.update({channel.id: channel for channel in current.channels})
        for sample in self._sample_browser.samples():
            for channel in sample.info.channels:
                channels_by_id.setdefault(channel.id, channel)

        def preview_callback(definitions, output_channel_id):
            sample = self._sample_data.get(self._current_sample_id or "")
            if sample is None:
                raise RuntimeError("select a loaded sample before preview")
            project = self._build_project_manifest()
            project["derived_parameters"] = definitions
            return PipelineRunner(project).preview_derived_parameter(
                sample, output_channel_id, max_events=200
            )

        dialog = DerivedParameterEditorDialog(
            self._derived_parameters,
            tuple(channels_by_id.values()),
            preview_callback=preview_callback,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._derived_parameters = dialog.definitions()
        self._mark_results_stale("Derived parameters changed")

    def _on_edit_annotations(self) -> None:
        """Edit project annotations through a GUI-independent data contract."""
        from flowdesk_qt.annotation_editor import AnnotationEditorDialog

        dialog = AnnotationEditorDialog(
            [sample.id for sample in self._sample_browser.samples()],
            self._annotations,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._annotations = dialog.annotations()
        self._mark_results_stale("Annotations changed")

    def _on_edit_transforms(self) -> None:
        """Edit versioned transform definitions without changing used IDs in place."""
        from flowdesk_qt.transform_editor import TransformEditorDialog

        channels_by_id = {}
        for sample in self._sample_browser.samples():
            for channel in sample.info.channels:
                channels_by_id.setdefault(channel.id, channel)
        current = self._sample_data.get(self._current_sample_id or "")
        preview_values = {}
        if current is not None:
            channels_by_id.update({channel.id: channel for channel in current.channels})
            preview_values = {
                channel.id: current.events[:, index]
                for index, channel in enumerate(current.channels)
            }
        dialog = TransformEditorDialog(
            self._transforms,
            tuple(channels_by_id.values()),
            preview_values=preview_values,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.transforms()
        old_by_id = {value["id"]: value for value in self._transforms}
        new_by_id = {value["id"]: value for value in updated}
        referenced = {
            transform_id
            for gate in self._gate_editor.gates()
            for transform_id in (
                gate.x_transform_id or gate.transform_id,
                gate.y_transform_id,
            )
            if transform_id is not None
        }
        changed_references = sorted(
            transform_id for transform_id in referenced
            if old_by_id.get(transform_id) != new_by_id.get(transform_id)
        )
        if changed_references:
            QMessageBox.warning(
                self,
                "Transform is used by gates",
                "Create a new transform ID and explicitly migrate the gates first. "
                f"Used definitions were not changed: {', '.join(changed_references)}",
            )
            return
        self._transforms = updated
        self._mark_results_stale("Analysis transforms changed")
        self._replot()

    def _on_edit_compensation(self) -> None:
        """Edit compensation matrices and bindings."""
        from flowdesk_qt.compensation_editor import (
            CompensationMatrixEditorDialog,
        )

        channels_by_id = {}
        for sample in self._sample_browser.samples():
            for channel in sample.info.channels:
                channels_by_id.setdefault(channel.id, channel)
        current = self._sample_data.get(self._current_sample_id or "")
        if current is not None:
            channels_by_id.update({channel.id: channel for channel in current.channels})

        sample_ids = [s.id for s in self._sample_browser.samples()]
        group_ids = []

        dialog = CompensationMatrixEditorDialog(
            self._compensation_matrices,
            self._compensation_bindings,
            tuple(channels_by_id.values()),
            sample_ids,
            group_ids,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._compensation_matrices = dialog.matrices()
        self._compensation_bindings = dialog.bindings()
        self._mark_results_stale("Compensation changed")

    def _on_edit_compensation_calculations(self) -> None:
        """Edit compensation calculation specs (detector × control table)."""
        from flowdesk_qt.compensation_editor import (
            CompensationCalculationEditorDialog,
        )

        channels_by_id = {}
        for sample in self._sample_browser.samples():
            for channel in sample.info.channels:
                channels_by_id.setdefault(channel.id, channel)
        current = self._sample_data.get(self._current_sample_id or "")
        if current is not None:
            channels_by_id.update(
                {channel.id: channel for channel in current.channels}
            )

        population_ids = ["all_events"]
        for gate in self._gate_editor.gates():
            if gate.id not in population_ids:
                population_ids.append(gate.id)

        sample_ids = [s.id for s in self._sample_browser.samples()]

        # Build sample_data for "Run Calculation": events + population masks.
        sample_data: dict[str, dict[str, Any]] = {}
        report = self._population_tree.last_report()
        if report is not None and not self._results_stale:
            for sample_id, sample in self._sample_data.items():
                masks: dict[str, NDArray[np.bool_]] = {}
                for membership in report.population_membership:
                    if membership.sample_id == sample_id:
                        masks[membership.population_id] = membership.mask
                if masks:
                    sample_data[sample_id] = {
                        "events": sample.events,
                        "masks": masks,
                    }

        dialog = CompensationCalculationEditorDialog(
            self._compensation_calculations,
            tuple(channels_by_id.values()),
            population_ids,
            sample_ids,
            sample_data=sample_data,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._compensation_calculations = dialog.calculations()
        # Save the calculated matrix as an immutable result.
        calc_matrix = dialog.calculated_matrix()
        if calc_matrix is not None:
            self._compensation_matrices.append(calc_matrix)
            self._update_status(
                f"Calculated matrix saved: {calc_matrix['id']}"
            )
        self._mark_results_stale("Compensation calculations changed")

    def _on_edit_statistics(self) -> None:
        """Edit population statistic definitions."""
        self._open_statistics_editor()

    def _on_add_statistic_from_population_tree(self, population_id: str) -> None:
        """Open a new statistic definition scoped to a tree population."""
        self._open_statistics_editor(population_id=population_id)

    def _on_add_statistic_from_graph(self) -> None:
        """Open a new statistic definition using the graph X parameter."""
        self._open_statistics_editor(
            population_id=self._selected_population_id,
            parameter_id=self._channel_selector.x_channel_id() or None,
        )

    def _open_statistics_editor(
        self,
        *,
        population_id: str | None = None,
        parameter_id: str | None = None,
    ) -> None:
        """Edit persisted definitions without running scientific analysis in Qt."""
        from flowdesk_qt.statistics_editor import StatisticsEditorDialog

        channels_by_id = {}
        for sample in self._sample_browser.samples():
            for channel in sample.info.channels:
                channels_by_id.setdefault(channel.id, channel)
        current = self._sample_data.get(self._current_sample_id or "")
        if current is not None:
            channels_by_id.update(
                {channel.id: channel for channel in current.channels}
            )

        population_ids = ["all_events"]
        for gate in self._gate_editor.gates():
            if gate.id not in population_ids:
                population_ids.append(gate.id)

        dialog = StatisticsEditorDialog(
            self._statistics,
            tuple(channels_by_id.values()),
            population_ids,
            new_statistic_defaults=(
                {
                    "population_id": population_id or "all_events",
                    "parameter_id": parameter_id,
                    "metric": "mean" if parameter_id else "count",
                }
                if population_id is not None or parameter_id is not None
                else None
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._statistics = dialog.definitions()
        self._mark_results_stale("Statistics changed")

    def _on_migrate_gate(self, gate) -> None:
        """Preview and explicitly duplicate or replace one geometric gate."""
        if self._current_sample_id is None:
            QMessageBox.information(self, "No sample", "Select a loaded sample first.")
            return
        sample = self._sample_data.get(self._current_sample_id)
        if sample is None:
            QMessageBox.information(self, "No data", "Load the selected sample first.")
            return
        if self._compensation_matrices or self._derived_parameters:
            QMessageBox.information(
                self,
                "Canonical preview unavailable",
                "Gate migration preview is currently limited to projects without "
                "compensation or derived parameters; no raw-event approximation "
                "will be used for an analysis-changing decision.",
            )
            return
        target_x = self._transform_for_parameter(gate.x_parameter or "")
        target_y = (
            self._transform_for_parameter(gate.y_parameter or "")
            if gate.y_parameter else None
        )
        if target_x is None or (gate.y_parameter and target_y is None):
            QMessageBox.information(
                self,
                "Target transform missing",
                "Create one analysis transform for each gate parameter first.",
            )
            return
        parent_mask = None
        parent_id = gate.parent_population_id or "all_events"
        if parent_id != "all_events":
            report = self._population_tree.last_report()
            if report is None or self._results_stale:
                QMessageBox.information(
                    self,
                    "Run Pipeline first",
                    "A fresh full-event parent population is required for migration preview.",
                )
                return
            parent_mask = next(
                (
                    membership.mask for membership in report.population_membership
                    if membership.sample_id == sample.id
                    and membership.population_id == parent_id
                ),
                None,
            )
            if parent_mask is None:
                QMessageBox.warning(
                    self, "Parent unavailable", "Parent membership was not found."
                )
                return
        try:
            preview = preview_gate_transform_migration(
                gate,
                sample.events,
                [channel.id for channel in sample.channels],
                transforms=self._transform_specs(),
                target_x_transform=target_x,
                target_y_transform=target_y,
                parent_mask=parent_mask,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Migration unavailable", str(exc))
            return
        message = QMessageBox(self)
        message.setObjectName("gateTransformMigrationPreview")
        message.setWindowTitle("Gate transform migration preview")
        warning = (
            "\nPolygon vertices are reprojected approximately; straight edges are "
            "not scientifically equivalent across nonlinear coordinates."
            if not preview.scientifically_equivalent else ""
        )
        message.setText(
            f"Source events: {preview.source_event_count}\n"
            f"Candidate events: {preview.candidate_event_count}\n"
            f"Gained: {preview.gained_event_count}; Lost: {preview.lost_event_count}"
            f"{warning}"
        )
        duplicate_button = message.addButton("Duplicate", QMessageBox.ButtonRole.ActionRole)
        migrate_button = message.addButton("Migrate", QMessageBox.ButtonRole.AcceptRole)
        message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()
        clicked = message.clickedButton()
        if clicked not in {duplicate_button, migrate_button}:
            return
        candidate = preview.candidate_gate
        if clicked is duplicate_button:
            candidate = replace(
                candidate,
                id=f"gate_{uuid.uuid4().hex[:8]}",
                name=f"{candidate.name} (migrated copy)",
            )
            self._gate_editor.add_gate(candidate)
        else:
            index = next(
                index for index, value in enumerate(self._gate_editor.gates())
                if value.id == gate.id
            )
            self._gate_editor.update_gate(index, candidate, notify=True)

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

    def _validate_population_selection(self, report: Any) -> None:
        """Ensure the currently selected population ID is valid for the current sample.

        If the selected population does not exist in the new report data for the
        current sample, fall back to ``all_events``.
        """
        if self._selected_population_id == "all_events":
            return
        population_ids = {
            r.population_id
            for r in report.population_results
            if r.sample_id == self._current_sample_id
        }
        if self._selected_population_id not in population_ids:
            self._selected_population_id = "all_events"

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

        x_name = self._channel_selector.x_channel_id()
        y_name = self._channel_selector.y_channel_id()

        gate = GateSpec(
            id=f"gate_{uuid.uuid4().hex[:8]}",
            name=f"rect_{len(self._gate_editor.gates()) + 1}",
            gate_type="rectangle",
            parent_population_id=self._gate_editor.parent_population(),
            x_parameter=x_name,
            y_parameter=y_name,
            x_scale="linear" if self._transform_for_parameter(x_name) else (
                self._channel_selector.x_transform()
            ),
            y_scale="linear" if self._transform_for_parameter(y_name) else (
                self._channel_selector.y_transform()
            ),
            x_transform_id=(
                None if self._transform_for_parameter(x_name) is None
                else self._transform_for_parameter(x_name).id
            ),
            y_transform_id=(
                None if self._transform_for_parameter(y_name) is None
                else self._transform_for_parameter(y_name).id
            ),
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

        if self._channel_selector.is_count_mode():
            self._update_status(
                "2D gate creation is unavailable while Y is Count; "
                "select a channel for Y first."
            )
            return False

        if gate_type == "rectangle":
            self._gate_editor.cancel_polygon(preserve_child_mode=True)
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

    def _on_marginal_toggled(self, enabled: bool) -> None:
        """Handle marginal histogram toggle."""
        self._plot_widget.set_marginal_enabled(enabled)
        status = "Marginal histograms enabled" if enabled else "Marginal histograms disabled"
        self._update_status(status)
        self._replot()

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

    def _on_export_statistics(self) -> None:
        """Export custom statistics from the latest non-stale report."""
        report = self._population_tree.last_report()
        if report is None or not report.statistic_results:
            QMessageBox.information(
                self,
                "No results",
                "Run Pipeline before exporting Statistics.",
            )
            return
        if self._results_stale:
            QMessageBox.information(
                self,
                "Results stale",
                "Results are stale. Run Pipeline again before exporting.",
            )
            return

        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Statistics",
            "",
            "TSV files (*.tsv);;CSV files (*.csv);;All files (*)",
        )
        if not path_str:
            return
        delimiter = "," if selected_filter.startswith("CSV") or path_str.endswith(".csv") else "\t"
        try:
            self._export_statistics_to_path(path_str, delimiter=delimiter)
            self._update_status(f"Statistics exported to {path_str}")
        except Exception as exc:
            logger.error("Statistics export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_statistics_to_path(
        self,
        path: str | Path,
        delimiter: str = "\t",
    ) -> None:
        """Write current non-stale statistic results using core export helpers."""
        if self._results_stale:
            raise RuntimeError("Results are stale; rerun pipeline before export")
        report = self._population_tree.last_report()
        if report is None or not report.statistic_results:
            raise RuntimeError("No Statistics available for export")

        from flowdesk_core.export import write_statistic_results

        write_statistic_results(list(report.statistic_results), path, delimiter=delimiter)

    def _mark_results_stale(self, reason: str) -> None:
        self._results_stale = True
        self._population_tree.clear()
        self._population_tree.mark_results_stale()
        self._diagnostics_panel.clear(stale=True)
        self._gate_editor.clear_population_results()
        self._selected_population_id = "all_events"
        self._compensation_status_indicator.mark_stale()
        self._update_status(f"{reason} (results stale; rerun pipeline)")

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

    # -- compensation status -------------------------------------------------

    def _update_compensation_status(self) -> None:
        """Update the compensation status indicator based on current project state.

        Shows which matrix is applied to the current sample and its validity.
        """
        sample_id = self._current_sample_id
        if not sample_id:
            self._compensation_status_indicator.set_none(stale=self._results_stale)
            return

        # Build matrix specs from current compensation definitions
        matrix_specs = self._build_compensation_matrix_specs()
        if not matrix_specs:
            self._compensation_status_indicator.set_none(stale=self._results_stale)
            return

        # Resolve which matrix applies to the current sample
        known_ids = {spec.id for spec in matrix_specs}
        resolution = self._resolve_current_sample_binding(
            sample_id, known_ids, matrix_specs
        )

        if resolution is None:
            self._compensation_status_indicator.set_none(stale=self._results_stale)
            return

        matrix_id, matrix_name = resolution
        if not matrix_id:
            self._compensation_status_indicator.set_none(stale=self._results_stale)
            return

        # Inspect the matrix for validity
        spec = next(
            (s for s in matrix_specs if s.id == matrix_id),
            None,
        )
        if spec is None:
            self._compensation_status_indicator.set_error(
                f"Unknown matrix: {matrix_id}",
                stale=self._results_stale,
            )
            return

        channel_ids = self._get_current_channel_ids()
        try:
            inspection = inspect_compensation_matrix(spec, channel_ids)
            if not inspection.is_valid:
                error_msg = next(
                    (d.message for d in inspection.diagnostics if d.severity == "error"),
                    "Invalid compensation matrix",
                )
                self._compensation_status_indicator.set_error(
                    error_msg,
                    stale=self._results_stale,
                )
            elif inspection.condition_number is not None:
                from flowdesk_core.compensation import (
                    COMPENSATION_CONDITION_WARNING_THRESHOLD,
                )
                if (
                    inspection.condition_number
                    >= COMPENSATION_CONDITION_WARNING_THRESHOLD
                ):
                    self._compensation_status_indicator.set_warning(
                        matrix_name,
                        inspection.condition_number,
                        stale=self._results_stale,
                    )
                else:
                    self._compensation_status_indicator.set_valid(
                        matrix_name,
                        stale=self._results_stale,
                    )
            else:
                self._compensation_status_indicator.set_valid(
                    matrix_name,
                    stale=self._results_stale,
                )
        except Exception:
            self._compensation_status_indicator.set_error(
                "Matrix inspection failed",
                stale=self._results_stale,
            )

    def _build_compensation_matrix_specs(
        self,
    ) -> tuple[CompensationMatrixSpec, ...]:
        """Build CompensationMatrixSpec objects from current UI state."""
        specs = []
        for matrix_dict in self._compensation_matrices:
            try:
                specs.append(CompensationMatrixSpec(
                    id=matrix_dict["id"],
                    name=matrix_dict.get("name", matrix_dict["id"]),
                    source=matrix_dict.get("source", "user_defined"),
                    channels=tuple(matrix_dict.get("channels", [])),
                    matrix=tuple(
                        tuple(row) for row in matrix_dict.get("matrix", [])
                    ),
                    created_by=matrix_dict.get("created_by"),
                    created_at=matrix_dict.get("created_at"),
                    notes=matrix_dict.get("notes", ""),
                ))
            except (ValueError, KeyError):
                continue
        return tuple(specs)

    def _resolve_current_sample_binding(
        self,
        sample_id: str,
        known_matrix_ids: set[str],
        matrix_specs: tuple[CompensationMatrixSpec, ...],
    ) -> tuple[str | None, str] | None:
        """Resolve which compensation matrix applies to the current sample.

        Returns (matrix_id, matrix_name) or None if no binding.
        """
        from flowdesk_core.models import CompensationBindingSpec as BindingSpec

        bindings = []
        for binding_dict in self._compensation_bindings:
            try:
                bindings.append(BindingSpec(
                    id=binding_dict["id"],
                    matrix_id=binding_dict["matrix_id"],
                    scope=binding_dict.get("scope", "sample"),
                    target_id=binding_dict["target_id"],
                    created_at=binding_dict.get("created_at"),
                    created_by=binding_dict.get("created_by"),
                    notes=binding_dict.get("notes", ""),
                ))
            except (ValueError, KeyError):
                continue

        if not bindings:
            default_id = self._default_compensation_matrix_id
            if default_id:
                default_name = next(
                    (s.name for s in matrix_specs if s.id == default_id),
                    default_id,
                )
                return (default_id, default_name)
            return None

        try:
            resolution = resolve_compensation_binding(
                bindings,
                sample_id=sample_id,
                execution_profile_id="default",
                group_ids=[],
                default_matrix_id=self._default_compensation_matrix_id,
                known_matrix_ids=known_matrix_ids,
            )
            if resolution.matrix_id is None:
                return None
            matrix_name = next(
                (s.name for s in matrix_specs if s.id == resolution.matrix_id),
                resolution.matrix_id,
            )
            return (resolution.matrix_id, matrix_name)
        except Exception:
            return None

    def _get_current_channel_ids(self) -> list[str]:
        """Get the channel IDs for the currently selected sample."""
        sample = self._sample_data.get(self._current_sample_id or "")
        if sample is not None:
            return [ch.id for ch in sample.channels]
        selected = self._sample_browser.selected_sample()
        if selected is not None:
            return [ch.id for ch in selected.info.channels]
        return []
