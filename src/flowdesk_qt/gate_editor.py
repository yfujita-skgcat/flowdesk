"""Gate editor widget.

Allows the user to create and manage gate definitions.  Gate coordinates
are stored in **data coordinates**, never screen pixels.

This widget contains NO scientific execution logic.  It produces
``GateSpec`` objects that are consumed by ``flowdesk_core.gates`` and
``flowdesk_core.gating_strategy``.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.gating_strategy import GatingStrategyError, ordered_gates
from flowdesk_core.models import GateSpec, GatingStrategySpec

# ---------------------------------------------------------------------------
# Gate creation dialog
# ---------------------------------------------------------------------------


class _GateDialog(QDialog):
    """Simple dialog to collect gate parameters."""

    def __init__(
        self,
        gate_type: str,
        x_channel: str,
        y_channel: str,
        available_populations: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Gate")
        self._gate_type = gate_type
        self._x_channel = x_channel
        self._y_channel = y_channel
        self._available_populations = available_populations or []
        self._name: str = ""
        self._thresholds: dict[str, Any] = {}
        self._coordinates: list[tuple[float, float]] = []
        self._build_ui()

    def name(self) -> str:
        return self._name

    def thresholds(self) -> dict[str, Any]:
        return self._thresholds

    def coordinates(self) -> list[tuple[float, float]]:
        return self._coordinates

    def _build_ui(self) -> None:
        layout = QFormLayout(self)

        # Gate name
        from PySide6.QtWidgets import QLineEdit  # noqa: N812 - local import

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(f"gate_{self._gate_type}")
        layout.addRow("Gate name:", self._name_edit)
        self._name = self._name_edit.text()

        # Rectangle thresholds
        if self._gate_type == "rectangle":
            self._x_min = QDoubleSpinBox()
            self._x_min.setRange(-1e10, 1e10)
            self._x_min.setValue(0.0)
            self._x_max = QDoubleSpinBox()
            self._x_max.setRange(-1e10, 1e10)
            self._x_max.setValue(10000.0)
            self._y_min = QDoubleSpinBox()
            self._y_min.setRange(-1e10, 1e10)
            self._y_min.setValue(0.0)
            self._y_max = QDoubleSpinBox()
            self._y_max.setRange(-1e10, 1e10)
            self._y_max.setValue(10000.0)

            layout.addRow(f"X ({self._x_channel}) min:", self._x_min)
            layout.addRow(f"X ({self._x_channel}) max:", self._x_max)
            layout.addRow(f"Y ({self._y_channel}) min:", self._y_min)
            layout.addRow(f"Y ({self._y_channel}) max:", self._y_max)

        # Range thresholds
        elif self._gate_type == "range":
            self._r_min = QDoubleSpinBox()
            self._r_min.setRange(-1e10, 1e10)
            self._r_max = QDoubleSpinBox()
            self._r_max.setRange(-1e10, 1e10)
            self._r_max.setValue(10000.0)

            layout.addRow(f"Parameter ({self._x_channel}) min:", self._r_min)
            layout.addRow(f"Parameter ({self._x_channel}) max:", self._r_max)

        # Polygon: just a note that vertices are collected from plot clicks
        elif self._gate_type == "polygon":
            info = QLabel(
                "Polygon vertices will be collected by clicking on the plot.\n"
                "Press OK to return to the plot and start placing vertices.\n"
                "Double-click the plot to finish the polygon."
            )
            info.setWordWrap(True)
            layout.addRow(info)

        elif self._gate_type == "boolean":
            self._operation_combo = QComboBox()
            self._operation_combo.addItems(["and", "or", "not"])
            self._source_list = QListWidget()
            self._source_list.setSelectionMode(QAbstractItemView.MultiSelection)
            for pop_id, label in self._available_populations:
                item = QListWidgetItem(f"{label} [{pop_id}]")
                item.setData(Qt.UserRole, pop_id)
                self._source_list.addItem(item)
            layout.addRow("Operation:", self._operation_combo)
            layout.addRow("Source populations:", self._source_list)

        # Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow("", QWidget())  # spacer
        layout.addRow("", btn_layout)

        ok_btn.clicked.connect(self._on_ok)
        cancel_btn.clicked.connect(self.reject)

        self._ok_btn = ok_btn
        self._collect_ok_values()

    def _collect_ok_values(self) -> None:
        """Gather threshold values from widgets into self._thresholds."""
        self._name = self._name_edit.text() or f"gate_{self._gate_type}"
        self._thresholds.clear()

        if self._gate_type == "rectangle":
            self._thresholds["x_min"] = self._x_min.value()
            self._thresholds["x_max"] = self._x_max.value()
            self._thresholds["y_min"] = self._y_min.value()
            self._thresholds["y_max"] = self._y_max.value()

        elif self._gate_type == "range":
            self._thresholds["min"] = self._r_min.value()
            self._thresholds["max"] = self._r_max.value()

        elif self._gate_type == "boolean":
            source_ids = [
                item.data(Qt.UserRole)
                for item in self._source_list.selectedItems()
            ]
            self._thresholds["operation"] = self._operation_combo.currentText()
            self._thresholds["source_ids"] = source_ids

    def _on_ok(self) -> None:
        self._collect_ok_values()
        self.accept()


# ---------------------------------------------------------------------------
# GateEditor widget
# ---------------------------------------------------------------------------


class GateEditor(QWidget):
    """Right-pane widget for creating and managing gates.

    Gates are stored as ``GateSpec`` instances and can be retrieved via
    ``gates()``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gates: list[GateSpec] = []
        self._x_channel: str = ""
        self._y_channel: str = ""
        self._parent_population_id: str = "all_events"
        self._polygon_vertices: list[tuple[float, float]] = []
        self._collecting_polygon: bool = False
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def set_plot_channels(self, x: str, y: str) -> None:
        """Update the X/Y channel names used for new gates."""
        self._x_channel = x
        self._y_channel = y

    def set_parent_population(self, population_id: str) -> None:
        """Set the parent population id for new gates."""
        self._parent_population_id = population_id
        idx = self._parent_combo.findData(population_id)
        if idx >= 0:
            self._parent_combo.setCurrentIndex(idx)

    def parent_population(self) -> str:
        """Return the parent population id for new gates."""
        return self._parent_population_id

    def gates(self) -> list[GateSpec]:
        """Return all defined gates."""
        return list(self._gates)

    def add_gate(self, gate: GateSpec) -> None:
        """Add a gate programmatically."""
        candidate = [*self._gates, gate]
        self._validate_gates(candidate)
        self._gates = candidate
        self._add_gate_list_item(gate)
        self._refresh_parent_population_combo()
        self._status_label.setText("Ready")
        self._emit_gates_changed()

    def update_gate(self, index: int, gate: GateSpec, notify: bool = True) -> None:
        """Replace an existing gate definition and refresh the list label."""
        if index < 0 or index >= len(self._gates):
            return
        candidate = list(self._gates)
        candidate[index] = gate
        self._validate_gates(candidate)
        self._gates = candidate
        item = self._list_widget.item(index)
        if item is not None:
            self._updating_list_item = True
            try:
                item.setText(self._gate_label(gate))
            finally:
                self._updating_list_item = False
        self._refresh_parent_population_combo()
        if notify:
            self._emit_gates_changed()

    def clear_gates(self) -> None:
        """Remove all gates."""
        self._gates.clear()
        self._list_widget.clear()
        self._refresh_parent_population_combo()
        self._emit_gates_changed()

    def set_gates(self, gates: list[GateSpec], notify: bool = True) -> None:
        """Replace all gates after validating their complete dependency graph."""
        self._validate_gates(gates)
        self._gates = list(gates)
        self._list_widget.clear()
        for gate in self._gates:
            self._add_gate_list_item(gate)
        self._refresh_parent_population_combo()
        if notify:
            self._emit_gates_changed()

    def receive_polygon_vertex(self, data_x: float, data_y: float) -> None:
        """Add a vertex to the in-progress polygon gate.

        Call this from the main window when the user clicks on the plot.
        """
        if not self._collecting_polygon:
            return
        if self._polygon_vertices:
            last_x, last_y = self._polygon_vertices[-1]
            if abs(last_x - data_x) < 1e-12 and abs(last_y - data_y) < 1e-12:
                return
        self._polygon_vertices.append((data_x, data_y))

    def finish_polygon_gate(self, gate_name: str | None = None) -> None:
        """Finish collecting polygon vertices and create the gate."""
        if not self._collecting_polygon:
            return

        coords = tuple(self._polygon_vertices)
        if len(coords) < 3:
            QMessageBox.warning(
                self,
                "Polygon incomplete",
                "A polygon requires at least 3 vertices.",
            )
            self._cancel_polygon()
            return

        name = gate_name or "gate_polygon"
        gate = GateSpec(
            id=self._next_gate_id(),
            name=name,
            gate_type="polygon",
            parent_population_id=self._parent_population_id,
            x_parameter=self._x_channel,
            y_parameter=self._y_channel,
            coordinates=coords,
        )
        self._gates.append(gate)
        self._add_gate_list_item(gate)
        self._refresh_parent_population_combo()
        self._cancel_polygon()
        self._emit_gates_changed()

    def start_polygon_collection(self) -> None:
        """Begin collecting polygon vertices from plot clicks."""
        self._collecting_polygon = True
        self._polygon_vertices = []
        self._status_label.setText("Click on plot to add polygon vertices...")

    def is_collecting_polygon(self) -> bool:
        return self._collecting_polygon

    def cancel_polygon(self) -> None:
        """Cancel in-progress polygon collection."""
        self._cancel_polygon()

    # -- callbacks -----------------------------------------------------------

    def on_gate_selected(self, callback) -> None:
        """Register callback when a gate is selected in the list.

        Callback receives ``(gate_index: int)``.
        """
        self._gate_selected_callbacks.append(callback)

    def on_gates_changed(self, callback) -> None:
        """Register callback when the gate list changes.

        Fired on gate add, delete, clear, and polygon finish.
        Callback receives no arguments.
        """
        self._gates_changed_callbacks.append(callback)

    def on_interactive_gate_requested(self, callback) -> None:
        """Register callback for plot-based gate creation requests.

        Callback receives ``(gate_type: str)``.  Rectangle and polygon gates
        are drawn on the plot pane; range gates still use the numeric dialog.
        """
        self._interactive_gate_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _emit_gates_changed(self) -> None:
        """Notify all gates-changed callbacks."""
        for cb in self._gates_changed_callbacks:
            try:
                cb()
            except Exception:
                pass

    def _emit_interactive_gate_requested(self, gate_type: str) -> bool:
        accepted = False
        for cb in self._interactive_gate_callbacks:
            try:
                if cb(gate_type):
                    accepted = True
            except Exception:
                pass
        return accepted

    def _cancel_polygon(self) -> None:
        self._collecting_polygon = False
        self._polygon_vertices.clear()
        self._status_label.setText("Ready")

    def _next_gate_id(self) -> str:
        return f"gate_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _validate_gates(gates: list[GateSpec]) -> None:
        ordered_gates(
            GatingStrategySpec(id="gui_strategy", name="GUI Strategy", gates=tuple(gates))
        )

    def _available_populations(self) -> list[tuple[str, str]]:
        return [("all_events", "All Events")] + [
            (gate.id, gate.name) for gate in self._gates
        ]

    def _refresh_parent_population_combo(self) -> None:
        current = self._parent_population_id
        self._parent_combo.blockSignals(True)
        try:
            self._parent_combo.clear()
            for pop_id, label in self._available_populations():
                self._parent_combo.addItem(label, pop_id)
            idx = self._parent_combo.findData(current)
            if idx < 0:
                idx = 0
            self._parent_combo.setCurrentIndex(idx)
            self._parent_population_id = self._parent_combo.currentData()
        finally:
            self._parent_combo.blockSignals(False)

    def _create_gate_dialog(self) -> None:
        """Show gate creation dialog."""
        gate_type = self._type_combo.currentText()
        x_ch = self._x_channel or "X"
        y_ch = self._y_channel or "Y"
        self._parent_population_id = self._parent_combo.currentData() or "all_events"

        if gate_type in {"rectangle", "polygon"}:
            if not self._emit_interactive_gate_requested(gate_type):
                self._status_label.setText("Ready")
                return
            if gate_type == "rectangle":
                self._status_label.setText("Drag on plot to create rectangle gate...")
            else:
                self._status_label.setText("Click plot vertices; double-click to finish...")
            return

        dlg = _GateDialog(
            gate_type,
            x_ch,
            y_ch,
            self._available_populations(),
            self,
        )
        if dlg.exec() != QDialog.Accepted:
            return

        name = dlg.name()
        thresholds = dlg.thresholds()
        if gate_type == "boolean":
            source_ids = thresholds.get("source_ids", [])
            operation = thresholds.get("operation")
            min_sources = 1 if operation == "not" else 2
            if len(source_ids) < min_sources:
                QMessageBox.warning(
                    self,
                    "Boolean gate incomplete",
                    "Select enough source populations for the boolean operation.",
                )
                return
        gate_id = self._next_gate_id()

        gate = GateSpec(
            id=gate_id,
            name=name,
            gate_type=gate_type,
            parent_population_id=self._parent_population_id,
            x_parameter=self._x_channel if gate_type != "boolean" else None,
            y_parameter=self._y_channel if gate_type not in {"range", "boolean"} else None,
            thresholds=thresholds,
        )
        try:
            self._validate_gates([*self._gates, gate])
        except GatingStrategyError as exc:
            QMessageBox.warning(self, "Invalid gate", str(exc))
            return

        self._gates.append(gate)
        self._add_gate_list_item(gate)
        self._refresh_parent_population_combo()
        self._emit_gates_changed()

    def _delete_selected_gate(self) -> None:
        idx = self._list_widget.currentRow()
        if idx < 0:
            return
        if idx >= len(self._gates):
            return
        gate_id = self._gates[idx].id
        dependents = [
            gate.id
            for gate in self._gates
            if gate.parent_population_id == gate_id
            or gate_id in gate.thresholds.get("source_ids", [])
        ]
        if dependents:
            QMessageBox.warning(
                self,
                "Gate is referenced",
                f"Cannot delete {gate_id!r}; referenced by: {', '.join(dependents)}",
            )
            return
        self._gates.pop(idx)
        item = self._list_widget.takeItem(idx)
        del item  # free Qt object
        self._refresh_parent_population_combo()
        self._emit_gates_changed()

    def _on_list_selection_changed(self) -> None:
        idx = self._list_widget.currentRow()
        for cb in self._gate_selected_callbacks:
            try:
                cb(idx)
            except Exception:
                pass

    def _on_item_changed(self, item) -> None:
        if self._updating_list_item:
            return
        idx = self._list_widget.row(item)
        if idx < 0 or idx >= len(self._gates):
            return
        gate = self._gates[idx]
        new_name = self._name_from_item_text(item.text(), gate.gate_type)
        if not new_name:
            self._updating_list_item = True
            try:
                item.setText(self._gate_label(gate))
            finally:
                self._updating_list_item = False
            return
        if new_name == gate.name:
            return
        updated_gate = replace(gate, name=new_name)
        self._gates[idx] = updated_gate
        self._updating_list_item = True
        try:
            item.setText(self._gate_label(updated_gate))
        finally:
            self._updating_list_item = False
        self._refresh_parent_population_combo()
        self._emit_gates_changed()

    def _add_gate_list_item(self, gate: GateSpec) -> None:
        from PySide6.QtWidgets import QListWidgetItem  # noqa: N812

        item = QListWidgetItem(self._gate_label(gate))
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self._list_widget.addItem(item)

    def _gate_label(self, gate: GateSpec) -> str:
        return f"{gate.name} ({gate.gate_type})"

    def _name_from_item_text(self, text: str, gate_type: str) -> str:
        value = text.strip()
        suffix = f" ({gate_type})"
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
        return value

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._gate_selected_callbacks: list[Any] = []
        self._gates_changed_callbacks: list[Any] = []
        self._interactive_gate_callbacks: list[Any] = []
        self._updating_list_item = False

        # Gate type selector
        self._type_combo = QComboBox()
        self._type_combo.addItems(["rectangle", "range", "polygon", "boolean"])

        self._parent_combo = QComboBox()
        self._parent_combo.currentIndexChanged.connect(
            lambda *_args: setattr(
                self,
                "_parent_population_id",
                self._parent_combo.currentData() or "all_events",
            )
        )

        # Buttons
        self._btn_create = QPushButton("Create Gate")
        self._btn_create.clicked.connect(self._create_gate_dialog)

        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.clicked.connect(self._delete_selected_gate)

        # Gate list
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)
        self._list_widget.itemChanged.connect(self._on_item_changed)

        # Status
        self._status_label = QLabel("Ready")

        # Layout
        box = QGroupBox("Gates")
        box_layout = QVBoxLayout(box)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_create)
        btn_row.addWidget(self._btn_delete)

        box_layout.addWidget(QLabel("Gate type:"))
        box_layout.addWidget(self._type_combo)
        box_layout.addWidget(QLabel("Parent population:"))
        box_layout.addWidget(self._parent_combo)
        box_layout.addLayout(btn_row)
        box_layout.addWidget(QLabel("Defined gates:"))
        box_layout.addWidget(self._list_widget)
        box_layout.addWidget(self._status_label)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        self._refresh_parent_population_combo()
