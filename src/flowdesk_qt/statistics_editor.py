"""Qt editor for persistent population statistic definitions.

Allows the user to create, edit, and delete ``StatisticSpec`` definitions that
are persisted in the project manifest and evaluated by the headless pipeline.

This widget contains NO scientific execution logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
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


def _empty_statistic(
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a minimal statistic mapping ready for user editing."""
    statistic = {
        "id": "",
        "name": "",
        "population_id": "",
        "parameter_id": None,
        "metric": "count",
        "source_stage": "compensated",
        "transform_id": None,
        "value_policy": "full_events",
        "settings": {},
        "format": None,
        "notes": "",
    }
    if defaults:
        statistic.update(defaults)
    return statistic


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
        transforms: Sequence[Mapping[str, Any]] = (),
        new_statistic_defaults: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statisticsEditorDialog")
        self.setWindowTitle("Population Statistics")
        self.resize(850, 560)

        self._statistics = deepcopy(list(statistics))
        self._channels = tuple(available_channels)
        self._population_ids = tuple(population_ids)
        self._transforms = tuple(dict(value) for value in transforms)
        self._current_row = -1
        self._loading = False

        self._build_ui()

        if new_statistic_defaults is not None:
            self._statistics.append(_empty_statistic(new_statistic_defaults))
        elif not self._statistics:
            self._statistics.append(_empty_statistic())
        self._refresh_list(len(self._statistics) - 1)

    # -- Public API ----------------------------------------------------------

    def definitions(self) -> list[dict[str, Any]]:
        """Return validated statistic mappings without sharing mutable state."""
        self._commit_current()
        self._validate_all()
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
        btn_row.addWidget(self._new_button)
        btn_row.addWidget(self._delete_button)
        btn_row.addWidget(self._duplicate_button)
        btn_row.addWidget(self._clear_button)
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

        self._percentile_q_edit = QLineEdit("50")
        self._percentile_q_edit.setObjectName("statisticPercentileQEdit")
        self._percentile_q_label = QLabel("Percentile q:")
        self._percentile_q_label.setObjectName("statisticPercentileQLabel")

        self._format_edit = QLineEdit()
        self._format_edit.setObjectName("statisticFormatEdit")
        self._notes_edit = QLineEdit()
        self._notes_edit.setObjectName("statisticNotesEdit")

        form.addRow("Statistic ID:", self._id_edit)
        form.addRow("Name:", self._name_edit)
        form.addRow("Population:", self._population_combo)
        form.addRow("Parameter:", self._parameter_combo)
        form.addRow("Metric:", self._metric_combo)
        form.addRow("Source Stage:", self._source_combo)
        form.addRow("Transform:", self._transform_combo)
        form.addRow(self._percentile_q_label, self._percentile_q_edit)
        form.addRow("Format:", self._format_edit)
        form.addRow("Notes:", self._notes_edit)

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
        self._metric_combo.currentTextChanged.connect(self._on_metric_changed)
        self._source_combo.currentTextChanged.connect(self._on_source_changed)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        # Initial visibility of percentile q field
        self._on_metric_changed()
        self._on_source_changed()

    # -- Row management ------------------------------------------------------

    def _refresh_list(self, selected_row: int) -> None:
        self._loading = True
        try:
            self._list.clear()
            for stat in self._statistics:
                label = stat.get("name") or stat.get("id") or "New statistic"
                metric = stat.get("metric", "count")
                pop = stat.get("population_id", "")
                self._list.addItem(f"{label} ({metric}, pop={pop})")
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
            self._id_edit.setText(str(value.get("id", "")))
            self._name_edit.setText(str(value.get("name", "")))

            pop_id = str(value.get("population_id", ""))
            idx = self._population_combo.findData(pop_id)
            if idx >= 0:
                self._population_combo.setCurrentIndex(idx)

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
            self._diag_label.clear()
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

        self._statistics[self._current_row] = {
            "id": self._id_edit.text().strip(),
            "name": self._name_edit.text().strip(),
            "population_id": str(self._population_combo.currentData() or ""),
            "parameter_id": param_id,
            "metric": metric,
            "source_stage": self._source_combo.currentText(),
            "transform_id": str(self._transform_combo.currentData() or "") or None,
            "value_policy": "full_events",
            "settings": settings,
            "format": fmt_text,
            "notes": self._notes_edit.text().strip(),
        }

    def _on_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._commit_current()
        self._load_row(row)

    def _add_statistic(self) -> None:
        self._commit_current()
        self._statistics.append(_empty_statistic())
        self._refresh_list(len(self._statistics) - 1)

    def _delete_statistic(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._statistics.pop(row)
        self._current_row = -1
        if self._statistics:
            self._refresh_list(max(0, row - 1))

    def _duplicate_statistic(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._statistics):
            return
        self._commit_current()
        duplicate = deepcopy(self._statistics[row])
        duplicate["id"] = f"{duplicate.get('id', 'statistic')}-copy"
        duplicate["name"] = f"{duplicate.get('name', 'Statistic')} copy"
        self._statistics.insert(row + 1, duplicate)
        self._refresh_list(row + 1)

    def _clear_all(self) -> None:
        self._statistics.clear()
        self._current_row = -1
        self._statistics.append(_empty_statistic())
        self._refresh_list(0)

    # -- Metric-dependent UI -------------------------------------------------

    def _on_metric_changed(self) -> None:
        """Show/hide the percentile q field and adjust parameter requirement."""
        metric = self._metric_combo.currentText()
        is_value_metric = metric in _VALUE_METRICS
        is_percentile = metric == "percentile"

        self._percentile_q_label.setVisible(is_percentile)
        self._percentile_q_edit.setVisible(is_percentile)

        # For count/frequency metrics, disable parameter selection
        self._parameter_combo.setEnabled(is_value_metric)
        if not is_value_metric:
            self._parameter_combo.setCurrentIndex(0)

    def _on_source_changed(self) -> None:
        self._transform_combo.setEnabled(
            self._source_combo.currentText() == "transformed"
        )

    # -- Validation ----------------------------------------------------------

    def _validate_all(self) -> None:
        """Validate all statistic definitions. Raises ValueError on first issue."""
        ids: set[str] = set()
        for mapping in self._statistics:
            # Allow empty (unfilled) definitions to be silently skipped
            if not mapping.get("id") and not mapping.get("name"):
                continue

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
            if not spec.population_id:
                raise ValueError(
                    f"Statistic '{spec.name}' has an empty population_id"
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
