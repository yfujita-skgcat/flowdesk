"""Qt editor for persistent population statistic definitions.

Allows the user to create, edit, and delete ``StatisticSpec`` definitions that
are persisted in the project manifest and evaluated by the headless pipeline.

This widget contains NO scientific execution logic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.models import (
    ChannelSpec,
    StatisticSpec,
)
from flowdesk_core.parameter_catalog import ParameterCatalogEntry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_METRICS = [
    "count",
    "frequency_of_parent",
    "frequency_of_total",
    "mean",
    "median",
    "geometric_mean",
    "stddev",
    "cv",
    "mad",
    "percentile",
]

# Metrics that require a parameter_id (channel or derived parameter).
_VALUE_METRICS = frozenset([
    "mean",
    "median",
    "geometric_mean",
    "stddev",
    "cv",
    "mad",
    "percentile",
])

_SOURCE_STAGES = ["raw", "compensated", "transformed"]


def choose_population_targets(
    parent: QWidget,
    population_ids: Sequence[str],
    population_parents: Mapping[str, str | None],
    selected_ids: Sequence[str],
) -> tuple[str, ...] | None:
    """Show the shared stable-ID population target chooser."""
    dialog = QDialog(parent)
    dialog.setObjectName("statisticPopulationTargetsDialog")
    dialog.setWindowTitle("Select statistic populations")
    layout = QVBoxLayout(dialog)
    targets = QTreeWidget()
    targets.setObjectName("statisticPopulationTargetsList")
    targets.setHeaderLabels(["Population targets"])
    target_items: dict[str, QTreeWidgetItem] = {}
    selected = set(selected_ids)
    for population_id in population_ids:
        parent_id = population_parents.get(population_id)
        parent_item = target_items.get(parent_id)
        item = QTreeWidgetItem(parent_item or targets, [population_id])
        item.setData(0, Qt.ItemDataRole.UserRole, population_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            Qt.CheckState.Checked
            if population_id in selected else Qt.CheckState.Unchecked,
        )
        target_items[population_id] = item
    layout.addWidget(targets)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel
    )
    layout.addWidget(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return tuple(
        population_id for population_id in population_ids
        if target_items[population_id].checkState(0) == Qt.CheckState.Checked
    )


def _empty_statistic(
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a minimal statistic mapping ready for user editing."""
    statistic = {
        "id": "",
        "name": "",
        "population_id": "",
        "population_ids": [],
        "parameter_id": None,
        "metric": "count",
        "source_stage": "compensated",
        "transform_id": None,
        "value_policy": "full_events",
        "non_finite_policy": "strict",
        "settings": {},
        "format": None,
        "notes": "",
    }
    if defaults:
        statistic.update(defaults)
    return statistic


def _slug_identity(value: object) -> str:
    """Return a deterministic human-readable token for a generated ID/name."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "statistic"


def _statistic_identity_parts(
    value: Mapping[str, Any],
    parameter_labels: Mapping[str, str],
) -> tuple[str, str]:
    """Suggest ``name`` and ID components from parameter and metric."""
    metric = str(value.get("metric") or "count")
    parameter_id = str(value.get("parameter_id") or "").strip()
    if parameter_id:
        parameter_label = parameter_labels.get(parameter_id, parameter_id).strip()
        display_parameter = re.sub(r"\s+", "-", parameter_label)
        name = f"{display_parameter}_{metric}"
        identity = _slug_identity(display_parameter)
        identity = f"{identity}_{_slug_identity(metric)}"
    else:
        # Count/frequency metrics have no parameter, so use the metric itself.
        name = _slug_identity(metric)
        identity = name
    return name, f"stat_{identity}"


def _is_blank_statistic(value: Mapping[str, Any]) -> bool:
    """Return whether a definition is only an uncommitted editor placeholder."""
    return not any(
        str(value.get(key) or "").strip()
        for key in ("id", "name", "parameter_id")
    )


def repair_statistic_definitions(
    statistics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Repair named legacy definitions and drop completely blank placeholders."""
    repaired: list[dict[str, Any]] = []
    used_ids = {
        str(value.get("id"))
        for value in statistics
        if str(value.get("id") or "").strip()
    }
    for value in statistics:
        if _is_blank_statistic(value):
            continue
        statistic_id = str(value.get("id") or "").strip()
        if not statistic_id:
            source = str(
                value.get("name")
                or value.get("parameter_id")
                or value.get("metric")
                or "statistic"
            ).lower()
            slug = re.sub(r"[^a-z0-9]+", "_", source).strip("_") or "statistic"
            base_id = f"stat_{slug}"
            statistic_id = base_id
            suffix = 2
            while statistic_id in used_ids:
                statistic_id = f"{base_id}_{suffix}"
                suffix += 1
            value["id"] = statistic_id
        used_ids.add(statistic_id)
        repaired.append(value)
    return repaired


