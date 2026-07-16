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
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.gating_strategy import GatingStrategyError, ordered_gates
from flowdesk_core.models import GateSpec, GatingStrategySpec
from flowdesk_qt.diagnostics import invoke_callback

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
        population_parents: dict[str, str | None] | None = None,
        parent: QWidget | None = None,
        initial_gate: GateSpec | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Gate")
        self._gate_type = gate_type
        self._x_channel = x_channel
        self._y_channel = y_channel
        self._available_populations = available_populations or []
        self._population_parents = population_parents or {}
        self._initial_gate = initial_gate
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
            if self._initial_gate is not None:
                values = self._initial_gate.thresholds
                self._x_min.setValue(float(values.get("x_min", 0.0)))
                self._x_max.setValue(float(values.get("x_max", 10000.0)))
                self._y_min.setValue(float(values.get("y_min", 0.0)))
                self._y_max.setValue(float(values.get("y_max", 10000.0)))

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
            if self._initial_gate is not None:
                values = self._initial_gate.thresholds
                self._r_min.setValue(float(values.get("min", 0.0)))
                self._r_max.setValue(float(values.get("max", 10000.0)))

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
            self._coordinates_table = QTableWidget(0, 2)
            self._coordinates_table.setHorizontalHeaderLabels(["X", "Y"])
            self._coordinates_table.setObjectName("polygonCoordinatesTable")
            for x_value, y_value in (
                self._initial_gate.coordinates if self._initial_gate else ()
            ):
                row = self._coordinates_table.rowCount()
                self._coordinates_table.insertRow(row)
                self._coordinates_table.setItem(row, 0, QTableWidgetItem(str(x_value)))
                self._coordinates_table.setItem(row, 1, QTableWidgetItem(str(y_value)))
            layout.addRow("Vertices (data coordinates):", self._coordinates_table)

        elif self._gate_type == "ellipse":
            self._center_x = QDoubleSpinBox()
            self._center_y = QDoubleSpinBox()
            self._radius_x = QDoubleSpinBox()
            self._radius_y = QDoubleSpinBox()
            self._rotation = QDoubleSpinBox()
            for editor in (
                self._center_x,
                self._center_y,
                self._radius_x,
                self._radius_y,
                self._rotation,
            ):
                editor.setRange(-1e10, 1e10)
                editor.setDecimals(8)
            self._radius_x.setValue(10000.0)
            self._radius_y.setValue(10000.0)
            if self._initial_gate is not None:
                values = self._initial_gate.thresholds
                self._center_x.setValue(float(values.get("center_x", 0.0)))
                self._center_y.setValue(float(values.get("center_y", 0.0)))
                self._radius_x.setValue(float(values.get("radius_x", 10000.0)))
                self._radius_y.setValue(float(values.get("radius_y", 10000.0)))
                self._rotation.setValue(float(values.get("rotation", 0.0)))
            layout.addRow(f"Center X ({self._x_channel}):", self._center_x)
            layout.addRow(f"Center Y ({self._y_channel}):", self._center_y)
            layout.addRow("Radius X:", self._radius_x)
            layout.addRow("Radius Y:", self._radius_y)
            layout.addRow("Rotation (radians):", self._rotation)

        elif self._gate_type == "boolean":
            self._operation_combo = QComboBox()
            self._operation_combo.addItems(["and", "or", "not"])
            self._source_list = QListWidget()
            self._source_list.setSelectionMode(QAbstractItemView.MultiSelection)
            for pop_id, label in self._available_populations:
                item = QListWidgetItem(f"{label} [{pop_id}]")
                item.setData(Qt.UserRole, pop_id)
                self._source_list.addItem(item)
            self._source_list.hide()
            self._source_tree = QTreeWidget()
            self._source_tree.setObjectName("booleanSourcePopulationTree")
            self._source_tree.setHeaderLabels(["Source population"])
            self._source_tree.setSelectionMode(QAbstractItemView.MultiSelection)
            tree_items: dict[str, QTreeWidgetItem] = {}
            root = QTreeWidgetItem(["All Events [all_events]"])
            root.setData(0, Qt.UserRole, "all_events")
            self._source_tree.addTopLevelItem(root)
            tree_items["all_events"] = root
            pending = [
                (pop_id, label)
                for pop_id, label in self._available_populations
                if pop_id != "all_events"
            ]
            while pending:
                progressed = False
                for pop_id, label in list(pending):
                    parent_id = self._population_parents.get(pop_id) or "all_events"
                    parent_item = tree_items.get(parent_id)
                    if parent_item is None:
                        continue
                    item = QTreeWidgetItem([f"{label} [{pop_id}]"])
                    item.setData(0, Qt.UserRole, pop_id)
                    parent_item.addChild(item)
                    tree_items[pop_id] = item
                    pending.remove((pop_id, label))
                    progressed = True
                if not progressed:
                    break
            root.setExpanded(True)
            layout.addRow("Operation:", self._operation_combo)
            layout.addRow("Source populations:", self._source_tree)

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

        elif self._gate_type == "ellipse":
            self._thresholds.update(
                {
                    "center_x": self._center_x.value(),
                    "center_y": self._center_y.value(),
                    "radius_x": self._radius_x.value(),
                    "radius_y": self._radius_y.value(),
                    "rotation": self._rotation.value(),
                }
            )

        elif self._gate_type == "polygon":
            self._coordinates = []
            for row in range(self._coordinates_table.rowCount()):
                try:
                    x_value = float(self._coordinates_table.item(row, 0).text())
                    y_value = float(self._coordinates_table.item(row, 1).text())
                except (AttributeError, ValueError):
                    continue
                self._coordinates.append((x_value, y_value))

        elif self._gate_type == "boolean":
            source_ids = {
                item.data(Qt.UserRole)
                for item in self._source_list.selectedItems()
            }
            source_ids.update(
                item.data(0, Qt.UserRole)
                for item in self._source_tree.selectedItems()
            )
            self._thresholds["operation"] = self._operation_combo.currentText()
            self._thresholds["source_ids"] = sorted(source_ids)

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
        self._x_scale: str = "linear"
        self._y_scale: str = "linear"
        self._x_transform_id: str | None = None
        self._y_transform_id: str | None = None
        self._parent_population_id: str = "all_events"
        self._polygon_vertices: list[tuple[float, float]] = []
        self._collecting_polygon: bool = False
        self._current_sample_id: str = ""
        self._population_stats: dict[str, tuple[int, float | None, float | None]] = {}
        self._child_gate_mode = False
        self._previous_parent_population_id = "all_events"
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def set_plot_channels(self, x: str, y: str) -> None:
        """Update the X/Y channel names used for new gates."""
        self._x_channel = x
        self._y_channel = y
        self._update_creation_banner()

    def set_plot_scales(self, x_scale: str, y_scale: str) -> None:
        """Set coordinate scales used by newly created gates."""
        self._x_scale = x_scale
        self._y_scale = y_scale
        self._update_creation_banner()

    def set_plot_transforms(
        self, x_transform_id: str | None, y_transform_id: str | None
    ) -> None:
        """Bind exact analysis coordinate IDs used by newly drawn gates."""
        self._x_transform_id = x_transform_id
        self._y_transform_id = y_transform_id
        self._update_creation_banner()

    def set_current_sample_id(self, sample_id: str | None) -> None:
        self._current_sample_id = sample_id or ""
        self._update_creation_banner()

    def set_overlay_status(self, reasons: list[str]) -> None:
        if reasons:
            self._status_label.setText("Hidden: " + "; ".join(reasons))
        elif not self._collecting_polygon:
            self._status_label.setText("Ready")

    def set_population_results(self, results) -> None:
        """Attach display-only count/frequency details to hierarchy tooltips."""
        self._population_stats = {
            result.population_id: (
                result.event_count,
                result.frequency_of_parent,
                result.frequency_of_total,
            )
            for result in results
            if not self._current_sample_id or result.sample_id == self._current_sample_id
        }
        self._refresh_hierarchy_tree(
            self.selected_gate().id if self.selected_gate() else None
        )

    def clear_population_results(self) -> None:
        self._population_stats.clear()
        self._refresh_hierarchy_tree(
            self.selected_gate().id if self.selected_gate() else None
        )

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

    def selected_gate(self) -> GateSpec | None:
        """Return the selected hierarchy gate, identified by stable id."""
        item = self._tree_widget.currentItem()
        if item is None:
            return None
        gate_id = item.data(0, Qt.UserRole)
        return next((gate for gate in self._gates if gate.id == gate_id), None)

    def select_gate(self, gate_id: str) -> bool:
        item = self._tree_items.get(gate_id)
        if item is None:
            return False
        self._tree_widget.setCurrentItem(item)
        return True

    def begin_child_gate(self, parent_id: str) -> bool:
        """Explicitly choose a population as parent for the next gate."""
        if parent_id != "all_events" and not any(
            gate.id == parent_id for gate in self._gates
        ):
            return False
        if not self._child_gate_mode:
            self._previous_parent_population_id = self._parent_population_id
        self._child_gate_mode = True
        self.set_parent_population(parent_id)
        self._update_creation_banner()
        self._status_label.setText("Child-gate mode ready")
        return True

    def cancel_child_gate_mode(self) -> None:
        if not self._child_gate_mode:
            return
        previous = self._previous_parent_population_id
        self._child_gate_mode = False
        self.set_parent_population(previous)
        self._status_label.setText("Ready")

    def _finish_child_gate_mode(self) -> None:
        if not self._child_gate_mode:
            return
        previous = self._previous_parent_population_id
        self._child_gate_mode = False
        self.set_parent_population(previous)

    def reparent_gate(self, gate_id: str, parent_id: str | None) -> None:
        """Atomically reparent a gate after validating the complete graph."""
        index = next(
            (i for i, gate in enumerate(self._gates) if gate.id == gate_id), -1
        )
        if index < 0:
            raise GatingStrategyError(f"unknown gate: {gate_id!r}")
        parent_id = parent_id or "all_events"
        candidate = list(self._gates)
        candidate[index] = replace(candidate[index], parent_population_id=parent_id)
        self._validate_gates(candidate)
        self._gates = candidate
        self._refresh_all_views(select_gate_id=gate_id)
        self._emit_gates_changed()

    def update_boolean_gate(
        self,
        gate_id: str,
        operation: str,
        source_ids: list[str],
        parent_id: str | None = None,
    ) -> None:
        """Atomically update an existing Boolean expression by population id."""
        index = next(
            (i for i, gate in enumerate(self._gates) if gate.id == gate_id), -1
        )
        if index < 0 or self._gates[index].gate_type != "boolean":
            raise GatingStrategyError(f"unknown Boolean gate: {gate_id!r}")
        expected = 1 if operation == "not" else 2
        if (operation == "not" and len(source_ids) != 1) or (
            operation in {"and", "or"} and len(source_ids) < expected
        ):
            raise GatingStrategyError(
                f"Boolean {operation!r} has invalid source count: {len(source_ids)}"
            )
        updated = replace(
            self._gates[index],
            parent_population_id=parent_id or self._gates[index].parent_population_id,
            thresholds={"operation": operation, "source_ids": list(source_ids)},
        )
        candidate = list(self._gates)
        candidate[index] = updated
        self._validate_gates(candidate)
        self._gates = candidate
        self._refresh_all_views(select_gate_id=gate_id)
        self._emit_gates_changed()

    def add_gate(self, gate: GateSpec) -> None:
        """Add a gate programmatically."""
        candidate = [*self._gates, gate]
        self._validate_gates(candidate)
        self._gates = candidate
        self._add_gate_list_item(gate)
        self._refresh_all_views(select_gate_id=gate.id)
        self._status_label.setText("Ready")
        self._emit_gates_changed()
        self._finish_child_gate_mode()

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
        self._refresh_all_views(select_gate_id=gate.id)
        if notify:
            self._emit_gates_changed()

    def clear_gates(self) -> None:
        """Remove all gates."""
        self._gates.clear()
        self._list_widget.clear()
        self._refresh_all_views()
        self._emit_gates_changed()

    def set_gates(self, gates: list[GateSpec], notify: bool = True) -> None:
        """Replace all gates after validating their complete dependency graph."""
        self._validate_gates(gates)
        self._gates = list(gates)
        self._list_widget.clear()
        for gate in self._gates:
            self._add_gate_list_item(gate)
        self._refresh_all_views()
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
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            x_transform_id=self._x_transform_id,
            y_transform_id=self._y_transform_id,
            coordinates=coords,
        )
        self._gates.append(gate)
        self._add_gate_list_item(gate)
        self._refresh_all_views(select_gate_id=gate.id)
        self._cancel_polygon()
        self._emit_gates_changed()
        self._finish_child_gate_mode()

    def start_polygon_collection(self) -> None:
        """Begin collecting polygon vertices from plot clicks."""
        self._collecting_polygon = True
        self._polygon_vertices = []
        self._status_label.setText("Click on plot to add polygon vertices...")

    def is_collecting_polygon(self) -> bool:
        return self._collecting_polygon

    def cancel_polygon(self, preserve_child_mode: bool = False) -> None:
        """Cancel in-progress polygon collection."""
        self._cancel_polygon()
        if not preserve_child_mode:
            self.cancel_child_gate_mode()

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

    def on_show_gate(self, callback) -> None:
        """Register display-only navigation callback receiving a GateSpec."""
        self._show_gate_callbacks.append(callback)

    def on_migrate_gate(self, callback) -> None:
        """Register an explicit coordinate-migration request callback."""
        self._migrate_gate_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _emit_gates_changed(self) -> None:
        """Notify all gates-changed callbacks."""
        for cb in self._gates_changed_callbacks:
            invoke_callback(cb)

    def _emit_interactive_gate_requested(self, gate_type: str) -> bool:
        accepted = False
        for cb in self._interactive_gate_callbacks:
            if invoke_callback(cb, gate_type):
                accepted = True
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
                self.cancel_child_gate_mode()
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
            {gate.id: gate.parent_population_id for gate in self._gates},
            self,
        )
        if dlg.exec() != QDialog.Accepted:
            self.cancel_child_gate_mode()
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
                self.cancel_child_gate_mode()
                return
        gate_id = self._next_gate_id()

        gate = GateSpec(
            id=gate_id,
            name=name,
            gate_type=gate_type,
            parent_population_id=self._parent_population_id,
            x_parameter=self._x_channel if gate_type != "boolean" else None,
            y_parameter=self._y_channel if gate_type not in {"range", "boolean"} else None,
            x_scale=self._x_scale,
            y_scale=self._y_scale,
            x_transform_id=self._x_transform_id if gate_type != "boolean" else None,
            y_transform_id=(
                self._y_transform_id
                if gate_type not in {"range", "boolean"} else None
            ),
            thresholds=thresholds,
            coordinates=tuple(dlg.coordinates()),
        )
        try:
            self._validate_gates([*self._gates, gate])
        except GatingStrategyError as exc:
            QMessageBox.warning(self, "Invalid gate", str(exc))
            self.cancel_child_gate_mode()
            return

        self._gates.append(gate)
        self._add_gate_list_item(gate)
        self._refresh_all_views(select_gate_id=gate.id)
        self._emit_gates_changed()
        self._finish_child_gate_mode()

    def _on_edit_geometry_clicked(self) -> None:
        """Edit geometric thresholds/vertices in data coordinates."""
        gate = self.selected_gate()
        if gate is None or gate.gate_type not in {
            "rectangle",
            "range",
            "polygon",
            "ellipse",
        }:
            QMessageBox.information(
                self,
                "Select geometric gate",
                "Select a rectangle, range, polygon, or ellipse gate.",
            )
            return
        dialog = _GateDialog(
            gate.gate_type,
            gate.x_parameter or self._x_channel,
            gate.y_parameter or self._y_channel,
            initial_gate=gate,
            parent=self,
        )
        dialog.setWindowTitle("Edit Gate Geometry")
        dialog._name_edit.setText(gate.name)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = replace(
            gate,
            name=dialog.name(),
            thresholds=dialog.thresholds(),
            coordinates=tuple(dialog.coordinates()),
        )
        index = next(i for i, value in enumerate(self._gates) if value.id == gate.id)
        try:
            self.update_gate(index, updated, notify=True)
        except GatingStrategyError as exc:
            QMessageBox.warning(self, "Invalid gate geometry", str(exc))

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
        self._refresh_all_views()
        self._emit_gates_changed()

    def _on_list_selection_changed(self) -> None:
        idx = self._list_widget.currentRow()
        for cb in self._gate_selected_callbacks:
            invoke_callback(cb, idx)

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
        self._refresh_all_views(select_gate_id=updated_gate.id)
        self._emit_gates_changed()

    def _refresh_all_views(self, select_gate_id: str | None = None) -> None:
        self._refresh_parent_population_combo()
        self._refresh_reparent_combo()
        self._refresh_hierarchy_tree(select_gate_id)
        self._update_creation_banner()
        if select_gate_id:
            index = next(
                (i for i, gate in enumerate(self._gates) if gate.id == select_gate_id),
                -1,
            )
            if index >= 0:
                self._list_widget.setCurrentRow(index)

    def _refresh_hierarchy_tree(self, select_gate_id: str | None = None) -> None:
        expanded = {
            gate_id for gate_id, item in self._tree_items.items() if item.isExpanded()
        }
        self._tree_widget.blockSignals(True)
        try:
            self._tree_widget.clear()
            self._tree_items = {}
            root = QTreeWidgetItem(["All Events", "root", "-", "-"])
            root.setData(0, Qt.UserRole, "all_events")
            self._tree_widget.addTopLevelItem(root)
            root.setExpanded(True)
            pending = list(self._gates)
            while pending:
                progressed = False
                for gate in list(pending):
                    parent_id = gate.parent_population_id or "all_events"
                    parent_item = (
                        root
                        if parent_id == "all_events"
                        else self._tree_items.get(parent_id)
                    )
                    if parent_item is None:
                        continue
                    expression = ""
                    if gate.gate_type == "boolean":
                        operation = str(gate.thresholds.get("operation", "")).upper()
                        sources = ", ".join(gate.thresholds.get("source_ids", []))
                        expression = f"{operation}({sources})"
                    axes = (
                        f"{gate.x_parameter or '-'} / {gate.y_parameter or '-'} "
                        f"[{gate.x_scale}/{gate.y_scale}]"
                    )
                    item = QTreeWidgetItem([gate.name, gate.gate_type, axes, expression])
                    item.setData(0, Qt.UserRole, gate.id)
                    item.setToolTip(
                        0,
                        self._gate_tooltip(gate, parent_id, expression),
                    )
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    parent_item.addChild(item)
                    self._tree_items[gate.id] = item
                    pending.remove(gate)
                    progressed = True
                if not progressed:
                    break
            for gate_id, item in self._tree_items.items():
                item.setExpanded(gate_id in expanded)
            selected = self._tree_items.get(select_gate_id or "")
            if selected is not None:
                self._tree_widget.setCurrentItem(selected)
        finally:
            self._tree_widget.blockSignals(False)

    def _gate_tooltip(
        self, gate: GateSpec, parent_id: str, expression: str
    ) -> str:
        lines = [f"id={gate.id}", f"parent={parent_id}"]
        if expression:
            lines.append(expression)
        stats = self._population_stats.get(gate.id)
        if stats is not None:
            count, parent_frequency, total_frequency = stats
            lines.extend(
                [
                    f"events={count}",
                    f"frequency_of_parent={parent_frequency}",
                    f"frequency_of_total={total_frequency}",
                ]
            )
        return "\n".join(lines)

    def _refresh_reparent_combo(self) -> None:
        selected = self.selected_gate()
        current_parent = selected.parent_population_id if selected else "all_events"
        self._reparent_combo.blockSignals(True)
        try:
            self._reparent_combo.clear()
            for pop_id, label in self._available_populations():
                self._reparent_combo.addItem(f"{label} [{pop_id}]", pop_id)
            index = self._reparent_combo.findData(current_parent)
            self._reparent_combo.setCurrentIndex(max(0, index))
        finally:
            self._reparent_combo.blockSignals(False)

    def _update_creation_banner(self) -> None:
        labels = dict(self._available_populations())
        parent_id = self._parent_population_id or "all_events"
        self._creation_banner.setText(
            f"Parent: {labels.get(parent_id, parent_id)} [{parent_id}] | "
            f"Sample: {self._current_sample_id or '-'} | "
            f"Axes: {self._x_channel or '-'} / {self._y_channel or '-'} | "
            f"Scale: {self._x_scale}/{self._y_scale}"
            f" | Transform IDs: {self._x_transform_id or '-'} / "
            f"{self._y_transform_id or '-'}"
        )

    def _on_tree_selection_changed(self) -> None:
        gate = self.selected_gate()
        if gate is not None:
            index = next(i for i, value in enumerate(self._gates) if value.id == gate.id)
            self._list_widget.setCurrentRow(index)
        self._refresh_reparent_combo()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_tree or column != 0:
            return
        gate_id = item.data(0, Qt.UserRole)
        index = next((i for i, gate in enumerate(self._gates) if gate.id == gate_id), -1)
        if index < 0:
            return
        name = item.text(0).strip()
        if not name:
            self._refresh_hierarchy_tree(gate_id)
            return
        self._gates[index] = replace(self._gates[index], name=name)
        legacy_item = self._list_widget.item(index)
        if legacy_item is not None:
            self._updating_list_item = True
            legacy_item.setText(self._gate_label(self._gates[index]))
            self._updating_list_item = False
        self._refresh_parent_population_combo()
        self._emit_gates_changed()

    def _on_create_child_clicked(self) -> None:
        item = self._tree_widget.currentItem()
        if item is None:
            return
        parent_id = item.data(0, Qt.UserRole)
        if self.begin_child_gate(parent_id):
            self._create_gate_dialog()

    def _on_show_gate_clicked(self) -> None:
        gate = self.selected_gate()
        if gate is None:
            return
        for callback in self._show_gate_callbacks:
            invoke_callback(callback, gate)

    def _on_migrate_gate_clicked(self) -> None:
        gate = self.selected_gate()
        if gate is None:
            QMessageBox.information(self, "Select gate", "Select a gate to migrate.")
            return
        for callback in self._migrate_gate_callbacks:
            invoke_callback(callback, gate)

    def _on_apply_parent_clicked(self) -> None:
        gate = self.selected_gate()
        if gate is None:
            return
        parent_id = self._reparent_combo.currentData() or "all_events"
        affected = [
            value.name
            for value in self._gates
            if value.parent_population_id == gate.id
            or gate.id in value.thresholds.get("source_ids", [])
        ]
        detail = ", ".join(affected) if affected else "no direct dependents"
        answer = QMessageBox.question(
            self,
            "Change gate parent?",
            f"Move {gate.name} [{gate.id}] under {parent_id}?\n"
            f"Affected dependents: {detail}",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.reparent_gate(gate.id, parent_id)
        except GatingStrategyError as exc:
            QMessageBox.warning(self, "Invalid parent", str(exc))

    def _on_edit_boolean_clicked(self) -> None:
        gate = self.selected_gate()
        if gate is None or gate.gate_type != "boolean":
            QMessageBox.information(
                self, "Select Boolean gate", "Select a Boolean gate to edit."
            )
            return
        available = [
            population for population in self._available_populations()
            if population[0] != gate.id
        ]
        dialog = _GateDialog(
            "boolean",
            self._x_channel,
            self._y_channel,
            available,
            {value.id: value.parent_population_id for value in self._gates},
            self,
        )
        dialog.setWindowTitle("Edit Boolean Gate")
        dialog._name_edit.setText(gate.name)
        operation = str(gate.thresholds.get("operation", "and"))
        dialog._operation_combo.setCurrentText(operation)
        source_ids = set(gate.thresholds.get("source_ids", []))
        for row in range(dialog._source_list.count()):
            item = dialog._source_list.item(row)
            item.setSelected(item.data(Qt.UserRole) in source_ids)
        iterator = QTreeWidgetItemIterator(dialog._source_tree)
        while iterator.value() is not None:
            item = iterator.value()
            item.setSelected(item.data(0, Qt.UserRole) in source_ids)
            iterator += 1
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.update_boolean_gate(
                gate.id,
                str(dialog.thresholds().get("operation")),
                list(dialog.thresholds().get("source_ids", [])),
            )
            index = next(i for i, value in enumerate(self._gates) if value.id == gate.id)
            renamed = replace(self._gates[index], name=dialog.name())
            self.update_gate(index, renamed, notify=True)
        except GatingStrategyError as exc:
            QMessageBox.warning(self, "Invalid Boolean gate", str(exc))

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
        self._show_gate_callbacks: list[Any] = []
        self._migrate_gate_callbacks: list[Any] = []
        self._updating_list_item = False
        self._updating_tree = False
        self._tree_items: dict[str, QTreeWidgetItem] = {}
        self.setObjectName("gateEditor")

        # Gate type selector
        self._type_combo = QComboBox()
        self._type_combo.setObjectName("gateTypeCombo")
        self._type_combo.addItems(
            ["rectangle", "range", "polygon", "ellipse", "boolean"]
        )

        self._parent_combo = QComboBox()
        self._parent_combo.setObjectName("parentPopulationCombo")
        self._parent_combo.currentIndexChanged.connect(
            lambda *_args: setattr(
                self,
                "_parent_population_id",
                self._parent_combo.currentData() or "all_events",
            )
        )
        self._parent_combo.currentIndexChanged.connect(self._update_creation_banner)

        self._creation_banner = QLabel()
        self._creation_banner.setObjectName("gateCreationContextLabel")
        self._creation_banner.setWordWrap(True)

        # Buttons
        self._btn_create = QPushButton("Create Gate")
        self._btn_create.setObjectName("createGateButton")
        self._btn_create.clicked.connect(self._create_gate_dialog)

        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.setObjectName("deleteGateButton")
        self._btn_delete.clicked.connect(self._delete_selected_gate)

        self._btn_create_child = QPushButton("Create Child Gate")
        self._btn_create_child.setObjectName("createChildGateButton")
        self._btn_create_child.clicked.connect(self._on_create_child_clicked)

        self._btn_show_gate = QPushButton("Show Gate")
        self._btn_show_gate.setObjectName("showGateButton")
        self._btn_show_gate.clicked.connect(self._on_show_gate_clicked)

        self._btn_migrate_gate = QPushButton("Migrate Transform")
        self._btn_migrate_gate.setObjectName("migrateGateTransformButton")
        self._btn_migrate_gate.clicked.connect(self._on_migrate_gate_clicked)

        self._btn_apply_parent = QPushButton("Apply Parent")
        self._btn_apply_parent.setObjectName("applyGateParentButton")
        self._btn_apply_parent.clicked.connect(self._on_apply_parent_clicked)

        self._btn_edit_boolean = QPushButton("Edit Boolean")
        self._btn_edit_boolean.setObjectName("editBooleanGateButton")
        self._btn_edit_boolean.clicked.connect(self._on_edit_boolean_clicked)

        self._btn_edit_geometry = QPushButton("Edit Geometry")
        self._btn_edit_geometry.setObjectName("editGateGeometryButton")
        self._btn_edit_geometry.clicked.connect(self._on_edit_geometry_clicked)

        self._reparent_combo = QComboBox()
        self._reparent_combo.setObjectName("selectedGateParentCombo")

        # Gate list
        self._list_widget = QListWidget()
        self._list_widget.setObjectName("gateList")
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)
        self._list_widget.itemChanged.connect(self._on_item_changed)
        self._list_widget.hide()

        self._tree_widget = QTreeWidget()
        self._tree_widget.setObjectName("gateHierarchyTree")
        self._tree_widget.setColumnCount(4)
        self._tree_widget.setHeaderLabels(["Population", "Type", "Axes / Scale", "Expression"])
        self._tree_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree_widget.currentItemChanged.connect(
            lambda *_args: self._on_tree_selection_changed()
        )
        self._tree_widget.itemChanged.connect(self._on_tree_item_changed)

        # Status
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("gateStatusLabel")

        # Layout
        box = QGroupBox("Gates")
        box_layout = QVBoxLayout(box)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_create)
        btn_row.addWidget(self._btn_create_child)
        btn_row.addWidget(self._btn_delete)

        box_layout.addWidget(QLabel("Gate type:"))
        box_layout.addWidget(self._type_combo)
        box_layout.addWidget(QLabel("Parent population:"))
        box_layout.addWidget(self._parent_combo)
        box_layout.addWidget(self._creation_banner)
        box_layout.addLayout(btn_row)
        box_layout.addWidget(QLabel("Gate hierarchy:"))
        box_layout.addWidget(self._tree_widget)
        detail_row = QHBoxLayout()
        detail_row.addWidget(self._btn_show_gate)
        detail_row.addWidget(self._btn_migrate_gate)
        detail_row.addWidget(self._reparent_combo)
        detail_row.addWidget(self._btn_apply_parent)
        detail_row.addWidget(self._btn_edit_boolean)
        detail_row.addWidget(self._btn_edit_geometry)
        box_layout.addLayout(detail_row)
        box_layout.addWidget(self._list_widget)
        box_layout.addWidget(self._status_label)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        self._refresh_all_views()
