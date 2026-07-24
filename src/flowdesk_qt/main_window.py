"""Main window for Flowdesk.

Assembles the UI components and delegates all scientific computation to
``flowdesk_core.pipeline_runner``.  This module contains NO analysis logic.
"""

from __future__ import annotations

import logging
import os
import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QSettings, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolBar,
    QWidget,
)

from flowdesk_core.analysis_settings import preflight_analysis_settings
from flowdesk_core.compensation import (
    inspect_compensation_matrix,
    resolve_compensation_binding,
)
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import read_fcs_sample
from flowdesk_core.gate_transform_migration import preview_gate_transform_migration
from flowdesk_core.integrated_overlay import resolve_overlay_style
from flowdesk_core.models import (
    AnnotationSpec,
    ChannelSpec,
    CompensationMatrixSpec,
    OverlaySourceSpec,
    TransformSpec,
)
from flowdesk_core.overlays import Overlay2DLayer
from flowdesk_core.overrides import (
    GateOverrideError,
    gate_version_hash,
    inspect_gate_override_statuses,
    override_spec_from_mapping,
    resolve_gate_overrides,
)
from flowdesk_core.parameter_catalog import (
    ParameterCatalogDiagnostic,
    ParameterCatalogEntry,
    build_parameter_catalog,
)
from flowdesk_core.pipeline_runner import PipelineError, PipelineRunner
from flowdesk_core.plot_presentation import (
    SamplePresentationContext,
    resolve_overlay_sources,
    resolve_presentation_layers,
)
from flowdesk_core.preview import (
    PreviewReport,
    PreviewRequest,
    PreviewRevisionState,
)
from flowdesk_core.processed_display import (
    ProcessedDisplayRequest,
    ProcessedDisplayResult,
)
from flowdesk_core.project_commands import (
    CreateGateOverrideCommand,
    EditOverlaySourcesCommand,
    EditPlotPresentationCommand,
    EditPlotRenderingDownsampleCommand,
    ReplaceAnalysisSettingsCommand,
    UndoStack,
)
from flowdesk_core.sample import SampleData
from flowdesk_qt.app_info import APP_NAME, application_version
from flowdesk_qt.app_paths import cache_directory
from flowdesk_qt.channel_metadata import ChannelMetadataWorkspace
from flowdesk_qt.channel_selector import DEFAULT_DISPLAY_MAX_POINTS, ChannelSelector
from flowdesk_qt.diagnostics_panel import DiagnosticsPanel
from flowdesk_qt.gate_editor import GateEditor
from flowdesk_qt.gate_override_editor import GateOverrideDialog
from flowdesk_qt.group_panel import GroupPanel
from flowdesk_qt.plot_toolbar import PlotToolbar
from flowdesk_qt.plot_widget import PlotWidget
from flowdesk_qt.population_tree import PopulationTree
from flowdesk_qt.preview_scheduler import PreviewScheduler
from flowdesk_qt.processed_display_scheduler import ProcessedDisplayScheduler
from flowdesk_qt.results_export_dialog import ResultsExportOptions
from flowdesk_qt.results_state import RuntimeResultState
from flowdesk_qt.results_workspace import ResultsWorkspace
from flowdesk_qt.sample_browser import SampleBrowser, _SampleInfo
from flowdesk_qt.workspace_tree import WorkspaceTree
from flowdesk_storage.analysis_settings import (
    load_analysis_settings,
    save_analysis_settings,
)
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import load_project, resolve_sample_paths, save_project
from flowdesk_storage.recovery import AutosaveSettings, RecoveryManager
from flowdesk_storage.serialization import now_iso

logger = logging.getLogger(__name__)

RIGHT_PANE_MIN_WIDTH = 280


# Advanced overlay sources are display-only and are now consumed by the same canonical
# processed-display path as the Samples-pane overlay controls.
ADVANCED_OVERLAY_LIVE_RENDERING_AVAILABLE = True


