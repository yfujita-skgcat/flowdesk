"""Plot widget for 2D scatter plots.

Uses pyqtgraph for fast rendering.  Gate overlays are drawn as geometry
items (rectangles / polygons) in **data coordinates**.

This widget contains NO scientific execution logic.  It receives pre-
computed event arrays and gate definitions from the caller.

Axis transforms (linear, log10, asinh) are applied to the display data
before rendering.  The log10 path uses pyqtgraph's native ``setLogMode``
for proper axis tick formatting.  The asinh path pre-transforms the data
via ``flowdesk_core.transforms`` and plots on a linear axis.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from pyqtgraph import GraphicsLayoutWidget, ScatterPlotItem
from pyqtgraph.graphicsItems.ViewBox import ViewBox  # type: ignore[attr-defined]
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from flowdesk_core.models import GateSpec
from flowdesk_core.transforms import TransformError

AxisTransform = Literal["linear", "log10", "asinh"]

# ---------------------------------------------------------------------------
# PlotWidget
# ---------------------------------------------------------------------------


class PlotWidget(QWidget):
    """2D scatter plot with gate overlay and axis transform support.

    The widget renders points, axis labels, and gate geometries.
    All coordinates are in data space, never screen pixels.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scatter: ScatterPlotItem | None = None
        self._gate_items: list[Any] = []
        self._x_label: str = ""
        self._y_label: str = ""
        self._downsample_factor: int = 1
        self._mouse_callbacks: list[Any] = []
        # Axis transform state (display-only, defaults to linear).
        self._x_transform: AxisTransform = "linear"
        self._y_transform: AxisTransform = "linear"
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def set_downsample(self, factor: int) -> None:
        """Set the display downsample factor (>= 1).

        Downsampled data is used ONLY for rendering.  Gate coordinates are
        always in full-resolution data space.
        """
        if factor < 1:
            factor = 1
        self._downsample_factor = factor

    def set_axis_transforms(
        self,
        x_transform: AxisTransform = "linear",
        y_transform: AxisTransform = "linear",
    ) -> None:
        """Set the display axis transforms for X and Y.

        Args:
            x_transform: Transform for X axis (linear, log10, asinh).
            y_transform: Transform for Y axis (linear, log10, asinh).
        """
        self._x_transform = x_transform
        self._y_transform = y_transform

    def plot_events(
        self,
        x_data: NDArray[np.float64],
        y_data: NDArray[np.float64],
        x_label: str = "",
        y_label: str = "",
    ) -> None:
        """Render a scatter plot.

        Args:
          x_data: X values (full resolution).
          y_data: Y values (full resolution).
          x_label: X axis label.
          y_label: Y axis label.
        """
        self._x_label = x_label
        self._y_label = y_label

        # Apply axis transforms (display only).
        x_plot = self._apply_transform(x_data, self._x_transform)
        y_plot = self._apply_transform(y_data, self._y_transform)

        # Apply display downsample.
        if self._downsample_factor > 1 and len(x_plot) > 10_000:
            step = max(1, len(x_plot) // 10_000)
            x_plot = x_plot[::step]
            y_plot = y_plot[::step]

        # Remove NaN/Inf for plotting safety (does not affect analysis data).
        valid = ~np.isnan(x_plot) & ~np.isnan(y_plot) & np.isfinite(x_plot) & np.isfinite(y_plot)
        x_plot = x_plot[valid]
        y_plot = y_plot[valid]

        self._clear_scatter()
        self._scatter = self._plot_item.plot(
            x_plot,
            y_plot,
            pen=None,
            symbol="o",
            symbolSize=3,
            pxMode=True,
        )

        self._update_labels()
        self._update_log_mode()
        self._auto_range()

    def clear_plot(self) -> None:
        """Remove all data and gate overlays."""
        self._clear_scatter()
        self._clear_gates()
        self._x_label = ""
        self._y_label = ""
        self._update_labels()

    def add_gate_overlay(self, gate: GateSpec) -> None:
        """Add a gate geometry overlay in data coordinates."""
        item = self._create_gate_item(gate)
        if item is not None:
            self._plot_item.addItem(item)
            self._gate_items.append(item)

    def add_gate_overlays(self, gates: list[GateSpec]) -> None:
        """Add multiple gate overlays."""
        for g in gates:
            self.add_gate_overlay(g)

    def clear_gates(self) -> None:
        """Remove all gate overlays."""
        self._clear_gates()

    def screen_to_data(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        """Convert screen coordinates to data coordinates.

        Returns ``(data_x, data_y)``.
        """
        vb = self._view_box()
        if vb is None:
            return (0.0, 0.0)

        from PySide6.QtCore import QPoint  # noqa: N812 - local import

        try:
            # mapFromGlobal on the ViewBox converts screen -> data.
            result = vb.mapFromGlobal(QPoint(int(screen_x), int(screen_y)))
            return (float(result.x()), float(result.y()))
        except Exception:
            pass

        return (0.0, 0.0)

    def mouse_data_position(self) -> tuple[float, float] | None:
        """Return the last mouse position in data coordinates, if tracked."""
        return getattr(self, "_last_data_pos", None)

    # -- callbacks -----------------------------------------------------------

    def on_mouse_moved(self, callback) -> None:
        """Register a callback for mouse movement in data coordinates.

        The callback receives ``(data_x: float, data_y: float)``.
        """
        self._mouse_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _apply_transform(
        self,
        values: NDArray[np.float64],
        transform: AxisTransform,
    ) -> NDArray[np.float64]:
        """Apply a display transform to a 1-D array.

        For ``log10`` the data is NOT pre-transformed here; instead
        pyqtgraph's native ``setLogMode`` is used in ``_update_log_mode``
        for proper axis tick formatting.  The caller still receives raw
        data values for the log path.

        For ``asinh`` the data is pre-transformed via core transforms.

        Args:
            values: 1-D float64 array.
            transform: One of ``"linear"``, ``"log10"``, ``"asinh"``.

        Returns:
            A new array (may be the same object for linear/log10).
        """
        if transform == "linear":
            return values

        if transform == "log10":
            # log10 is handled by pyqtgraph setLogMode; return raw data.
            return values

        if transform == "asinh":
            from flowdesk_core.models import TransformSpec
            from flowdesk_core.transforms import apply_transform

            spec = TransformSpec(
                id="display_asinh",
                name="asinh",
                transform_type="asinh",
                parameter="display",
                settings={"cofactor": 1.0},
            )
            try:
                return apply_transform(spec, values)
            except TransformError:
                return values

        return values

    def _update_log_mode(self) -> None:
        """Configure pyqtgraph ViewBox log mode based on current axis transforms.

        pyqtgraph's setLogMode(axis, logMode) enables native log-axis
        rendering with proper tick marks and labels.  It must be called
        per-axis because X and Y can have different transforms.
        """
        vb = self._view_box()
        if vb is None:
            return

        if self._x_transform == "log10":
            vb.setLogMode("x", True)
        else:
            vb.setLogMode("x", False)

        if self._y_transform == "log10":
            vb.setLogMode("y", True)
        else:
            vb.setLogMode("y", False)

    def _create_gate_item(self, gate: GateSpec) -> Any:
        """Create a pyqtgraph geometry item for a gate."""
        from pyqtgraph import mkPen  # type: ignore[attr-defined]

        pen = mkPen(color="y", width=2, style=Qt.DashLine)

        if gate.gate_type == "rectangle":
            x_min = gate.thresholds.get("x_min", 0)
            x_max = gate.thresholds.get("x_max", 0)
            y_min = gate.thresholds.get("y_min", 0)
            y_max = gate.thresholds.get("y_max", 0)
            from pyqtgraph import RectROI  # type: ignore[attr-defined]

            rect = RectROI(
                [x_min, y_min],
                [x_max - x_min, y_max - y_min],
                pen=pen,
                movable=False,
                removable=False,
            )
            return rect

        if gate.gate_type == "polygon":
            if len(gate.coordinates) < 3:
                return None
            from pyqtgraph import PolygonROI  # type: ignore[attr-defined]

            pts = list(gate.coordinates)
            poly = PolygonROI(pts, pen=pen, closed=True, movable=False, removable=False)
            return poly

        # range / boolean gates do not have a 2D geometry overlay.
        return None

    def _clear_scatter(self) -> None:
        if self._scatter is not None:
            try:
                self._plot_item.removeItem(self._scatter)
            except Exception:
                pass
            self._scatter = None

    def _clear_gates(self) -> None:
        for item in self._gate_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:
                pass
        self._gate_items.clear()

    def _update_labels(self) -> None:
        # setLabel lives on PlotItem, not on ViewBox.
        self._plot_item.setLabel("bottom", self._x_label)
        self._plot_item.setLabel("left", self._y_label)

    def _robust_range(self, data: NDArray[np.float64]) -> tuple[float, float]:
        """Compute a robust display range using percentiles.

        Uses 0.5% and 99.5% percentiles to exclude extreme outliers while
        retaining the vast majority of the population.  Falls back to
        finite min/max if the percentile range collapses.

        Returns:
            (low, high) range values.
        """
        finite = data[np.isfinite(data)]
        if len(finite) == 0:
            return (0.0, 1.0)

        low = float(np.percentile(finite, 0.5))
        high = float(np.percentile(finite, 99.5))

        # Fallback if percentiles collapse (e.g. all same value).
        if high <= low:
            low = float(finite.min())
            high = float(finite.max())
            if high <= low:
                high = low + 1.0

        return (low, high)

    def _auto_range(self) -> None:
        """Set the view range using robust percentile-based bounds."""
        vb = self._view_box()
        if vb is None:
            return

        # Use the last plotted data stored in the scatter item.
        x_data, y_data = None, None
        if self._scatter is not None:
            try:
                x_data = np.asarray(self._scatter.xData, dtype=np.float64)
                y_data = np.asarray(self._scatter.yData, dtype=np.float64)
            except Exception:
                pass

        if x_data is not None and y_data is not None:
            x_arr = np.asarray(x_data, dtype=np.float64)
            y_arr = np.asarray(y_data, dtype=np.float64)
            x_low, x_high = self._robust_range(x_arr)
            y_low, y_high = self._robust_range(y_arr)
            vb.setXRange(x_low, x_high, padding=0.02)
            vb.setYRange(y_low, y_high, padding=0.02)
        else:
            vb.autoRange(padding=0.02)

    def _view_box(self) -> ViewBox | None:
        """Return the ViewBox of the PlotItem.

        The PlotItem created by addPlot() has a .vb attribute that is the
        ViewBox controlling axis ranges and labels.
        """
        try:
            return self._plot_item.vb  # type: ignore[attr-defined]
        except Exception:
            return None

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create the pyqtgraph layout widget.
        self._glw = GraphicsLayoutWidget()
        self._glw.setWindowTitle("")

        # addPlot() returns a PlotItem with .plot(), .vb, etc.
        self._plot_item = self._glw.addPlot()

        layout.addWidget(self._glw)
