"""Plot toolbar for viewport and export actions.

Gate creation is started from the gate editor's ``Create Gate`` action.
This toolbar intentionally does not expose persistent interaction modes:
normal mouse input belongs to pyqtgraph navigation unless an interactive
gate creation is in progress.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QButtonGroup, QToolBar, QToolButton, QWidget

from flowdesk_qt.diagnostics import invoke_callback


class PlotToolbar(QToolBar):
    """Toolbar for plot display actions.

    Callbacks:
      on_reset_robust()
      on_reset_full()
      on_export_png()
      on_marginal_toggled(enabled: bool)
      on_add_statistic()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Plot Tools", parent)
        self.setObjectName("plotToolbar")
        self.setMovable(False)
        self._callbacks: dict[str, list[Callable]] = {
            "reset_robust": [],
            "reset_full": [],
            "export_png": [],
            "export_svg": [],
            "export_pdf": [],
            "marginal_toggled": [],
            "add_statistic": [],
            "interaction_mode": [],
        }
        self._marginal_enabled: bool = False
        self._build_toolbar()

    def is_marginal_enabled(self) -> bool:
        """Return whether marginal histograms are currently enabled."""
        return self._marginal_enabled

    def set_marginal_enabled(self, enabled: bool) -> None:
        """Programmatically enable or disable marginal histograms."""
        self._marginal_enabled = enabled
        if hasattr(self, "_marginal_checkbox"):
            self._marginal_checkbox.setChecked(enabled)

    def set_marginal_available(self, available: bool) -> None:
        """Disable the control while a 1D histogram is displayed."""
        self._marginal_checkbox.setEnabled(available)

    def on_reset_robust(self, callback: Callable[[], None]) -> None:
        """Register callback for reset to robust auto-range."""
        self._callbacks["reset_robust"].append(callback)

    def on_reset_full(self, callback: Callable[[], None]) -> None:
        """Register callback for reset to full data range."""
        self._callbacks["reset_full"].append(callback)

    def on_export_png(self, callback: Callable[[], None]) -> None:
        """Register callback for PNG export request."""
        self._callbacks["export_png"].append(callback)

    def on_export_svg(self, callback: Callable[[], None]) -> None:
        self._callbacks["export_svg"].append(callback)

    def on_export_pdf(self, callback: Callable[[], None]) -> None:
        self._callbacks["export_pdf"].append(callback)

    def on_marginal_toggled(self, callback: Callable[[bool], None]) -> None:
        """Register callback for marginal histogram toggle."""
        self._callbacks["marginal_toggled"].append(callback)

    def on_add_statistic(self, callback: Callable[[], None]) -> None:
        """Register a callback to create a statistic from the graph context."""
        self._callbacks["add_statistic"].append(callback)

    def on_interaction_mode(self, callback: Callable[[str], None]) -> None:
        self._callbacks["interaction_mode"].append(callback)

    def _emit(self, key: str, *args: Any) -> None:
        for cb in self._callbacks.get(key, []):
            invoke_callback(cb, *args)

    def _on_reset_robust_clicked(self) -> None:
        self._emit("reset_robust")

    def _on_reset_full_clicked(self) -> None:
        self._emit("reset_full")

    def _on_export_clicked(self) -> None:
        self._emit("export_png")

    def _on_export_svg_clicked(self) -> None:
        self._emit("export_svg")

    def _on_export_pdf_clicked(self) -> None:
        self._emit("export_pdf")

    def _on_add_statistic_clicked(self) -> None:
        self._emit("add_statistic")

    def _on_marginal_toggled(self, checked: bool) -> None:
        self._marginal_enabled = checked
        self._emit("marginal_toggled", checked)

    def _on_interaction_mode(self, mode: str) -> None:
        self._emit("interaction_mode", mode)

    def _build_toolbar(self) -> None:
        btn_robust = QToolButton()
        btn_robust.setObjectName("resetRobustRangeButton")
        btn_robust.setText("Reset Robust Range")
        btn_robust.setToolTip("Reset viewport to robust auto-range (0.5%-99.5% percentiles)")
        btn_robust.clicked.connect(self._on_reset_robust_clicked)
        self.addWidget(btn_robust)

        btn_full = QToolButton()
        btn_full.setObjectName("resetFullRangeButton")
        btn_full.setText("Reset Full Range")
        btn_full.setToolTip("Reset viewport to full data range")
        btn_full.clicked.connect(self._on_reset_full_clicked)
        self.addWidget(btn_full)

        self.addSeparator()

        btn_export = QToolButton()
        btn_export.setObjectName("exportPngButton")
        btn_export.setText("Export PNG")
        btn_export.setToolTip("Export current plot view to PNG")
        btn_export.clicked.connect(self._on_export_clicked)
        self.addWidget(btn_export)

        btn_svg = QToolButton()
        btn_svg.setObjectName("exportSvgButton")
        btn_svg.setText("Export SVG")
        btn_svg.clicked.connect(self._on_export_svg_clicked)
        self.addWidget(btn_svg)

        btn_pdf = QToolButton()
        btn_pdf.setObjectName("exportPdfButton")
        btn_pdf.setText("Export PDF")
        btn_pdf.clicked.connect(self._on_export_pdf_clicked)
        self.addWidget(btn_pdf)

        btn_statistic = QToolButton()
        btn_statistic.setObjectName("addStatisticFromGraphButton")
        btn_statistic.setText("Add Statistic")
        btn_statistic.setToolTip(
            "Create a statistic definition using the graph X parameter"
        )
        btn_statistic.clicked.connect(self._on_add_statistic_clicked)
        self.addWidget(btn_statistic)

        self.addSeparator()
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        for mode, label in (("pan", "Pan"), ("select", "Select"), ("gate", "Gate")):
            button = QToolButton()
            button.setObjectName(f"{mode}InteractionModeButton")
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(mode == "pan")
            button.clicked.connect(lambda _checked, value=mode: self._on_interaction_mode(value))
            mode_group.addButton(button)
            self.addWidget(button)

        self.addSeparator()

        self._marginal_checkbox = QToolButton()
        self._marginal_checkbox.setText("Marginals")
        self._marginal_checkbox.setCheckable(True)
        self._marginal_checkbox.setObjectName("toggleMarginalHistogramsButton")
        self._marginal_checkbox.setToolTip("Toggle marginal histograms on X and Y axes")
        self._marginal_checkbox.toggled.connect(self._on_marginal_toggled)
        self.addWidget(self._marginal_checkbox)
