"""Gate editor widget.

Allows the user to create and manage gate definitions.  Gate coordinates
are stored in **data coordinates**, never screen pixels.

This widget contains NO scientific execution logic.  It produces
``GateSpec`` objects that are consumed by ``flowdesk_core.gates`` and
``flowdesk_core.gating_strategy``.
"""

from __future__ import annotations

import uuid
from typing import Any

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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.models import GateSpec

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Gate")
        self._gate_type = gate_type
        self._x_channel = x_channel
        self._y_channel = y_channel
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

    def gates(self) -> list[GateSpec]:
        """Return all defined gates."""
        return list(self._gates)

    def add_gate(self, gate: GateSpec) -> None:
        """Add a gate programmatically."""
        self._gates.append(gate)
        self._list_widget.addItem(f"{gate.name} ({gate.gate_type})")
        self._status_label.setText("Ready")
        self._emit_gates_changed()

    def clear_gates(self) -> None:
        """Remove all gates."""
        self._gates.clear()
        self._list_widget.clear()
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
        self._list_widget.addItem(f"{gate.name} (polygon)")
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

    def _create_gate_dialog(self) -> None:
        """Show gate creation dialog."""
        gate_type = self._type_combo.currentText()
        x_ch = self._x_channel or "X"
        y_ch = self._y_channel or "Y"

        if gate_type in {"rectangle", "polygon"}:
            if not self._emit_interactive_gate_requested(gate_type):
                self._status_label.setText("Ready")
                return
            if gate_type == "rectangle":
                self._status_label.setText("Drag on plot to create rectangle gate...")
            else:
                self._status_label.setText("Click plot vertices; double-click to finish...")
            return

        dlg = _GateDialog(gate_type, x_ch, y_ch, self)
        if dlg.exec() != QDialog.Accepted:
            return

        name = dlg.name()
        thresholds = dlg.thresholds()
        gate_id = self._next_gate_id()

        gate = GateSpec(
            id=gate_id,
            name=name,
            gate_type=gate_type,
            parent_population_id=self._parent_population_id,
            x_parameter=self._x_channel,
            y_parameter=self._y_channel,
            thresholds=thresholds,
        )

        self._gates.append(gate)
        self._list_widget.addItem(f"{name} ({gate_type})")
        self._emit_gates_changed()

    def _delete_selected_gate(self) -> None:
        idx = self._list_widget.currentRow()
        if idx < 0:
            return
        if idx < len(self._gates):
            self._gates.pop(idx)
        item = self._list_widget.takeItem(idx)
        del item  # free Qt object
        self._emit_gates_changed()

    def _on_list_selection_changed(self) -> None:
        idx = self._list_widget.currentRow()
        for cb in self._gate_selected_callbacks:
            try:
                cb(idx)
            except Exception:
                pass

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._gate_selected_callbacks: list[Any] = []
        self._gates_changed_callbacks: list[Any] = []
        self._interactive_gate_callbacks: list[Any] = []

        # Gate type selector
        self._type_combo = QComboBox()
        self._type_combo.addItems(["rectangle", "range", "polygon"])

        # Buttons
        self._btn_create = QPushButton("Create Gate")
        self._btn_create.clicked.connect(self._create_gate_dialog)

        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.clicked.connect(self._delete_selected_gate)

        # Gate list
        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)

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
        box_layout.addLayout(btn_row)
        box_layout.addWidget(QLabel("Defined gates:"))
        box_layout.addWidget(self._list_widget)
        box_layout.addWidget(self._status_label)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
