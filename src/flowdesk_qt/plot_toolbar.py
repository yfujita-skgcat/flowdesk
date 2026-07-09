"""Plot toolbar with tool mode selection and plot actions.

Provides buttons for:
  - Tool mode selection (pan/select, rectangle gate, polygon gate, range gate)
  - Reset viewport (robust range / full range)
  - Export current plot view to PNG

This toolbar emits signals (via registered callbacks) when the active tool
mode or an action changes.  It contains NO scientific execution logic.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QButtonGroup,
    QToolBar,
    QToolButton,
    QWidget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool mode identifiers
# ---------------------------------------------------------------------------

TOOL_PAN = "pan"
TOOL_RECTANGLE_GATE = "rectangle_gate"
TOOL_POLYGON_GATE = "polygon_gate"
TOOL_RANGE_GATE = "range_gate"

ALL_TOOLS = [TOOL_PAN, TOOL_RECTANGLE_GATE, TOOL_POLYGON_GATE, TOOL_RANGE_GATE]

_TOOL_LABELS: dict[str, str] = {
    TOOL_PAN: "Pan / Select",
    TOOL_RECTANGLE_GATE: "Rectangle Gate",
    TOOL_POLYGON_GATE: "Polygon Gate",
    TOOL_RANGE_GATE: "Range Gate",
}

# ---------------------------------------------------------------------------
# PlotToolbar
# ---------------------------------------------------------------------------


class PlotToolbar(QToolBar):
    """Toolbar for plot interaction modes and actions.

    Callbacks:
      on_tool_mode_changed(mode: str)
      on_reset_robust()
      on_reset_full()
      on_export_png()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Plot Tools", parent)
        self.setMovable(False)
        self._current_tool: str = TOOL_PAN
        self._callbacks: dict[str, list[Callable]] = {
            "tool_mode_changed": [],
            "reset_robust": [],
            "reset_full": [],
            "export_png": [],
        }
        self._build_actions()
        self._build_toolbar()

    # -- public API ----------------------------------------------------------

    def current_tool(self) -> str:
        """Return the currently active tool mode identifier."""
        return self._current_tool

    def set_tool_mode(self, mode: str) -> None:
        """Set the active tool mode programmatically."""
        if mode not in ALL_TOOLS:
            return
        self._current_tool = mode
        for btn, btn_mode in self._tool_buttons.items():
            btn.setChecked(btn_mode == mode)

    def on_tool_mode_changed(self, callback: Callable[[str], None]) -> None:
        """Register callback for tool mode changes.

        Callback receives ``(mode: str)``.
        """
        self._callbacks["tool_mode_changed"].append(callback)

    def on_reset_robust(self, callback: Callable[[], None]) -> None:
        """Register callback for reset to robust auto-range."""
        self._callbacks["reset_robust"].append(callback)

    def on_reset_full(self, callback: Callable[[], None]) -> None:
        """Register callback for reset to full data range."""
        self._callbacks["reset_full"].append(callback)

    def on_export_png(self, callback: Callable[[], None]) -> None:
        """Register callback for PNG export request."""
        self._callbacks["export_png"].append(callback)

    # -- private ------------------------------------------------------------

    def _emit(self, key: str, *args: Any) -> None:
        for cb in self._callbacks.get(key, []):
            try:
                cb(*args)
            except Exception as exc:
                logger.error("Toolbar callback error: %s", exc)

    def _on_tool_toggled(self, button: QToolButton, mode: str) -> None:
        if button.isChecked():
            self._current_tool = mode
            self._emit("tool_mode_changed", mode)

    def _on_group_button_toggled(self, button: QToolButton, checked: bool) -> None:
        """Handle exclusive button group toggle."""
        if not checked:
            return
        mode = self._tool_buttons.get(button)
        if mode is None:
            return
        self._current_tool = mode
        self._emit("tool_mode_changed", mode)

    def _on_reset_robust_clicked(self) -> None:
        self._emit("reset_robust")

    def _on_reset_full_clicked(self) -> None:
        self._emit("reset_full")

    def _on_export_clicked(self) -> None:
        self._emit("export_png")

    def _build_actions(self) -> None:
        self._tool_buttons: dict[QToolButton, str] = {}
        self._tool_button_group: QButtonGroup | None = None

    def _build_toolbar(self) -> None:
        # --- Tool mode buttons (mutually exclusive toggle group) ---
        self._tool_button_group = QButtonGroup(self)
        self._tool_button_group.setExclusive(True)

        for idx, mode in enumerate(ALL_TOOLS):
            label = _TOOL_LABELS.get(mode, mode)
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setChecked(mode == self._current_tool)
            btn.setToolTip(label)

            self._tool_button_group.addButton(btn, idx)
            self._tool_buttons[btn] = mode
            self.addWidget(btn)

        # React to button group changes (exclusive toggle)
        self._tool_button_group.buttonToggled.connect(self._on_group_button_toggled)

        self.addSeparator()

        # --- Reset buttons ---
        btn_robust = QToolButton()
        btn_robust.setText("Reset Robust Range")
        btn_robust.setToolTip("Reset viewport to robust auto-range (0.5%-99.5% percentiles)")
        btn_robust.clicked.connect(self._on_reset_robust_clicked)
        self.addWidget(btn_robust)

        btn_full = QToolButton()
        btn_full.setText("Reset Full Range")
        btn_full.setToolTip("Reset viewport to full data range")
        btn_full.clicked.connect(self._on_reset_full_clicked)
        self.addWidget(btn_full)

        self.addSeparator()

        # --- Export ---
        btn_export = QToolButton()
        btn_export.setText("Export PNG")
        btn_export.setToolTip("Export current plot view to PNG")
        btn_export.clicked.connect(self._on_export_clicked)
        self.addWidget(btn_export)