def _is_release_build() -> bool:
    """Return whether unfinished UI must be hidden rather than shown disabled."""
    return os.environ.get("FLOWDESK_BUILD_CHANNEL", "development").strip().lower() == "release"


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
        revision: int = 0,
    ) -> None:
        super().__init__()
        self._project = project
        self._samples = samples
        self._profile_id = profile_id
        self.revision = revision
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

    LEFT_PANE_MIN_WIDTH = 220

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("flowdeskMainWindow")
        self.setWindowTitle("Flowdesk")
        self.resize(1400, 900)

        # Internal state
        self._event_data: dict[str, NDArray[np.float64]] = {}
        self._sample_data: dict[str, SampleData] = {}
        self._channel_names: list[str] = []
        # These are deliberately independent display states.  The sample being
        # viewed, the population membership used for filtering, and the gate
        # definition being edited must not be inferred from one another.
        self._active_sample_id: str | None = None
        self._worker: _PipelineWorker | None = None
        self._results_stale = False
        self._results_stale_reason: str | None = None
        self._pending_results_export: tuple[
            ResultsExportOptions, str, str
        ] | None = None
        self._auto_recalculate_timer = QTimer(self)
        self._auto_recalculate_timer.setSingleShot(True)
        self._auto_recalculate_timer.setInterval(300)
        self._auto_recalculate_timer.timeout.connect(
            self._start_auto_recalculation
        )
        self._project_dirty = False
        self._autosave_settings = AutosaveSettings(
            enabled=bool(QSettings().value("autosave/enabled", True, type=bool)),
            interval_seconds=int(QSettings().value("autosave/interval_seconds", 300)),
            retention=int(QSettings().value("autosave/retention", 5)),
        )
        self._recovery_manager = RecoveryManager(cache_directory() / "recovery")
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self._autosave_settings.interval_seconds * 1000)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        if self._autosave_settings.enabled:
            self._autosave_timer.start()
        self._project_id = "flowdesk_session"
        self._project_path: Path | None = None
        self._derived_parameters: list[dict[str, Any]] = []
        self._parameter_catalog: tuple[ParameterCatalogEntry, ...] = ()
        self._compensation_matrices: list[dict[str, Any]] = []
        self._compensation_bindings: list[dict[str, Any]] = []
        self._compensation_calculations: list[dict[str, Any]] = []
        self._transforms: list[dict[str, Any]] = []
        self._statistics: list[dict[str, Any]] = []
        self._batch_plot_exports: list[dict[str, Any]] = []
        self._plot_views: list[dict[str, Any]] = []
        self._overlays: list[dict[str, Any]] = []
        self._overlay_undo_stack = UndoStack(
            {"plot_views": []}, on_changed=self._on_overlay_state_changed
        )
        self._analysis_settings_undo_stack: UndoStack | None = None
        self._backgating_specs: list[dict[str, Any]] = []
        self._auto_gate_templates: list[dict[str, Any]] = []
        self._auto_gate_fits: list[dict[str, Any]] = []
        self._magnetic_gate_templates: list[dict[str, Any]] = []
        self._magnetic_gate_fits: list[dict[str, Any]] = []
        self._tethered_gate_templates: list[dict[str, Any]] = []
        self._tethered_gate_fits: list[dict[str, Any]] = []
        self._default_compensation_matrix_id: str | None = None
        self._migration_diagnostics: list[dict[str, Any]] = []
        self._advanced_groups_enabled = False
        self._sample_groups: list[dict[str, Any]] = []
        self._group_strategy_bindings: list[dict[str, Any]] = []
        self._annotations: list[dict[str, Any]] = []
        self._gate_overrides: list[dict[str, Any]] = []
        self._override_undo_stack = UndoStack({"gate_overrides": []})
        self._display_population_id: str = "all_events"
        self._plot_transform_overrides: dict[str, str | None] = {}
        self._display_transform_overrides: dict[str, str] = {}
        self._selected_gate_id: str | None = None
        self._pending_gate_geometry_updates: dict[str, Any] = {}
        self._preview_revision = PreviewRevisionState()
        self._preview_report: PreviewReport | None = None
        self._last_result_report = None
        self._processed_display_cache: dict[tuple[object, ...], ProcessedDisplayResult] = {}
        self._old_membership_banner = False
        self._result_state = RuntimeResultState()
        self._preview_scheduler = PreviewScheduler(self)
        self._preview_scheduler.preview_ready.connect(self._on_preview_ready)
        self._preview_scheduler.preview_failed.connect(self._on_preview_failed)
        self._processed_display_scheduler = ProcessedDisplayScheduler(self)
        self._processed_display_scheduler.display_ready.connect(
            self._on_processed_display_ready
        )
        self._processed_display_scheduler.display_failed.connect(
            self._on_processed_display_failed
        )

        self._compensation_status_indicator = _CompensationStatusIndicator()
        self._build_menu()
        self._build_toolbar()
        self._build_central_widget()
        self._connect_signals()
        self._update_status("Ready")
        self._update_compensation_status()
        self._update_undo_actions()

    # -- public API ----------------------------------------------------------

    @property
    def _current_sample_id(self) -> str | None:
        """Backward-compatible name for the active sample display state."""
        return self._active_sample_id

    @_current_sample_id.setter
    def _current_sample_id(self, value: str | None) -> None:
        self._active_sample_id = value

    @property
    def _selected_population_id(self) -> str:
        """Backward-compatible name for the display population state."""
        return self._display_population_id

    @_selected_population_id.setter
    def _selected_population_id(self, value: str) -> None:
        self._display_population_id = value

    @property
    def active_sample_id(self) -> str | None:
        return self._active_sample_id

    @property
    def display_population_id(self) -> str:
        return self._display_population_id

    @property
    def selected_gate_id(self) -> str | None:
        return self._selected_gate_id

    @property
    def analysis_revision(self) -> int:
        return self._preview_revision.analysis_revision

    @property
    def authoritative_result_revision(self) -> int | None:
        return self._preview_revision.authoritative_result_revision

    @property
    def preview_result_revision(self) -> int | None:
        return self._preview_revision.preview_result_revision

    @property
    def preview_status(self) -> str:
        return self._preview_revision.preview_status

    def load_samples_from_directory(self, directory: str | Path) -> int:
        """Load FCS samples from a directory."""
        return self._sample_browser.add_samples_from_directory(directory)

    def debug_state(self) -> dict[str, object]:
        """Return JSON-serializable GUI state without raw event arrays."""
        worker = self._worker
        report = self._population_tree.last_report()
        worker_error = None if worker is None else worker._error
        return {
            "application": {"name": APP_NAME, "version": application_version()},
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
            "active_sample_id": self._active_sample_id,
            "display_population_id": self._display_population_id,
            "selected_gate_id": self._selected_gate_id,
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
                "analysis_revision": self.analysis_revision,
                "authoritative_result_revision": self.authoritative_result_revision,
                "preview_result_revision": self.preview_result_revision,
                "preview_status": self.preview_status,
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
                "selected_population_id": self._display_population_id,
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

        self.action_save_analysis_settings = QAction(
            "Save Analysis Settings...", self
        )
        self.action_save_analysis_settings.setObjectName(
            "actionSaveAnalysisSettings"
        )
        self.action_save_analysis_settings.triggered.connect(
            self._on_save_analysis_settings
        )
        file_menu.addAction(self.action_save_analysis_settings)

        self.action_load_analysis_settings = QAction(
            "Load Analysis Settings...", self
        )
        self.action_load_analysis_settings.setObjectName(
            "actionLoadAnalysisSettings"
        )
        self.action_load_analysis_settings.triggered.connect(
            self._on_load_analysis_settings
        )
        file_menu.addAction(self.action_load_analysis_settings)

        file_menu.addSeparator()

        self.action_export_results = QAction("Export &Results...", self)
        self.action_export_results.setObjectName("actionExportResults")
        self.action_export_results.triggered.connect(self._on_export_results)

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
        self.action_undo_analysis_settings = QAction(
            "Undo Analysis Settings", self
        )
        self.action_undo_analysis_settings.setObjectName(
            "actionUndoAnalysisSettings"
        )
        self.action_undo_analysis_settings.triggered.connect(
            self._on_undo_analysis_settings
        )
        edit_menu.addAction(self.action_undo_analysis_settings)
        self.action_redo_analysis_settings = QAction(
            "Redo Analysis Settings", self
        )
        self.action_redo_analysis_settings.setObjectName(
            "actionRedoAnalysisSettings"
        )
        self.action_redo_analysis_settings.triggered.connect(
            self._on_redo_analysis_settings
        )
        edit_menu.addAction(self.action_redo_analysis_settings)
        self.action_create_gate_override = QAction(
            "Create Sample Gate &Override...", self
        )
        self.action_create_gate_override.setObjectName("actionCreateGateOverride")
        self.action_create_gate_override.triggered.connect(
            self._on_create_gate_override
        )
        edit_menu.addAction(self.action_create_gate_override)
        self.action_undo_overlay_sources = QAction("Undo Overlay Source Change", self)
        self.action_undo_overlay_sources.setObjectName("actionUndoOverlaySourceChange")
        self.action_undo_overlay_sources.triggered.connect(self._on_undo_overlay_sources)
        edit_menu.addAction(self.action_undo_overlay_sources)
        self.action_redo_overlay_sources = QAction("Redo Overlay Source Change", self)
        self.action_redo_overlay_sources.setObjectName("actionRedoOverlaySourceChange")
        self.action_redo_overlay_sources.triggered.connect(self._on_redo_overlay_sources)
        edit_menu.addAction(self.action_redo_overlay_sources)

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

        self.action_transforms = QAction("Manage Parameter &Transforms...", self)
        self.action_transforms.setObjectName("actionTransforms")
        self.action_transforms.triggered.connect(self._on_edit_transforms)
        analysis_menu.addAction(self.action_transforms)

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

        # Results owns persisted statistic definitions and result export. Context actions
        # elsewhere only prefill the same shared editor.
        results_menu = menubar.addMenu("&Results")
        self.action_add_statistic = QAction("&Add Statistic...", self)
        self.action_add_statistic.setObjectName("actionAddStatistic")
        self.action_add_statistic.triggered.connect(
            lambda: self._on_add_statistic_from_results("all_events")
        )
        results_menu.addAction(self.action_add_statistic)
        self.action_statistics = QAction("Manage &Statistics...", self)
        self.action_statistics.setObjectName("actionStatistics")
        self.action_statistics.triggered.connect(self._on_edit_statistics)
        results_menu.addAction(self.action_statistics)
        results_menu.addSeparator()
        results_menu.addAction(self.action_export_results)
        self.action_batch_plot_export = QAction("Batch Plot E&xport...", self)
        self.action_batch_plot_export.setObjectName("actionBatchPlotExport")
        self.action_batch_plot_export.triggered.connect(self._on_batch_plot_export)
        results_menu.addAction(self.action_batch_plot_export)

        # Data owns sample metadata presentation. The detailed parameter workspace stays
        # read-only in this increment; catalog integration follows in B7.4 Increment 2.
        data_menu = menubar.addMenu("&Data")
        self.action_sample_sheet = QAction("Sample &Sheet...", self)
        self.action_sample_sheet.setObjectName("actionSampleSheet")
        self.action_sample_sheet.triggered.connect(self._on_edit_sample_sheet)
        data_menu.addAction(self.action_sample_sheet)
        self.action_parameter_information = QAction(
            "Channel / Parameter &Information", self
        )
        self.action_parameter_information.setObjectName("actionParameterInformation")
        self.action_parameter_information.triggered.connect(
            self._on_focus_parameter_information
        )
        data_menu.addAction(self.action_parameter_information)

        # Plot owns display-only actions. Advanced sources and Samples-pane Ov controls
        # share the same processed-display renderer.
        plot_menu = menubar.addMenu("&Plot")
        self.action_overlay_samples = QAction("Overlay &Samples", self)
        self.action_overlay_samples.setObjectName("actionOverlaySamples")
        self.action_overlay_samples.setToolTip(
            "Use the Samples pane Ov column to select compatible overlay samples."
        )
        self.action_overlay_samples.triggered.connect(self._on_focus_overlay_samples)
        plot_menu.addAction(self.action_overlay_samples)
        self.action_overlay_sources = QAction(
            "Advanced Overlay Sources...", self
        )
        self.action_overlay_sources.setObjectName("actionOverlaySources")
        self.action_overlay_sources.setToolTip(
            "Configure compatible per-layer sample/population overlays and styles."
        )
        self.action_overlay_sources.setStatusTip(self.action_overlay_sources.toolTip())
        self.action_overlay_sources.setEnabled(ADVANCED_OVERLAY_LIVE_RENDERING_AVAILABLE)
        self.action_overlay_sources.setVisible(
            ADVANCED_OVERLAY_LIVE_RENDERING_AVAILABLE or not _is_release_build()
        )
        if ADVANCED_OVERLAY_LIVE_RENDERING_AVAILABLE:
            self.action_overlay_sources.triggered.connect(self._on_edit_overlay_sources)
        plot_menu.addAction(self.action_overlay_sources)
        self.action_plot_presentation = QAction("Plot &Presentation...", self)
        self.action_plot_presentation.setObjectName("actionPlotPresentation")
        self.action_plot_presentation.triggered.connect(self._on_edit_plot_presentation)
        plot_menu.addAction(self.action_plot_presentation)

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
        action_export_results.setObjectName("toolbarExportResults")
        action_export_results.triggered.connect(self._on_export_results)
        toolbar.addAction(action_export_results)

    # -- central widget ------------------------------------------------------

    def _build_central_widget(self) -> None:
        # --- Left pane: sample browser ---
        self._sample_browser = SampleBrowser()

        # --- Center pane: channel selector + plot ---
        self._channel_selector = ChannelSelector()
        self._plot_widget = PlotWidget()
        self._plot_widget.set_max_display_points(
            self._channel_selector.display_max_points()
        )
        self._plot_widget.appearance_requested.connect(
            self._on_plot_appearance_requested
        )
        self._plot_widget.view_range_requested.connect(
            self._on_set_numeric_view_range
        )

        center_widget = self._create_center_pane()

        # --- Right pane: gate editor + population tree ---
        self._gate_editor = GateEditor()
        self._group_panel = GroupPanel()
        self._group_panel.setVisible(False)
        self._population_tree = PopulationTree()
        self._results_workspace = ResultsWorkspace()
        self._channel_metadata = ChannelMetadataWorkspace()
        self._workspace_tree = WorkspaceTree()
        self._diagnostics_panel = DiagnosticsPanel()
        self._workspace_navigation = self._create_workspace_navigation()

        right_widget = self._create_right_pane()

        # --- Assemble with splitters ---
        splitter1 = QSplitter(Qt.Horizontal)
        splitter1.setObjectName("mainContentSplitter")
        splitter1.addWidget(self._sample_browser)
        splitter1.addWidget(center_widget)
        self._sample_browser.setMinimumWidth(self.LEFT_PANE_MIN_WIDTH)
        splitter1.setCollapsible(0, False)
        splitter1.setStretchFactor(0, 1)
        splitter1.setStretchFactor(1, 3)

        splitter2 = QSplitter(Qt.Horizontal)
        splitter2.setObjectName("mainOuterSplitter")
        splitter2.addWidget(splitter1)
        splitter2.addWidget(right_widget)
        splitter2.setStretchFactor(0, 4)
        splitter2.setStretchFactor(1, 2)
        splitter2.setCollapsible(1, False)

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
        widget.setMinimumWidth(RIGHT_PANE_MIN_WIDTH)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.setObjectName("gatingResultsTabs")
        tabs.setMinimumWidth(RIGHT_PANE_MIN_WIDTH)

        gating_tab = QWidget()
        gating_layout = QVBoxLayout(gating_tab)
        gating_layout.setContentsMargins(0, 0, 0, 0)
        gating_layout.addWidget(self._gate_editor)
        gating_layout.addWidget(self._group_panel)
        gating_layout.setStretch(0, 1)
        tabs.addTab(gating_tab, "Gating")

        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self._workspace_navigation)
        results_layout.addWidget(self._results_workspace)
        results_layout.addWidget(self._diagnostics_panel)
        results_layout.setStretch(0, 0)
        results_layout.setStretch(1, 1)
        results_layout.setStretch(2, 1)
        tabs.addTab(results_tab, "Results")

        channels_tab = QWidget()
        channels_layout = QVBoxLayout(channels_tab)
        channels_layout.setContentsMargins(0, 0, 0, 0)
        channels_layout.addWidget(self._channel_metadata)
        tabs.addTab(channels_tab, "Channels")

        # Transitional adapters remain available to existing callers/tests,
        # but duplicate result tables are no longer visible in the GUI.
        self._workspace_tree.setVisible(False)
        self._population_tree.setVisible(False)
        layout.addWidget(tabs)
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

    def _refresh_override_statuses(self) -> None:
        """Refresh definition badges and the plot banner without executing analysis."""
        strategy = PipelineRunner._strategy_from_mapping({
            "id": "default_strategy",
            "name": "Default Strategy",
            "gates": [asdict(gate) for gate in self._gate_editor.gates()],
        })
        try:
            overrides = tuple(
                override_spec_from_mapping(value)
                for value in self._gate_overrides
            )
            statuses = inspect_gate_override_statuses(
                strategy,
                [sample.id for sample in self._sample_browser.samples()],
                overrides,
                results_stale=self._results_stale,
            )
        except Exception as exc:
            logger.warning("Could not inspect gate overrides: %s", exc)
            statuses = {
                sample.id: {
                    "override_status": "missing",
                    "results_stale": self._results_stale,
                }
                for sample in self._sample_browser.samples()
            }
        self._workspace_tree.set_override_statuses(statuses)
        current = statuses.get(self._current_sample_id or "", {})
        definition_status = str(current.get("override_status", "shared"))
        banner = "" if definition_status == "shared" else f"override {definition_status}"
        if current.get("results_stale"):
            stale_reason = self._results_stale_reason or "Analysis definition changed"
            stale_banner = f"{stale_reason} — results stale; rerun Pipeline"
            banner = f"{banner}; {stale_banner}" if banner else stale_banner
        self._plot_widget.set_status_banner(banner)

    def _on_create_gate_override(self) -> None:
        """Create an override only through an explicit audited user action."""
        sample_id = self._current_sample_id
        gate = self._gate_editor.selected_gate()
        if not sample_id or gate is None:
            QMessageBox.information(
                self,
                "Select Gate",
                "Select a sample and gate before creating a sample override.",
            )
            return
        sample_ids = [sample_id]
        selected = self._sample_browser.selected_sample()
        if selected is not None:
            for group in self._sample_groups:
                if selected.id in group.get("sample_ids", []):
                    sample_ids = [str(value) for value in group.get("sample_ids", [])]
                    break
        dialog = GateOverrideDialog(
            gate,
            sample_id,
            sample_ids,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        specification = dialog.specification()
        purpose = specification["gate_purpose"]
        warning = (
            "This creates a comparison-critical sample override. It changes the "
            "selected sample's geometry for comparison and will be recorded in QC."
            if purpose == "comparison_critical"
            else (
                "This creates a sample-specific geometry override. Other samples "
                "remain on group geometry."
            )
        )
        answer = QMessageBox.question(
            self,
            "Confirm Sample Override",
            warning + "\n\nAffected samples: " + ", ".join(sample_ids),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        override = {
            "id": f"{sample_id}:{gate.id}:{uuid.uuid4().hex[:8]}",
            "base_version_hash": gate_version_hash(gate),
            "created_at": now_iso(),
            **specification,
          }
        try:
            state = self._override_undo_stack.execute(
                CreateGateOverrideCommand(override)
            )
        except Exception as exc:
            QMessageBox.warning(self, "Override Not Created", str(exc))
            return
        self._gate_overrides = deepcopy(state["gate_overrides"])
        self._project_dirty = True
        self._mark_results_stale("Sample gate override created")
        self._replot()

    def _display_gates(self) -> list[Any]:
        """Resolve only plot overlays; GateEditor continues editing shared gates."""
        gates = list(self._gate_editor.gates())
        if not self._current_sample_id or not self._gate_overrides:
            return gates
        strategy = PipelineRunner._strategy_from_mapping({
            "id": "default_strategy",
            "name": "Default Strategy",
            "gates": [asdict(gate) for gate in gates],
        })
        try:
            overrides = tuple(
                override_spec_from_mapping(value)
                for value in self._gate_overrides
            )
            return list(resolve_gate_overrides(strategy, self._current_sample_id, overrides).gates)
        except (GateOverrideError, ValueError, TypeError) as exc:
            logger.warning("Could not resolve gate overlay: %s", exc)
            return gates

    # -- signal connections --------------------------------------------------

    def _connect_signals(self) -> None:
        # When a sample is selected, load its channels and plot
        self._sample_browser.on_sample_selected(self._on_sample_selected)

        # When a sample is removed, clean up its associated state
        self._sample_browser.on_sample_removed(self._on_sample_removed)
        self._sample_browser.on_sample_reconnected(self._on_sample_reconnected)
        self._sample_browser.on_overlay_changed(self._on_manual_overlay_changed)

        # When channel selection changes, replot
        self._channel_selector.on_channel_changed(self._on_channel_changed)
        self._channel_selector.on_display_max_points_changed(
            self._on_display_max_points_changed
        )
        self._channel_selector.on_analysis_transform_requested(
            self._on_axis_analysis_transform_requested
        )

        # When a gate is selected, update highlight
        self._gate_editor.on_gate_selected(self._on_gate_selected)

        # When the gate list changes (add/delete/clear), refresh overlays and invalidate results
        self._gate_editor.on_gates_changed(self._on_gates_changed)
        self._gate_editor.population_display_color_changed.connect(
            self._on_population_display_color_changed
        )

        # Interactive gate creation starts from the gate editor.
        self._gate_editor.on_interactive_gate_requested(self._on_interactive_gate_requested)
        self._gate_editor.on_show_gate(self._on_show_gate)
        self._gate_editor.on_show_population(self._on_show_population)
        self._gate_editor.on_migrate_gate(self._on_migrate_gate)

        # Plot toolbar callbacks
        self._plot_toolbar.on_reset_robust(self._on_reset_robust)
        self._plot_toolbar.on_reset_full(self._on_reset_full)
        self._plot_toolbar.on_export_png(self._on_export_png)
        self._plot_toolbar.on_export_svg(self._on_export_svg)
        self._plot_toolbar.on_export_pdf(self._on_export_pdf)
        self._plot_toolbar.on_export_aspect_toggled(self._on_export_aspect_toggled)
        self._plot_toolbar.on_add_statistic(self._on_add_statistic_from_graph)
        self._plot_toolbar.on_interaction_mode(self._on_interaction_mode)
        self._plot_toolbar.on_marginal_toggled(self._on_marginal_toggled)
        self._group_panel.groups_changed.connect(self._on_groups_changed)

        # Population selection (display-only filter)
        self._population_tree.on_population_selected(self._on_population_selected)
        self._population_tree.on_add_statistic_requested(
            self._on_add_statistic_from_population_tree
        )
        self._results_workspace.on_selection_changed(
            self._on_results_workspace_selected
        )
        self._results_workspace.on_add_statistic_requested(
            self._on_add_statistic_from_results
        )
        self._results_workspace.on_manage_statistics_requested(
            self._open_statistics_manager
        )
        self._results_workspace.on_auto_recalculate_changed(
            self._on_auto_recalculate_changed
        )
        self._workspace_tree.on_selection_changed(self._on_workspace_tree_selected)

        # Connect plot mouse events to gate creation
        self._plot_widget.on_mouse_clicked(self._on_plot_mouse_clicked)
        self._plot_widget.on_gate_geometry_changed(self._queue_gate_geometry_changed)

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
        self._refresh_sample_display_names()
        self._results_workspace.set_population_hierarchy(
            self._population_parent_map(), self._population_name_map()
        )
        self._channel_metadata.set_sample(sample)
        self._workspace_tree.select("sample", sample.id)
        self._update_workspace_navigation()
        self._refresh_override_statuses()
        report = self._population_tree.last_report()
        if report is not None and not self._results_stale:
            self._validate_population_selection(report)
        self._channel_names = [ch.name for ch in sample.info.channels]
        self._parameter_catalog = self._catalog_for_sample(sample)
        self._channel_metadata.set_parameter_catalog(self._parameter_catalog)
        x_preserved, y_preserved = self._channel_selector.set_parameter_catalog(
            self._parameter_catalog, allow_derived=True
        )

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

    def _on_manual_overlay_changed(self, state: dict[str, object]) -> None:
        """Refresh display layers without changing active sample or pipeline state."""
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            None,
        )
        if view is not None:
            view["manual_overlay_sample_ids"] = list(
                state.get("manual_overlay_sample_ids", [])
            )
            view["manual_overlay_colors"] = dict(
                state.get("manual_overlay_colors", {})
            )
            view["overlay_mode"] = state.get("overlay_mode", "manual_only")
        # Loading a selected FCS is input acquisition only.  Coordinates still
        # come exclusively from the canonical processed-display runner.
        selected_ids = set(state.get("manual_overlay_sample_ids", []))
        samples_by_id = {sample.id: sample for sample in self._sample_browser.samples()}
        for sample_id in selected_ids:
            if sample_id in self._event_data:
                continue
            sample = samples_by_id.get(sample_id)
            if sample is not None and sample.status not in {"missing", "fingerprint mismatch"}:
                self._load_sample_events(sample)
        self._project_dirty = True
        # Retain immediate overlay feedback for the supported Samples-pane
        # control.  The calculation remains in the core runner; subsequent
        # plot changes continue through the coalescing display scheduler.
        active = self._sample_data.get(self._current_sample_id or "")
        if active is not None:
            x_id = self._channel_selector.x_channel_id()
            y_id = self._channel_selector.y_channel_id()
            request = self._processed_display_request(
                active,
                x_id,
                y_id,
                self._active_plot_transform(x_id),
                None
                if self._channel_selector.is_count_mode()
                else self._active_plot_transform(y_id),
            )
            key = self._processed_display_key(request)
            if key not in self._processed_display_cache:
                try:
                    self._processed_display_cache[key] = PipelineRunner(
                        self._build_project_manifest()
                    ).prepare_display_sample(request)
                except Exception as exc:
                    self._update_status(f"Processed display error: {exc}")
        self._replot()

    def _on_population_display_color_changed(
        self, _population_id: str, _definitions: object
    ) -> None:
        """Persist and redraw display-only population color edits."""
        self._project_dirty = True
        self._replot()

    def _on_sample_removed(self, sample: _SampleInfo) -> None:
        """Called when a sample is removed from the browser."""
        # Remove event data for this sample
        self._event_data.pop(sample.id, None)
        self._sample_data.pop(sample.id, None)
        self._mark_results_stale(f"Removed: {sample.name}")

        # If the removed sample was the currently selected one, clear UI state
        if self._current_sample_id == sample.id:
            self._current_sample_id = None
            self._channel_metadata.set_sample(None)
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
        population_parents = self._population_parent_map()
        removed_population_ids = (
            self._result_state.defined_population_ids
            - set(population_parents)
        )
        self._result_state.remove_populations(removed_population_ids)
        self._last_result_report = None
        self._population_tree.set_population_parents(population_parents)
        self._workspace_tree.set_population_hierarchy(
            population_parents, self._population_name_map()
        )
        self._results_workspace.set_population_hierarchy(
            population_parents, self._population_name_map()
        )
        self._result_state.update_definitions(
            sample_ids=tuple(sample.id for sample in self._sample_browser.samples()),
            population_ids=tuple(population_parents),
            statistic_definitions=tuple(
                (
                    str(value.get("id")),
                    str(population_id),
                    bool(value.get("compute_enabled", True)),
                )
                for value in self._statistics
                if value.get("id")
                for population_id in value.get(
                    "population_ids",
                    [value.get("population_id", "all_events")],
                )
            ),
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

    def _on_undo_analysis_settings(self) -> None:
        stack = self._analysis_settings_undo_stack
        if stack is not None and stack.can_undo:
            stack.undo()

    def _on_redo_analysis_settings(self) -> None:
        stack = self._analysis_settings_undo_stack
        if stack is not None and stack.can_redo:
            stack.redo()

    def _update_undo_actions(self) -> None:
        self.action_undo.setEnabled(self._gate_editor.can_undo())
        self.action_redo.setEnabled(self._gate_editor.can_redo())
        settings_stack = self._analysis_settings_undo_stack
        self.action_undo_analysis_settings.setEnabled(
            settings_stack is not None and settings_stack.can_undo
        )
        self.action_redo_analysis_settings.setEnabled(
            settings_stack is not None and settings_stack.can_redo
        )
        self.action_undo_overlay_sources.setEnabled(self._overlay_undo_stack.can_undo)
        self.action_redo_overlay_sources.setEnabled(self._overlay_undo_stack.can_redo)

    # -- channel selection ---------------------------------------------------

    def _on_channel_changed(self, x_name: str, y_name: str) -> None:
        """Called when X or Y channel selection changes."""
        self._replot()

    def _on_axis_analysis_transform_requested(self, axis: str, choice: str) -> None:
        """Create or select one persisted analysis transform from an axis request."""
        if choice == "custom":
            self._on_edit_transforms()
            return
        parameter_id = (
            self._channel_selector.x_channel_id()
            if axis == "x"
            else self._channel_selector.y_channel_id()
        )
        if not parameter_id or parameter_id == "__count__":
            return
        settings_by_type: dict[str, dict[str, Any]] = {
            "log": {"base": 10.0, "invalid_value_policy": "to_nan"},
            "asinh": {"cofactor": 1.0},
            "logicle": {
                "T": 262144.0,
                "W": 0.5,
                "M": 4.5,
                "A": 0.0,
                "implementation_version": "logicle-gml2-moore-parks-2012-v1",
            },
        }
        if self._gate_editor.gates() and choice in settings_by_type:
            # Existing gates retain their immutable coordinate definitions.
            # Select (or create) a formal definition for the current plot so
            # that a subsequently drawn gate records the same transform ID.
            transform = next(
                (
                    value
                    for value in self._transform_specs()
                    if value.parameter == parameter_id
                    and value.transform_type == choice
                ),
                None,
            )
            if transform is None:
                transform_id = (
                    f"transform_{parameter_id}_{choice}_{uuid.uuid4().hex[:8]}"
                )
                self._transforms.append({
                    "id": transform_id,
                    "name": f"{parameter_id} {choice}",
                    "transform_type": choice,
                    "parameter": parameter_id,
                    "settings": settings_by_type[choice],
                    "role": "analysis",
                    "notes": "Created from the axis Transform selector.",
                })
            else:
                transform_id = transform.id
            self._plot_transform_overrides[parameter_id] = transform_id
            self._display_transform_overrides.pop(parameter_id, None)
            self._replot()
            labels = {"log": "Log10", "asinh": "Asinh", "logicle": "Logicle"}
            self._update_status(
                f"{axis.upper()} analysis transform set to {labels[choice]}; "
                "existing gate memberships unchanged"
            )
            return
        self._plot_transform_overrides.pop(parameter_id, None)
        self._display_transform_overrides.pop(parameter_id, None)
        existing = self._active_plot_transform(parameter_id)
        if choice == "linear" and existing is not None:
            # A transform referenced by a gate is part of the analysis definition.
            # Switching the plot to linear is display-only; keep that definition
            # and hide incompatible gate overlays instead of blocking the view.
            self._plot_transform_overrides[parameter_id] = None
            if axis == "x":
                self._channel_selector.set_x_transform("linear")
            else:
                self._channel_selector.set_y_transform("linear")
            self._channel_selector.set_analysis_transform_choice(axis, "linear")
            self._replot()
            self._update_status(
                f"{axis.upper()} display transform set to Linear; "
                "incompatible gate overlays are hidden"
            )
            return
        if choice == "linear":
            if existing is not None:
                if not self._replaceable_axis_transform(existing, axis):
                    return
                self._remove_axis_transform(existing)
            if axis == "x":
                self._channel_selector.set_x_transform("linear")
            else:
                self._channel_selector.set_y_transform("linear")
            self._channel_selector.set_analysis_transform_choice(axis, "linear")
            self._mark_results_stale(f"{axis.upper()} analysis transform set to Linear")
            self._replot()
            return
        if existing is not None:
            if existing.transform_type == choice:
                return
            if not self._replaceable_axis_transform(existing, axis):
                return
            self._remove_axis_transform(existing)
        if choice not in settings_by_type:
            return
        transform_id = f"transform_{parameter_id}_{choice}_{uuid.uuid4().hex[:8]}"
        self._transforms.append({
            "id": transform_id,
            "name": f"{parameter_id} {choice}",
            "transform_type": choice,
            "parameter": parameter_id,
            "settings": settings_by_type[choice],
            "role": "analysis",
            "notes": "Created from the axis Transform selector.",
        })
        self._plot_transform_overrides[parameter_id] = transform_id
        labels = {"log": "Log10", "asinh": "Asinh", "logicle": "Logicle"}
        self._mark_results_stale(f"{axis.upper()} analysis transform set to {labels[choice]}")
        self._channel_selector.set_analysis_transform_choice(axis, choice)
        # Synchronize PlotWidget and GateEditor before the user can draw a gate.
        # Without this refresh, the newly created transform exists in the
        # registry but the gate creation context still contains the previous
        # transform ID (usually None).
        self._replot()

    def _replaceable_axis_transform(self, transform: TransformSpec, axis: str) -> bool:
        """Return whether an axis quick-selection may replace *transform* safely."""
        references = self._transform_references(transform)
        if not references:
            return True
        QMessageBox.information(
            self,
            "Versioned transform is active",
            "This transform is referenced by " + ", ".join(references) + ". "
            "Create a new version in Manage Parameter Transforms and explicitly "
            "migrate dependent gates or definitions before changing this axis.",
        )
        self._channel_selector.set_analysis_transform_choice(
            axis, transform.transform_type
        )
        return False

    def _remove_axis_transform(self, transform: TransformSpec) -> None:
        """Remove an unreferenced axis transform before creating a new version."""
        self._transforms = [
            value for value in self._transforms if value.get("id") != transform.id
        ]

    def _transform_references(self, transform: TransformSpec) -> list[str]:
        """List persisted definitions that prevent replacement of a transform ID."""
        references: list[str] = []
        for gate in self._gate_editor.gates():
            x_transform_id = gate.x_transform_id
            if x_transform_id == transform.id:
                references.append(f"gate {gate.name} (X axis)")
            if gate.y_transform_id == transform.id or (
                gate.y_transform_id is None and gate.y_parameter == transform.parameter
            ):
                references.append(f"gate {gate.name} (Y axis)")
        for statistic in self._statistics:
            if statistic.get("transform_id") == transform.id:
                references.append(
                    f"statistic {statistic.get('name', statistic.get('id', 'unknown'))}"
                )
        for collection_name, definitions, source_key in (
            ("plot view", self._plot_views, "overlay_sources"),
            ("overlay", self._overlays, "sources"),
        ):
            for definition in definitions:
                name = str(definition.get("name", definition.get("id", "unknown")))
                if definition.get("transform_id") == transform.id:
                    references.append(f"{collection_name} {name}")
                for axis in ("x", "y"):
                    if definition.get(f"{axis}_transform_id") == transform.id:
                        references.append(f"{collection_name} {name} ({axis.upper()} axis)")
                for source in definition.get(source_key, []):
                    for axis in ("x", "y"):
                        if source.get(f"{axis}_transform_id") == transform.id:
                            source_name = source.get(
                                "display_name", source.get("source_id", "unknown")
                            )
                            references.append(
                                f"{collection_name} {name} source {source_name} "
                                f"({axis.upper()} axis)"
                            )
        return references

    def _on_display_max_points_changed(self, max_points: int) -> None:
        """Persist and redraw a display-only scatter sampling change."""
        try:
            self._overlay_undo_stack.execute(
                EditPlotRenderingDownsampleCommand(
                    self._overlay_view_id(), int(max_points)
                )
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Plot Parameters", str(exc))
            return
        self._replot()

    def _preview_fallback_population(self, target_population_id: str) -> str:
        """Return a current preview ancestor or All Events during recalculation."""
        report = self._preview_report
        if report is None:
            return "all_events"
        available = {
            result.population_id for result in report.population_results
        }
        fallback = self._preview_revision.nearest_valid_population(
            target_population_id,
            self._population_parent_map(),
            available,
            report.revision,
        )
        return fallback or "all_events"

    def _on_population_selected(self, population_id: str, sample_id: str) -> None:
        """Called when the user selects a population in the results table.

        This is a display-only change; it does not modify gates or analysis state.
        """
        if sample_id and sample_id != self._current_sample_id:
            self._sample_browser.select_sample(sample_id)
        # A definition change clears the authoritative report.  While preview
        # is pending, use the closest current ancestor rather than an old
        # descendant membership.  Once a current preview is accepted, its
        # complete sample result can safely drive this display-only selection.
        self._display_population_id = population_id
        self._update_workspace_navigation()
        self._replot()
        if self._results_stale:
            self._schedule_current_preview(population_id)

    def _update_workspace_navigation(self) -> None:
        sample = self._sample_browser.selected_sample()
        sample_name = sample.name if sample is not None else "-"
        population_id = self._display_population_id or "all_events"
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
        population_id = self._display_population_id or "all_events"
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

    def _on_results_workspace_selected(
        self, kind: str, stable_id: str, sample_id: str
    ) -> None:
        """Apply Results navigation without changing the gate editing target."""
        if kind == "sample":
            if sample_id != self._current_sample_id:
                self._sample_browser.select_sample(sample_id)
            return
        if kind == "population":
            self._on_population_selected(stable_id, sample_id)

    def _replot(self) -> None:
        """Replot the current sample with current channel selection and axis transforms.

        When Y channel is set to the Count option, renders a 1D histogram instead
        of a 2D scatter plot (Phase 4).
        """
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            None,
        )
        if self._current_sample_id is None:
            return

        sample_data = self._sample_data.get(self._current_sample_id)
        if sample_data is None or not self._channel_names:
            return

        x_name = self._channel_selector.x_channel()
        y_name = self._channel_selector.y_channel()
        x_id = self._channel_selector.x_channel_id()
        y_id = self._channel_selector.y_channel_id()

        x_spec = self._active_plot_transform(x_id)
        if self._channel_selector.is_count_mode():
            y_spec = None
        else:
            y_spec = self._active_plot_transform(y_id)
        self._channel_selector.set_analysis_transform_bound(
            x_spec is not None, y_spec is not None
        )
        self._channel_selector.set_analysis_transform_choice(
            "x",
            self._display_transform_overrides.get(
                x_id, "linear" if x_spec is None else x_spec.transform_type
            ),
        )
        if not self._channel_selector.is_count_mode():
            self._channel_selector.set_analysis_transform_choice(
                "y",
                self._display_transform_overrides.get(
                    y_id, "linear" if y_spec is None else y_spec.transform_type
                ),
            )
        self._plot_widget.set_axis_transform_specs(x_spec, y_spec)

        x_display_scale = (
            "linear"
            if x_spec is not None
            else self._channel_selector.x_analysis_display_transform()
        )
        y_display_scale = (
            "linear"
            if y_spec is not None
            else self._channel_selector.y_analysis_display_transform()
        )

        # Sync gate editor with current channels
        self._gate_editor.set_plot_channels(x_id, y_id)
        self._gate_editor.set_plot_scales(
            x_display_scale,
            "linear" if self._channel_selector.is_count_mode() else y_display_scale,
        )
        self._gate_editor.set_plot_transforms(
            None if x_spec is None else x_spec.id,
            None if y_spec is None else y_spec.id,
        )

        request = self._processed_display_request(
            sample_data, x_id, y_id, x_spec, y_spec
        )
        key = self._processed_display_key(request)
        processed = self._processed_display_cache.get(key)
        if processed is None:
            previous = self._previous_processed_display(request)
            if (
                previous is not None
                and self._results_stale
                and self._preview_revision.preview_status != "current"
            ):
                self._old_membership_banner = True
                processed = previous
            else:
                self._queue_processed_display(request)
                processed = self._processed_display_cache.get(key)
                if processed is None:
                    self._plot_widget.clear_plot()
                    if self._results_stale:
                        self._refresh_override_statuses()
                    else:
                        self._plot_widget.set_status_banner(
                            "Preparing canonical processed display…"
                        )
                    return
        data = processed.events

        try:
            x_idx = processed.channel_index(x_id)
        except KeyError:
            return

        x_data = data[:, x_idx]

        # Determine if we are in histogram (Count) mode.
        is_histogram = self._channel_selector.is_count_mode()
        self._plot_toolbar.set_marginal_available(not is_histogram)

        if is_histogram:
            # 1D histogram: only X channel data is needed.
            x_data = x_data[processed.display_mask]

            self._plot_widget.set_axis_transforms(x_display_scale, "linear")
            self._plot_widget.plot_histogram(x_data, x_label=x_name)

            # No 2D gate overlays in histogram mode.
            self._plot_widget.clear_gates()
            self._plot_widget.clear_overlay_layers()
        else:
            # 2D scatter plot.
            try:
                y_idx = processed.channel_index(y_id)
            except KeyError:
                return

            y_data = data[:, y_idx]

            # Apply population membership mask (display filter, Phase 3).
            display_mask = processed.display_mask
            x_data, y_data = x_data[display_mask], y_data[display_mask]
            event_colors = self._population_event_colors(
                self._current_sample_id,
                data.shape[0],
                display_mask,
                report=processed.preview_report,
            )

            # For marginal histograms, use unfiltered data (or population-filtered if preferred).
            # Use the same filtered data for marginal histograms.
            marginal_x = x_data
            marginal_y = y_data

            # Apply axis transform settings to the plot widget.
            self._plot_widget.set_axis_transforms(x_display_scale, y_display_scale)

            self._plot_widget.plot_events(
                x_data, y_data,
                x_label=x_name, y_label=y_name,
                marginal_x_data=marginal_x,
                marginal_y_data=marginal_y,
                event_colors=event_colors,
            )
            self._render_manual_overlays(x_id, y_id)

            # Refresh gate overlays
            self._plot_widget.clear_gates()
            for idx, gate in enumerate(self._display_gates()):
                if gate.x_parameter == x_id and gate.y_parameter == y_id:
                    self._plot_widget.add_gate_overlay(
                        gate,
                        idx,
                        self._gate_editor.population_outline_color(gate.id),
                    )
            self._gate_editor.set_overlay_status(
                self._plot_widget.display_state()["hidden_gate_reasons"]
            )

        if self._old_membership_banner:
            self._plot_widget.set_status_banner(
                "Recalculating — displayed events are from the previous revision"
            )
        # plot_events updates labels from stable channel IDs; apply independent
        # presentation labels last so display edits never alter those IDs.
        presentation = {} if view is None else deepcopy(
            view.get("presentation", {})
        )
        if self._current_sample_id is not None:
            presentation["title"] = self._current_sample_title()
        self._plot_widget.set_presentation(presentation)
        if self._results_stale and not self._old_membership_banner:
            self._refresh_override_statuses()

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

    def _processed_display_request(
        self,
        sample: SampleData,
        x_parameter_id: str,
        y_parameter_id: str | None,
        x_transform: TransformSpec | None,
        y_transform: TransformSpec | None,
    ) -> ProcessedDisplayRequest:
        """Build an immutable core request for the active plot selection."""
        return ProcessedDisplayRequest(
            revision=self._preview_revision.analysis_revision,
            sample=sample,
            population_id=self._display_population_id,
            x_parameter_id=x_parameter_id,
            y_parameter_id=(
                None if self._channel_selector.is_count_mode() else y_parameter_id
            ),
            x_transform_id=None if x_transform is None else x_transform.id,
            y_transform_id=None if y_transform is None else y_transform.id,
            display_max_points=self._channel_selector.display_max_points(),
            plot_type=(
                "histogram" if self._channel_selector.is_count_mode() else "scatter"
            ),
        )
    @staticmethod
    def _processed_display_key(
        request: ProcessedDisplayRequest,
    ) -> tuple[object, ...]:
        return (
            request.revision,
            request.sample_id,
            request.population_id,
            request.x_parameter_id,
            request.y_parameter_id,
            request.x_transform_id,
            request.y_transform_id,
            request.plot_type,
            request.display_max_points,
        )

    def _queue_processed_display(self, request: ProcessedDisplayRequest) -> None:
        """Adopt a core display result without ever calculating values in Qt.

        The existing preview scheduler remains responsible for debounced gate
        recalculation.  Initial plot selection must still establish a complete
        current display atomically, rather than exposing a blank raw fallback
        while a separate worker is pending.
        """
        try:
            result = PipelineRunner(
                self._build_project_manifest()
            ).prepare_display_sample(request)
            if result.revision != self._preview_revision.analysis_revision:
                return
            self._processed_display_cache[self._processed_display_key(result)] = result
            self._replot()
        except Exception as exc:
            self._plot_widget.clear_plot()
            self._plot_widget.set_status_banner(
                f"Processed display unavailable: {exc}"
            )
            self._update_status(f"Processed display error: {exc}")

    def _previous_processed_display(
        self, request: ProcessedDisplayRequest
    ) -> ProcessedDisplayResult | None:
        """Find only an explicitly labeled prior-revision plot for transition UI."""
        for result in reversed(tuple(self._processed_display_cache.values())):
            if (
                result.sample_id == request.sample_id
                and result.x_parameter_id == request.x_parameter_id
                and result.y_parameter_id == request.y_parameter_id
                and result.x_transform_id == request.x_transform_id
                and result.y_transform_id == request.y_transform_id
                and result.plot_type == request.plot_type
                and result.population_id == request.population_id
            ):
                return result
        # A newly created population has no prior membership.  During the
        # transition, All Events is the only honest fallback—not another
        # population's old mask.
        if request.population_id != "all_events":
            for result in reversed(tuple(self._processed_display_cache.values())):
                if (
                    result.sample_id == request.sample_id
                    and result.population_id == "all_events"
                    and result.x_parameter_id == request.x_parameter_id
                    and result.y_parameter_id == request.y_parameter_id
                    and result.x_transform_id == request.x_transform_id
                    and result.y_transform_id == request.y_transform_id
                    and result.plot_type == request.plot_type
                ):
                    return result
        return None

    def _on_processed_display_ready(self, result: ProcessedDisplayResult) -> None:
        """Adopt only the result matching the current plot definition atomically."""
        if result.revision != self._preview_revision.analysis_revision:
            return
        sample = self._sample_data.get(self._current_sample_id or "")
        if sample is None or sample.sample_id != result.sample_id:
            return
        x_id = self._channel_selector.x_channel_id()
        y_id = self._channel_selector.y_channel_id()
        x_transform = self._active_plot_transform(x_id)
        y_transform = (
            None
            if self._channel_selector.is_count_mode()
            else self._active_plot_transform(y_id)
        )
        current = self._processed_display_request(
            sample, x_id, y_id, x_transform, y_transform
        )
        if self._processed_display_key(result) != self._processed_display_key(current):
            return
        self._processed_display_cache[self._processed_display_key(result)] = result
        self._replot()

    def _on_processed_display_failed(
        self, request: ProcessedDisplayRequest, error: Exception
    ) -> None:
        """Never substitute raw events when canonical processing fails."""
        if request.revision != self._preview_revision.analysis_revision:
            return
        self._plot_widget.clear_plot()
        self._plot_widget.set_status_banner(
            f"Processed display unavailable: {error}"
        )
        self._update_status(f"Processed display error: {error}")

    def _render_manual_overlays(self, x_parameter_id: str, y_parameter_id: str) -> None:
        """Render simple overlays or persisted advanced sources through one path."""
        self._plot_widget.clear_overlay_layers()
        self._plot_widget.set_status_banner("")
        state = self._sample_browser.overlay_state()
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            None,
        )
        advanced_sources = [
            dict(source) for source in (view or {}).get("overlay_sources", [])
            if bool(source.get("visible", True))
        ]
        selected = set(state.get("manual_overlay_sample_ids", []))
        selected.update(
            self._sample_browser.comparison_overlay_sample_ids(self._current_sample_id)
        )
        selected.update(
            str(source.get("sample_id")) for source in advanced_sources
            if source.get("sample_id")
        )
        selected.discard(self._current_sample_id)
        if not advanced_sources and not selected:
            return
        samples_by_id = {
            sample.id: sample for sample in self._sample_browser.samples()
        }
        for sample_id in sorted(selected):
            if sample_id in self._event_data:
                continue
            sample = samples_by_id.get(sample_id)
            if sample is None:
                continue
            if sample.status in {"missing", "fingerprint mismatch"}:
                continue
            self._load_sample_events(sample)
        layers: list[Overlay2DLayer] = []
        diagnostics: list[str] = []
        x_transform = self._active_plot_transform(x_parameter_id)
        y_transform = self._active_plot_transform(y_parameter_id)
        source_definitions: list[dict[str, Any]] = advanced_sources or [
            {
                "source_id": f"manual:{sample_id}",
                "sample_id": sample_id,
                "population_id": self._display_population_id,
                "display_name": sample_id,
                "x_parameter_id": x_parameter_id,
                "y_parameter_id": y_parameter_id,
                "x_transform_id": None if x_transform is None else x_transform.id,
                "y_transform_id": None if y_transform is None else y_transform.id,
                "order": order,
            }
            for order, sample_id in enumerate(sorted(selected))
        ]
        source_statuses = self._overlay_status_resolver(source_definitions)
        for source in source_definitions:
            source_id = str(source.get("source_id", ""))
            sample_id = str(source.get("sample_id", ""))
            source_status, source_messages = source_statuses.get(
                source_id, ("error", ("unresolved source",))
            )
            if source_status != "compatible":
                diagnostics.append(f"{sample_id}: " + "; ".join(source_messages))
                continue
            sample_data = self._sample_data.get(sample_id)
            if sample_data is None:
                diagnostics.append(f"{sample_id}: missing channel metadata")
                continue
            try:
                source_x_id = str(source.get("x_parameter_id") or x_parameter_id)
                source_y_id = str(source.get("y_parameter_id") or y_parameter_id)
                processed = PipelineRunner(
                    self._build_project_manifest()
                ).prepare_display_sample(ProcessedDisplayRequest(
                    revision=self._preview_revision.analysis_revision,
                    sample=sample_data,
                    population_id=str(source.get("population_id") or self._display_population_id),
                    x_parameter_id=source_x_id,
                    y_parameter_id=source_y_id,
                    x_transform_id=source.get("x_transform_id"),
                    y_transform_id=source.get("y_transform_id"),
                    display_max_points=self._channel_selector.display_max_points(),
                ))
                x_values = processed.events[:, processed.channel_index(source_x_id)]
                y_values = processed.events[:, processed.channel_index(source_y_id)]
                x_values = x_values[processed.display_mask]
                y_values = y_values[processed.display_mask]
            except (KeyError, PipelineError) as exc:
                diagnostics.append(f"{sample_id}: {exc}")
                continue
            x_values = self._plot_widget._apply_axis_transform(x_values, "x")
            y_values = self._plot_widget._apply_axis_transform(y_values, "y")
            style = dict(source.get("style") or {})
            role_color = None
            for comparison in state.get("comparison_sets", []):
                for member in comparison.get("members", []):
                    if member.get("sample_id") == sample_id:
                        role_color = state.get("comparison_role_colors", {}).get(
                            member.get("role")
                        )
            layers.append(
                Overlay2DLayer(
                    self._display_population_id,
                    x_values,
                    y_values,
                    {
                        "color": (
                            style.get("color")
                            or state.get("manual_overlay_colors", {}).get(sample_id)
                            or role_color
                            or self._plot_widget.style().dot_color
                        ),
                        "alpha": float(style.get("alpha", 0.65)),
                        "label": style.get("legend_label", source.get("display_name", sample_id)),
                    },
                )
            )
        self._plot_widget.plot_overlay_layers(layers)
        if diagnostics:
            self._plot_widget.set_status_banner("Overlay warning: " + "; ".join(diagnostics))

    def _population_event_colors(
        self,
        sample_id: str | None,
        event_count: int,
        display_mask: NDArray[np.bool_] | None,
        *,
        report: object | None = None,
    ) -> NDArray[np.str_] | None:
        """Resolve active-layer colors from existing membership masks only."""
        definitions = self._gate_editor.population_display_definitions()
        colored = {
            population_id: value.get("color")
            for population_id, value in definitions.items()
            if isinstance(value.get("color"), str) and value.get("color")
        }
        if not colored:
            return None
        report = (
            report
            or self._preview_report
            or self._last_result_report
            or self._population_tree.last_report()
        )
        memberships = getattr(report, "population_membership", ()) if report is not None else ()
        # ``dtype=str`` creates a one-character NumPy string array (``<U1``),
        # truncating ``#RRGGBB`` values to ``#`` and making all points
        # effectively invisible. Reserve the full display-color width.
        colors = np.full(event_count, self._plot_widget.style().dot_color, dtype="<U7")
        parents = self._population_parent_map()
        hierarchy_order = {
            population_id: index
            for index, population_id in enumerate(
                sorted(set(parents) | set(colored))
            )
        }

        def depth(population_id: str) -> int:
            current = population_id
            seen: set[str] = set()
            value = 0
            while current in parents and current not in seen:
                seen.add(current)
                parent = parents.get(current)
                if not parent or parent == "all_events":
                    break
                value += 1
                current = parent
            return value

        ordered = sorted(
            colored,
            key=lambda population_id: (
                depth(population_id),
                -int(definitions[population_id].get("z_order") or 2**31 - 1),
                -hierarchy_order.get(population_id, 0),
                population_id,
            ),
        )
        for population_id in ordered:
            membership = next(
                (
                    value.mask for value in memberships
                    if value.sample_id == sample_id
                    and value.population_id == population_id
                    and len(value.mask) == event_count
                ),
                None,
            )
            if membership is None:
                continue
            mask = membership.copy()
            if display_mask is not None and len(display_mask) == event_count:
                mask &= display_mask
            colors[mask] = str(colored[population_id])
        if display_mask is not None and len(display_mask) == event_count:
            colors = colors[display_mask]
        return colors

    def _get_population_mask(self) -> NDArray[np.bool_] | None:
        """Return the membership boolean mask for the current sample and selected population.

        Returns ``None`` when no valid membership data is available (stale results,
        no report, or missing population/sample).  In that case the caller should
        fall back to displaying all events.
        """
        self._old_membership_banner = False
        report = self._preview_report
        result_revision = None
        if report is not None:
            result_revision = report.revision
        elif self._results_stale:
            report = self._last_result_report
            self._old_membership_banner = report is not None
        else:
            report = self._last_result_report or self._population_tree.last_report()
            result_revision = self._preview_revision.authoritative_result_revision
        if report is None:
            return None
        if not hasattr(report, "population_membership") or not report.population_membership:
            return None

        sample_id = self._current_sample_id
        population_id = self._display_population_id

        # all_events is always valid: no filter needed
        if population_id == "all_events":
            return None

        if not self._old_membership_banner and not self._preview_revision.result_is_current(
          population_id, result_revision
        ):
            return None

        # Find matching membership entry for (sample_id, population_id)
        for membership in report.population_membership:
            if membership.sample_id == sample_id and membership.population_id == population_id:
                return membership.mask

        # Selected population does not exist for this sample; fall back to all events
        self._old_membership_banner = False
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
            self._selected_gate_id = gates[gate_index].id

    def _on_show_gate(self, gate) -> None:
        """Display the gate's parent population with the gate outline."""
        self._display_population_id = gate.parent_population_id or "all_events"
        if gate.x_parameter:
            y_parameter = gate.y_parameter or self._channel_selector.y_channel_id()
            self._channel_selector.set_selected_channels(
                gate.x_parameter, y_parameter
            )
        self._display_transform_overrides.pop(gate.x_parameter or "", None)
        self._display_transform_overrides.pop(gate.y_parameter or "", None)
        self._plot_transform_overrides[gate.x_parameter or ""] = gate.x_transform_id
        self._restore_gate_axis_transform("x", gate.x_transform_id)
        self._plot_transform_overrides[gate.y_parameter or ""] = gate.y_transform_id
        self._restore_gate_axis_transform("y", gate.y_transform_id)
        self._replot()
        self._update_status(
            f"Showing gate: {gate.name} [{gate.id}] on "
            f"{self._gate_transform_status(gate, 'x')}/"
            f"{self._gate_transform_status(gate, 'y')}"
        )

    def _restore_gate_axis_transform(
        self, axis: str, transform_id: str | None
    ) -> None:
        """Restore one gate axis using its exact transform ID when available."""
        transform = self._transform_by_id(transform_id)
        if transform is not None:
            setter = (
                self._channel_selector.set_x_transform
                if axis == "x"
                else self._channel_selector.set_y_transform
            )
            setter("linear")
            self._channel_selector.set_analysis_transform_choice(
                axis, str(transform.transform_type)
            )
            return
        setter = (
            self._channel_selector.set_x_transform
            if axis == "x"
            else self._channel_selector.set_y_transform
        )
        setter("linear")
        self._channel_selector.set_analysis_transform_choice(
            axis, "linear"
        )

    def _gate_transform_status(self, gate: Any, axis: str) -> str:
        transform_id = (
            gate.x_transform_id if axis == "x" else gate.y_transform_id
        )
        if transform_id:
            transform = self._transform_by_id(transform_id)
            return (
                f"{transform_id} ({transform.transform_type})"
                if transform is not None else str(transform_id)
            )
        return "Linear"

    def _on_show_population(self, gate) -> None:
        """Display a gate-derived population only when its result is current."""
        report = self._population_tree.last_report()
        if report is None or self._results_stale:
            self._update_status(
                f"Population unavailable for {gate.name}; run Pipeline first"
            )
            return
        result = next(
            (
                value for value in report.population_results
                if value.sample_id == self._current_sample_id
                and value.population_id == gate.id
            ),
            None,
        )
        if result is None:
            self._update_status(
                f"Population unavailable for {gate.name} in the active sample"
            )
            return
        self._display_population_id = gate.id
        self._update_workspace_navigation()
        self._replot()
        self._update_status(f"Showing population: {gate.name} [{gate.id}]")

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

    def _active_plot_transform(self, parameter: str) -> TransformSpec | None:
        """Return the transform explicitly selected for the current plot axis."""
        if parameter in self._plot_transform_overrides:
            return self._transform_by_id(self._plot_transform_overrides[parameter])
        return self._transform_for_parameter(parameter)

    def _transform_by_id(self, transform_id: str | None) -> TransformSpec | None:
        if not transform_id:
            return None
        return next(
            (transform for transform in self._transform_specs()
             if transform.id == transform_id),
            None,
        )

    def _on_clear_gates(self) -> None:
        """Clear all gates."""
        self._plot_widget.clear_gate_creation()
        self._gate_editor.cancel_polygon()
        self._gate_editor.clear_gates()
        self._plot_widget.clear_gates()

    # -- pipeline execution --------------------------------------------------

    def _on_run_pipeline(self) -> None:
        """Run the analysis pipeline on loaded samples."""
        from flowdesk_qt.statistics_editor import repair_statistic_definitions

        repaired_statistics = repair_statistic_definitions(self._statistics)
        if repaired_statistics != self._statistics:
            self._statistics = repaired_statistics
            self._project_dirty = True
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

        self._preview_scheduler.suspend()
        project = self._build_project_manifest()
        self._update_status("Running pipeline...")
        self._worker = _PipelineWorker(
            project,
            tuple(self._sample_data.values()),
            revision=self._preview_revision.analysis_revision,
        )
        self._worker.finished.connect(self._on_pipeline_finished)
        self._worker.start()

    def _on_auto_recalculate_changed(self, enabled: bool) -> None:
        """Toggle automatic full-sample recalculation for stale Results."""
        self._project_dirty = True
        if enabled and self._results_stale:
            self._preview_scheduler.cancel_pending()
            self._request_auto_recalculation()

    def _request_auto_recalculation(self) -> None:
        """Coalesce stale changes before starting the canonical batch runner."""
        if not self._results_workspace.auto_recalculate_stale_results():
            return
        self._auto_recalculate_timer.start()

    def _start_auto_recalculation(self) -> None:
        """Start one latest-definition pipeline after stale changes settle."""
        if not self._results_workspace.auto_recalculate_stale_results():
            return
        if not self._results_stale:
            return
        if self._worker is not None and self._worker.isRunning():
            self._request_auto_recalculation()
            return
        self._on_run_pipeline()

    def _build_project_manifest(self) -> dict[str, Any]:
        """Build a project manifest from current UI state.

        This constructs a minimal project dictionary that the PipelineRunner
        can consume.  Gate definitions from the gate editor are included.
        """
        # ROI callbacks are queued to avoid mutating/deleting Qt objects while
        # pyqtgraph is dispatching its region-change signal.  Any consumer of
        # project state must first commit those already-finished edits.
        self._flush_pending_gate_geometry_updates()
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

        plot_views = deepcopy(self._plot_views)
        view_id = self._overlay_view_id()
        current_view = next(
            (item for item in plot_views if item.get("id") == view_id), None
        )
        if current_view is None:
            current_view = {"id": view_id}
            plot_views.append(current_view)
        current_view["rendering_downsample"] = {
            "max_points": self._channel_selector.display_max_points()
        }

        project: dict[str, Any] = {
            "project_id": self._project_id,
            "project_version": CURRENT_PROJECT_VERSION,
            "pipeline_version": "0.1",
            "samples": samples,
            "comparison_set_definitions": deepcopy(
                self._sample_browser.overlay_state().get("comparison_sets", [])
            ),
            "comparison_role_colors": {
                "reference": "#377eb8",
                "target": "#e67e22",
                "positive_control": "#2ca02c",
                "negative_control": "#7f7f7f",
            },
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
            "gate_overrides": deepcopy(self._gate_overrides),
            "derived_parameters": deepcopy(self._derived_parameters),
            "transforms": deepcopy(self._transforms),
            "compensation_matrices": deepcopy(self._compensation_matrices),
            "compensation_bindings": deepcopy(self._compensation_bindings),
            "compensation_calculations": deepcopy(
                self._compensation_calculations
            ),
            "statistics": deepcopy(self._statistics),
            "batch_plot_exports": deepcopy(self._batch_plot_exports),
            "plot_views": plot_views,
            "overlays": deepcopy(self._overlays),
            "backgating_specs": deepcopy(self._backgating_specs),
            "auto_gate_templates": deepcopy(self._auto_gate_templates),
            "auto_gate_fits": deepcopy(self._auto_gate_fits),
            "magnetic_gate_templates": deepcopy(self._magnetic_gate_templates),
            "magnetic_gate_fits": deepcopy(self._magnetic_gate_fits),
            "tethered_gate_templates": deepcopy(self._tethered_gate_templates),
            "tethered_gate_fits": deepcopy(self._tethered_gate_fits),
            "default_compensation_matrix_id": self._default_compensation_matrix_id,
            "migration_diagnostics": deepcopy(self._migration_diagnostics),
            "sample_path_resolution_policy": "relative_to_project_or_absolute",
            "plot_display_settings": {
                "selected_sample_id": self._current_sample_id,
                "x_channel": self._channel_selector.x_channel_id(),
                "y_channel": self._channel_selector.y_channel_id(),
                "x_scale": self._channel_selector.x_transform(),
                "y_scale": self._channel_selector.y_transform(),
                "x_tick_policy": self._plot_widget.tick_policy(),
                "y_tick_policy": self._plot_widget.tick_policy(),
                "marginal_enabled": self._plot_widget.is_marginal_enabled(),
                "display_max_points": (
                    self._channel_selector.display_max_points()
                ),
                "integrated_overlay": self._sample_browser.overlay_state(),
                "population_display_colors": (
                    self._gate_editor.population_display_definitions()
                ),
            },
            "results_display_settings": {
                "mode": self._results_workspace.mode(),
                "auto_recalculate_stale_results": (
                    self._results_workspace.auto_recalculate_stale_results()
                ),
                "statistic_column_visibility": (
                    self._results_workspace.statistic_column_visibility()
                ),
                "statistic_column_order": list(
                    self._results_workspace.statistic_column_order()
                ),
                "statistic_column_widths": (
                    self._results_workspace.statistic_column_widths()
                ),
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
            if self._pending_results_export is not None:
                self._pending_results_export = None
                QMessageBox.critical(
                    self,
                    "Export Error",
                    "Pipeline failed; Results were not exported.",
                )
            self._release_pipeline_worker(worker)
            self._preview_scheduler.resume()
            return

        report = worker._report
        if worker.revision != self._preview_revision.analysis_revision:
            self._results_stale = True
            self._results_stale_reason = (
                "Pipeline result discarded; analysis definitions changed during execution"
            )
            self._refresh_override_statuses()
            self._update_status(
                "Pipeline result discarded; analysis definitions changed during execution"
            )
            self._release_pipeline_worker(worker)
            self._preview_scheduler.resume()
            if self._pending_results_export is not None:
                self._update_status(
                    "Analysis changed during Pipeline; rerunning before export..."
                )
                self._on_run_pipeline()
            elif self._results_workspace.auto_recalculate_stale_results():
                self._request_auto_recalculation()
            return
        if report is not None:
            self._auto_gate_fits = deepcopy(report.auto_gate_fits)
            self._magnetic_gate_fits = deepcopy(report.magnetic_gate_fits)
            self._tethered_gate_fits = deepcopy(report.tethered_gate_fits)
            self._population_tree.set_population_names(self._population_name_map())
            self._population_tree.set_report(report)
            self._workspace_tree.set_report(report)
            self._last_result_report = report
            self._refresh_parameter_catalog()
            self._result_state.set_authoritative_report(
                report,
                self._preview_revision.analysis_revision,
                sample_ids=tuple(
                    sample.id for sample in self._sample_browser.samples()
                ),
                population_ids=tuple(self._population_parent_map()),
                statistic_definitions=tuple(
                    (
                        str(value.get("id")),
                        str(population_id),
                        bool(value.get("compute_enabled", True)),
                    )
                    for value in self._statistics
                    if value.get("id")
                    for population_id in value.get(
                        "population_ids",
                        [value.get("population_id", "all_events")],
                    )
                ),
            )
            self._results_workspace.set_statistic_definition_names(
                {
                    str(value.get("id")): str(value.get("name"))
                    for value in self._statistics
                    if value.get("id") and value.get("name")
                }
            )
            self._results_workspace.set_result_state(self._result_state)
            self._refresh_override_statuses()
            self._diagnostics_panel.set_report(
                report,
                gate_labels=self._diagnostic_gate_labels(),
                statistic_labels=self._diagnostic_statistic_labels(),
            )
            self._gate_editor.set_population_results(report.population_results)
            self._results_stale = False
            self._results_stale_reason = None
            self._preview_report = None
            self._preview_revision.accept_authoritative(
                self._preview_revision.analysis_revision
            )
            self._preview_scheduler.cancel_pending()
            self._compensation_status_indicator.clear_stale()
            self._validate_population_selection(report)
            self._refresh_override_statuses()
            self._update_status(f"Pipeline complete: {report.summary}")
            # Replot to apply the now-valid population membership mask.
            self._replot()
            self._update_compensation_status()
            self._complete_pending_results_export()
        else:
            self._update_status("Pipeline finished with no report")
            if self._pending_results_export is not None:
                self._pending_results_export = None
                QMessageBox.critical(
                    self,
                    "Export Error",
                    "Pipeline produced no Results; the export was not written.",
                )

        self._release_pipeline_worker(worker)
        self._preview_scheduler.resume()

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
        self._preview_scheduler.shutdown()
        self._processed_display_scheduler.shutdown()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait()
        if worker is not None:
            self._release_pipeline_worker(worker)
        self._plot_widget.release_transient_items()
        super().closeEvent(event)

    def set_autosave_settings(self, settings: AutosaveSettings) -> None:
        """Update global autosave preference and restart its timer."""
        self._autosave_settings = settings
        values = QSettings()
        values.setValue("autosave/enabled", settings.enabled)
        values.setValue("autosave/interval_seconds", settings.interval_seconds)
        values.setValue("autosave/retention", settings.retention)
        self._autosave_timer.stop()
        self._autosave_timer.setInterval(settings.interval_seconds * 1000)
        if settings.enabled:
            self._autosave_timer.start()

    def _autosave_tick(self) -> None:
        """Autosave only dirty projects and never while analysis is executing."""
        if not self._project_dirty or self._project_path is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            self._recovery_manager.autosave(
                self._project_id, self._build_project_manifest(), dirty=True,
                retention=self._autosave_settings.retention,
            )
            self._update_status("Autosaved recovery copy")
        except Exception as exc:
            logger.error("Autosave failed: %s", exc)

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

    def _on_save_analysis_settings(self) -> None:
        """Save reusable definitions without samples or computed Results."""
        path_str = QFileDialog.getExistingDirectory(
            self,
            "Select analysis settings bundle directory",
            str(self._project_path.parent if self._project_path else Path.cwd()),
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix != ".flowdesk-settings":
            path = path.with_suffix(".flowdesk-settings")
        try:
            save_analysis_settings(path, self._build_project_manifest())
            self._update_status(f"Analysis settings saved to {path}")
        except Exception as exc:
            logger.error("Analysis settings save failed: %s", exc)
            QMessageBox.critical(self, "Analysis Settings Save Error", str(exc))

    def _on_load_analysis_settings(self) -> None:
        """Load settings or extract reusable definitions from a project."""
        path_str = QFileDialog.getExistingDirectory(
            self,
            "Open Analysis Settings or Flowdesk Project",
            str(self._project_path.parent if self._project_path else Path.cwd()),
        )
        if not path_str:
            return
        try:
            settings = load_analysis_settings(path_str)
            current = self._build_project_manifest()
            diagnostics = preflight_analysis_settings(current, settings)
            if diagnostics:
                QMessageBox.warning(
                    self,
                    "Analysis Settings Incompatible",
                    "The settings were not loaded:\n\n" + "\n".join(diagnostics),
                )
                return
            choice = QMessageBox.question(
                self,
                "Replace Analysis Definitions",
                "Replace the current analysis definitions?\n\n"
                "Samples and FCS paths will be kept. Results and previews "
                "will be cleared and Pipeline must be run again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            if self._analysis_settings_undo_stack is None:
                self._analysis_settings_undo_stack = UndoStack(
                    current,
                    on_changed=self._on_analysis_settings_state_changed,
                )
            self._analysis_settings_undo_stack.execute(
                ReplaceAnalysisSettingsCommand(settings)
            )
            self._update_status("Analysis settings loaded; Results are stale")
        except Exception as exc:
            logger.error("Analysis settings load failed: %s", exc)
            QMessageBox.critical(self, "Analysis Settings Load Error", str(exc))

    def _on_analysis_settings_state_changed(
        self, state: dict[str, Any], reason: str
    ) -> None:
        """Apply a validated definition-only command state to the GUI."""
        strategy_data = state.get("gating_strategies_data", {}).get(
            "default_strategy"
        )
        if strategy_data is None:
            strategy_data = next(
                iter(state.get("gating_strategies_data", {}).values())
            )
        strategy = PipelineRunner._strategy_from_mapping(strategy_data)
        self._gate_editor.set_gates(list(strategy.gates), notify=False)
        self._gate_editor.mark_undo_clean()
        self._derived_parameters = deepcopy(state.get("derived_parameters", []))
        self._transforms = deepcopy(state.get("transforms", []))
        self._compensation_matrices = deepcopy(
            state.get("compensation_matrices", [])
        )
        self._statistics = deepcopy(state.get("statistics", []))
        self._plot_views = deepcopy(state.get("plot_views", []))
        self._auto_gate_templates = deepcopy(
            state.get("auto_gate_templates", [])
        )
        self._magnetic_gate_templates = deepcopy(
            state.get("magnetic_gate_templates", [])
        )
        self._tethered_gate_templates = deepcopy(
            state.get("tethered_gate_templates", [])
        )
        self._auto_gate_fits = []
        self._magnetic_gate_fits = []
        self._tethered_gate_fits = []
        self._last_result_report = None
        self._default_compensation_matrix_id = state.get(
            "default_compensation_matrix_id"
        )
        self._overlay_undo_stack = UndoStack(
            {"plot_views": deepcopy(self._plot_views)},
            on_changed=self._on_overlay_state_changed,
        )
        self._mark_results_stale(reason)
        self._project_dirty = True
        self._refresh_parameter_catalog()
        self._population_tree.set_population_parents(self._population_parent_map())
        self._workspace_tree.set_population_hierarchy(
            self._population_parent_map(), self._population_name_map()
        )
        self._update_undo_actions()
        self._replot()

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
        recovery_candidates = self._recovery_manager.newer_than(
            project_path, str(manifest["project_id"])
        )
        if recovery_candidates:
            choice = QMessageBox.question(
                self, "Recovery Available",
                "A newer recovery copy is available. Open it as a separate copy?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice == QMessageBox.StandardButton.Yes:
                destination = QFileDialog.getExistingDirectory(
                    self, "Select recovery copy destination", str(project_path.parent)
                )
                if destination:
                    recovered_path = Path(destination)
                    if recovered_path.suffix != ".flowdesk":
                        recovered_path = recovered_path.with_suffix(".flowdesk")
                    self._recovery_manager.recover_copy(recovery_candidates[0], recovered_path)
                    project_path = recovered_path
                    manifest = load_project(project_path)
        strategy_data = manifest.get("gating_strategies_data", {}).get(
            "default_strategy",
            {"id": "default_strategy", "name": "Default Strategy", "gates": []},
        )
        strategy = PipelineRunner._strategy_from_mapping(strategy_data)

        self._sample_browser.clear_samples()
        self._event_data.clear()
        self._sample_data.clear()
        self._processed_display_scheduler.cancel_pending()
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
        self._batch_plot_exports = deepcopy(manifest.get("batch_plot_exports", []))
        self._plot_views = deepcopy(manifest.get("plot_views", []))
        self._overlays = deepcopy(manifest.get("overlays", []))
        self._overlay_undo_stack = UndoStack(
            {"plot_views": deepcopy(self._plot_views)},
            on_changed=self._on_overlay_state_changed,
        )
        self._backgating_specs = deepcopy(manifest.get("backgating_specs", []))
        self._auto_gate_templates = deepcopy(manifest.get("auto_gate_templates", []))
        self._auto_gate_fits = deepcopy(manifest.get("auto_gate_fits", []))
        self._magnetic_gate_templates = deepcopy(manifest.get("magnetic_gate_templates", []))
        self._magnetic_gate_fits = deepcopy(manifest.get("magnetic_gate_fits", []))
        self._tethered_gate_templates = deepcopy(manifest.get("tethered_gate_templates", []))
        self._tethered_gate_fits = deepcopy(manifest.get("tethered_gate_fits", []))
        self._sample_groups = deepcopy(manifest.get("sample_groups", []))
        self._group_strategy_bindings = deepcopy(
            manifest.get("group_strategy_bindings", [])
        )
        self._annotations = deepcopy(manifest.get("annotations", []))
        self._gate_overrides = deepcopy(manifest.get("gate_overrides", []))
        self._override_undo_stack = UndoStack({"gate_overrides": self._gate_overrides})
        self._group_panel.set_groups(self._sample_groups)
        self.action_advanced_groups.setChecked(
            bool(manifest.get("advanced_groups_enabled", False))
        )

        resolved_samples = resolve_sample_paths(manifest, project_path)
        display = manifest.get("plot_display_settings", {})
        results_display = manifest.get("results_display_settings", {})
        if isinstance(results_display, dict):
            mode = results_display.get("mode")
            if mode in {"Hierarchy", "Flat table", "Statistics detail"}:
                self._results_workspace.set_mode(mode)
            self._results_workspace.set_auto_recalculate_stale_results(
                bool(results_display.get("auto_recalculate_stale_results", False))
            )
            visibility = results_display.get("statistic_column_visibility")
            if isinstance(visibility, dict):
                self._results_workspace.set_statistic_column_visibility(
                    {
                        str(statistic_id): bool(is_visible)
                        for statistic_id, is_visible in visibility.items()
                    }
                )
            order = results_display.get("statistic_column_order")
            if isinstance(order, list):
                self._results_workspace.set_statistic_column_order(
                    [str(statistic_id) for statistic_id in order]
                )
            widths = results_display.get("statistic_column_widths")
            if isinstance(widths, dict):
                self._results_workspace.set_statistic_column_widths(widths)
        self._sample_browser.add_project_samples(resolved_samples)
        integrated_overlay = display.get("integrated_overlay", {})
        if not integrated_overlay:
            view = next(
                (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
                {},
            )
            integrated_overlay = {
                "manual_overlay_sample_ids": view.get("manual_overlay_sample_ids", []),
                "manual_overlay_colors": view.get("manual_overlay_colors", {}),
                "comparison_sets": manifest.get("comparison_set_definitions", []),
                "overlay_mode": view.get("overlay_mode", "manual_only"),
            }
        self._sample_browser.set_overlay_state(
            integrated_overlay.get("manual_overlay_sample_ids", []),
            integrated_overlay.get("manual_overlay_colors", {}),
            integrated_overlay.get("overlay_roles", {}),
            integrated_overlay.get(
                "comparison_sets", manifest.get("comparison_set_definitions", [])
            ),
            integrated_overlay.get("overlay_mode", "manual_only"),
            integrated_overlay.get(
                "comparison_role_colors", manifest.get("comparison_role_colors", {})
            ),
        )
        self._gate_editor.set_population_display_definitions(
            display.get("population_display_colors", {})
        )
        self._group_panel.set_sample_ids(
            [item.id for item in self._sample_browser.samples()]
        )
        self._channel_selector.set_x_transform(display.get("x_scale", "linear"))
        self._channel_selector.set_y_transform(display.get("y_scale", "linear"))
        self._plot_widget.set_tick_policy(
            str(display.get("x_tick_policy", display.get("tick_policy", "auto")))
        )
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            {},
        )
        rendering_downsample = view.get("rendering_downsample", {})
        max_points = rendering_downsample.get(
            "max_points",
            display.get("display_max_points", DEFAULT_DISPLAY_MAX_POINTS),
        )
        self._channel_selector.set_display_max_points(int(max_points))
        self._plot_widget.set_max_display_points(int(max_points))
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
        self._analysis_settings_undo_stack = None
        self._update_undo_actions()
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
        updated = dialog.definitions()
        removed_outputs = {
            str(value.get("output_channel_id") or value.get("id"))
            for value in self._derived_parameters
        } - {
            str(value.get("output_channel_id") or value.get("id"))
            for value in updated
        }
        references = self._derived_parameter_references(removed_outputs)
        if references:
            QMessageBox.warning(
                self,
                "Derived parameter is in use",
                "Cannot delete a derived parameter while it is referenced by:\n- "
                + "\n- ".join(references),
            )
            return
        self._derived_parameters = updated
        self._refresh_parameter_catalog()
        self._mark_results_stale("Derived parameters changed")

    def _derived_parameter_references(self, output_ids: set[str]) -> list[str]:
        """List persisted dependencies before a derived output may be removed."""
        if not output_ids:
            return []
        references: list[str] = []
        for value in self._derived_parameters:
            inputs = {str(item) for item in value.get("input_parameters", [])}
            if inputs & output_ids:
                references.append(f"derived parameter {value.get('name', value.get('id'))}")
        for value in self._transforms:
            if value.get("parameter") in output_ids:
                references.append(f"transform {value.get('name', value.get('id'))}")
        for gate in self._gate_editor.gates():
            if {gate.x_parameter, gate.y_parameter} & output_ids:
                references.append(f"gate {gate.name}")
        for value in self._statistics:
            if value.get("parameter_id") in output_ids:
                references.append(f"statistic {value.get('name', value.get('id'))}")
        for view in self._plot_views:
            if {view.get("x_parameter"), view.get("y_parameter")} & output_ids:
                references.append(f"plot view {view.get('name', view.get('id'))}")
        return references

    def _on_edit_annotations(self) -> None:
        """Compatibility shortcut to the unified Sample Sheet surface."""
        self._on_edit_sample_sheet()

    def _on_edit_sample_sheet(self) -> None:
        """Edit titles and annotations with dependency-aware invalidation."""
        from flowdesk_qt.sample_sheet import SampleSheetDialog

        samples = [
            {"id": item.id, "name": item.name, "path": item.path}
            for item in self._sample_browser.samples()
        ]
        dialog = SampleSheetDialog(samples, self._annotations, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        before = self._annotations
        self._annotations = dialog.annotations()
        self._refresh_sample_display_names()
        self._replot()
        changed_keywords = self._changed_annotation_keywords(before, self._annotations)
        referenced_keywords = self._group_rule_annotation_keywords()
        if changed_keywords & referenced_keywords:
            self._mark_results_stale("Group-referenced annotations changed")
        else:
            self._project_dirty = True
            if changed_keywords - {"sample_title"}:
                self._update_status("Sample annotations updated (analysis unaffected)")
            else:
                self._update_status("Sample titles updated")

    @staticmethod
    def _changed_annotation_keywords(
        before: list[dict[str, Any]], after: list[dict[str, Any]]
    ) -> set[str]:
        def values(items: list[dict[str, Any]]) -> dict[tuple[str, str, str], Any]:
            return {
                (str(item["sample_id"]), str(item["keyword"]), str(item["source"])):
                item.get("value")
                for item in items
            }
        previous = values(before)
        current = values(after)
        return {
            key[1]
            for key in set(previous) | set(current)
            if previous.get(key) != current.get(key)
        }

    def _group_rule_annotation_keywords(self) -> set[str]:
        """Collect safe-rule keyword operands used for group assignment."""
        result: set[str] = set()

        def visit(value: object) -> None:
            if not isinstance(value, dict):
                return
            keyword = value.get("keyword")
            if isinstance(keyword, str):
                result.add(keyword)
            for child in value.get("all", []) if isinstance(value.get("all"), list) else []:
                visit(child)
            for child in value.get("any", []) if isinstance(value.get("any"), list) else []:
                visit(child)
            visit(value.get("not"))

        for group in self._sample_groups:
            visit(group.get("membership_rule"))
        return result

    def _on_focus_parameter_information(self) -> None:
        """Focus the read-only parameter information workspace."""
        self._channel_metadata.setFocus(Qt.FocusReason.MenuBarFocusReason)
        self._update_status("Channel / Parameter Information is shown in the workspace")

    def _on_focus_overlay_samples(self) -> None:
        """Direct users to the supported Samples-pane overlay controls."""
        self._sample_browser.setFocus(Qt.FocusReason.MenuBarFocusReason)
        self._update_status("Use the Samples pane Ov column to overlay compatible samples")

    def _refresh_parameter_catalog(self) -> None:
        """Refresh the selected sample's typed parameter view after definition edits."""
        sample = self._sample_browser.selected_sample()
        if sample is None:
            self._parameter_catalog = ()
            self._channel_metadata.set_parameter_catalog(())
            return
        self._parameter_catalog = self._catalog_for_sample(sample)
        self._channel_metadata.set_parameter_catalog(self._parameter_catalog)
        self._channel_selector.set_parameter_catalog(
            self._parameter_catalog, allow_derived=True
        )

    def _catalog_for_sample(
        self, sample: _SampleInfo
    ) -> tuple[ParameterCatalogEntry, ...]:
        """Attach current/stale pipeline status to the immutable definition catalog."""
        catalog = build_parameter_catalog(
            sample.info.channels,
            self._derived_parameters,
            sample_id=sample.id,
        )
        report = self._last_result_report
        if report is None:
            return catalog
        diagnostics_by_parameter: dict[str, list[ParameterCatalogDiagnostic]] = {}
        for diagnostic in report.diagnostics:
            if diagnostic.sample_id not in {None, sample.id} or not diagnostic.parameter_id:
                continue
            diagnostics_by_parameter.setdefault(diagnostic.parameter_id, []).append(
                ParameterCatalogDiagnostic(
                    code=diagnostic.code,
                    message=diagnostic.message,
                    parameter_id=diagnostic.parameter_id,
                )
            )
        refreshed: list[ParameterCatalogEntry] = []
        for entry in catalog:
            if entry.kind != "derived" or entry.availability != "not_run":
                refreshed.append(entry)
                continue
            diagnostics = tuple(
                diagnostics_by_parameter.get(entry.parameter_id, [])
                + diagnostics_by_parameter.get(entry.definition_id or "", [])
            )
            availability = "stale" if self._results_stale else "available"
            if any(
                diagnostic.code == "derived_parameter_evaluation_failed"
                for diagnostic in diagnostics
            ):
                availability = "error"
            refreshed.append(replace(
                entry, availability=availability, diagnostics=diagnostics
            ))
        return tuple(refreshed)

    def _refresh_sample_display_names(self) -> None:
        """Refresh non-scientific labels after a title edit."""
        from flowdesk_core.annotations import resolve_sample_title

        annotations = [
            AnnotationSpec(
                sample_id=str(value["sample_id"]),
                keyword=str(value["keyword"]),
                value=value.get("value"),
                source=value["source"],
            )
            for value in self._annotations
        ]
        rows = [
            (item.id, resolve_sample_title(item.id, item.name, item.path, annotations))
            for item in self._sample_browser.samples()
        ]
        self._sample_browser.set_display_names(dict(rows))
        self._workspace_tree.set_samples(rows)
        self._results_workspace.set_samples(rows)

    def _current_sample_title(self) -> str:
        """Resolve the active sample's title using the Sample Sheet rules."""
        from flowdesk_core.annotations import resolve_sample_title

        sample = next(
            (
                item for item in self._sample_browser.samples()
                if item.id == self._current_sample_id
            ),
            None,
        )
        if sample is None:
            return ""
        annotations = [
            AnnotationSpec(
                sample_id=str(value["sample_id"]),
                keyword=str(value["keyword"]),
                value=value.get("value"),
                source=value["source"],
            )
            for value in self._annotations
        ]
        return resolve_sample_title(
            sample.id, sample.name, sample.path, annotations
        )

    def _set_current_sample_title(self, title: str) -> None:
        """Store a Plot Appearance title as the active sample's workspace title."""
        from flowdesk_core.annotations import set_sample_title

        if self._current_sample_id is None:
            return
        annotations = tuple(
            AnnotationSpec(
                sample_id=str(value["sample_id"]),
                keyword=str(value["keyword"]),
                value=value.get("value"),
                source=value["source"],
            )
            for value in self._annotations
        )
        updated = set_sample_title(annotations, self._current_sample_id, title)
        self._annotations = [asdict(value) for value in updated]
        self._project_dirty = True

    def _on_batch_plot_export(self) -> None:
        """Run a persisted batch plot definition through the CLI/core adapter."""
        if self._project_path is None:
            QMessageBox.information(
                self, "Save project first", "Save the project before batch export."
            )
            return
        if not self._batch_plot_exports:
            QMessageBox.information(
                self, "No batch export", "No BatchPlotExportSpec is configured."
            )
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Batch Plot Output Directory")
        if not output_dir:
            return
        export_id = str(self._batch_plot_exports[0].get("id", ""))
        try:
            from flowdesk_cli.batch_plot import batch_plot_command

            status = batch_plot_command(str(self._project_path), export_id, output_dir)
        except Exception as exc:
            logger.error("Batch plot export failed: %s", exc)
            QMessageBox.critical(self, "Batch Plot Export Error", str(exc))
            return
        if status != 0:
            QMessageBox.warning(self, "Batch Plot Export", "Batch export completed with failures.")
        else:
            self._update_status(f"Batch plot export completed: {output_dir}")

    def _overlay_view_id(self) -> str:
        """Return the stable persisted view receiving source-list edits."""
        if self._plot_views and self._plot_views[0].get("id"):
            return str(self._plot_views[0]["id"])
        return "main-view"

    def _sync_display_max_points_from_view(self) -> None:
        """Apply the persisted current-view sampling definition to the GUI."""
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            {},
        )
        value = view.get("rendering_downsample", {}).get(
            "max_points", DEFAULT_DISPLAY_MAX_POINTS
        )
        max_points = max(0, int(value))
        self._channel_selector.set_display_max_points(max_points)
        self._plot_widget.set_max_display_points(max_points)

    def _overlay_samples_for_editor(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sample.id,
                "name": sample.name,
                "channels": [asdict(channel) for channel in sample.info.channels],
            }
            for sample in self._sample_browser.samples()
        ]

    def _overlay_population_ids_for_editor(self) -> tuple[str, ...]:
        report = self._last_result_report or self._population_tree.last_report()
        population_ids = {"all_events"}
        if report is not None:
            population_ids.update(result.population_id for result in report.population_results)
        population_ids.update(gate.id for gate in self._gate_editor.gates())
        return tuple(sorted(population_ids))

    def _overlay_status_resolver(
        self,
        sources: list[dict[str, Any]],
    ) -> dict[str, tuple[str, tuple[str, ...]]]:
        """Adapt persisted JSON definitions to the core compatibility resolver."""
        contexts: dict[str, SamplePresentationContext] = {}
        report = self._last_result_report or self._population_tree.last_report()
        populations_by_sample: dict[str, set[str]] = {}
        if report is not None:
            for result in report.population_results:
                populations_by_sample.setdefault(result.sample_id, set()).add(result.population_id)
        transform_specs: list[TransformSpec] = []
        for value in self._transforms:
            try:
                transform_specs.append(TransformSpec(**value))
            except (TypeError, ValueError):
                continue
        for sample in self._sample_browser.samples():
            population_ids = populations_by_sample.get(sample.id, set()) | {"all_events"}
            population_ids.update(gate.id for gate in self._gate_editor.gates())
            catalog_channels = tuple(
                ChannelSpec(
                    id=entry.parameter_id,
                    name=entry.display_name,
                    unit=entry.unit,
                )
                for entry in self._catalog_for_sample(sample)
            )
            contexts[sample.id] = SamplePresentationContext(
                sample_id=sample.id,
                channels=catalog_channels,
                population_ids=tuple(sorted(population_ids)),
                transform_ids=tuple(transform.id for transform in transform_specs),
                transforms=tuple(transform_specs),
                analysis_revision=str(self.analysis_revision),
            )
        typed_sources: list[OverlaySourceSpec] = []
        source_by_id: dict[str, dict[str, Any]] = {}
        for value in sources:
            source_by_id[str(value.get("source_id", ""))] = value
            source = dict(value)
            source.pop("style", None)
            source.pop("display_name", None)
            source.setdefault("display_name", str(value.get("source_id", "source")))
            source.setdefault("sample_id", None)
            source.setdefault("population_id", None)
            try:
                typed_sources.append(OverlaySourceSpec(**source))
            except (TypeError, ValueError):
                continue
        resolutions = resolve_overlay_sources(tuple(typed_sources), contexts)
        result: dict[str, tuple[str, tuple[str, ...]]] = {
            source_id: ("error", ("malformed overlay source definition",))
            for source_id in source_by_id
        }
        for resolution in resolutions:
            result[resolution.source_id] = (
                resolution.status,
                tuple(diagnostic.message for diagnostic in resolution.diagnostics),
            )
        # All layers must share the active scientific coordinate system.  A source
        # may vary sample/population/style, but arbitrary per-layer parameter or
        # transform changes would make a visual comparison scientifically invalid.
        active_x = self._channel_selector.x_channel_id()
        active_y = (
            None if self._channel_selector.is_count_mode()
            else self._channel_selector.y_channel_id()
        )
        active_x_transform = self._active_plot_transform(active_x or "")
        active_y_transform = self._active_plot_transform(active_y or "")
        expected_x_transform = None if active_x_transform is None else active_x_transform.id
        expected_y_transform = None if active_y_transform is None else active_y_transform.id
        for source in sources:
            source_id = str(source.get("source_id", ""))
            if source.get("x_parameter_id") != active_x:
                result[source_id] = (
                    "incompatible",
                    ("overlay X parameter must match the active plot",),
                )
            elif source.get("y_parameter_id") != active_y:
                result[source_id] = (
                    "incompatible",
                    ("overlay Y parameter must match the active plot",),
                )
            elif source.get("x_transform_id") != expected_x_transform:
                result[source_id] = (
                    "incompatible",
                    ("overlay X transform must match the active plot",),
                )
            elif source.get("y_transform_id") != expected_y_transform:
                result[source_id] = (
                    "incompatible",
                    ("overlay Y transform must match the active plot",),
                )
        return result

    def _on_edit_overlay_sources(self) -> None:
        """Edit display sources; this operation never reruns the scientific pipeline."""
        from flowdesk_qt.overlay_source_editor import OverlaySourceEditorDialog

        view_id = self._overlay_view_id()
        view = next((item for item in self._plot_views if item.get("id") == view_id), None)
        sources = [] if view is None else list(view.get("overlay_sources", []))
        dialog = OverlaySourceEditorDialog(
            self._overlay_samples_for_editor(),
            self._overlay_population_ids_for_editor(),
            self._transforms,
            sources,
            status_resolver=self._overlay_status_resolver,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._overlay_undo_stack.execute(
                EditOverlaySourcesCommand(view_id, dialog.sources())
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Overlay Sources", str(exc))
            return
        self._update_status("Overlay display definition updated")
        self._replot()

    def _on_edit_plot_presentation(self) -> None:
        """Edit display presentation only; no authoritative pipeline rerun occurs."""
        from flowdesk_qt.plot_style_editor import PlotStyleEditorDialog

        view_id = self._overlay_view_id()
        view = next((item for item in self._plot_views if item.get("id") == view_id), None)
        source_ids = tuple(
            str(source.get("source_id"))
            for source in (view or {}).get("overlay_sources", [])
            if source.get("source_id")
        )
        plot_type = str((view or {}).get(
            "plot_type",
            "histogram" if self._channel_selector.is_count_mode() else "scatter",
        ))
        presentation = deepcopy((view or {}).get("presentation", {}))
        if self._current_sample_id is not None:
            presentation["title"] = self._current_sample_title()
        dialog = PlotStyleEditorDialog(
            plot_type,
            presentation,
            source_ids,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited_presentation = dialog.presentation()
        if self._current_sample_id is not None:
            self._set_current_sample_title(
                str(edited_presentation.get("title", ""))
            )
        try:
            self._overlay_undo_stack.execute(
                EditPlotPresentationCommand(view_id, edited_presentation)
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Plot Presentation", str(exc))
            return
        self._update_status("Plot presentation updated")
        self._refresh_sample_display_names()
        self._replot()

    def _on_plot_appearance_requested(self, action_id: str) -> None:
        """Route plot-area appearance actions through the existing editor command."""
        if action_id.startswith("axisTicks:"):
            policy = action_id.split(":", 1)[1]
            self._plot_widget.set_tick_policy(policy)  # type: ignore[arg-type]
            self._project_dirty = True
            self._update_status(f"Axis tick policy: {policy}")
            return
        if action_id == "plotResetAppearance":
            view_id = self._overlay_view_id()
            try:
                self._overlay_undo_stack.execute(
                    EditPlotPresentationCommand(view_id, {})
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Plot Appearance", str(exc))
                return
            self._update_status("Plot appearance reset")
            self._replot()
            return
        self._on_edit_plot_presentation()

    def _on_overlay_state_changed(self, state: dict[str, Any], reason: str) -> None:
        self._plot_views = deepcopy(state.get("plot_views", []))
        self._sync_display_max_points_from_view()
        self._project_dirty = True
        self._update_undo_actions()
        self._update_status(reason)

    def _on_undo_overlay_sources(self) -> None:
        if self._overlay_undo_stack.can_undo:
            self._overlay_undo_stack.undo()
            self._replot()

    def _on_redo_overlay_sources(self) -> None:
        if self._overlay_undo_stack.can_redo:
            self._overlay_undo_stack.redo()
            self._replot()

    def _on_edit_transforms(self) -> None:
        """Edit versioned transform definitions without changing used IDs in place."""
        from flowdesk_qt.transform_editor import TransformEditorDialog

        catalog = self._parameter_catalog
        if not catalog:
            channels_by_id = {}
            for sample in self._sample_browser.samples():
                for channel in sample.info.channels:
                    channels_by_id.setdefault(channel.id, channel)
            catalog = build_parameter_catalog(
                tuple(channels_by_id.values()), self._derived_parameters
            )
        current = self._sample_data.get(self._current_sample_id or "")
        preview_values = {}
        if current is not None:
            preview_values = {
                channel.id: current.events[:, index]
                for index, channel in enumerate(current.channels)
            }
        dialog = TransformEditorDialog(
            self._transforms,
            catalog,
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
                gate.x_transform_id,
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
            channels_by_id.update({channel.id: channel for channel in current.channels})

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
        self._open_statistics_editor(
            population_id=population_id,
            parameter_id=self._channel_selector.x_channel_id() or None,
        )

    def _on_add_statistic_from_results(self, population_id: str) -> None:
        """Open the shared statistic editor from the Results workspace."""
        self._open_statistics_editor(
            population_id=population_id,
            parameter_id=self._channel_selector.x_channel_id() or None,
        )

    def _on_add_statistic_from_graph(self) -> None:
        """Open a new statistic definition using the graph X parameter."""
        self._open_statistics_editor(
            population_id=self._display_population_id,
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

        catalog = self._parameter_catalog
        if not catalog:
            channels_by_id = {}
            for sample in self._sample_browser.samples():
                for channel in sample.info.channels:
                    channels_by_id.setdefault(channel.id, channel)
            catalog = build_parameter_catalog(
                tuple(channels_by_id.values()), self._derived_parameters
            )

        population_ids = ["all_events"]
        for gate in self._gate_editor.gates():
            if gate.id not in population_ids:
                population_ids.append(gate.id)

        dialog = StatisticsEditorDialog(
            self._statistics,
            catalog,
            population_ids,
            population_parents=self._population_parent_map(),
            population_labels=self._population_name_map(),
            statistic_references=self._statistic_reference_map(),
            transforms=self._transforms,
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

    def _statistic_reference_map(self) -> dict[str, tuple[str, ...]]:
        """Describe persisted downstream bindings before a statistic is removed."""
        references: dict[str, list[str]] = {}
        for binding in self._group_strategy_bindings:
            binding_id = str(binding.get("id", "binding"))
            for statistic_id in binding.get("statistic_ids", ()):
                references.setdefault(str(statistic_id), []).append(
                    f"Group strategy binding: {binding_id}"
                )
        return {statistic_id: tuple(values) for statistic_id, values in references.items()}

    def _open_statistics_manager(self) -> None:
        """Edit Compute/Show flags without mixing display state with analysis."""
        from flowdesk_qt.statistics_editor import StatisticManagementDialog

        dialog = StatisticManagementDialog(
            self._statistics,
            self._results_workspace.statistic_column_visibility(),
            parameter_labels={
                entry.parameter_id: entry.display_name
                for entry in self._parameter_catalog
            },
            population_labels=self._population_name_map(),
            population_ids=tuple(self._population_parent_map()),
            population_parents=self._population_parent_map(),
            available_channels=self._parameter_catalog,
            transforms=self._transforms,
            statistic_references=self._statistic_reference_map(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.definitions()
        compute_changed = [
            value for old, value in zip(self._statistics, updated, strict=True)
            if bool(old.get("compute_enabled", True))
            != bool(value.get("compute_enabled", True))
        ]
        targets_changed = any(
            tuple(old.get("population_ids") or [old.get("population_id", "")])
            != tuple(value.get("population_ids") or [value.get("population_id", "")])
            for old, value in zip(self._statistics, updated, strict=True)
        )
        calculation_keys = (
            "parameter_id",
            "metric",
            "source_stage",
            "transform_id",
            "value_policy",
            "non_finite_policy",
            "settings",
        )
        calculation_changed = any(
            any(old.get(key) != value.get(key) for key in calculation_keys)
            for old, value in zip(self._statistics, updated, strict=True)
        )
        self._statistics = updated
        self._sync_statistic_result_definitions()
        self._results_workspace.set_statistic_column_visibility(dialog.visibility())
        self._project_dirty = True
        if compute_changed or targets_changed or calculation_changed:
            reason = (
                "Statistic targets changed"
                if targets_changed and not compute_changed
                else "Statistics definition changed"
                if calculation_changed and not compute_changed
                else "Statistic Compute settings changed"
            )
            self._mark_results_stale(reason)

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
        target_x = self._active_plot_transform(gate.x_parameter or "")
        target_y = (
            self._active_plot_transform(gate.y_parameter or "")
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

    def _diagnostic_gate_labels(self) -> dict[str, str]:
        """Build readable gate references for diagnostic presentation only."""
        return {
            gate.id: f"{gate.name} [{gate.gate_type}; ID={gate.id}]"
            for gate in self._gate_editor.gates()
        }

    def _diagnostic_statistic_labels(self) -> dict[str, str]:
        """Build readable statistic references for diagnostic presentation only."""
        labels: dict[str, str] = {}
        for value in self._statistics:
            statistic_id = str(value.get("id") or "")
            if not statistic_id:
                continue
            name = str(value.get("name") or statistic_id)
            metric = str(value.get("metric") or "count")
            parameter = str(value.get("parameter_id") or "no parameter")
            labels[statistic_id] = (
                f"{name} [{metric}; parameter={parameter}; ID={statistic_id}]"
            )
        return labels

    def _validate_population_selection(self, report: Any) -> None:
        """Ensure the currently selected population ID is valid for the current sample.

        If the selected population does not exist in the new report data for the
        current sample, fall back to ``all_events``.
        """
        if self._display_population_id == "all_events":
            return
        population_ids = {
            r.population_id
            for r in report.population_results
            if r.sample_id == self._current_sample_id
        }
        if self._display_population_id not in population_ids:
            self._display_population_id = "all_events"

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

        _x_scale, _y_scale, x_transform_id, y_transform_id = (
            self._gate_editor.plot_coordinate_context()
        )
        if not self._gate_editor.has_plot_coordinate_context():
            # This fallback supports programmatic creation before a plot refresh.
            # Normal interactive creation always uses the exact context synced
            # by ``_replot`` above.
            x_transform = self._active_plot_transform(x_name)
            y_transform = self._active_plot_transform(y_name)
            x_transform_id = None if x_transform is None else x_transform.id
            y_transform_id = None if y_transform is None else y_transform.id
        gate = GateSpec(
            id=f"gate_{uuid.uuid4().hex[:8]}",
            name=f"rect_{len(self._gate_editor.gates()) + 1}",
            gate_type="rectangle",
            parent_population_id=(
                self._gate_editor.creation_parent_population_id()
            ),
            x_parameter=x_name,
            y_parameter=y_name,
            x_transform_id=x_transform_id,
            y_transform_id=y_transform_id,
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
        # The ROI item is already at the final geometry. Avoid the generic
        # gates-changed handler, which immediately destroys and rebuilds the
        # entire scatter/gate display before the new membership exists. The
        # core preview will trigger the one necessary replot when ready.
        self._gate_editor.update_gate(gate_index, gate, notify=False)
        self._mark_results_stale("Gate geometry changed", {gate.id})
        # sigRegionChangeFinished means interaction has ended, so the normal
        # debounce delay adds latency without coalescing any more drag events.
        if not self._results_workspace.auto_recalculate_stale_results():
            self._preview_scheduler.start_pending_now()
        self._project_dirty = True
        self._update_undo_actions()

    def _queue_gate_geometry_changed(self, gate_index: int, gate) -> None:
        """Persist an ROI edit after its Qt signal finishes dispatching."""
        del gate_index  # Resolve the current index by stable gate ID at apply time.
        self._pending_gate_geometry_updates[gate.id] = gate
        QTimer.singleShot(
            0,
            lambda gate_id=gate.id: self._apply_pending_gate_geometry_update(gate_id),
        )

    def _apply_pending_gate_geometry_update(self, gate_id: str) -> None:
        gate = self._pending_gate_geometry_updates.pop(gate_id, None)
        if gate is None:
            return
        gate_index = next(
            (
                index for index, current in enumerate(self._gate_editor.gates())
                if current.id == gate_id
            ),
            -1,
        )
        if gate_index >= 0:
            self._on_gate_geometry_changed(gate_index, gate)

    def _flush_pending_gate_geometry_updates(self) -> None:
        """Commit finished ROI edits before save/export/pipeline state reads."""
        for gate_id in tuple(self._pending_gate_geometry_updates):
            self._apply_pending_gate_geometry_update(gate_id)

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

    def _on_set_numeric_view_range(self) -> None:
        """Set the display ViewBox range from explicit numeric values."""
        current = self._plot_widget.view_range()
        if current is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Set View Range")
        form = QFormLayout(dialog)
        fields: dict[str, QDoubleSpinBox] = {}
        for name, value in (
            ("X minimum", current[0][0]),
            ("X maximum", current[0][1]),
            ("Y minimum", current[1][0]),
            ("Y maximum", current[1][1]),
        ):
            field = QDoubleSpinBox(dialog)
            field.setRange(-1e15, 1e15)
            field.setDecimals(12)
            field.setValue(value)
            field.setObjectName("viewRange" + name.replace(" ", ""))
            fields[name] = field
            form.addRow(name, field)
        x_hint = self._plot_widget.axis_range_input_hint("x")
        y_hint = self._plot_widget.axis_range_input_hint("y")
        note = QLabel(
            f"X values: {x_hint}; Y values: {y_hint}.",
            dialog,
        )
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        x_range = (fields["X minimum"].value(), fields["X maximum"].value())
        y_range = (fields["Y minimum"].value(), fields["Y maximum"].value())
        if x_range[0] >= x_range[1] or y_range[0] >= y_range[1]:
            QMessageBox.warning(
                self, "Invalid View Range", "Minimum values must be smaller than maximum values."
            )
            return
        self._plot_widget.set_manual_view_range(x_range, y_range)
        self._update_status("Viewport set from numeric range")

    def _on_export_aspect_toggled(self, enabled: bool) -> None:
        self._update_status(
            "Export aspect: 1:1" if enabled else "Export aspect: current view"
        )

    def _on_marginal_toggled(self, enabled: bool) -> None:
        """Handle marginal histogram toggle."""
        self._plot_widget.set_marginal_enabled(enabled)
        status = "Marginal histograms enabled" if enabled else "Marginal histograms disabled"
        self._update_status(status)
        self._replot()

    def _on_interaction_mode(self, mode: str) -> None:
        """Forward the exclusive toolbar mode to the display widget."""
        self._plot_widget.set_interaction_mode(mode)  # type: ignore[arg-type]
        self._update_status(f"Plot interaction mode: {mode}")

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
            self._plot_widget.set_export_metadata(self._current_plot_export_metadata())
            self._plot_widget.export_png(
                path_str,
                aspect_1_to_1=self._plot_toolbar.export_aspect_1_to_1(),
            )
            self._update_status(f"Plot exported to {path_str}")
        except Exception as exc:
            logger.error("PNG export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_export_svg(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Export Plot as SVG", "", "SVG files (*.svg)")[0]
        if not path:
            return
        try:
            self._plot_widget.set_export_metadata(self._current_plot_export_metadata())
            self._plot_widget.export_vector(
                path, "SVG",
                aspect_1_to_1=self._plot_toolbar.export_aspect_1_to_1(),
            )
            self._update_status(f"Plot exported to {path}")
        except Exception as exc:
            logger.error("SVG export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _on_export_pdf(self) -> None:
        path = QFileDialog.getSaveFileName(self, "Export Plot as PDF", "", "PDF files (*.pdf)")[0]
        if not path:
            return
        try:
            self._plot_widget.set_export_metadata(self._current_plot_export_metadata())
            self._plot_widget.export_vector(
                path, "PDF",
                aspect_1_to_1=self._plot_toolbar.export_aspect_1_to_1(),
            )
            self._update_status(f"Plot exported to {path}")
        except Exception as exc:
            logger.error("PDF export failed: %s", exc)
            QMessageBox.critical(self, "Export Error", str(exc))

    def _current_plot_export_metadata(self) -> dict[str, Any]:
        """Prepare display-only export metadata from the persisted view.

        The widget remains a renderer: source identity, ordering, compatibility
        diagnostics, and presentation precedence are resolved here through the
        GUI-independent core contracts.
        """
        view = next(
            (item for item in self._plot_views if item.get("id") == self._overlay_view_id()),
            None,
        )
        if view is None:
            return {}
        sources = sorted(
            view.get("overlay_sources", []),
            key=lambda item: (int(item.get("order", 0)), str(item.get("source_id", ""))),
        )
        statuses = self._overlay_status_resolver(sources)
        visible = [source for source in sources if source.get("visible", True)]
        invalid = [
            source.get("source_id", "") for source in visible
            if statuses.get(source.get("source_id", ""), ("missing", ()))[0]
            != "compatible"
        ]
        if invalid:
            raise ValueError(
                "cannot export with incompatible visible overlay source(s): "
                + ", ".join(str(source_id) for source_id in invalid)
            )
        source_ids = tuple(str(source.get("source_id", "")) for source in visible)
        resolved = resolve_presentation_layers(
            view.get("presentation", {}), source_ids=source_ids
        )
        return {
            "plot_id": view.get("id"),
            "definition_version": 1,
            "plot_type": view.get("plot_type", "scatter"),
            "ordered_source_ids": list(source_ids),
            "sources": [
                {
                    "source_id": source.get("source_id"),
                    "sample_id": source.get("sample_id"),
                    "population_id": source.get("population_id"),
                    "x_parameter_id": source.get("x_parameter_id"),
                    "y_parameter_id": source.get("y_parameter_id"),
                    "x_transform_id": source.get("x_transform_id"),
                    "y_transform_id": source.get("y_transform_id"),
                    "visible": bool(source.get("visible", True)),
                }
                for source in visible
            ],
            "presentation": asdict(resolved.presentation),
            "style_provenance": dict(resolved.provenance),
            "integrated_overlay": self._sample_browser.overlay_state(),
            "integrated_style_provenance": self._integrated_style_provenance(),
            "population_display_colors": (
                self._gate_editor.population_display_definitions()
            ),
            "diagnostics": [
                {"source_id": source_id, "messages": messages}
                for source_id, (_, messages) in statuses.items()
                if messages
            ],
            "scientific_note": (
                "Presentation settings and display sampling do not alter scientific results."
            ),
        }

    def _integrated_style_provenance(self) -> dict[str, dict[str, object]]:
        """Expose resolved integrated overlay colors for export sidecars."""
        state = self._sample_browser.overlay_state()
        manual_ids = set(state.get("manual_overlay_sample_ids", []))
        manual_ids.update(
            self._sample_browser.comparison_overlay_sample_ids(self._current_sample_id)
        )
        role_colors = state.get("comparison_role_colors", {})
        result: dict[str, dict[str, object]] = {}
        for sample_id in sorted(manual_ids - {self._current_sample_id}):
            role_color = None
            for comparison in state.get("comparison_sets", []):
                for member in comparison.get("members", []):
                    if member.get("sample_id") == sample_id:
                        role_color = role_colors.get(member.get("role"))
            resolution = resolve_overlay_style(
                explicit_overlay_color=state.get("manual_overlay_colors", {}).get(sample_id),
                comparison_role_color=role_color,
                default_event_color=self._plot_widget.style().dot_color,
            )
            result[sample_id] = {
                "color": resolution.color,
                "provenance": resolution.provenance,
                "used_fallback": resolution.used_fallback,
            }
        return result

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

    def _on_export_results(self) -> None:
        """Export Results, rerunning the pipeline when the report is stale."""
        report = self._last_result_report or self._population_tree.last_report()
        if not self._sample_data and (report is None or not report.population_results):
            QMessageBox.information(
                self,
                "No results",
                "Run Pipeline before exporting Results.",
            )
            return

        from flowdesk_qt.results_export_dialog import ResultsExportDialog

        options_dialog = ResultsExportDialog(self)
        if options_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = options_dialog.options()
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "",
            "TSV files (*.tsv);;CSV files (*.csv);;All files (*)",
        )
        if not path_str:
            return
        delimiter = "," if selected_filter.startswith("CSV") or path_str.endswith(".csv") else "\t"
        pipeline_running = self._worker is not None and self._worker.isRunning()
        needs_pipeline = (
            pipeline_running
            or self._results_stale
            or report is None
            or not report.population_results
        )
        if needs_pipeline and not self._sample_data:
            QMessageBox.information(
                self,
                "No samples",
                "Load samples before exporting Results.",
            )
            return
        self._pending_results_export = (options, path_str, delimiter)
        if needs_pipeline:
            if pipeline_running:
                self._update_status(
                    "Pipeline is running; export will continue when it finishes..."
                )
            else:
                self._update_status("Results stale; running Pipeline before export...")
                self._on_run_pipeline()
            return
        self._complete_pending_results_export()

    def _complete_pending_results_export(self) -> None:
        """Write a queued Results export from the current authoritative report."""
        pending = self._pending_results_export
        if pending is None:
            return
        self._pending_results_export = None
        options, path_str, delimiter = pending
        report = self._last_result_report or self._population_tree.last_report()
        if report is None or not report.population_results or self._results_stale:
            QMessageBox.critical(
                self,
                "Export Error",
                "No current Results are available; the export was not written.",
            )
            return
        try:
            project = self._build_project_manifest()
            if options.layout == "long":
                from flowdesk_core.export import write_results_long as writer
            else:
                from flowdesk_core.export import write_results_wide as writer
            writer(
                report,
                project,
                path_str,
                delimiter=delimiter,
                include_population_metrics=options.include_population_metrics,
                include_custom_statistics=options.include_custom_statistics,
                include_internal_ids=options.include_internal_ids,
                include_qc=options.include_qc,
            )
            self._update_status(f"Results exported to {path_str}")
        except Exception as exc:
            logger.error("Results export failed: %s", exc)
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

    def _population_ids_for_gates(
        self,
        gate_ids: set[str] | frozenset[str] | None,
    ) -> set[str]:
        """Return changed gates plus all descendants in the current hierarchy."""
        gates = self._gate_editor.gates()
        children: dict[str, set[str]] = {}
        for gate in gates:
            parent = gate.parent_population_id or "all_events"
            children.setdefault(parent, set()).add(gate.id)
        roots = set(gate_ids) if gate_ids is not None else {gate.id for gate in gates}
        affected: set[str] = set()
        pending = list(roots)
        while pending:
            population_id = pending.pop()
            if population_id in affected:
                continue
            affected.add(population_id)
            pending.extend(children.get(population_id, ()))
        return affected

    def _schedule_current_preview(
        self, requested_population_id: str | None = None
    ) -> None:
        """Submit the active sample to the debounced core preview scheduler."""
        sample_id = self._current_sample_id
        sample = self._sample_data.get(sample_id or "")
        if sample is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        population_id = requested_population_id or self._display_population_id or "all_events"
        revision = self._preview_revision.analysis_revision
        try:
            project = self._build_project_manifest()
            requested_statistic_ids = tuple(
                str(value.get("id"))
                for value in project.get("statistics", [])
                if isinstance(value, dict)
                and value.get("population_id") == population_id
                and isinstance(value.get("id"), str)
            )
            request = PreviewRequest(
                revision=revision,
                sample=sample,
                execution_profile_id="default",
                strategy_id="default_strategy",
                required_population_id=population_id,
                requested_statistic_ids=requested_statistic_ids,
                invalidation_reason="definition_changed",
            )
            self._preview_revision.mark_pending()
            self._preview_scheduler.schedule(project, request)
        except Exception as exc:
            self._preview_revision.mark_error()
            self._update_status(f"Current-sample preview error: {exc}")

    def _on_preview_ready(self, report: PreviewReport) -> None:
        """Atomically accept a current-revision report on the GUI thread."""
        if report.sample_id != self._current_sample_id:
            return
        population_ids = {
            result.population_id for result in report.population_results
        }
        if not self._preview_revision.accept_preview(
            report.revision, population_ids
        ):
            return
        if not self._result_state.accept_preview(report):
            return
        self._preview_report = report
        self._old_membership_banner = False
        self._results_workspace.set_statistic_definition_names(
            {
                str(value.get("id")): str(value.get("name"))
                for value in self._statistics
                if value.get("id") and value.get("name")
            }
        )
        self._results_workspace.set_result_state(self._result_state)
        self._refresh_override_statuses()
        self._replot()

    def _on_preview_failed(
        self, request: PreviewRequest, error: Exception
    ) -> None:
        """Keep authoritative results unchanged when preview execution fails."""
        if request.sample_id != self._current_sample_id:
            return
        self._preview_revision.mark_error()
        self._update_status(f"Current-sample preview error: {error}")

    def _mark_results_stale(
        self,
        reason: str,
        affected_gate_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        # Keep newly added/edited definitions visible as missing or stale
        # result columns immediately. Values are still produced only by the
        # canonical pipeline/preview runner.
        self._sync_statistic_result_definitions()
        self._results_stale_reason = reason
        affected_population_ids = self._population_ids_for_gates(affected_gate_ids)
        revision = self._preview_revision.invalidate(affected_population_ids)
        if self._current_sample_id is not None:
            self._result_state.invalidate(
                revision=revision,
                active_sample_id=self._current_sample_id,
                affected_population_ids=tuple(affected_population_ids),
            )
        self._preview_report = None
        self._processed_display_scheduler.cancel_pending()
        self._results_stale = True
        self._population_tree.clear()
        self._population_tree.mark_results_stale()
        self._results_workspace.set_statistic_definition_names(
            {
                str(value.get("id")): str(value.get("name"))
                for value in self._statistics
                if value.get("id") and value.get("name")
            }
        )
        self._results_workspace.set_result_state(self._result_state)
        self._diagnostics_panel.clear(stale=True)
        self._gate_editor.clear_population_results()
        self._compensation_status_indicator.mark_stale()
        self._refresh_parameter_catalog()
        self._refresh_override_statuses()
        self._update_status(f"{reason} (results stale; rerun pipeline)")
        if self._results_workspace.auto_recalculate_stale_results():
            self._preview_scheduler.cancel_pending()
            self._request_auto_recalculation()
        else:
            self._schedule_current_preview()

    def _sync_statistic_result_definitions(self) -> None:
        """Expose persisted statistic columns before their next calculation."""
        self._result_state.update_definitions(
            sample_ids=tuple(sample.id for sample in self._sample_browser.samples()),
            population_ids=tuple(self._population_parent_map()),
            statistic_definitions=tuple(
                (
                    str(value.get("id")),
                    str(population_id),
                    bool(value.get("compute_enabled", True)),
                )
                for value in self._statistics
                if value.get("id")
                for population_id in value.get(
                    "population_ids",
                    [value.get("population_id", "all_events")],
                )
            ),
        )
    # -- help ----------------------------------------------------------------

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Flowdesk",
            f"{APP_NAME}\n\n"
            "Linux-first FlowJo-like flow cytometry analysis application.\n"
            f"Version {application_version()}",
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
