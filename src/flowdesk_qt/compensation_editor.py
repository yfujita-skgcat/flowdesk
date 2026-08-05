"""Qt editor for compensation matrices and bindings.

Provides a matrix list, heat-map preview, duplicate-before-edit workflow,
and binding management.  Follows the same list+form pattern as
``TransformEditorDialog`` and ``DerivedParameterEditorDialog``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.compensation import (
    CompensationCalculationResult,
    apply_compensation,
    calculate_spillover_matrix,
    inspect_compensation_matrix,
)
from flowdesk_core.compensation_preview import (
    CompensationPreviewRequest,
    CompensationPreviewResult,
)
from flowdesk_core.models import (
    CompensationBindingSpec,
    CompensationCalculationSpec,
    CompensationMatrixSpec,
)
from flowdesk_qt.compensation_preview_scheduler import CompensationPreviewScheduler
from flowdesk_qt.plot_widget import PlotWidget

# ---------------------------------------------------------------------------
# Heatmap colour helper
# ---------------------------------------------------------------------------


def _heatmap_color(value: float) -> QColor:
    """Return a diverging colour for a spillover matrix cell value.

    Values near 1.0 (diagonal) are white; positive off-diagonal values are
    orange/yellow; values near 0 are light grey.
    """
    clamped = max(0.0, min(1.0, value))
    if clamped >= 0.9:
        return QColor.fromRgbF(1.0, 1.0, 1.0, 0.95)
    if clamped >= 0.5:
        t = (clamped - 0.5) / 0.4
        r = 1.0
        g = 0.6 + 0.4 * t
        b = 0.2 + 0.8 * t
        return QColor.fromRgbF(r, g, b, 0.9)
    if clamped >= 0.1:
        t = clamped / 0.5
        r = 0.3 + 0.7 * t
        g = 0.3 + 0.3 * t
        b = 0.3 + 0.3 * t
        return QColor.fromRgbF(r, g, b, 0.8)
    return QColor.fromRgbF(0.15, 0.15, 0.15, 0.7)


# ---------------------------------------------------------------------------
# Empty factory
# ---------------------------------------------------------------------------


def _empty_matrix_mapping() -> dict[str, Any]:
    """Return a minimal compensation matrix mapping ready for user editing."""
    return {
        "id": "",
        "name": "",
        "source": "user_defined",
        "channels": [],
        "matrix": [],
        "created_by": None,
        "created_at": None,
        "notes": "",
        "provenance": {},
    }


def _empty_binding_mapping() -> dict[str, Any]:
    """Return a minimal compensation binding mapping."""
    return {
        "id": "",
        "matrix_id": "",
        "scope": "sample",
        "target_id": "",
        "created_by": None,
        "created_at": None,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# CompensationMatrixEditorDialog
# ---------------------------------------------------------------------------


class CompensationMatrixEditorDialog(QDialog):
    """Edit compensation matrix definitions and bindings.

    The dialog supports:
    - Adding / editing / deleting compensation matrices.
    - Heat-map preview of the spillover matrix.
    - Duplicate-before-edit (immutability enforcement).
    - Adding / editing / deleting bindings between matrices and scopes.
    - Condition-number validation preview.
    """

    def __init__(
        self,
        matrices: Sequence[dict[str, Any]],
        bindings: Sequence[dict[str, Any]],
        available_channels: Sequence[dict[str, Any]],
        sample_ids: Sequence[str],
        group_ids: Sequence[str],
        *,
        sample_data: dict[str, dict[str, Any]] | None = None,
        sample_labels: dict[str, str] | None = None,
        population_ids: Sequence[str] | None = None,
        population_labels: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the compensation editor dialog.

        Args:
            matrices: Compensation matrix definitions.
            bindings: Compensation binding definitions.
            available_channels: Channel metadata available in the project.
            sample_ids: Sample identifiers.
            group_ids: Group identifiers.
            sample_data: Optional mapping from sample_id to a dict with keys
                ``events`` (NDArray[np.float64]) and ``channel_ids`` (list[str])
                for compensated/uncompensated preview.
            parent: Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("compensationMatrixEditorDialog")
        self.setWindowTitle("Compensation Matrices")
        self.resize(1200, 900)

        self._matrices = deepcopy(list(matrices))
        self._bindings = deepcopy(list(bindings))
        self._channels = tuple(available_channels)
        self._sample_ids = tuple(sample_ids)
        self._group_ids = tuple(group_ids)
        self._sample_data = sample_data or {}
        self._sample_labels = dict(sample_labels or {})
        self._population_ids = tuple(population_ids or ("all_events",))
        self._population_labels = dict(population_labels or {})
        self._binding_panel: QWidget | None = None
        self._loading = False
        self._current_matrix_row = -1
        self._current_binding_row = -1
        self._source_matrix_snapshot: dict[str, Any] | None = None
        self._manual_source_snapshots: dict[str, dict[str, Any]] = {}
        self._selected_pair: tuple[str, str] | None = None
        self._control_assignments: dict[str, dict[str, Any]] = {}
        self._preview_revision = 0
        self._preview_preserved_view_range = None
        self._setting_coefficient = False
        self._preview_scheduler = CompensationPreviewScheduler(self)

        self._build_ui()
        self._preview_scheduler.preview_ready.connect(
            self._on_candidate_preview_ready
        )
        self._preview_scheduler.preview_failed.connect(
            self._on_candidate_preview_failed
        )

        if not self._matrices:
            self._matrices.append(_empty_matrix_mapping())
        self._refresh_matrix_list(0)
        if self._bindings:
            self._refresh_binding_list(0)

    # -- Public API ----------------------------------------------------------

    def matrices(self) -> list[dict[str, Any]]:
        """Return a deep copy of the current matrix definitions."""
        self._commit_current_matrix()
        return deepcopy(self._matrices)

    def bindings(self) -> list[dict[str, Any]]:
        """Return a deep copy of the current binding definitions."""
        self._commit_current_binding()
        return deepcopy(self._bindings)

    def set_control_assignments(
        self, calculations: Sequence[dict[str, Any]]
    ) -> None:
        """Use explicit calculation controls to choose preview data.

        The mapping is display metadata only.  The core preview still receives
        stable channel IDs and immutable masks from ``sample_data``.
        """
        assignments: dict[str, dict[str, Any]] = {}
        for calculation in calculations:
            for control in calculation.get("controls", []):
                detector = str(control.get("detector_channel_id", ""))
                if detector and detector not in assignments:
                    assignments[detector] = deepcopy(control)
        self._control_assignments = assignments
        self._schedule_candidate_preview(preserve_range=False)

    def add_matrix_mapping(
        self, mapping: dict[str, Any], *, select: bool = True
    ) -> bool:
        """Add a calculated matrix once and optionally select it for review."""
        matrix_id = str(mapping.get("id", ""))
        if not matrix_id or any(
            str(value.get("id", "")) == matrix_id for value in self._matrices
        ):
            return False
        self._commit_current_matrix()
        self._matrices.append(deepcopy(mapping))
        self._refresh_matrix_list(len(self._matrices) - 1 if select else 0)
        return True

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Stop candidate preview work before the dialog is destroyed."""
        self._preview_scheduler.shutdown()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        """Stop candidate preview work on both accept and reject."""
        self._preview_scheduler.shutdown()
        super().done(result)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left side: matrix list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)

        matrix_group = QGroupBox("Matrices")
        matrix_layout = QVBoxLayout(matrix_group)
        self._matrix_list = QListWidget()
        self._matrix_list.setObjectName("compensationMatrixList")
        matrix_layout.addWidget(self._matrix_list)

        matrix_btns = QHBoxLayout()
        self._new_matrix_btn = QPushButton("New")
        self._new_matrix_btn.setObjectName("compensationNewMatrixButton")
        self._duplicate_matrix_btn = QPushButton("Save as Copy")
        self._duplicate_matrix_btn.setObjectName("compensationDuplicateMatrixButton")
        self._delete_matrix_btn = QPushButton("Delete")
        self._delete_matrix_btn.setObjectName("compensationDeleteMatrixButton")
        matrix_btns.addWidget(self._new_matrix_btn)
        matrix_btns.addWidget(self._duplicate_matrix_btn)
        matrix_btns.addWidget(self._delete_matrix_btn)
        matrix_layout.addLayout(matrix_btns)
        left_layout.addWidget(matrix_group)

        left_layout.addStretch(1)

        # --- Right side: matrix form + heat map ---
        details = QWidget()
        details_layout = QVBoxLayout(details)

        form = QFormLayout()
        self._id_edit = QLineEdit()
        self._id_edit.setObjectName("compensationMatrixIdEdit")
        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("compensationMatrixNameEdit")
        self._source_combo = QComboBox()
        self._source_combo.setObjectName("compensationSourceCombo")
        self._source_combo.addItems([
            "user_defined",
            "fcs_metadata_spillover",
            "imported",
            "calculated",
        ])
        self._notes_edit = QLineEdit()
        self._notes_edit.setObjectName("compensationNotesEdit")
        form.addRow("Matrix ID:", self._id_edit)
        form.addRow("Name:", self._name_edit)
        form.addRow("Source:", self._source_combo)
        form.addRow("Notes:", self._notes_edit)

        # Channel selection
        self._channels_list = QListWidget()
        self._channels_list.setObjectName("compensationChannelsList")
        self._channels_list.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        form.addRow("Channels:", self._channels_list)

        channel_btns = QHBoxLayout()
        self._add_channel_btn = QPushButton("Select All Channels")
        self._add_channel_btn.setObjectName("compensationAddChannelButton")
        self._remove_channel_btn = QPushButton("Clear All Channels")
        self._remove_channel_btn.setObjectName("compensationRemoveChannelButton")
        channel_btns.addWidget(self._add_channel_btn)
        channel_btns.addWidget(self._remove_channel_btn)
        form.addRow("", channel_btns)
        details_layout.addLayout(form)

        # Heat map table
        heat_group = QGroupBox("Matrix Heat Map Preview")
        heat_layout = QVBoxLayout(heat_group)
        direction_label = QLabel(
            "Columns: Source channel (spill from) →   "
            "Rows: Receiving channel (spill into) ↓"
        )
        direction_label.setObjectName("compensationMatrixDirectionLabel")
        direction_label.setWordWrap(True)
        heat_layout.addWidget(direction_label)
        self._heat_map = QTableWidget()
        self._heat_map.setObjectName("compensationHeatMap")
        self._heat_map.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._heat_map.verticalHeader().setVisible(True)
        self._heat_map.horizontalHeader().setVisible(True)
        self._heat_map.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._heat_map.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        heat_layout.addWidget(self._heat_map)
        details_layout.addWidget(heat_group, 1)

        coefficient_group = QGroupBox("Selected off-diagonal coefficient")
        coefficient_form = QFormLayout(coefficient_group)
        self._coefficient_label = QLabel("No pair selected")
        self._coefficient_label.setObjectName("compensationCoefficientLabel")
        self._coefficient_spin = QDoubleSpinBox()
        self._coefficient_spin.setObjectName("compensationCoefficientSpin")
        self._coefficient_spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self._coefficient_spin.setDecimals(6)
        self._coefficient_spin.setSingleStep(0.001)
        self._coefficient_spin.setSuffix(" %")
        self._coefficient_slider = QSlider(Qt.Orientation.Horizontal)
        self._coefficient_slider.setObjectName("compensationCoefficientSlider")
        self._coefficient_reset_btn = QPushButton("Reset to source value")
        self._coefficient_reset_btn.setObjectName("compensationCoefficientResetButton")
        coefficient_form.addRow("Pair:", self._coefficient_label)
        coefficient_form.addRow("Coefficient:", self._coefficient_spin)
        coefficient_form.addRow("Fine adjustment:", self._coefficient_slider)
        coefficient_form.addRow("", self._coefficient_reset_btn)
        details_layout.addWidget(coefficient_group)

        # Validation label
        actions = QHBoxLayout()
        self._validate_btn = QPushButton("Validate")
        self._validate_btn.setObjectName("compensationValidateButton")
        actions.addWidget(self._validate_btn)
        actions.addStretch(1)
        details_layout.addLayout(actions)
        self._diag_label = QLabel("Not validated")
        self._diag_label.setObjectName("compensationDiagnosticLabel")
        self._diag_label.setWordWrap(True)
        details_layout.addWidget(self._diag_label)

        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        self._build_preview_section(preview_layout)

        splitter.addWidget(left)
        splitter.addWidget(details)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 5)
        splitter.setSizes([220, 420, 760])
        outer.addWidget(splitter)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("compensationDialogButtons")
        outer.addWidget(buttons)

        # --- Signal connections ---
        self._matrix_list.currentRowChanged.connect(self._on_matrix_row_changed)
        self._new_matrix_btn.clicked.connect(self._add_matrix)
        self._duplicate_matrix_btn.clicked.connect(self._duplicate_matrix)
        self._delete_matrix_btn.clicked.connect(self._delete_matrix)
        self._add_channel_btn.clicked.connect(self._add_channel)
        self._remove_channel_btn.clicked.connect(self._remove_channel)
        self._heat_map.cellClicked.connect(self._on_heat_map_cell_clicked)
        self._heat_map.cellChanged.connect(self._on_heat_map_cell_changed)
        self._coefficient_spin.valueChanged.connect(
            self._on_coefficient_spin_changed
        )
        self._coefficient_slider.valueChanged.connect(
            self._on_coefficient_slider_changed
        )
        self._coefficient_reset_btn.clicked.connect(self._reset_coefficient)
        self._validate_btn.clicked.connect(self._validate_current)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        self._build_binding_panel()

    def _build_binding_panel(self) -> None:
        """Build binding management in a separate workspace tab."""
        panel = QWidget()
        panel.setObjectName("compensationBindingsPanel")
        layout = QVBoxLayout(panel)
        binding_group = QGroupBox("Bindings")
        binding_layout = QVBoxLayout(binding_group)
        self._binding_list = QListWidget()
        self._binding_list.setObjectName("compensationBindingList")
        binding_layout.addWidget(self._binding_list, 1)
        binding_btns = QHBoxLayout()
        self._new_binding_btn = QPushButton("New")
        self._new_binding_btn.setObjectName("compensationNewBindingButton")
        self._delete_binding_btn = QPushButton("Delete")
        self._delete_binding_btn.setObjectName("compensationDeleteBindingButton")
        binding_btns.addWidget(self._new_binding_btn)
        binding_btns.addWidget(self._delete_binding_btn)
        binding_layout.addLayout(binding_btns)
        layout.addWidget(binding_group, 1)
        self._build_binding_form(layout)
        self._binding_list.currentRowChanged.connect(self._on_binding_row_changed)
        self._new_binding_btn.clicked.connect(self._add_binding)
        self._delete_binding_btn.clicked.connect(self._delete_binding)
        self._binding_panel = panel

    def binding_panel(self) -> QWidget:
        """Return the bindings editor page for the unified workspace."""
        if self._binding_panel is None:
            raise RuntimeError("binding panel has not been built")
        return self._binding_panel

    def _build_binding_form(self, layout: QVBoxLayout) -> None:
        """Build the inline binding editor form."""
        binding_form_group = QGroupBox("Binding Editor")
        form_layout = QVBoxLayout(binding_form_group)
        form = QFormLayout()

        self._b_id_edit = QLineEdit()
        self._b_id_edit.setObjectName("compensationBindingIdEdit")
        self._b_matrix_combo = QComboBox()
        self._b_matrix_combo.setObjectName("compensationBindingMatrixCombo")
        self._b_scope_combo = QComboBox()
        self._b_scope_combo.setObjectName("compensationBindingScopeCombo")
        self._b_scope_combo.addItems(["sample", "group", "execution_profile"])
        self._b_target_edit = QLineEdit()
        self._b_target_edit.setObjectName("compensationBindingTargetEdit")
        self._b_notes_edit = QLineEdit()
        self._b_notes_edit.setObjectName("compensationBindingNotesEdit")

        form.addRow("Binding ID:", self._b_id_edit)
        form.addRow("Matrix:", self._b_matrix_combo)
        form.addRow("Scope:", self._b_scope_combo)
        form.addRow("Target ID:", self._b_target_edit)
        form.addRow("Notes:", self._b_notes_edit)
        form_layout.addLayout(form)
        layout.addWidget(binding_form_group)

        # Populate matrix combo
        self._refresh_matrix_combo()

    # -- Preview section -----------------------------------------------------

    def _build_preview_section(self, layout: QVBoxLayout) -> None:
        """Build the candidate compensated preview widget."""
        preview_group = QGroupBox("Compensated Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Sample selector
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Sample:"))
        self._preview_sample_combo = QComboBox()
        self._preview_sample_combo.setObjectName(
            "compensationPreviewSampleCombo"
        )
        preview_available = [sid for sid in self._sample_ids if sid in self._sample_data]
        if preview_available:
            for sample_id in preview_available:
                self._preview_sample_combo.addItem(
                    self._sample_labels.get(sample_id, sample_id), sample_id
                )
        else:
            self._preview_sample_combo.insertItem(
                0, "(no data available)"
            )
        sel_row.addWidget(self._preview_sample_combo)
        sel_row.addStretch(1)
        preview_layout.addLayout(sel_row)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setObjectName("compensationPreviewButton")
        preview_layout.addWidget(self._preview_btn)
        self._preview_sample_combo.currentIndexChanged.connect(
            lambda _index: self._schedule_candidate_preview(preserve_range=False)
        )
        self._preview_population_combo = QComboBox()
        self._preview_population_combo.setObjectName(
            "compensationPreviewPopulationCombo"
        )
        for population_id in self._population_ids:
            label = self._population_labels.get(population_id, population_id)
            self._preview_population_combo.addItem(label, population_id)
        self._preview_population_combo.currentIndexChanged.connect(
            lambda _index: self._schedule_candidate_preview(preserve_range=False)
        )
        sel_row.addWidget(QLabel("Population / gate:"))
        sel_row.addWidget(self._preview_population_combo)
        self._preview_x_transform_combo = QComboBox()
        self._preview_x_transform_combo.setObjectName(
            "compensationPreviewXTransformCombo"
        )
        self._preview_y_transform_combo = QComboBox()
        self._preview_y_transform_combo.setObjectName(
            "compensationPreviewYTransformCombo"
        )
        for combo in (
            self._preview_x_transform_combo,
            self._preview_y_transform_combo,
        ):
            combo.addItem("Linear", "linear")
            combo.addItem("Log10", "log10")
            combo.addItem("Asinh", "asinh")
            combo.currentIndexChanged.connect(
                lambda _index: self._on_preview_transform_changed()
            )
        sel_row.addWidget(QLabel("X transform:"))
        sel_row.addWidget(self._preview_x_transform_combo)
        sel_row.addWidget(QLabel("Y transform:"))
        sel_row.addWidget(self._preview_y_transform_combo)

        self._preview_pair_label = QLabel(
            "Select an off-diagonal matrix cell to inspect a source → receiving pair."
        )
        self._preview_pair_label.setObjectName("compensationPreviewPairLabel")
        self._preview_pair_label.setWordWrap(True)
        preview_layout.addWidget(self._preview_pair_label)

        self._compensated_plot = PlotWidget()
        self._compensated_plot.setObjectName("compensationCompensatedPlot")
        self._compensated_plot.setMinimumHeight(360)
        preview_layout.addWidget(self._compensated_plot)

        # Preview table: columns = channel, compensated candidate
        self._preview_table = QTableWidget()
        self._preview_table.setObjectName("compensationPreviewTable")
        self._preview_table.setColumnCount(2)
        self._preview_table.setHorizontalHeaderLabels([
            "Channel", "Compensated",
        ])
        self._preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        preview_layout.addWidget(self._preview_table)

        layout.addWidget(preview_group)
        self._preview_btn.clicked.connect(self._on_preview)

    def _on_preview(self) -> None:
        """Execute the candidate compensated preview using core apply_compensation."""
        idx = self._preview_sample_combo.currentIndex()
        if idx < 0:
            return
        sample_id = str(self._preview_sample_combo.itemData(idx) or "")
        if (
            not sample_id
            or self._preview_sample_combo.currentText() == "(no data available)"
        ):
            self._diag_label.setText("No sample data available for preview")
            return

        self._commit_current_matrix()
        if self._current_matrix_row < 0 or self._current_matrix_row >= len(
            self._matrices
        ):
            self._diag_label.setText("No matrix selected for preview")
            return

        matrix_mapping = self._matrices[self._current_matrix_row]
        sample_info = self._sample_data.get(sample_id)
        if sample_info is None:
            self._diag_label.setText(
                f"No event data for sample {sample_id}"
            )
            return

        try:
            spec = CompensationMatrixSpec(**matrix_mapping)
            events = sample_info["events"]
            channel_ids = sample_info["channel_ids"]
            population_id = str(
                self._preview_population_combo.currentData() or "all_events"
            )
            compensated = apply_compensation(spec, events, channel_ids)

            # Show first 10 events for each compensation channel
            preview_channels = spec.channels
            n_show = min(10, compensated.shape[0])
            self._preview_table.setRowCount(n_show * len(preview_channels))
            row = 0
            for ch in preview_channels:
                try:
                    col_idx = channel_ids.index(ch)
                except ValueError:
                    continue
                for evt in range(n_show):
                    self._preview_table.setItem(
                        row, 0, QTableWidgetItem(self._channel_label(ch))
                    )
                    self._preview_table.setItem(
                        row, 1, QTableWidgetItem(
                            f"{compensated[evt, col_idx]:.4f}"
                        )
                    )
                    row += 1

            self._preview_table.setRowCount(row)
            self._diag_label.setText(
                f"Preview: {row} cells (matrix {spec.id}, sample {sample_id}, "
                f"population {population_id})"
            )
            self._schedule_candidate_preview(preserve_range=False)
        except Exception as exc:
            self._diag_label.setText(f"Preview failed: {exc}")

    def _on_preview_transform_changed(self) -> None:
        """Apply the selected display transforms to the preview plot."""
        self._apply_preview_axis_transforms()
        self._schedule_candidate_preview(preserve_range=False)

    def _apply_preview_axis_transforms(self) -> None:
        x_transform = str(
            self._preview_x_transform_combo.currentData() or "linear"
        )
        y_transform = str(
            self._preview_y_transform_combo.currentData() or "linear"
        )
        self._compensated_plot.set_axis_transforms(x_transform, y_transform)

    # -- Matrix list ---------------------------------------------------------

    def _refresh_matrix_list(self, selected_row: int) -> None:
        self._loading = True
        try:
            self._matrix_list.clear()
            for matrix in self._matrices:
                name = matrix.get("name") or matrix.get("id") or "New matrix"
                n_channels = len(matrix.get("channels", []))
                self._matrix_list.addItem(f"{name} ({n_channels} channels)")
            if self._matrices:
                self._matrix_list.setCurrentRow(
                    min(max(selected_row, 0), len(self._matrices) - 1)
                )
        finally:
            self._loading = False
        if self._matrices:
            self._load_matrix_row(self._matrix_list.currentRow())
        else:
            self._clear_matrix_fields()
        self._refresh_matrix_combo()

    def _refresh_matrix_combo(self) -> None:
        """Refresh the matrix dropdown in the binding form."""
        self._b_matrix_combo.blockSignals(True)
        self._b_matrix_combo.clear()
        for matrix in self._matrices:
            name = matrix.get("name") or matrix.get("id") or "(unnamed)"
            self._b_matrix_combo.addItem(name, matrix.get("id", ""))
        self._b_matrix_combo.blockSignals(False)

    def _load_matrix_row(self, row: int) -> None:
        if row < 0 or row >= len(self._matrices):
            return
        self._loading = True
        try:
            self._current_matrix_row = row
            value = self._matrices[row]
            self._id_edit.setText(str(value.get("id", "")))
            self._name_edit.setText(str(value.get("name", "")))
            self._source_combo.setCurrentText(
                str(value.get("source", "user_defined"))
            )
            self._notes_edit.setText(str(value.get("notes", "")))
            self._source_matrix_snapshot = deepcopy(
                self._manual_source_snapshots.get(
                    str(value.get("id", "")), value
                )
            )
            self._refresh_channels_list(value.get("channels", []))
            self._update_heat_map(value)
            self._selected_pair = self._first_off_diagonal_pair(value)
            self._update_preview_pair_label()
            self._load_coefficient_controls()
            self._set_calculated_matrix_editability(
                value.get("source") == "calculated"
            )
            self._diag_label.setText("Not validated")
        finally:
            self._loading = False
        if self._selected_pair is not None and self._sample_data:
            self._schedule_candidate_preview(preserve_range=False)

    def _clear_matrix_fields(self) -> None:
        self._loading = True
        try:
            self._current_matrix_row = -1
            self._id_edit.clear()
            self._name_edit.clear()
            self._source_combo.setCurrentIndex(0)
            self._notes_edit.clear()
            self._channels_list.clear()
            self._heat_map.setRowCount(0)
            self._heat_map.setColumnCount(0)
            self._source_matrix_snapshot = None
            self._selected_pair = None
            self._update_preview_pair_label()
            self._set_calculated_matrix_editability(False)
            self._diag_label.setText("No matrix selected")
        finally:
            self._loading = False

    def _on_matrix_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._commit_current_matrix()
        self._load_matrix_row(row)

    def _add_matrix(self) -> None:
        self._commit_current_matrix()
        self._matrices.append(_empty_matrix_mapping())
        self._refresh_matrix_list(len(self._matrices) - 1)

    def _duplicate_matrix(self) -> None:
        """Duplicate the current matrix with provenance tracking."""
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            QMessageBox.information(
                self,
                "No matrix selected",
                "Select a matrix to duplicate.",
            )
            return
        original = self._matrices[self._current_matrix_row]
        original_id = original.get("id", "")
        if not original_id:
            QMessageBox.warning(
                self,
                "Cannot duplicate",
                "Save the matrix with an ID first before duplicating.",
            )
            return
        new_matrix = deepcopy(original)
        new_matrix["id"] = f"{original_id}_edit_{uuid.uuid4().hex[:8]}"
        new_matrix["name"] = f"{original.get('name', '')} (edit copy)"
        if original.get("source") == "calculated":
            new_matrix["source"] = "user_defined"
        provenance = dict(new_matrix.get("provenance", {}))
        provenance["derived_from_matrix_id"] = original_id
        provenance["software_version"] = "flowdesk-gui"
        provenance["manual_edits"] = []
        new_matrix["provenance"] = provenance
        self._manual_source_snapshots[str(new_matrix["id"])] = deepcopy(original)
        self._matrices.append(new_matrix)
        self._refresh_matrix_list(len(self._matrices) - 1)

    def _set_calculated_matrix_editability(self, is_calculated: bool) -> None:
        """Keep a persisted calculation result immutable in the editor."""
        for widget in (
            self._id_edit,
            self._name_edit,
            self._source_combo,
            self._notes_edit,
            self._channels_list,
            self._add_channel_btn,
            self._remove_channel_btn,
            self._heat_map,
        ):
            widget.setEnabled(not is_calculated)

    def _delete_matrix(self) -> None:
        row = self._current_matrix_row
        if row < 0:
            return
        matrix_id = self._matrices[row].get("id", "")
        # Warn if bindings reference this matrix
        referencing = [
            b["id"]
            for b in self._bindings
            if b.get("matrix_id") == matrix_id
        ]
        if referencing:
            QMessageBox.warning(
                self,
                "Matrix in use",
                f"Delete bindings {', '.join(referencing)} first, "
                "then delete the matrix.",
            )
            return
        self._matrices.pop(row)
        self._current_matrix_row = -1
        self._refresh_matrix_list(
            min(max(row - 1, 0), max(len(self._matrices) - 1, 0))
            if self._matrices else 0
        )

    # -- Channel selection ---------------------------------------------------

    def _channel_display_name(self, channel_id: object) -> str:
        """Return the project-facing label for a stable channel ID."""
        target = str(channel_id)
        for channel in self._channels:
            if isinstance(channel, dict):
                candidate_id = channel.get("id", channel.get("name", ""))
                if str(candidate_id) != target:
                    continue
                return str(
                    channel.get("display_name")
                    or channel.get("name")
                    or target
                )
            candidate_id = getattr(channel, "id", getattr(channel, "name", ""))
            if str(candidate_id) != target:
                continue
            return str(
                getattr(channel, "display_name", None)
                or getattr(channel, "short_name", None)
                or getattr(channel, "name", None)
                or target
            )
        return target

    def _channel_label(self, channel_id: object) -> str:
        """Format a readable label while retaining the stable ID for clarity."""
        stable_id = str(channel_id)
        display_name = self._channel_display_name(stable_id)
        if display_name == stable_id:
            return stable_id
        return f"{display_name} [{stable_id}]"

    def _short_channel_label(self, channel_id: object) -> str:
        """Return the compact project label used inside plots and heat maps."""
        return self._channel_display_name(channel_id)

    def _refresh_channels_list(self, selected_ids: list[str]) -> None:
        self._channels_list.clear()
        for channel in self._channels:
            if isinstance(channel, dict):
                ch_id = channel.get("id", channel.get("name", ""))
            else:
                ch_id = getattr(channel, "id", getattr(channel, "name", ""))
            item = QListWidgetItem(self._channel_label(ch_id))
            item.setData(Qt.ItemDataRole.UserRole, ch_id)
            item.setData(Qt.ItemDataRole.CheckStateRole, Qt.CheckState.Checked
                        if ch_id in selected_ids else Qt.CheckState.Unchecked)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self._channels_list.addItem(item)

    def _add_channel(self) -> None:
        """Select all unselected channels."""
        for i in range(self._channels_list.count()):
            item = self._channels_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                item.setCheckState(Qt.CheckState.Checked)

    def _remove_channel(self) -> None:
        """Deselect all selected channels."""
        for i in range(self._channels_list.count()):
            item = self._channels_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                item.setCheckState(Qt.CheckState.Unchecked)

    # -- Heat map ------------------------------------------------------------

    def _update_heat_map(self, matrix_mapping: dict[str, Any]) -> None:
        channels = matrix_mapping.get("channels", [])
        matrix_data = matrix_mapping.get("matrix", [])
        n = len(channels)

        self._heat_map.setRowCount(n)
        self._heat_map.setColumnCount(n)

        for row_idx in range(n):
            label = channels[row_idx] if row_idx < len(channels) else f"R{row_idx}"
            header = QTableWidgetItem(self._short_channel_label(label))
            header.setToolTip(str(label))
            self._heat_map.setVerticalHeaderItem(row_idx, header)
        for col_idx in range(n):
            label = channels[col_idx] if col_idx < len(channels) else f"C{col_idx}"
            header = QTableWidgetItem(self._short_channel_label(label))
            header.setToolTip(str(label))
            self._heat_map.setHorizontalHeaderItem(col_idx, header)

        for row_idx in range(n):
            for col_idx in range(n):
                if row_idx < len(matrix_data) and col_idx < len(matrix_data[row_idx]):
                    value = matrix_data[row_idx][col_idx]
                else:
                    value = 0.0
                item = QTableWidgetItem(f"{value:.4f}")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                clamped_val = value if 0 <= value <= 1 else (
                    value / 10 if value > 0 else 0
                )
                bg = _heatmap_color(clamped_val)
                item.setBackground(bg)
                # Calculated matrices are immutable; cells are read-only.
                if (
                    matrix_mapping.get("source") == "calculated"
                    or row_idx == col_idx
                ):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._heat_map.setItem(row_idx, col_idx, item)
        self._load_coefficient_controls()

    @staticmethod
    def _first_off_diagonal_pair(
        matrix_mapping: dict[str, Any],
    ) -> tuple[str, str] | None:
        channels = [str(value) for value in matrix_mapping.get("channels", [])]
        for receiving_index, receiving in enumerate(channels):
            for source_index, source in enumerate(channels):
                if receiving_index != source_index:
                    return source, receiving
        return None

    def _update_preview_pair_label(self) -> None:
        if self._selected_pair is None:
            self._preview_pair_label.setText(
                "Select an off-diagonal matrix cell to inspect a source → receiving pair."
            )
            return
        source, receiving = self._selected_pair
        self._preview_pair_label.setText(
                f"Source channel (spill from) {self._short_channel_label(source)} → "
                f"Receiving channel (spill into) {self._short_channel_label(receiving)}"
        )

    def _on_heat_map_cell_clicked(self, row: int, column: int) -> None:
        if self._loading or not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        matrix = self._matrices[self._current_matrix_row]
        channels = [str(value) for value in matrix.get("channels", [])]
        if row < 0 or column < 0 or row >= len(channels) or column >= len(channels):
            return
        if row == column:
            self._selected_pair = None
            self._update_preview_pair_label()
            self._diag_label.setText("Diagonal compensation coefficients are fixed at 100%.")
            return
        self._selected_pair = channels[column], channels[row]
        self._update_preview_pair_label()
        self._load_coefficient_controls()
        self._schedule_candidate_preview(preserve_range=False)

    def _on_heat_map_cell_changed(self, _row: int, _column: int) -> None:
        if not self._loading:
            self._load_coefficient_controls()
            self._schedule_candidate_preview()

    def _load_coefficient_controls(self) -> None:
        if self._selected_pair is None:
            self._coefficient_label.setText("No pair selected")
            self._coefficient_spin.setEnabled(False)
            self._coefficient_slider.setEnabled(False)
            self._coefficient_reset_btn.setEnabled(False)
            return
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        matrix = self._matrices[self._current_matrix_row]
        channels = [str(value) for value in matrix.get("channels", [])]
        source, receiving = self._selected_pair
        if source not in channels or receiving not in channels:
            return
        source_index = channels.index(source)
        receiving_index = channels.index(receiving)
        item = self._heat_map.item(receiving_index, source_index)
        if item is None:
            return
        try:
            percent = float(item.text()) * 100.0
        except ValueError:
            return
        self._setting_coefficient = True
        try:
            self._coefficient_label.setText(
                f"{self._short_channel_label(source)} → {self._short_channel_label(receiving)}"
            )
            editable = matrix.get("source") != "calculated"
            self._coefficient_spin.setEnabled(editable)
            self._coefficient_slider.setEnabled(editable)
            self._coefficient_reset_btn.setEnabled(editable)
            self._coefficient_spin.setValue(percent)
            center = round(percent * 1000.0)
            self._coefficient_slider.setRange(center - 5000, center + 5000)
            self._coefficient_slider.setValue(center)
        finally:
            self._setting_coefficient = False

    def _set_selected_coefficient_percent(self, percent: float) -> None:
        if self._setting_coefficient or self._selected_pair is None:
            return
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        matrix = self._matrices[self._current_matrix_row]
        if matrix.get("source") == "calculated":
            return
        channels = [str(value) for value in matrix.get("channels", [])]
        source, receiving = self._selected_pair
        if source not in channels or receiving not in channels:
            return
        item = self._heat_map.item(channels.index(receiving), channels.index(source))
        if item is None:
            return
        self._setting_coefficient = True
        try:
            item.setText(f"{percent / 100.0:.8g}")
        finally:
            self._setting_coefficient = False
        self._schedule_candidate_preview()

    def _on_coefficient_spin_changed(self, value: float) -> None:
        self._set_selected_coefficient_percent(float(value))

    def _on_coefficient_slider_changed(self, value: int) -> None:
        if self._setting_coefficient:
            return
        self._set_selected_coefficient_percent(float(value) / 1000.0)

    def _reset_coefficient(self) -> None:
        if self._selected_pair is None or self._source_matrix_snapshot is None:
            return
        source, receiving = self._selected_pair
        channels = [
            str(value) for value in self._source_matrix_snapshot.get("channels", [])
        ]
        if source not in channels or receiving not in channels:
            return
        value = self._source_matrix_snapshot.get("matrix", [])[channels.index(receiving)][
            channels.index(source)
        ]
        self._set_selected_coefficient_percent(float(value) * 100.0)

    def _schedule_candidate_preview(self, *, preserve_range: bool = True) -> None:
        if not preserve_range:
            self._preview_preserved_view_range = None
        elif self._preview_preserved_view_range is None:
            ranges = self._compensated_plot.view_range()
            if ranges is not None and self._compensated_plot.has_rendered_data():
                self._preview_preserved_view_range = ranges
        if self._selected_pair is None:
            return
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        source_channel = self._selected_pair[0]
        assignment = self._control_assignments.get(source_channel)
        if assignment is not None:
            assigned_sample = str(assignment.get("sample_id", ""))
            assigned_index = self._preview_sample_combo.findData(assigned_sample)
            if assigned_index >= 0:
                self._preview_sample_combo.blockSignals(True)
                self._preview_sample_combo.setCurrentIndex(assigned_index)
                self._preview_sample_combo.blockSignals(False)
        sample_index = self._preview_sample_combo.currentIndex()
        if sample_index < 0:
            return
        sample_id = str(self._preview_sample_combo.itemData(sample_index) or "")
        if sample_id == "(no data available)":
            return
        sample_info = self._sample_data.get(sample_id)
        if sample_info is None:
            return
        self._commit_current_matrix()
        mapping = self._matrices[self._current_matrix_row]
        try:
            candidate = CompensationMatrixSpec(**mapping)
        except (TypeError, ValueError) as exc:
            self._diag_label.setText(f"Preview waiting for valid matrix: {exc}")
            return
        events = np.asarray(sample_info.get("events"), dtype=np.float64)
        channel_ids = tuple(str(value) for value in sample_info.get("channel_ids", ()))
        population_mask = np.asarray(
            sample_info.get("masks", {}).get(
                str(self._preview_population_combo.currentData() or "all_events"),
                sample_info.get(
                    "population_mask", np.ones(len(events), dtype=np.bool_)
                ),
            ),
            dtype=np.bool_,
        )
        positive_mask = None
        negative_mask = None
        masks = sample_info.get("masks", {})
        if assignment is not None and isinstance(masks, dict):
            positive_mask = masks.get(str(assignment.get("positive_population_id", "")))
            negative_mask = masks.get(str(assignment.get("negative_population_id", "")))
            if positive_mask is not None and negative_mask is not None:
                positive_mask = np.asarray(positive_mask, dtype=np.bool_)
                negative_mask = np.asarray(negative_mask, dtype=np.bool_)
                population_mask = population_mask & (positive_mask | negative_mask)
        self._preview_revision += 1
        request = CompensationPreviewRequest(
            revision=self._preview_revision,
            sample_id=sample_id,
            events=events,
            channel_ids=channel_ids,
            population_mask=population_mask,
            candidate_matrix=candidate,
            source_matrix=(
                CompensationMatrixSpec(**self._source_matrix_snapshot)
                if self._source_matrix_snapshot is not None
                else None
            ),
            source_channel_id=self._selected_pair[0],
            receiving_channel_id=self._selected_pair[1],
            positive_mask=positive_mask if positive_mask is not None else (
                np.asarray(sample_info["positive_mask"], dtype=np.bool_)
                if sample_info.get("positive_mask") is not None else None
            ),
            negative_mask=negative_mask if negative_mask is not None else (
                np.asarray(sample_info["negative_mask"], dtype=np.bool_)
                if sample_info.get("negative_mask") is not None else None
            ),
            outlier_policy=str(sample_info.get("outlier_policy", "none")),
            display_max_points=20_000,
        )
        self._diag_label.setText(
            f"Preview pending (revision {request.revision})"
        )
        self._preview_scheduler.schedule(request)

    def _on_candidate_preview_ready(
        self,
        request: CompensationPreviewRequest,
        result: CompensationPreviewResult,
    ) -> None:
        if request.revision != self._preview_revision:
            return
        source_label = self._short_channel_label(result.source_channel_id)
        receiving_label = self._short_channel_label(result.receiving_channel_id)
        self._apply_preview_axis_transforms()
        self._compensated_plot.plot_events(
            result.compensated_x,
            result.compensated_y,
            x_label=source_label,
            y_label=receiving_label,
        )
        self._compensated_plot.set_presentation(
            {"title": "Compensated candidate", "background_color": "#ffffff"}
        )
        if self._preview_preserved_view_range is None:
            self._apply_shared_preview_range(result.axis_limits)
        else:
            self._apply_preserved_preview_range(self._preview_preserved_view_range)
        diagnostic = result.diagnostics[0] if result.diagnostics else None
        if diagnostic is None:
            self._diag_label.setText(
                f"Preview ready (revision {result.revision}); no pair diagnostic."
            )
            return
        details = []
        if diagnostic.automatic_coefficient is not None:
            details.append(
                f"source={diagnostic.automatic_coefficient * 100:.6g}%"
            )
        details.append(f"candidate={diagnostic.candidate_coefficient * 100:.6g}%")
        if diagnostic.coefficient_difference is not None:
            details.append(
                f"difference={diagnostic.coefficient_difference * 100:+.6g}pp"
            )
        if diagnostic.residual_slope is not None:
            details.append(f"residual slope={diagnostic.residual_slope:.5g}")
        if diagnostic.correlation is not None:
            details.append(f"r={diagnostic.correlation:.5g}")
        if diagnostic.receiving_median_difference is not None:
            details.append(
                f"receiving median difference={diagnostic.receiving_median_difference:.5g}"
            )
        details.append(
            f"control events={diagnostic.included_event_count}"
            f" (+{diagnostic.positive_event_count}/-{diagnostic.negative_event_count})"
        )
        if diagnostic.excluded_event_count:
            details.append(f"excluded={diagnostic.excluded_event_count}")
        if diagnostic.condition_number is not None:
            details.append(f"condition={diagnostic.condition_number:.5g}")
        if diagnostic.undefined_reasons:
            details.append("undefined=" + ",".join(diagnostic.undefined_reasons))
        self._diag_label.setText(
            f"Preview ready (revision {result.revision}); "
            f"events={result.population_event_count}; "
            + "; ".join(details)
        )

    def _apply_shared_preview_range(
        self,
        axis_limits: tuple[float, float, float, float] | None,
    ) -> None:
        """Apply one canonical X/Y range to the compensated preview plot.

        The core preview computes this range from the candidate preview data.
        Never let PlotWidget auto-range independently after a coefficient update.
        """
        if axis_limits is None:
            return
        x_min, x_max, y_min, y_max = axis_limits
        self._compensated_plot.set_manual_view_range(
            (x_min, x_max), (y_min, y_max)
        )

    def _apply_preserved_preview_range(
        self,
        view_range: tuple[tuple[float, float], tuple[float, float]],
    ) -> None:
        """Restore the user's current ViewBox range after coefficient edits."""
        view_box = self._compensated_plot._view_box()
        if view_box is not None:
            view_box.setRange(
                xRange=view_range[0], yRange=view_range[1], padding=0
            )

    def _on_candidate_preview_failed(
        self,
        request: CompensationPreviewRequest,
        error: Exception,
    ) -> None:
        if request.revision != self._preview_revision:
            return
        self._diag_label.setText(
            f"Preview failed for revision {request.revision}: {error}"
        )

    # -- Matrix commit -------------------------------------------------------

    def _commit_current_matrix(self) -> None:
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        original = self._matrices[self._current_matrix_row]
        if original.get("source") == "calculated":
            return
        selected_channels = [
            str(self._channels_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self._channels_list.count())
            if self._channels_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        original["id"] = self._id_edit.text().strip()
        original["name"] = self._name_edit.text().strip()
        original["source"] = self._source_combo.currentText()
        original["notes"] = self._notes_edit.text().strip()
        original["channels"] = selected_channels

        # Rebuild matrix from heat map if channels changed size
        n = len(selected_channels)
        current_matrix = original.get("matrix", [])
        if len(current_matrix) != n:
            new_matrix: list[list[float]] = []
            for _r in range(n):
                row_vals = [1.0 if _r == c else 0.0 for c in range(n)]
                new_matrix.append(row_vals)
            original["matrix"] = new_matrix
            # Rebuild heat map items for new size
            self._update_heat_map(original)
        else:
            # Sync heat map text back to matrix data
            new_matrix = []
            for r in range(n):
                row_vals = []
                for c in range(n):
                    item = self._heat_map.item(r, c)
                    if item is not None:
                        try:
                            row_vals.append(float(item.text()))
                        except ValueError:
                            row_vals.append(0.0)
                    else:
                        row_vals.append(0.0)
                new_matrix.append(row_vals)
            original["matrix"] = new_matrix

        source = self._source_matrix_snapshot
        if (
            source is not None
            and str(source.get("id", "")) != str(original.get("id", ""))
        ):
            old_channels = [str(value) for value in source.get("channels", [])]
            old_matrix = source.get("matrix", [])
            new_channels = [str(value) for value in original.get("channels", [])]
            edits: list[dict[str, Any]] = []
            for old_row, row_channel in enumerate(old_channels):
                for old_column, column_channel in enumerate(old_channels):
                    if row_channel not in new_channels or column_channel not in new_channels:
                        continue
                    new_row = new_channels.index(row_channel)
                    new_column = new_channels.index(column_channel)
                    if old_row >= len(old_matrix) or old_column >= len(old_matrix[old_row]):
                        continue
                    old_value = float(old_matrix[old_row][old_column])
                    new_value = float(original["matrix"][new_row][new_column])
                    if old_value == new_value:
                        continue
                    edits.append({
                        "row_channel_id": row_channel,
                        "column_channel_id": column_channel,
                        "old_value": old_value,
                        "new_value": new_value,
                        "edited_at": datetime.now(UTC).isoformat(),
                        "edited_by": "flowdesk-gui",
                        "reason": "interactive compensation preview adjustment",
                    })
            if edits:
                provenance = dict(original.get("provenance", {}))
                provenance["derived_from_matrix_id"] = str(source.get("id", ""))
                provenance["manual_edits"] = edits
                original["provenance"] = provenance

    # -- Validation ----------------------------------------------------------

    def _validate_current(self) -> bool:
        self._commit_current_matrix()
        if self._current_matrix_row < 0 or self._current_matrix_row >= len(self._matrices):
            self._diag_label.setText("No matrix selected")
            return False
        try:
            spec = CompensationMatrixSpec(**self._matrices[self._current_matrix_row])
            channel_ids = [
                ch["id"] if isinstance(ch, dict) else getattr(ch, "id", "")
                for ch in self._channels
            ]
            result = inspect_compensation_matrix(spec, channel_ids)
            if result.is_valid:
                cond = result.condition_number
                if cond is not None:
                    self._diag_label.setText(
                        f"Valid. Condition number: {cond:.4g}"
                    )
                else:
                    self._diag_label.setText("Valid")
                return True
            else:
                error_msgs = [
                    d.message for d in result.diagnostics if d.severity == "error"
                ]
                self._diag_label.setText("; ".join(error_msgs))
                return False
        except (ValueError, TypeError) as exc:
            self._diag_label.setText(str(exc))
            return False

    # -- Binding list --------------------------------------------------------

    def _refresh_binding_list(self, selected_row: int) -> None:
        self._loading = True
        try:
            self._binding_list.clear()
            for binding in self._bindings:
                matrix_id = binding.get("matrix_id", "")
                scope = binding.get("scope", "")
                target = binding.get("target_id", "")
                self._binding_list.addItem(
                    f"{matrix_id} -> {scope}:{target}"
                )
            if self._bindings:
                self._binding_list.setCurrentRow(
                    min(max(selected_row, 0), len(self._bindings) - 1)
                )
        finally:
            self._loading = False
        if self._bindings:
            self._load_binding_row(self._binding_list.currentRow())

    def _load_binding_row(self, row: int) -> None:
        if row < 0 or row >= len(self._bindings):
            return
        self._loading = True
        try:
            self._current_binding_row = row
            value = self._bindings[row]
            self._b_id_edit.setText(str(value.get("id", "")))
            matrix_id = value.get("matrix_id", "")
            idx = self._b_matrix_combo.findData(matrix_id)
            if idx >= 0:
                self._b_matrix_combo.setCurrentIndex(idx)
            self._b_scope_combo.setCurrentText(str(value.get("scope", "sample")))
            self._b_target_edit.setText(str(value.get("target_id", "")))
            self._b_notes_edit.setText(str(value.get("notes", "")))
        finally:
            self._loading = False

    def _on_binding_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._commit_current_binding()
        self._load_binding_row(row)

    def _add_binding(self) -> None:
        self._commit_current_binding()
        self._bindings.append(_empty_binding_mapping())
        self._refresh_binding_list(len(self._bindings) - 1)

    def _delete_binding(self) -> None:
        row = self._current_binding_row
        if row < 0:
            return
        self._bindings.pop(row)
        self._current_binding_row = -1
        if self._bindings:
            self._refresh_binding_list(
                min(max(row - 1, 0), len(self._bindings) - 1)
            )

    def _commit_current_binding(self) -> None:
        if not (0 <= self._current_binding_row < len(self._bindings)):
            return
        original = self._bindings[self._current_binding_row]
        original["id"] = self._b_id_edit.text().strip()
        original["matrix_id"] = str(self._b_matrix_combo.currentData() or "")
        original["scope"] = self._b_scope_combo.currentText()
        original["target_id"] = self._b_target_edit.text().strip()
        original["notes"] = self._b_notes_edit.text().strip()

    # -- Accept --------------------------------------------------------------

    def _accept_if_valid(self) -> None:
        try:
            self._commit_current_matrix()
            self._commit_current_binding()
            self._validate_all_matrices()
            self._validate_all_bindings()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid compensation", str(exc))
            return
        self.accept()

    def _validate_all_matrices(self) -> None:
        ids: set[str] = set()
        for mapping in self._matrices:
            spec = CompensationMatrixSpec(**mapping)
            if not spec.id:
                raise ValueError("Every matrix must have a non-empty ID")
            if spec.id in ids:
                raise ValueError(f"Duplicate matrix ID: {spec.id}")
            ids.add(spec.id)
            channel_ids = [
                ch["id"] if isinstance(ch, dict) else getattr(ch, "id", "")
                for ch in self._channels
            ]
            inspect_compensation_matrix(spec, channel_ids)

    def _validate_all_bindings(self) -> None:
        matrix_ids = {m["id"] for m in self._matrices if m.get("id")}
        binding_ids: set[str] = set()
        scope_targets: set[tuple[str, str]] = set()
        for mapping in self._bindings:
            spec = CompensationBindingSpec(**mapping)
            if not spec.id:
                raise ValueError("Every binding must have a non-empty ID")
            if spec.id in binding_ids:
                raise ValueError(f"Duplicate binding ID: {spec.id}")
            binding_ids.add(spec.id)
            if spec.matrix_id not in matrix_ids:
                raise ValueError(
                    f"Binding {spec.id} references unknown matrix: {spec.matrix_id}"
                )
            key = (spec.scope, spec.target_id)
            if key in scope_targets:
                raise ValueError(
                    f"Duplicate binding scope+target: {spec.scope} -> {spec.target_id}"
                )
            scope_targets.add(key)


# ---------------------------------------------------------------------------
# Empty factory for calculations
# ---------------------------------------------------------------------------


def _empty_calculation_mapping() -> dict[str, Any]:
    """Return a minimal compensation calculation mapping ready for editing."""
    return {
        "id": "",
        "name": "",
        "controls": [],
        "regression_method": "linear",
        "outlier_policy": "iqr",
        "minimum_positive_events": 100,
        "minimum_negative_events": 50,
        "created_by": None,
        "created_at": None,
        "notes": "",
    }


def _empty_control_mapping() -> dict[str, Any]:
    """Return a minimal control assignment mapping."""
    return {
        "detector_channel_id": "",
        "positive_population_id": "",
        "negative_population_id": "",
        "sample_id": "",
    }


# ---------------------------------------------------------------------------
# CompensationCalculationEditorDialog
# ---------------------------------------------------------------------------


class CompensationCalculationEditorDialog(QDialog):
    """Edit compensation calculation specs (detector × control assignments).

    Provides:
    - A list of compensation calculation definitions (add/edit/delete).
    - A detector × control assignment table where each row is a
      ``CompensationCalculationControlSpec``.
    - Global settings per calculation: regression_method, outlier_policy,
      minimum_positive/negative_events.
    """

    def __init__(
        self,
        calculations: Sequence[dict[str, Any]],
        available_channels: Sequence[dict[str, Any]],
        population_ids: Sequence[str],
        sample_ids: Sequence[str],
        *,
        sample_data: dict[str, dict[str, Any]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("compensationCalculationEditorDialog")
        self.setWindowTitle("Compensation Calculations")
        self.resize(900, 600)

        self._calculations = deepcopy(list(calculations))
        self._channels = tuple(available_channels)
        self._population_ids = tuple(population_ids)
        self._sample_ids = tuple(sample_ids)
        self._sample_data = sample_data or {}
        self._loading = False
        self._current_calc_row = -1
        self._calculation_result: CompensationCalculationResult | None = None
        self._calculation_result_definition: dict[str, Any] | None = None

        self._channel_ids = [
            ch.get("id", ch.get("name", "")) if isinstance(ch, dict)
            else getattr(ch, "id", getattr(ch, "name", ""))
            for ch in self._channels
        ]

        self._build_ui()

        if not self._calculations:
            self._calculations.append(_empty_calculation_mapping())
        self._refresh_calc_list(0)

    # -- Public API ----------------------------------------------------------

    def calculations(self) -> list[dict[str, Any]]:
        """Return a deep copy of the current calculation definitions."""
        self._commit_current_calculation()
        return deepcopy(self._calculations)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left side: calculation list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)

        calc_group = QGroupBox("Calculations")
        calc_layout = QVBoxLayout(calc_group)
        self._calc_list = QListWidget()
        self._calc_list.setObjectName("compensationCalculationList")
        calc_layout.addWidget(self._calc_list)

        calc_btns = QHBoxLayout()
        self._new_calc_btn = QPushButton("New")
        self._new_calc_btn.setObjectName("compensationNewCalcButton")
        self._delete_calc_btn = QPushButton("Delete")
        self._delete_calc_btn.setObjectName("compensationDeleteCalcButton")
        calc_btns.addWidget(self._new_calc_btn)
        calc_btns.addWidget(self._delete_calc_btn)
        calc_layout.addLayout(calc_btns)
        left_layout.addWidget(calc_group)
        left_layout.addStretch(1)

        splitter.addWidget(left)

        # --- Right side: form + control table ---
        right = QWidget()
        right_layout = QVBoxLayout(right)

        form = QFormLayout()
        self._id_edit = QLineEdit()
        self._id_edit.setObjectName("compensationCalcIdEdit")
        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("compensationCalcNameEdit")
        self._regression_combo = QComboBox()
        self._regression_combo.setObjectName("compensationCalcRegressionCombo")
        self._regression_combo.addItems(["linear", "median"])
        self._outlier_combo = QComboBox()
        self._outlier_combo.setObjectName("compensationCalcOutlierCombo")
        self._outlier_combo.addItems(["iqr", "zscore", "none"])
        self._min_pos_edit = QLineEdit("100")
        self._min_pos_edit.setObjectName("compensationCalcMinPosEdit")
        self._min_neg_edit = QLineEdit("50")
        self._min_neg_edit.setObjectName("compensationCalcMinNegEdit")
        self._notes_edit = QLineEdit()
        self._notes_edit.setObjectName("compensationCalcNotesEdit")

        form.addRow("Calculation ID:", self._id_edit)
        form.addRow("Name:", self._name_edit)
        form.addRow("Regression:", self._regression_combo)
        form.addRow("Outlier Policy:", self._outlier_combo)
        form.addRow("Min Positive Events:", self._min_pos_edit)
        form.addRow("Min Negative Events:", self._min_neg_edit)
        form.addRow("Notes:", self._notes_edit)
        right_layout.addLayout(form)

        # --- Control assignment table ---
        ctrl_group = QGroupBox("Detector × Control Assignments")
        ctrl_layout = QVBoxLayout(ctrl_group)

        self._control_table = QTableWidget()
        self._control_table.setObjectName("compensationControlTable")
        self._control_table.setColumnCount(4)
        self._control_table.setHorizontalHeaderLabels([
            "Detector Channel",
            "Control Sample",
            "Positive Population",
            "Negative Population",
        ])
        self._control_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        ctrl_layout.addWidget(self._control_table)

        table_btns = QHBoxLayout()
        self._add_ctrl_btn = QPushButton("Add Control")
        self._add_ctrl_btn.setObjectName("compensationAddControlButton")
        self._delete_ctrl_btn = QPushButton("Delete Control")
        self._delete_ctrl_btn.setObjectName("compensationDeleteControlButton")
        table_btns.addWidget(self._add_ctrl_btn)
        table_btns.addWidget(self._delete_ctrl_btn)
        table_btns.addStretch(1)
        ctrl_layout.addLayout(table_btns)
        right_layout.addWidget(ctrl_group)

        # Calculation button
        calc_btn_row = QHBoxLayout()
        self._calc_run_btn = QPushButton("Run Calculation")
        self._calc_run_btn.setObjectName("compensationCalcRunButton")
        self._calc_save_btn = QPushButton("Save Matrix")
        self._calc_save_btn.setObjectName("compensationCalcSaveButton")
        calc_btn_row.addWidget(self._calc_run_btn)
        calc_btn_row.addWidget(self._calc_save_btn)
        calc_btn_row.addStretch(1)
        right_layout.addLayout(calc_btn_row)

        # Calculation diagnostics panel
        diag_group = QGroupBox("Calculation Diagnostics")
        diag_layout = QVBoxLayout(diag_group)

        self._diag_table = QTableWidget()
        self._diag_table.setObjectName("compensationCalcDiagnosticTable")
        self._diag_table.setColumnCount(8)
        self._diag_table.setHorizontalHeaderLabels([
            "Detector",
            "Pos Events",
            "Neg Events",
            "Median Pos",
            "Median Neg",
            "Slope (Self)",
            "Residual RMS",
            "Outliers",
        ])
        self._diag_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        diag_layout.addWidget(self._diag_table)

        self._cond_label = QLabel("Condition number: —")
        self._cond_label.setObjectName("compensationCalcConditionLabel")
        diag_layout.addWidget(self._cond_label)

        right_layout.addWidget(diag_group)

        # Validation label
        self._diag_label = QLabel("Not validated")
        self._diag_label.setObjectName("compensationCalcDiagnosticLabel")
        self._diag_label.setWordWrap(True)
        right_layout.addWidget(self._diag_label)

        right_layout.addStretch(1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("compensationCalcDialogButtons")
        outer.addWidget(buttons)

        # --- Signal connections ---
        self._calc_list.currentRowChanged.connect(self._on_calc_row_changed)
        self._new_calc_btn.clicked.connect(self._add_calculation)
        self._delete_calc_btn.clicked.connect(self._delete_calculation)
        self._add_ctrl_btn.clicked.connect(self._add_control)
        self._delete_ctrl_btn.clicked.connect(self._delete_control)
        self._calc_run_btn.clicked.connect(self._on_run_calculation)
        self._calc_save_btn.clicked.connect(self._on_save_matrix)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

    # -- Calculation list ----------------------------------------------------

    def _refresh_calc_list(self, selected_row: int) -> None:
        self._loading = True
        try:
            self._calc_list.clear()
            for calc in self._calculations:
                name = calc.get("name") or calc.get("id") or "New calculation"
                n_ctrl = len(calc.get("controls", []))
                self._calc_list.addItem(f"{name} ({n_ctrl} controls)")
            if self._calculations:
                self._calc_list.setCurrentRow(
                    min(max(selected_row, 0), len(self._calculations) - 1)
                )
        finally:
            self._loading = False
        if self._calculations:
            self._load_calc_row(self._calc_list.currentRow())
        else:
            self._clear_calc_fields()

    def _load_calc_row(self, row: int) -> None:
        if row < 0 or row >= len(self._calculations):
            return
        self._loading = True
        try:
            self._calculation_result = None
            self._calculation_result_definition = None
            self._current_calc_row = row
            value = self._calculations[row]
            self._id_edit.setText(str(value.get("id", "")))
            self._name_edit.setText(str(value.get("name", "")))
            self._regression_combo.setCurrentText(
                str(value.get("regression_method", "linear"))
            )
            self._outlier_combo.setCurrentText(
                str(value.get("outlier_policy", "iqr"))
            )
            self._min_pos_edit.setText(
                str(value.get("minimum_positive_events", 100))
            )
            self._min_neg_edit.setText(
                str(value.get("minimum_negative_events", 50))
            )
            self._notes_edit.setText(str(value.get("notes", "")))
            self._update_control_table(value.get("controls", []))
            self._diag_label.setText("Not validated")
        finally:
            self._loading = False

    def _clear_calc_fields(self) -> None:
        self._loading = True
        try:
            self._current_calc_row = -1
            self._id_edit.clear()
            self._name_edit.clear()
            self._regression_combo.setCurrentIndex(0)
            self._outlier_combo.setCurrentIndex(0)
            self._min_pos_edit.setText("100")
            self._min_neg_edit.setText("50")
            self._notes_edit.clear()
            self._control_table.setRowCount(0)
            self._diag_label.setText("No calculation selected")
        finally:
            self._loading = False

    def _on_calc_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._commit_current_calculation()
        self._load_calc_row(row)

    def _add_calculation(self) -> None:
        self._commit_current_calculation()
        self._calculation_result = None
        self._calculation_result_definition = None
        self._calculations.append(_empty_calculation_mapping())
        self._refresh_calc_list(len(self._calculations) - 1)

    def _delete_calculation(self) -> None:
        row = self._current_calc_row
        if row < 0:
            return
        self._calculation_result = None
        self._calculation_result_definition = None
        self._calculations.pop(row)
        self._current_calc_row = -1
        if self._calculations:
            self._refresh_calc_list(
                min(max(row - 1, 0), len(self._calculations) - 1)
            )
        else:
            self._refresh_calc_list(0)

    # -- Control table -------------------------------------------------------

    def _channel_label(self, channel_id: object) -> str:
        """Show a readable channel label while retaining stable ID in data."""
        target = str(channel_id)
        for channel in self._channels:
            if isinstance(channel, dict):
                value = channel.get("id", channel.get("name", ""))
                if str(value) != target:
                    continue
                display = channel.get("display_name") or channel.get("name") or target
            else:
                value = getattr(channel, "id", getattr(channel, "name", ""))
                if str(value) != target:
                    continue
                display = (
                    getattr(channel, "display_name", None)
                    or getattr(channel, "short_name", None)
                    or getattr(channel, "name", None)
                    or target
                )
            return target if str(display) == target else f"{display} [{target}]"
        return target

    def _update_control_table(self, controls: list[dict[str, Any]]) -> None:
        self._loading = True
        try:
            self._control_table.setRowCount(len(controls))
            for row_idx, ctrl in enumerate(controls):
                self._set_control_row(row_idx, ctrl)
        finally:
            self._loading = False

    def _set_control_row(self, row_idx: int, ctrl: dict[str, Any]) -> None:
        det_combo = QComboBox()
        for channel_id in self._channel_ids:
            det_combo.addItem(self._channel_label(channel_id), channel_id)
        detector_id = str(ctrl.get("detector_channel_id", ""))
        detector_index = det_combo.findData(detector_id)
        if detector_index >= 0:
            det_combo.setCurrentIndex(detector_index)
        self._control_table.setCellWidget(row_idx, 0, det_combo)

        sample_combo = QComboBox()
        sample_combo.addItems(list(self._sample_ids))
        sample_combo.setCurrentText(str(ctrl.get("sample_id", "")))
        self._control_table.setCellWidget(row_idx, 1, sample_combo)

        pos_combo = QComboBox()
        pos_combo.addItems(list(self._population_ids))
        pos_combo.setCurrentText(str(ctrl.get("positive_population_id", "")))
        self._control_table.setCellWidget(row_idx, 2, pos_combo)

        neg_combo = QComboBox()
        neg_combo.addItems(list(self._population_ids))
        neg_combo.setCurrentText(str(ctrl.get("negative_population_id", "")))
        self._control_table.setCellWidget(row_idx, 3, neg_combo)

    def _read_control_row(self, row_idx: int) -> dict[str, Any]:
        result = {}
        for col, key in [
            (0, "detector_channel_id"),
            (1, "sample_id"),
            (2, "positive_population_id"),
            (3, "negative_population_id"),
        ]:
            widget = self._control_table.cellWidget(row_idx, col)
            if isinstance(widget, QComboBox):
                result[key] = (
                    widget.currentData()
                    if col == 0 else widget.currentText()
                ) or ""
            else:
                result[key] = ""
        return result

    def _add_control(self) -> None:
        current_count = self._control_table.rowCount()
        self._control_table.setRowCount(current_count + 1)
        self._set_control_row(current_count, _empty_control_mapping())
        self._control_table.setCurrentCell(current_count, 0)

    def _delete_control(self) -> None:
        current_row = self._control_table.currentRow()
        if current_row < 0:
            return
        self._control_table.removeRow(current_row)

    # -- Commit --------------------------------------------------------------

    def _commit_current_calculation(self) -> None:
        if not (0 <= self._current_calc_row < len(self._calculations)):
            return
        original = self._calculations[self._current_calc_row]
        original["id"] = self._id_edit.text().strip()
        original["name"] = self._name_edit.text().strip()
        original["regression_method"] = self._regression_combo.currentText()
        original["outlier_policy"] = self._outlier_combo.currentText()
        try:
            original["minimum_positive_events"] = int(self._min_pos_edit.text())
        except ValueError:
            original["minimum_positive_events"] = 100
        try:
            original["minimum_negative_events"] = int(self._min_neg_edit.text())
        except ValueError:
            original["minimum_negative_events"] = 50
        original["notes"] = self._notes_edit.text().strip()

        controls = []
        for row_idx in range(self._control_table.rowCount()):
            controls.append(self._read_control_row(row_idx))
        original["controls"] = controls
        if (
            self._calculation_result is not None
            and self._calculation_result_definition is not None
            and original != self._calculation_result_definition
        ):
            self._calculation_result = None
            self._calculation_result_definition = None
            self._diag_label.setText(
                "Calculation inputs changed; run calculation again."
            )

    # -- Validation & accept -------------------------------------------------

    def _accept_if_valid(self) -> None:
        try:
            self._commit_current_calculation()
            self._validate_all()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid calculation", str(exc))
            return
        self.accept()

    def _validate_all(self) -> None:
        ids: set[str] = set()
        for mapping in self._calculations:
            # The editor starts with a blank draft row.  It is a UI affordance,
            # not a persisted calculation definition, and may remain blank when
            # the user only reviews matrices in the unified workspace.
            if not str(mapping.get("id", "")).strip() and not mapping.get("controls"):
                continue
            try:
                spec = CompensationCalculationSpec(**mapping)
            except ValueError as exc:
                calc_id = mapping.get("id", "(unnamed)")
                raise ValueError(
                    f"Validation failed for '{calc_id}': {exc}"
                ) from exc
            if spec.id in ids:
                raise ValueError(f"Duplicate calculation ID: {spec.id}")
            ids.add(spec.id)

    # -- Public API for calculation results ----------------------------------

    def calculation_result(
        self,
    ) -> CompensationCalculationResult | None:
        """Return the most recent calculation result, or None."""
        return self._calculation_result

    def calculated_matrix(self) -> dict[str, Any] | None:
        """Return the calculated matrix as a serializable mapping, or None."""
        if self._calculation_result is None:
            return None
        spec = self._calculation_result.matrix_spec
        return {
            "id": spec.id,
            "name": spec.name,
            "source": spec.source,
            "channels": list(spec.channels),
            "matrix": [list(row) for row in spec.matrix],
            "created_by": spec.created_by,
            "created_at": spec.created_at,
            "notes": spec.notes,
            "provenance": {
                "source_sample_id": spec.provenance.source_sample_id,
                "source_metadata_key": spec.provenance.source_metadata_key,
                "control_sample_ids": list(spec.provenance.control_sample_ids),
                "control_population_ids": list(
                    spec.provenance.control_population_ids,
                ),
                "algorithm": spec.provenance.algorithm,
                "algorithm_version": spec.provenance.algorithm_version,
                "software_version": spec.provenance.software_version,
                "derived_from_matrix_id": spec.provenance.derived_from_matrix_id,
                "manual_edits": [],
            },
        }

    # -- Run calculation -----------------------------------------------------

    def _on_run_calculation(self) -> None:
        """Run the compensation calculation using core and display diagnostics.

        This delegates all computation to ``calculate_spillover_matrix``.
        The GUI only collects the inputs from the current calculation spec
        and displays the structured diagnostics.
        """
        self._commit_current_calculation()
        if self._current_calc_row < 0 or self._current_calc_row >= len(
            self._calculations
        ):
            self._diag_label.setText("No calculation selected")
            return

        mapping = self._calculations[self._current_calc_row]
        try:
            spec = CompensationCalculationSpec(**mapping)
        except ValueError as exc:
            self._diag_label.setText(f"Invalid spec: {exc}")
            return

        detector_ids = tuple(
            c.detector_channel_id for c in spec.controls
        )
        channel_ids = list(self._channel_ids)
        if not set(detector_ids).issubset(set(channel_ids)):
            missing = sorted(set(detector_ids) - set(channel_ids))
            self._diag_label.setText(
                f"Detector channels not in sample data: {', '.join(missing)}"
            )
            return

        # Build events/masks keyed by sample ID.
        events_by_sample: dict[str, Any] = {}
        masks_by_sample: dict[str, dict[str, Any]] = {}
        for ctrl in spec.controls:
            sid = ctrl.sample_id
            if sid not in events_by_sample and sid in self._sample_data:
                sd = self._sample_data[sid]
                events_by_sample[sid] = sd["events"]
                masks_by_sample[sid] = sd.get("masks", {})

        if not events_by_sample:
            self._diag_label.setText(
                "No sample data available for calculation. "
                "Ensure sample_data is provided."
            )
            return

        # Build population masks mapping: sample_id -> {pop_id: mask}
        population_masks: dict[str, dict[str, Any]] = {}
        for sid, ctrl_masks in masks_by_sample.items():
            population_masks[sid] = dict(ctrl_masks)

        # Verify all referenced populations exist.
        for ctrl in spec.controls:
            sid = ctrl.sample_id
            ctrl_masks = population_masks.get(sid, {})
            if ctrl.positive_population_id not in ctrl_masks:
                self._diag_label.setText(
                    f"Positive population {ctrl.positive_population_id!r} "
                    f"not found in sample {sid!r}"
                )
                return
            if ctrl.negative_population_id not in ctrl_masks:
                self._diag_label.setText(
                    f"Negative population {ctrl.negative_population_id!r} "
                    f"not found in sample {sid!r}"
                )
                return

        try:
            result = calculate_spillover_matrix(
                spec,
                events_by_sample,
                {sid: channel_ids for sid in events_by_sample},
                population_masks,
            )
            self._calculation_result = result
            self._calculation_result_definition = deepcopy(mapping)
            self._update_diagnostic_panel(result)
            self._diag_label.setText(
                f"Calculation successful (condition={result.condition_number:.4g})"
            )
        except Exception as exc:
            self._calculation_result = None
            self._diag_label.setText(f"Calculation failed: {exc}")

    def _on_save_matrix(self) -> None:
        """Accept the dialog to save the calculated immutable matrix.

        The calculated matrix is returned via ``calculated_matrix()`` and
        must be saved by the caller.  Editing a calculated matrix directly
        is not allowed; the caller should use ``Duplicate`` to create an
        editable copy with ``derived_from_matrix_id`` provenance.
        """
        if self._calculation_result is None:
            QMessageBox.warning(
                self,
                "No calculation result",
                "Run the calculation first before saving the matrix.",
            )
            return
        self.accept()

    def _update_diagnostic_panel(
        self, result: CompensationCalculationResult
    ) -> None:
        """Populate the diagnostic table from a calculation result."""
        diags = result.channel_diagnostics
        self._diag_table.setRowCount(len(diags))
        for row_idx, diag in enumerate(diags):
            self._diag_table.setItem(
                row_idx, 0, QTableWidgetItem(
                    self._channel_label(diag.detector_channel_id)
                )
            )
            self._diag_table.setItem(
                row_idx, 1, QTableWidgetItem(
                    f"{diag.positive_event_count}"
                )
            )
            self._diag_table.setItem(
                row_idx, 2, QTableWidgetItem(
                    f"{diag.negative_event_count}"
                )
            )
            self._diag_table.setItem(
                row_idx, 3, QTableWidgetItem(
                    f"{diag.median_positive:.4f}"
                )
            )
            self._diag_table.setItem(
                row_idx, 4, QTableWidgetItem(
                    f"{diag.median_negative:.4f}"
                )
            )
            # Slope (self) is the diagonal element (reference detector coefficient)
            spillover = diag.spillover_row
            self_slope = spillover[
                list(d.detector_channel_id for d in diags
                     ).index(diag.detector_channel_id)
            ] if spillover else 0.0
            self._diag_table.setItem(
                row_idx, 5, QTableWidgetItem(
                    f"{self_slope:.6f}"
                )
            )
            residual_str = (
                f"{diag.residual_rms:.6f}"
                if diag.residual_rms is not None
                else "—"
            )
            self._diag_table.setItem(
                row_idx, 6, QTableWidgetItem(residual_str)
            )
            self._diag_table.setItem(
                row_idx, 7, QTableWidgetItem(
                    f"{diag.outlier_count}"
                )
            )

        self._cond_label.setText(
            f"Condition number: {result.condition_number:.4g}"
        )
