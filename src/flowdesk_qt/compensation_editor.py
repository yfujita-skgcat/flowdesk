"""Qt editor for compensation matrices and bindings.

Provides a matrix list, heat-map preview, duplicate-before-edit workflow,
and binding management.  Follows the same list+form pattern as
``TransformEditorDialog`` and ``DerivedParameterEditorDialog``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.compensation import (
    apply_compensation,
    inspect_compensation_matrix,
)
from flowdesk_core.models import (
    CompensationBindingSpec,
    CompensationMatrixSpec,
)

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
        self.resize(960, 660)

        self._matrices = deepcopy(list(matrices))
        self._bindings = deepcopy(list(bindings))
        self._channels = tuple(available_channels)
        self._sample_ids = tuple(sample_ids)
        self._group_ids = tuple(group_ids)
        self._sample_data = sample_data or {}
        self._loading = False
        self._current_matrix_row = -1
        self._current_binding_row = -1

        self._build_ui()

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

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left side: matrix list + binding list ---
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
        self._duplicate_matrix_btn = QPushButton("Duplicate")
        self._duplicate_matrix_btn.setObjectName("compensationDuplicateMatrixButton")
        self._delete_matrix_btn = QPushButton("Delete")
        self._delete_matrix_btn.setObjectName("compensationDeleteMatrixButton")
        matrix_btns.addWidget(self._new_matrix_btn)
        matrix_btns.addWidget(self._duplicate_matrix_btn)
        matrix_btns.addWidget(self._delete_matrix_btn)
        matrix_layout.addLayout(matrix_btns)
        left_layout.addWidget(matrix_group)

        binding_group = QGroupBox("Bindings")
        binding_layout = QVBoxLayout(binding_group)
        self._binding_list = QListWidget()
        self._binding_list.setObjectName("compensationBindingList")
        binding_layout.addWidget(self._binding_list)

        binding_btns = QHBoxLayout()
        self._new_binding_btn = QPushButton("New")
        self._new_binding_btn.setObjectName("compensationNewBindingButton")
        self._delete_binding_btn = QPushButton("Delete")
        self._delete_binding_btn.setObjectName("compensationDeleteBindingButton")
        binding_btns.addWidget(self._new_binding_btn)
        binding_btns.addWidget(self._delete_binding_btn)
        binding_layout.addLayout(binding_btns)
        left_layout.addWidget(binding_group)
        left_layout.addStretch(1)

        # --- Right side: matrix form + heat map ---
        right = QWidget()
        right_layout = QVBoxLayout(right)

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
        self._add_channel_btn = QPushButton("Add Channel")
        self._add_channel_btn.setObjectName("compensationAddChannelButton")
        self._remove_channel_btn = QPushButton("Remove Channel")
        self._remove_channel_btn.setObjectName("compensationRemoveChannelButton")
        channel_btns.addWidget(self._add_channel_btn)
        channel_btns.addWidget(self._remove_channel_btn)
        form.addRow("", channel_btns)
        right_layout.addLayout(form)

        # Heat map table
        heat_group = QGroupBox("Matrix Heat Map Preview")
        heat_layout = QVBoxLayout(heat_group)
        self._heat_map = QTableWidget()
        self._heat_map.setObjectName("compensationHeatMap")
        self._heat_map.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._heat_map.verticalHeader().setVisible(True)
        self._heat_map.horizontalHeader().setVisible(True)
        self._heat_map.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._heat_map.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        heat_layout.addWidget(self._heat_map)
        right_layout.addWidget(heat_group)

        # Validation label
        actions = QHBoxLayout()
        self._validate_btn = QPushButton("Validate")
        self._validate_btn.setObjectName("compensationValidateButton")
        actions.addWidget(self._validate_btn)
        actions.addStretch(1)
        right_layout.addLayout(actions)
        self._diag_label = QLabel("Not validated")
        self._diag_label.setObjectName("compensationDiagnosticLabel")
        self._diag_label.setWordWrap(True)
        right_layout.addWidget(self._diag_label)

        # Compensated / uncompensated preview
        self._build_preview_section(right_layout)

        right_layout.addStretch(1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("compensationDialogButtons")
        outer.addWidget(buttons)

        # --- Signal connections ---
        self._matrix_list.currentRowChanged.connect(self._on_matrix_row_changed)
        self._binding_list.currentRowChanged.connect(self._on_binding_row_changed)
        self._new_matrix_btn.clicked.connect(self._add_matrix)
        self._duplicate_matrix_btn.clicked.connect(self._duplicate_matrix)
        self._delete_matrix_btn.clicked.connect(self._delete_matrix)
        self._new_binding_btn.clicked.connect(self._add_binding)
        self._delete_binding_btn.clicked.connect(self._delete_binding)
        self._add_channel_btn.clicked.connect(self._add_channel)
        self._remove_channel_btn.clicked.connect(self._remove_channel)
        self._validate_btn.clicked.connect(self._validate_current)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        # --- Binding form (shown inline on left) ---
        self._build_binding_form(left_layout)

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
        """Build the compensated / uncompensated preview widget."""
        preview_group = QGroupBox("Compensated / Uncompensated Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Sample selector
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Sample:"))
        self._preview_sample_combo = QComboBox()
        self._preview_sample_combo.setObjectName(
            "compensationPreviewSampleCombo"
        )
        preview_available = [
            sid for sid in self._sample_ids if sid in self._sample_data
        ]
        if preview_available:
            self._preview_sample_combo.addItems(preview_available)
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

        # Preview table: columns = channel, uncompensated, compensated
        self._preview_table = QTableWidget()
        self._preview_table.setObjectName("compensationPreviewTable")
        self._preview_table.setColumnCount(3)
        self._preview_table.setHorizontalHeaderLabels([
            "Channel", "Uncompensated", "Compensated",
        ])
        self._preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        preview_layout.addWidget(self._preview_table)

        layout.addWidget(preview_group)
        self._preview_btn.clicked.connect(self._on_preview)

    def _on_preview(self) -> None:
        """Execute compensated/uncompensated preview using core apply_compensation."""
        idx = self._preview_sample_combo.currentIndex()
        if idx < 0:
            return
        sample_id = str(self._preview_sample_combo.itemText(idx))
        if sample_id == "(no data available)":
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
                    uncomp = compensated[evt, col_idx]
                    self._preview_table.setItem(
                        row, 0, QTableWidgetItem(ch)
                    )
                    self._preview_table.setItem(
                        row, 1, QTableWidgetItem(
                            f"{events[evt, col_idx]:.4f}"
                        )
                    )
                    self._preview_table.setItem(
                        row, 2, QTableWidgetItem(
                            f"{uncomp:.4f}"
                        )
                    )
                    row += 1

            self._preview_table.setRowCount(row)
            self._diag_label.setText(
                f"Preview: {row} cells (matrix {spec.id}, sample {sample_id})"
            )
        except Exception as exc:
            self._diag_label.setText(f"Preview failed: {exc}")

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
            self._refresh_channels_list(value.get("channels", []))
            self._update_heat_map(value)
            self._diag_label.setText("Not validated")
        finally:
            self._loading = False

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
        provenance = dict(new_matrix.get("provenance", {}))
        provenance["derived_from_matrix_id"] = original_id
        provenance["software_version"] = "flowdesk-gui"
        provenance["manual_edits"] = []
        new_matrix["provenance"] = provenance
        self._matrices.append(new_matrix)
        self._refresh_matrix_list(len(self._matrices) - 1)

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

    def _refresh_channels_list(self, selected_ids: list[str]) -> None:
        self._channels_list.clear()
        for channel in self._channels:
            if isinstance(channel, dict):
                ch_id = channel.get("id", channel.get("name", ""))
                ch_name = channel.get("name", ch_id)
            else:
                ch_id = getattr(channel, "id", getattr(channel, "name", ""))
                ch_name = getattr(channel, "name", ch_id)
            item = QListWidgetItem(f"{ch_name} [{ch_id}]")
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
            self._heat_map.setVerticalHeaderItem(row_idx, QTableWidgetItem(label))
        for col_idx in range(n):
            label = channels[col_idx] if col_idx < len(channels) else f"C{col_idx}"
            self._heat_map.setHorizontalHeaderItem(col_idx, QTableWidgetItem(label))

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
                self._heat_map.setItem(row_idx, col_idx, item)

    # -- Matrix commit -------------------------------------------------------

    def _commit_current_matrix(self) -> None:
        if not (0 <= self._current_matrix_row < len(self._matrices)):
            return
        original = self._matrices[self._current_matrix_row]
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