# ---------------------------------------------------------------------------
# StatisticsEditorDialog
# ---------------------------------------------------------------------------


class StatisticsEditorDialog(QDialog):
    """Edit statistic definitions for population-level statistics.

    Follows the same list+form pattern as ``TransformEditorDialog``.
    """

    def __init__(
        self,
        statistics: Sequence[dict[str, Any]],
        available_channels: Sequence[ChannelSpec | ParameterCatalogEntry],
        population_ids: Sequence[str],
        *,
        population_parents: Mapping[str, str | None] | None = None,
        population_labels: Mapping[str, str] | None = None,
        statistic_references: Mapping[str, Sequence[str]] | None = None,
        transforms: Sequence[Mapping[str, Any]] = (),
        new_statistic_defaults: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statisticsEditorDialog")
        self.setWindowTitle("Population Statistics")
        self.resize(850, 560)

        # Existing definitions keep their persisted IDs; only definitions created
        # through New receive the new population/metric-based suggestion.
        self._statistics = repair_statistic_definitions(deepcopy(list(statistics)))
        self._fixed_statistic_ids = {
            str(value.get("id"))
            for value in self._statistics
            if str(value.get("id") or "").strip()
        }
        self._channels = tuple(available_channels)
        self._parameter_labels = {
            (
                channel.parameter_id
                if isinstance(channel, ParameterCatalogEntry)
                else channel.id
            ): (
                channel.display_name
                if isinstance(channel, ParameterCatalogEntry)
                else channel.name
            )
            for channel in self._channels
        }
        self._population_ids = tuple(population_ids)
        self._population_labels = dict(population_labels or {})
        self._population_parents = dict(population_parents or {})
        self._statistic_references = {
            str(statistic_id): tuple(str(reference) for reference in references)
            for statistic_id, references in (statistic_references or {}).items()
        }
        self._transforms = tuple(dict(value) for value in transforms)
        # Defaults supplied by an entry point (for example Results -> Add
        # Statistic...) are applied only when the user explicitly clicks New.
        # Opening the editor must be side-effect free and must not create an
        # uncommitted placeholder definition.
        self._pending_new_defaults = (
            dict(new_statistic_defaults)
            if new_statistic_defaults is not None else None
        )
        self._current_row = -1
        self._last_valid_parameter_id = ""
        self._target_population_ids: tuple[str, ...] = ()
        self._loading = False
        self._undo_history: list[list[dict[str, Any]]] = []
        self._redo_history: list[list[dict[str, Any]]] = []

        self._build_ui()

        self._refresh_list(len(self._statistics) - 1 if self._statistics else -1)

    # -- Public API ----------------------------------------------------------

    def definitions(self) -> list[dict[str, Any]]:
        """Return validated statistic mappings without sharing mutable state."""
        self._commit_current()
        self._statistics = repair_statistic_definitions(self._statistics)
        self._validate_all()
        self._fixed_statistic_ids.update(
            str(value.get("id"))
            for value in self._statistics
            if str(value.get("id") or "").strip()
        )
        if 0 <= self._current_row < len(self._statistics):
            self._id_edit.setReadOnly(True)
        return deepcopy(self._statistics)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: list ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.setObjectName("statisticDefinitionList")
        left_layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._new_button = QPushButton("New")
        self._new_button.setObjectName("statisticNewButton")
        self._delete_button = QPushButton("Delete")
        self._delete_button.setObjectName("statisticDeleteButton")
        self._duplicate_button = QPushButton("Duplicate")
        self._duplicate_button.setObjectName("statisticDuplicateButton")
        self._clear_button = QPushButton("Clear All")
        self._clear_button.setObjectName("statisticClearButton")
        self._undo_button = QPushButton("Undo")
        self._undo_button.setObjectName("statisticUndoButton")
        self._redo_button = QPushButton("Redo")
        self._redo_button.setObjectName("statisticRedoButton")
        btn_row.addWidget(self._new_button)
        btn_row.addWidget(self._delete_button)
        btn_row.addWidget(self._duplicate_button)
        btn_row.addWidget(self._clear_button)
        btn_row.addWidget(self._undo_button)
        btn_row.addWidget(self._redo_button)
        left_layout.addLayout(btn_row)
        left_layout.addStretch(1)

        # --- Right: form ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        form = QFormLayout()

        self._id_edit = QLineEdit()
        self._id_edit.setObjectName("statisticIdEdit")
        self._name_edit = QLineEdit()
        self._name_edit.setObjectName("statisticNameEdit")

        self._population_combo = QComboBox()
        self._population_combo.setObjectName("statisticPopulationCombo")
        self._population_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for pid in self._population_ids:
            self._population_combo.addItem(pid, pid)
        self._population_scope_combo = QComboBox()
        self._population_scope_combo.setObjectName("statisticPopulationScopeCombo")
        self._population_scope_combo.addItem("Current population", "current")
        self._population_scope_combo.addItem(
            "Current population and descendants", "descendants"
        )
        self._population_scope_combo.addItem("Selected populations...", "selected")
        self._population_scope_combo.addItem("All current populations", "all")
        self._target_button = QPushButton("Targets...")
        self._target_button.setObjectName("statisticPopulationTargetsButton")
        population_row = QWidget()
        population_layout = QHBoxLayout(population_row)
        population_layout.setContentsMargins(0, 0, 0, 0)
        population_layout.addWidget(self._population_combo)
        population_layout.addWidget(self._population_scope_combo)
        population_layout.addWidget(self._target_button)

        self._parameter_combo = QComboBox()
        self._parameter_combo.setObjectName("statisticParameterCombo")
        self._parameter_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._parameter_combo.addItem("(none)", "")
        for channel in self._channels:
            if isinstance(channel, ParameterCatalogEntry):
                label = channel.selector_label
                enabled = channel.is_definition_valid
                tooltip = "; ".join(
                    diagnostic.message for diagnostic in channel.diagnostics
                ) or channel.availability
                parameter_id = channel.parameter_id
            else:
                label = f"{channel.name} [{channel.id}]"
                enabled = True
                tooltip = ""
                parameter_id = channel.id
            self._parameter_combo.addItem(
                label, parameter_id
            )
            index = self._parameter_combo.count() - 1
            self._parameter_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            model = self._parameter_combo.model()
            item = model.item(index) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(enabled)

        self._parameter_status_label = QLabel("")
        self._parameter_status_label.setObjectName("statisticParameterStatusLabel")
        self._parameter_status_label.setWordWrap(True)

        self._metric_combo = QComboBox()
        self._metric_combo.setObjectName("statisticMetricCombo")
        self._metric_combo.addItems(_METRICS)

        self._source_combo = QComboBox()
        self._source_combo.setObjectName("statisticSourceCombo")
        self._source_combo.addItems(_SOURCE_STAGES)

        self._transform_combo = QComboBox()
        self._transform_combo.setObjectName("statisticTransformCombo")
        self._transform_combo.addItem("(native value space)", "")
        for transform in self._transforms:
            self._transform_combo.addItem(
                f"{transform.get('name', transform.get('id'))} [{transform.get('id')}]",
                transform.get("id"),
            )
        self._nonfinite_combo = QComboBox()
        self._nonfinite_combo.setObjectName("statisticNonFinitePolicyCombo")
        self._nonfinite_combo.addItem("Strict (undefined on any NaN/Inf)", "strict")
        self._nonfinite_combo.addItem("Exclude invalid values (explicit)", "exclude_invalid")

        self._percentile_q_edit = QLineEdit("50")
        self._percentile_q_edit.setObjectName("statisticPercentileQEdit")
        self._percentile_q_label = QLabel("Percentile q:")
        self._percentile_q_label.setObjectName("statisticPercentileQLabel")

        self._format_edit = QLineEdit()
        self._format_edit.setObjectName("statisticFormatEdit")
        self._notes_edit = QLineEdit()
        self._notes_edit.setObjectName("statisticNotesEdit")
        self._compute_check = QCheckBox("Compute enabled")
        self._compute_check.setObjectName("statisticComputeEnabledCheck")
        self._compute_check.setChecked(True)

        self._id_edit.setToolTip(
            "Generated once when the statistic is created; fixed thereafter."
        )
        form.addRow("Statistic ID (fixed):", self._id_edit)
        form.addRow("Name:", self._name_edit)
        form.addRow("Population targets:", population_row)
        form.addRow("Parameter:", self._parameter_combo)
        form.addRow("Parameter status:", self._parameter_status_label)
        form.addRow("Metric:", self._metric_combo)
        form.addRow("Value domain:", self._source_combo)
        form.addRow("Transform:", self._transform_combo)
        form.addRow("Non-finite policy:", self._nonfinite_combo)
        form.addRow(self._percentile_q_label, self._percentile_q_edit)
        form.addRow("Format:", self._format_edit)
        form.addRow("Notes:", self._notes_edit)
        form.addRow("Analysis:", self._compute_check)

        right_layout.addLayout(form)

        self._diag_label = QLabel("")
        self._diag_label.setObjectName("statisticDiagnosticLabel")
        self._diag_label.setWordWrap(True)
        right_layout.addWidget(self._diag_label)
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
        buttons.setObjectName("statisticDialogButtons")
        outer.addWidget(buttons)

        # --- Signal connections ---
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._new_button.clicked.connect(self._add_statistic)
        self._delete_button.clicked.connect(self._delete_statistic)
        self._duplicate_button.clicked.connect(self._duplicate_statistic)
        self._clear_button.clicked.connect(self._clear_all)
        self._undo_button.clicked.connect(self._undo)
        self._redo_button.clicked.connect(self._redo)
        self._metric_combo.currentTextChanged.connect(self._on_metric_changed)
        self._metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        self._parameter_combo.currentIndexChanged.connect(
            lambda _index: self._update_parameter_status()
        )
        self._source_combo.currentTextChanged.connect(self._on_source_changed)
        self._population_scope_combo.currentIndexChanged.connect(
            self._on_population_scope_changed
        )
        self._population_combo.currentIndexChanged.connect(
            self._on_population_base_changed
        )
        self._target_button.clicked.connect(self._select_population_targets)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        # Initial visibility of percentile q field
        self._on_metric_changed()
        self._on_source_changed()
        self._update_history_buttons()

    # -- Row management ------------------------------------------------------

    def _refresh_list(self, selected_row: int) -> None:
        self._loading = True
        try:
            self._list.clear()
            for stat in self._statistics:
                label = stat.get("name") or stat.get("id") or "New statistic"
                metric = stat.get("metric", "count")
                populations = stat.get("population_ids") or [
                    stat.get("population_id", "")
                ]
                populations = [str(value) for value in populations if value]
                scope = ", ".join(populations) or "(none)"
                self._list.addItem(f"{label} ({metric}, pop={scope})")
            if self._statistics:
                self._list.setCurrentRow(
                    min(selected_row, len(self._statistics) - 1)
                )
        finally:
            self._loading = False
        if self._statistics:
            self._load_row(self._list.currentRow())

    def _load_row(self, row: int) -> None:
        if row < 0 or row >= len(self._statistics):
            return
        self._loading = True
        try:
            self._current_row = row
            value = self._statistics[row]
            statistic_id = str(value.get("id", ""))
            if not statistic_id:
                self._initialize_statistic_identity(value)
                statistic_id = str(value.get("id", ""))
            self._id_edit.setText(statistic_id)
            self._id_edit.setReadOnly(statistic_id in self._fixed_statistic_ids)
            self._name_edit.setText(str(value.get("name", "")))

            pop_id = str(value.get("population_id", ""))
            idx = self._population_combo.findData(pop_id)
            if idx >= 0:
                self._population_combo.setCurrentIndex(idx)
            raw_targets = value.get("population_ids")
            if not isinstance(raw_targets, list) or not raw_targets:
                raw_targets = [pop_id] if pop_id else []
            self._target_population_ids = tuple(
                str(population_id) for population_id in raw_targets
            )
            self._update_population_scope_label()

            param_id = value.get("parameter_id") or ""
            pidx = self._parameter_combo.findData(str(param_id))
            if pidx >= 0:
                self._parameter_combo.setCurrentIndex(pidx)

            metric = str(value.get("metric", "count"))
            self._metric_combo.setCurrentText(metric)

            source = str(value.get("source_stage", "compensated"))
            self._source_combo.setCurrentText(source)
            transform_index = self._transform_combo.findData(value.get("transform_id"))
            self._transform_combo.setCurrentIndex(max(0, transform_index))
            policy_index = self._nonfinite_combo.findData(
                value.get("non_finite_policy", "strict")
            )
            self._nonfinite_combo.setCurrentIndex(max(0, policy_index))

            settings = value.get("settings", {})
            self._percentile_q_edit.setText(
                str(settings.get("q", 50))
            )

            fmt = value.get("format")
            if fmt is not None:
                self._format_edit.setText(str(fmt))
            else:
                self._format_edit.clear()

            self._notes_edit.setText(str(value.get("notes", "")))
            self._compute_check.setChecked(bool(value.get("compute_enabled", True)))
            self._on_metric_changed()
            # Reapply after all row fields and enabled states have settled.  This
            # prevents a persisted count definition from leaving the Parameter
            # selector disabled when the user changes Metric to a value metric.
            self._on_metric_changed()
        finally:
            self._loading = False

    def _commit_current(self) -> None:
        if self._current_row < 0 or self._current_row >= len(self._statistics):
            return

        metric = self._metric_combo.currentText()
        param_id = str(self._parameter_combo.currentData() or "")
        if not param_id:
            param_id = None

        settings: dict[str, Any] = {}
        if metric == "percentile":
            try:
                settings["q"] = float(self._percentile_q_edit.text())
            except (ValueError, TypeError):
                settings["q"] = 50.0

        fmt_text = self._format_edit.text().strip()
        if not fmt_text:
            fmt_text = None

        target_ids = self._target_population_ids
        scope = self._population_scope_combo.currentData()
        if not target_ids and scope != "selected":
            current_population = str(self._population_combo.currentData() or "")
            target_ids = (current_population,) if current_population else ()
        current = self._statistics[self._current_row]
        if not str(current.get("id") or "").strip():
            self._initialize_statistic_identity(current)
        statistic_id = str(current.get("id") or "")
        if statistic_id not in self._fixed_statistic_ids:
            statistic_id = self._id_edit.text().strip()
        self._statistics[self._current_row] = {
            # New definitions may edit the generated suggestion until accepted.
            # Existing definitions use their persisted, fixed ID.
            "id": statistic_id,
            "name": self._name_edit.text().strip(),
            "population_id": target_ids[0] if target_ids else "",
            "population_ids": list(target_ids),
            "parameter_id": param_id,
            "metric": metric,
            "source_stage": self._source_combo.currentText(),
            "transform_id": str(self._transform_combo.currentData() or "") or None,
            "value_policy": "full_events",
            "non_finite_policy": self._nonfinite_combo.currentData() or "strict",
            "settings": settings,
            "format": fmt_text,
            "notes": self._notes_edit.text().strip(),
            "compute_enabled": self._compute_check.isChecked(),
        }

    def _on_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._commit_current()
        self._load_row(row)

    def _add_statistic(self) -> None:
        self._record_history()
        self._commit_current()
        defaults = self._pending_new_defaults
        self._pending_new_defaults = None
        value = _empty_statistic(defaults)
        self._initialize_statistic_identity(value)
        self._statistics.append(value)
        self._refresh_list(len(self._statistics) - 1)

    def _initialize_statistic_identity(self, value: dict[str, Any]) -> None:
        """Assign a collision-free immutable ID and a readable initial name."""
        suggested_name, suggested_id = _statistic_identity_parts(
            value, self._parameter_labels
        )
        if not str(value.get("name") or "").strip():
            value["name"] = suggested_name
        if str(value.get("id") or "").strip():
            return
        used_ids = {
            str(item.get("id")) for item in self._statistics
            if str(item.get("id") or "").strip() and item is not value
        }
        statistic_id = suggested_id
        suffix = 2
        while statistic_id in used_ids:
            statistic_id = f"{suggested_id}_{suffix}"
            suffix += 1
        value["id"] = statistic_id

    def _delete_statistic(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        statistic_id = str(self._statistics[row].get("id", ""))
        references = self._statistic_references.get(statistic_id, ())
        if references:
            QMessageBox.information(
                self,
                "Statistic has dependencies",
                "Remove these references before deleting "
                + statistic_id + ":\n- " + "\n- ".join(references),
            )
            return
        self._record_history()
        self._statistics.pop(row)
        self._current_row = -1
        if self._statistics:
            self._refresh_list(max(0, row - 1))

    def _duplicate_statistic(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._statistics):
            return
        self._commit_current()
        self._record_history()
        duplicate = deepcopy(self._statistics[row])
        duplicate["id"] = f"{duplicate.get('id', 'statistic')}-copy"
        duplicate["name"] = f"{duplicate.get('name', 'Statistic')} copy"
        self._statistics.insert(row + 1, duplicate)
        self._refresh_list(row + 1)

    def _clear_all(self) -> None:
        self._record_history()
        self._statistics.clear()
        self._current_row = -1
        value = _empty_statistic()
        self._initialize_statistic_identity(value)
        self._statistics.append(value)
        self._refresh_list(0)

    def _record_history(self) -> None:
        self._commit_current()
        self._undo_history.append(deepcopy(self._statistics))
        self._redo_history.clear()
        self._update_history_buttons()

    def _restore_history(self, snapshot: list[dict[str, Any]]) -> None:
        self._statistics = deepcopy(snapshot)
        self._current_row = -1
        self._refresh_list(min(self._list.currentRow(), len(self._statistics) - 1))
        self._update_history_buttons()

    def _undo(self) -> None:
        if not self._undo_history:
            return
        self._redo_history.append(deepcopy(self._statistics))
        self._restore_history(self._undo_history.pop())

    def _redo(self) -> None:
        if not self._redo_history:
            return
        self._undo_history.append(deepcopy(self._statistics))
        self._restore_history(self._redo_history.pop())

    def _update_history_buttons(self) -> None:
        self._undo_button.setEnabled(bool(self._undo_history))
        self._redo_button.setEnabled(bool(self._redo_history))

    # -- Metric-dependent UI -------------------------------------------------

    def _on_metric_changed(self) -> None:
        """Show/hide the percentile q field and adjust parameter requirement."""
        metric = self._metric_combo.currentText()
        is_value_metric = metric in _VALUE_METRICS
        is_percentile = metric == "percentile"

        self._percentile_q_label.setVisible(is_percentile)
        self._percentile_q_edit.setVisible(is_percentile)

        current_parameter = str(self._parameter_combo.currentData() or "")
        if is_value_metric:
            if self._parameter_item_enabled(current_parameter):
                self._last_valid_parameter_id = current_parameter
            elif self._parameter_item_enabled(self._last_valid_parameter_id):
                self._parameter_combo.setCurrentIndex(
                    self._parameter_combo.findData(self._last_valid_parameter_id)
                )
            self._parameter_combo.setEnabled(self._has_valid_parameter())
        else:
            if current_parameter:
                self._last_valid_parameter_id = current_parameter
            self._parameter_combo.setCurrentIndex(0)
            self._parameter_combo.setEnabled(False)
        self._update_parameter_status(is_value_metric)

    def _parameter_item_enabled(self, parameter_id: str) -> bool:
        if not parameter_id:
            return False
        index = self._parameter_combo.findData(parameter_id)
        if index < 0:
            return False
        item = self._parameter_combo.model().item(index)
        return item is not None and item.isEnabled()

    def _has_valid_parameter(self) -> bool:
        model = self._parameter_combo.model()
        return any(
            index > 0 and model.item(index) is not None and model.item(index).isEnabled()
            for index in range(self._parameter_combo.count())
        )

    def _update_parameter_status(self, is_value_metric: bool | None = None) -> None:
        if is_value_metric is None:
            is_value_metric = self._metric_combo.currentText() in _VALUE_METRICS
        if not is_value_metric:
            self._parameter_status_label.setText(
                "This metric counts events or frequency; it does not use a parameter."
            )
            return
        if not self._has_valid_parameter():
            self._parameter_status_label.setText(
                "No valid parameters are available. Check acquired channels and "
                "derived-parameter diagnostics."
            )
            return
        current = str(self._parameter_combo.currentData() or "")
        if current and not self._parameter_item_enabled(current):
            self._parameter_status_label.setText(
                "The saved parameter is unavailable; choose an enabled parameter."
            )
            return
        self._parameter_status_label.setText(
            "Select a valid acquired or derived parameter for this value metric."
        )

    def _on_source_changed(self) -> None:
        self._transform_combo.setEnabled(
            self._source_combo.currentText() == "transformed"
        )

    def _descendant_population_ids(self, population_id: str) -> tuple[str, ...]:
        targets = [population_id]
        changed = True
        while changed:
            changed = False
            for candidate, parent in self._population_parents.items():
                if candidate not in targets and parent in targets:
                    targets.append(candidate)
                    changed = True
        return tuple(
            candidate for candidate in self._population_ids if candidate in targets
        )

    def _on_population_scope_changed(self, _index: int) -> None:
        if self._loading:
            return
        scope = self._population_scope_combo.currentData()
        current = str(self._population_combo.currentData() or "")
        if scope == "current":
            self._target_population_ids = (current,) if current else ()
        elif scope == "descendants":
            self._target_population_ids = self._descendant_population_ids(current)
        elif scope == "all":
            self._target_population_ids = tuple(self._population_ids)
        elif scope == "selected":
            self._select_population_targets()
        self._update_population_scope_label()

    def _on_population_base_changed(self, _index: int) -> None:
        """Recompute an implicit scope when its anchor population changes."""
        if self._loading:
            return
        scope = self._population_scope_combo.currentData()
        current = str(self._population_combo.currentData() or "")
        if scope == "current":
            self._target_population_ids = (current,) if current else ()
        elif scope == "descendants":
            self._target_population_ids = self._descendant_population_ids(current)
        self._update_population_scope_label()

    def _update_population_scope_label(self) -> None:
        count = len(self._target_population_ids)
        self._target_button.setText(f"Targets ({count})...")
        missing = sorted(
            set(self._target_population_ids) - set(self._population_ids)
        )
        self._diag_label.setText(
            "Missing population target(s): " + ", ".join(missing)
            if missing else ""
        )

    def _select_population_targets(self) -> None:
        selected = choose_population_targets(
            self,
            self._population_ids,
            self._population_parents,
            self._target_population_ids,
        )
        if selected is None:
            return
        self._target_population_ids = selected
        self._update_population_scope_label()

    # -- Validation ----------------------------------------------------------

    def _validate_all(self) -> None:
        """Validate all statistic definitions. Raises ValueError on first issue."""
        ids: set[str] = set()
        for mapping in self._statistics:
            # Allow empty (unfilled) definitions to be silently skipped
            if not mapping.get("id") and not mapping.get("name"):
                continue

            raw_targets = mapping.get("population_ids")
            if raw_targets == [] or (
                not raw_targets and not mapping.get("population_id")
            ):
                raise ValueError(
                    f"Statistic '{mapping.get('name', mapping.get('id', '?'))}' "
                    "has no population targets"
                )

            try:
                spec = StatisticSpec(**mapping)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid statistic '{mapping.get('name', mapping.get('id', '?'))}': {exc}"
                ) from exc

            if not spec.id:
                raise ValueError(
                    f"Statistic '{spec.name}' has an empty ID"
                )
            if not spec.name:
                raise ValueError(
                    f"Statistic '{spec.id}' has an empty name"
                )
            if not spec.population_ids:
                raise ValueError(
                    f"Statistic '{spec.name}' has no population targets"
                )
            missing_targets = set(spec.population_ids) - set(self._population_ids)
            if missing_targets:
                raise ValueError(
                    f"Statistic '{spec.name}' has missing population target(s): "
                    + ", ".join(sorted(missing_targets))
                )

            if spec.metric in _VALUE_METRICS and not spec.parameter_id:
                raise ValueError(
                    f"Statistic '{spec.name}' metric '{spec.metric}' requires a parameter"
                )

            if spec.id in ids:
                raise ValueError(f"Duplicate statistic ID: {spec.id}")
            ids.add(spec.id)

    # -- Accept --------------------------------------------------------------

    def _accept_if_valid(self) -> None:
        try:
            self.definitions()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid statistic definition", str(exc))
            return
        self.accept()


class StatisticManagementDialog(QDialog):
    """Compact Compute/Show management table for persisted statistics.

    This dialog only edits analysis flags and Results display state. Scientific
    values are never calculated here; detailed definition editing remains in
    :class:`StatisticsEditorDialog`.
    """

    _HEADERS = (
        "Compute", "Show", "Statistic", "Parameter", "Metric",
        "Value domain", "Applies to",
    )

    def __init__(
        self,
        statistics: Sequence[dict[str, Any]],
        visibility: Mapping[str, bool] | None = None,
        *,
        parameter_labels: Mapping[str, str] | None = None,
        population_labels: Mapping[str, str] | None = None,
        population_ids: Sequence[str] = (),
        population_parents: Mapping[str, str | None] | None = None,
        available_channels: Sequence[ChannelSpec | ParameterCatalogEntry] = (),
        transforms: Sequence[Mapping[str, Any]] = (),
        statistic_references: Mapping[str, Sequence[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statisticManagementDialog")
        self.setWindowTitle("Manage Statistics")
        self.resize(900, 420)
        self._statistics = deepcopy(list(statistics))
        self._visibility = dict(visibility or {})
        self._parameter_labels = dict(parameter_labels or {})
        self._population_labels = dict(population_labels or {})
        self._population_ids = tuple(str(value) for value in population_ids)
        self._population_parents = dict(population_parents or {})
        self._available_channels = tuple(available_channels)
        self._transforms = tuple(dict(value) for value in transforms)
        self._statistic_references = dict(statistic_references or {})
        self._compute_checks: dict[str, QCheckBox] = {}
        self._show_checks: dict[str, QCheckBox] = {}
        self._target_ids: dict[str, tuple[str, ...]] = {}

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setObjectName("statisticManagementTable")
        self._table.setHorizontalHeaderLabels(list(self._HEADERS))
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellDoubleClicked.connect(self._edit_row_at)
        layout.addWidget(self._table)

        edit_definition = QPushButton("Edit Definition...")
        edit_definition.setObjectName("statisticEditDefinitionButton")
        edit_definition.clicked.connect(self._edit_selected_definition)
        layout.addWidget(edit_definition)

        edit_targets = QPushButton("Edit Applies to...")
        edit_targets.setObjectName("statisticEditTargetsButton")
        edit_targets.clicked.connect(self._edit_selected_targets)
        layout.addWidget(edit_targets)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("statisticManagementDialogButtons")
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._statistics = repair_statistic_definitions(self._statistics)
        self._populate()

    def _populate(self) -> None:
        self._table.setRowCount(len(self._statistics))
        for row, value in enumerate(self._statistics):
            statistic_id = str(value.get("id", ""))
            compute = QCheckBox()
            compute.setObjectName(f"statisticComputeCheck_{statistic_id}")
            compute.setChecked(bool(value.get("compute_enabled", True)))
            show = QCheckBox()
            show.setObjectName(f"statisticShowCheck_{statistic_id}")
            show.setChecked(self._visibility.get(statistic_id, True))
            self._compute_checks[statistic_id] = compute
            self._show_checks[statistic_id] = show
            self._table.setCellWidget(row, 0, compute)
            self._table.setCellWidget(row, 1, show)
            self._set_item(row, 2, value.get("name") or statistic_id)
            self._table.item(row, 2).setToolTip(
                f"name={value.get('name') or statistic_id}; "
                f"metric={value.get('metric', 'count')}; ID={statistic_id}"
            )
            parameter_id = str(value.get("parameter_id") or "")
            self._set_item(
                row, 3,
                self._parameter_labels.get(parameter_id, parameter_id) or "(none)",
            )
            self._set_item(row, 4, value.get("metric", "count"))
            self._set_item(row, 5, value.get("transform_id") or value.get("source_stage", ""))
            targets = value.get("population_ids") or [value.get("population_id", "")]
            target_ids = tuple(str(target) for target in targets if target)
            self._target_ids[statistic_id] = target_ids
            target_labels = [
                self._population_labels.get(str(target), str(target))
                for target in targets if target
            ]
            applies_to = ", ".join(target_labels) or "(none)"
            self._set_item(row, 6, applies_to)
            self._table.item(row, 6).setToolTip(applies_to)

    def _edit_selected_targets(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._edit_targets(row)

    def _edit_row_at(self, row: int, column: int) -> None:
        if column == 6:
            self._edit_targets(row)
        else:
            self._edit_definition(row)

    def _edit_selected_definition(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            self._edit_definition(row)

    def _edit_definition(self, row: int) -> None:
        if not (0 <= row < len(self._statistics)):
            return
        statistic_id = str(self._statistics[row].get("id", ""))
        dialog = StatisticsEditorDialog(
            [self._statistics[row]],
            self._available_channels,
            self._population_ids,
            population_parents=self._population_parents,
            population_labels=self._population_labels,
            statistic_references={
                statistic_id: self._statistic_references.get(statistic_id, ())
            },
            transforms=self._transforms,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.definitions()
        if updated:
            self._statistics[row] = updated[0]
            self._populate()
            self._table.selectRow(row)

    def _edit_targets(self, row: int) -> None:
        if not self._population_ids or not (0 <= row < len(self._statistics)):
            return
        statistic_id = str(self._statistics[row].get("id", ""))
        selected = choose_population_targets(
            self,
            self._population_ids,
            self._population_parents,
            self._target_ids.get(statistic_id, ()),
        )
        if selected is None:
            return
        self._target_ids[statistic_id] = selected
        labels = [self._population_labels.get(target, target) for target in selected]
        applies_to = ", ".join(labels) or "(none)"
        item = self._table.item(row, 6)
        if item is not None:
            item.setText(applies_to)
            item.setToolTip(applies_to)

    def _set_item(self, row: int, column: int, value: object) -> None:
        self._table.setItem(row, column, QTableWidgetItem(str(value)))

    def definitions(self) -> list[dict[str, Any]]:
        result = deepcopy(self._statistics)
        result = repair_statistic_definitions(result)
        for value in result:
            statistic_id = str(value.get("id", ""))
            value["compute_enabled"] = self._compute_checks[statistic_id].isChecked()
            if self._population_ids:
                targets = list(self._target_ids.get(statistic_id, ()))
                value["population_ids"] = targets
                value["population_id"] = targets[0] if targets else ""
        return result

    def visibility(self) -> dict[str, bool]:
        return {
            statistic_id: check.isChecked()
            for statistic_id, check in self._show_checks.items()
        }
