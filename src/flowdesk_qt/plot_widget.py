"""Plot widget for 2D scatter plots.

Uses pyqtgraph for fast rendering.  Gate overlays are drawn as geometry
items (rectangles / polygons / ellipses) in **data coordinates**.

This widget contains NO scientific execution logic.  It receives pre-
computed event arrays and gate definitions from the caller.

Axis transforms (linear, log10, asinh) are applied to the display data
before rendering.  The log10 path uses pyqtgraph's native ``setLogMode``
for proper axis tick formatting.  The asinh path pre-transforms the data
via ``flowdesk_core.transforms`` and plots on a linear axis.

Display style (colors, dot size, opacity, background, grid) is controlled
by ``PlotStyleSettings``.  Changing these settings must NEVER affect gate
membership or any analytical result.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from pyqtgraph import GraphicsLayoutWidget, ScatterPlotItem
from pyqtgraph.graphicsItems.ViewBox import ViewBox  # type: ignore[attr-defined]
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from flowdesk_core.models import GateSpec, TransformSpec
from flowdesk_core.plot_presentation import resolve_presentation_layers
from flowdesk_core.transforms import (
    TransformError,
    TransformTick,
    apply_transform,
    generate_transform_ticks,
    validate_transform,
)
from flowdesk_qt.diagnostics import invoke_callback
from flowdesk_qt.plot_style import PlotStyleSettings

logger = logging.getLogger(__name__)

AxisTransform = Literal["linear", "log10", "asinh"]
InteractiveGateType = Literal["rectangle", "polygon"]
InteractionMode = Literal["pan", "select", "gate"]
RangeMode = Literal["robust_auto", "full_auto", "manual"]

# ---------------------------------------------------------------------------
# PlotWidget
# ---------------------------------------------------------------------------


class PlotWidget(QWidget):
    """2D scatter plot with gate overlay and axis transform support.

    The widget renders points, axis labels, and gate geometries.
    All coordinates are in data space, never screen pixels.
  """

    appearance_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plotWidget")
        self._scatter: ScatterPlotItem | None = None
        self._event_colors: NDArray[np.str_] | None = None
        self._event_brush_cache_colors: NDArray[np.str_] | None = None
        self._event_brush_cache_opacity: float | None = None
        self._event_brush_cache: list[Any] | None = None
        self._gate_items: list[Any] = []
        self._gate_item_callbacks: dict[int, Any] = {}
        self._hidden_gate_reasons: list[str] = []
        self._preview_item: Any | None = None
        self._gate_geometry_callbacks: list[Any] = []
        self._x_label: str = ""
        self._y_label: str = ""
        self._downsample_factor: int = 1
        self._mouse_callbacks: list[Any] = []
        # Axis transform state (display-only, defaults to linear).
        self._x_transform: AxisTransform = "linear"
        self._y_transform: AxisTransform = "linear"
        self._x_transform_spec: TransformSpec | None = None
        self._y_transform_spec: TransformSpec | None = None
        self._x_ticks: tuple[TransformTick, ...] = ()
        self._y_ticks: tuple[TransformTick, ...] = ()
        # Display style settings (display-only, never affects analysis).
        self._style: PlotStyleSettings = PlotStyleSettings()
        self._export_metadata: dict[str, Any] | None = None
        # Cached raw data for range reset operations.
        self._cached_x: NDArray[np.float64] | None = None
        self._cached_y: NDArray[np.float64] | None = None
        self._range_mode: RangeMode = "robust_auto"
        self._manual_view_range: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._setting_view_range = False
        self._polygon_preview_vertices: list[tuple[float, float]] = []
        self._interaction_mode: InteractionMode = "pan"
        # Histogram mode state (display-only).
        self._is_histogram_mode: bool = False
        self._histogram_item: Any | None = None
        self._overlay_scatter_items: list[Any] = []
        self._histogram_bins: int = 60
        self._excluded_event_count: int = 0
        # Marginal histogram state (display-only).
        self._marginal_enabled: bool = False
        self._marginal_x_item: Any | None = None
        self._marginal_y_item: Any | None = None
        self._marginal_x_plot: Any | None = None
        self._marginal_y_plot: Any | None = None
        self._status_banner: QLabel | None = None
        self._cached_marginal_x: NDArray[np.float64] | None = None
        self._cached_marginal_y: NDArray[np.float64] | None = None
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

    def set_interaction_mode(self, mode: InteractionMode) -> None:
        """Set mutually exclusive display interaction mode."""
        if mode not in {"pan", "select", "gate"}:
            raise ValueError(f"unsupported interaction mode: {mode!r}")
        self._interaction_mode = mode

    def interaction_mode(self) -> InteractionMode:
        return self._interaction_mode

    # -- style / appearance API (display-only) --------------------------------

    def set_style(self, style: PlotStyleSettings) -> None:
        """Update display style settings.

        This changes only visual appearance (colors, sizes, background, grid).
        It does NOT reload data, recompute gates, or change analytical results.
        """
        self._style = style
        self._apply_style()

    def style(self) -> PlotStyleSettings:
        """Return the current display style settings."""
        return self._style

    def set_presentation(self, presentation: dict[str, Any] | None) -> None:
        """Apply display-only presentation labels and basic appearance.

        This method consumes persisted presentation state only.  It never
        changes event data, memberships, gates, or pipeline results.
        """
        value = {
            key: value
            for key, value in resolve_presentation_layers(
                presentation or {}, source_ids=()
            ).presentation.__dict__.items()
        }
        title = str(value.get("title", ""))
        self._plot_item.setTitle(title)
        self._plot_item.setLabel(
            "bottom", str(value.get("x_axis_display_label") or self._x_label)
        )
        self._plot_item.setLabel(
            "left", str(value.get("y_axis_display_label") or self._y_label)
        )
        style_updates: dict[str, Any] = {}
        for key in ("background_color", "gate_outline_color"):
            if isinstance(value.get(key), str) and value[key]:
                style_updates[key] = value[key]
        if style_updates:
            self.set_style(replace(self._style, **style_updates))

    def set_export_metadata(self, metadata: dict[str, Any] | None) -> None:
        """Attach prepared core export metadata to subsequent display exports."""
        self._export_metadata = None if metadata is None else dict(metadata)

    # -- range reset API (display-only) ---------------------------------------

    def set_robust_range(self) -> None:
        """Reset viewport to robust auto-range (percentile-based)."""
        self._range_mode = "robust_auto"
        self._auto_range()

    def set_full_range(self) -> None:
        """Reset viewport to full data range (all finite points).

        Uses the cached raw data from the last plot_events call.
        """
        self._range_mode = "full_auto"
        self._set_full_range_internal()

    def set_manual_view_range(
        self,
        x_range: tuple[float, float],
        y_range: tuple[float, float],
    ) -> None:
        """Set and remember a display-only manual ViewBox range."""
        self._range_mode = "manual"
        self._manual_view_range = (x_range, y_range)
        self._apply_manual_range()

    def view_range(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return the current ViewBox range as ``((x_min, x_max), (y_min, y_max))``."""
        vb = self._view_box()
        if vb is None:
            return None
        try:
            x_range, y_range = vb.viewRange()
            return (
                (float(x_range[0]), float(x_range[1])),
                (float(y_range[0]), float(y_range[1])),
            )
        except Exception:
            return None

    def range_mode(self) -> RangeMode:
        """Return the current viewport range mode."""
        return self._range_mode

    def set_status_banner(self, text: str = "") -> None:
        """Show definition status separately from the results-stale state."""
        if self._status_banner is None:
            return
        self._status_banner.setText(text)
        self._status_banner.setVisible(bool(text))

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
        if self._x_transform_spec is not None and x_transform != "linear":
            raise TransformError(
                "display_analysis_transform_conflict",
                "X axis cannot combine an analysis transform with a display scale",
            )
        if self._y_transform_spec is not None and y_transform != "linear":
            raise TransformError(
                "display_analysis_transform_conflict",
                "Y axis cannot combine an analysis transform with a display scale",
            )
        self._x_transform = x_transform
        self._y_transform = y_transform

    def set_axis_transform_specs(
        self,
        x_transform: TransformSpec | None,
        y_transform: TransformSpec | None,
    ) -> None:
        """Select versioned analysis coordinates for display and gate editing."""
        for axis, transform in (("X", x_transform), ("Y", y_transform)):
            if transform is None:
                continue
            validate_transform(transform)
            if transform.role != "analysis":
                raise TransformError(
                    "invalid_transform_role",
                    f"{axis} axis transform must have role='analysis'",
                )
        self._x_transform_spec = x_transform
        self._y_transform_spec = y_transform
        if x_transform is not None:
            self._x_transform = "linear"
        if y_transform is not None:
            self._y_transform = "linear"

    def axis_ticks(self, axis: Literal["x", "y"]) -> tuple[TransformTick, ...]:
        """Return ticks generated by the active core transform definition."""
        if axis == "x":
            return self._x_ticks
        return self._y_ticks

    def set_marginal_enabled(self, enabled: bool) -> None:
        """Enable or disable marginal histograms on X and Y axes."""
        self._marginal_enabled = enabled

    def is_marginal_enabled(self) -> bool:
        """Return whether marginal histograms are currently enabled."""
        return self._marginal_enabled

    def display_state(self) -> dict[str, object]:
        """Return compact, JSON-safe plot state without event arrays."""
        return {
            "mode": "histogram" if self._is_histogram_mode else "scatter",
            "histogram_bins": self._histogram_bins,
            "excluded_event_count": self._excluded_event_count,
            "marginal_enabled": self._marginal_enabled,
            "marginal_visible": (
                self._marginal_enabled and not self._is_histogram_mode
            ),
            "hidden_gate_reasons": list(self._hidden_gate_reasons),
        }

    def plot_events(
        self,
        x_data: NDArray[np.float64],
        y_data: NDArray[np.float64],
        x_label: str = "",
        y_label: str = "",
        marginal_x_data: NDArray[np.float64] | None = None,
        marginal_y_data: NDArray[np.float64] | None = None,
        event_colors: NDArray[np.str_] | list[str] | None = None,
    ) -> None:
        """Render a scatter plot.

        Args:
          x_data: X values (full resolution).
          y_data: Y values (full resolution).
          x_label: X axis label.
          y_label: Y axis label.
          marginal_x_data: X data for marginal histogram (optional, defaults to x_data).
          marginal_y_data: Y data for marginal histogram (optional, defaults to y_data).
        """
        self._x_label = x_label
        self._y_label = y_label

        # Cache raw data for range reset operations.
        self._cached_x = x_data
        self._cached_y = y_data

        # Cache marginal data for histogram updates.
        self._cached_marginal_x = marginal_x_data if marginal_x_data is not None else x_data
        self._cached_marginal_y = marginal_y_data if marginal_y_data is not None else y_data

        # Apply axis transforms (display only).
        x_plot = self._apply_axis_transform(x_data, "x")
        y_plot = self._apply_axis_transform(y_data, "y")
        colors_plot = None if event_colors is None else np.asarray(event_colors, dtype=str)
        if colors_plot is not None and colors_plot.shape[0] != x_plot.shape[0]:
            raise ValueError("event_colors must have one color per event")

        # Apply display downsample.
        if self._downsample_factor > 1 and len(x_plot) > 10_000:
            step = max(1, len(x_plot) // 10_000)
            x_plot = x_plot[::step]
            y_plot = y_plot[::step]
            if colors_plot is not None:
                colors_plot = colors_plot[::step]

        # Remove NaN/Inf for plotting safety (does not affect analysis data).
        valid = np.isfinite(x_plot) & np.isfinite(y_plot)
        if self._x_transform_spec is None and self._x_transform == "log10":
            valid &= x_plot > 0
        if self._y_transform_spec is None and self._y_transform == "log10":
            valid &= y_plot > 0
        self._excluded_event_count = int(len(x_plot) - np.count_nonzero(valid))
        x_plot = x_plot[valid]
        y_plot = y_plot[valid]
        if colors_plot is not None:
            colors_plot = colors_plot[valid]
        self._event_colors = colors_plot

        self._is_histogram_mode = False
        self._clear_histogram()
        self._clear_scatter()
        brush: Any = self._make_brush(self._style.dot_color, self._style.dot_opacity)
        if colors_plot is not None:
            brush = self._event_brushes(colors_plot, self._style.dot_opacity)
        self._scatter = self._plot_item.plot(
            x_plot,
            y_plot,
            pen=None,
            symbolPen=None,
            symbol="o",
            symbolSize=self._style.dot_size,
            pxMode=True,
            symbolBrush=brush,
        )

        self._update_labels()
        self._update_log_mode()
        self._update_transform_ticks(x_plot, y_plot)
        if self._range_mode == "manual":
            self._apply_manual_range()
        elif self._range_mode == "full_auto":
            self._set_full_range_internal()
        else:
            self._auto_range()

        # Update marginal histograms if enabled.
        self._update_marginal_histograms()

    def plot_histogram(
        self,
        values: NDArray[np.float64],
        x_label: str = "",
        num_bins: int | None = None,
    ) -> None:
        """Render a 1D histogram.

        This is a display-only operation.  Bin counts do NOT affect gate
        membership, population statistics, or any analytical result.

        Args:
          values: 1-D values (full resolution, population-filtered).
          x_label: X axis label.
          num_bins: Number of histogram bins (default 60).
        """
        self._x_label = x_label
        self._y_label = "Count"

        n_bins = num_bins if num_bins is not None else self._histogram_bins

        # Apply X axis transform to display coordinates.
        values_plot = self._apply_axis_transform(values, "x")

        # Remove NaN/Inf for plotting safety.
        valid = np.isfinite(values_plot)
        if self._x_transform_spec is None and self._x_transform == "log10":
            valid &= values_plot > 0
        self._excluded_event_count = int(len(values_plot) - np.count_nonzero(valid))
        values_plot = values_plot[valid]

        if len(values_plot) == 0:
            self._clear_histogram()
            self._clear_scatter()
            self._clear_marginal_histograms()
            self._is_histogram_mode = True
            self._update_labels()
            self._update_log_mode()
            return

        # Compute histogram (display-only).
        counts, bin_edges = np.histogram(values_plot, bins=n_bins)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
        bin_widths = bin_edges[1:] - bin_edges[:-1]

        self._is_histogram_mode = True
        self._clear_scatter()
        self._clear_histogram()
        self._clear_marginal_histograms()

        # Use pyqtgraph BarGraphItem for the histogram display.
        from pyqtgraph import BarGraphItem  # type: ignore[attr-defined]

        self._histogram_item = BarGraphItem(
            x=bin_centers,
            height=counts,
            width=bin_widths,
            brush=self._make_brush(self._style.dot_color, self._style.dot_opacity),
        )

        self._plot_item.addItem(self._histogram_item)

        self._update_labels()
        self._update_log_mode()
        if self._range_mode == "manual":
            self._apply_manual_range()
        elif self._range_mode == "full_auto":
            self._set_full_range_internal()
        else:
            self._auto_range()

    def clear_plot(self) -> None:
        """Remove all data and gate overlays."""
        self._clear_scatter()
        self._clear_histogram()
        self._clear_marginal_histograms()
        self._clear_gates()
        self.clear_overlay_layers()
        self._clear_preview()
        self._x_label = ""
        self._y_label = ""
        self._cached_x = None
        self._cached_y = None
        self._cached_marginal_x = None
        self._cached_marginal_y = None
        self._is_histogram_mode = False
        self._update_labels()

    def release_transient_items(self) -> None:
        """Disconnect and dispose Qt items that can retain Python callbacks."""
        self._clear_gates()
        self._clear_preview()

    def closeEvent(self, event: Any) -> None:
        """Break ROI callback cycles before Qt destroys the graphics scene."""
        self.release_transient_items()
        super().closeEvent(event)

    def plot_overlay_layers(self, layers: list[Any] | tuple[Any, ...]) -> None:
        """Display prepared core overlay layers with persisted styles."""
        self.clear_overlay_layers()
        for layer in layers:
            style = dict(getattr(layer, "style", {}))
            item = self._plot_item.plot(
                layer.x,
                layer.y,
                pen=None,
                symbolPen=None,
                symbol="o",
                symbolSize=self._style.dot_size,
                pxMode=True,
                symbolBrush=self._make_brush(
                    style.get("color", self._style.dot_color),
                    float(style.get("alpha", self._style.dot_opacity)),
                ),
            )
            self._overlay_scatter_items.append(item)

    def clear_overlay_layers(self) -> None:
        """Remove display-only overlay layers without changing analysis state."""
        for item in self._overlay_scatter_items:
            self._plot_item.removeItem(item)
        self._overlay_scatter_items.clear()

    def add_gate_overlay(
        self,
        gate: GateSpec,
        gate_index: int | None = None,
        outline_color: str | None = None,
    ) -> None:
        """Add a gate geometry overlay in data coordinates."""
        item = self._create_gate_item(gate, gate_index, outline_color)
        if item is not None:
            self._plot_item.addItem(item)
            self._gate_items.append(item)
        elif not self._gate_matches_current_axes(gate):
            self._hidden_gate_reasons.append(
                f"{gate.name} [{gate.id}] uses different axis transforms"
            )

    def add_gate_overlays(self, gates: list[GateSpec]) -> None:
        """Add multiple gate overlays."""
        for idx, gate in enumerate(gates):
            self.add_gate_overlay(gate, idx)

    def clear_gates(self) -> None:
        """Remove all gate overlays."""
        self._clear_gates()
        self._hidden_gate_reasons.clear()

    def highlight_gate_index(self, index: int) -> None:
        """Highlight a gate overlay by index.

        The selected gate gets a solid white pen; all others revert to
        the style-defined dashed outline.
        """
        from pyqtgraph import mkPen  # type: ignore[attr-defined]

        s = self._style
        default_pen = mkPen(
            color=s.gate_outline_color,
            width=2,
            style=Qt.DashLine,
        )
        highlight_pen = mkPen(
            color="#ffffff",
            width=3,
            style=Qt.SolidLine,
        )

        for idx, item in enumerate(self._gate_items):
            try:
                if idx == index:
                    item.setPen(highlight_pen)
                else:
                    item.setPen(default_pen)
            except Exception:
                pass

    def export_png(
        self,
        path: str | Path,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Render the current plot widget to a PNG file.

        This exports the display state only.  It does not run analysis,
        change event data, or affect gate membership.
        """
        original_size = self.size()
        resized = width is not None or height is not None
        try:
            if resized:
                if width is None:
                    width = max(1, original_size.width())
                if height is None:
                    height = max(1, original_size.height())
                self.resize(max(1, width), max(1, height))

            image = QImage(self.size(), QImage.Format_ARGB32)
            image.fill(Qt.white)
            self.render(image, QPoint(0, 0))

            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(out_path), "PNG"):
                raise OSError(f"failed to write PNG plot: {out_path}")
            metadata = dict(self._export_metadata or {})
            metadata.update({
                "format": "PNG",
                "display_state": self.display_state(),
                "scientific_note": (
                    "display export; does not contain analytical statistics"
                ),
            })
            out_path.with_suffix(out_path.suffix + ".json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        finally:
            if resized:
                self.resize(original_size)

    def export_vector(self, path: str | Path, format_name: Literal["SVG", "PDF"]) -> None:
        """Export the display-only scene as SVG/PDF and write a metadata sidecar."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if format_name == "SVG":
            device = QSvgGenerator()
            device.setFileName(str(out_path))
            device.setSize(self.size())
        else:
            device = QPdfWriter(str(out_path))
            device.setResolution(96)
            device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        painter = QPainter(device)
        try:
            self.render(painter, QPoint(0, 0))
        finally:
            painter.end()
        metadata = dict(self._export_metadata or {})
        metadata.update({
          "format": format_name,
          "display_state": self.display_state(),
          "scientific_note": "display export; does not contain analytical statistics",
        })
        out_path.with_suffix(out_path.suffix + ".json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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

    def on_mouse_clicked(self, callback) -> None:
        """Register a callback for mouse clicks in data coordinates.

        The callback receives ``(data_x: float, data_y: float,
        is_double_click: bool)``.
        """
        self._click_callbacks.append(callback)

    def on_gate_geometry_changed(self, callback) -> None:
        """Register callback for interactive gate geometry edits.

        Callback receives ``(gate_index: int, gate: GateSpec)`` after an ROI
        move or handle edit is finished.
        """
        self._gate_geometry_callbacks.append(callback)

    def begin_gate_creation(self, gate_type: InteractiveGateType) -> None:
        """Temporarily capture plot mouse input for interactive gate creation.

        Outside this short-lived state, mouse events are delegated to
        pyqtgraph so normal pan/zoom/range operations remain available.
        """
        if gate_type not in ("rectangle", "polygon"):
            raise ValueError(f"unsupported interactive gate type: {gate_type}")
        self._active_gate_creation = gate_type
        self._drag_start = None
        self._clear_preview()

    def clear_gate_creation(self) -> None:
        """Return plot mouse handling to pyqtgraph defaults."""
        self._active_gate_creation = None
        self._drag_start = None
        self._clear_preview()

    def add_polygon_preview_vertex(self, data_x: float, data_y: float) -> None:
        """Add a vertex in the current gate coordinate scale."""
        self._polygon_preview_vertices.append((data_x, data_y))
        self._update_polygon_preview()

    # -- callback storage (initialised in _build_ui) -------------------------
    # These are populated in _build_ui to avoid forward-reference issues.
    # _click_callbacks: list[Callable[[float, float, bool], None]]
    # _drag_start: tuple[float, float] | None
    # _active_gate_creation: InteractiveGateType | None

    # -- private ------------------------------------------------------------

    def _make_brush(
        self,
        color: str,
        opacity: float,
    ) -> Any:
        """Create a Qt brush from a hex color string and opacity."""
        try:
            from PySide6.QtGui import QBrush

            c = QColor(color)
            c.setAlphaF(max(0.0, min(1.0, opacity)))
            return QBrush(c)
        except Exception:
            return QColor(color)

    def _event_brushes(
        self, colors: NDArray[np.str_], opacity: float
    ) -> list[Any]:
        """Return cached per-event brushes for a display color array.

        Population colors are display-only, but a normal replot can happen for
        unrelated navigation or axis changes. Reusing the immutable brush list
        avoids constructing one QBrush per event on every such replot.
        """
        if (
            self._event_brush_cache is not None
            and self._event_brush_cache_colors is not None
            and self._event_brush_cache_opacity == opacity
            and np.array_equal(self._event_brush_cache_colors, colors)
        ):
            return self._event_brush_cache
        brushes = [
            self._make_brush(str(color), opacity)
            for color in colors
        ]
        self._event_brush_cache_colors = colors.copy()
        self._event_brush_cache_opacity = opacity
        self._event_brush_cache = brushes
        return brushes

    def _apply_style(self) -> None:
        """Apply current style settings to the plot display.

        This updates background, grid, scatter appearance, and gate colors
        without reloading data or recomputing gates.
        """
        s = self._style

        # Background (set on ViewBox, not PlotItem)
        vb = self._view_box()
        if vb is not None:
            vb.setBackgroundColor(s.background_color)

        # Grid
        if s.show_grid:
            self._plot_item.showGrid(True, True, alpha=0.3)
        else:
            self._plot_item.showGrid(False, False)

        # Re-apply scatter brush/size if scatter exists
        if self._scatter is not None:
            brush: Any = self._make_brush(s.dot_color, s.dot_opacity)
            if self._event_colors is not None:
                brush = self._event_brushes(self._event_colors, s.dot_opacity)
                self._scatter.setData(symbolBrush=brush)
            else:
                self._scatter.setSymbolBrush(brush)
            self._scatter.setSymbolSize(s.dot_size)

        # Re-apply gate overlay colors
        self._refresh_gate_colors()

    def _refresh_gate_colors(self) -> None:
        """Update gate overlay outline and fill colors without removing items."""
        s = self._style
        from pyqtgraph import mkColor, mkPen  # type: ignore[attr-defined]

        try:
            fill_color = mkColor(s.gate_fill_color)
            fill_color.setAlphaF(max(0.0, min(1.0, s.gate_fill_opacity)))
        except Exception:
            fill_color = None

        pen = mkPen(
            color=s.gate_outline_color,
            width=2,
            style=Qt.DashLine,
        )

        for item in self._gate_items:
            try:
                item.setPen(pen)
            except Exception:
                pass
            try:
                if hasattr(item, "setBrush"):
                    if fill_color is not None:
                        from PySide6.QtGui import QBrush  # noqa: N812

                        item.setBrush(QBrush(fill_color))
                    else:
                        item.setBrush(None)
            except Exception:
                pass

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

    def _apply_axis_transform(
        self,
        values: NDArray[np.float64],
        axis: Literal["x", "y"],
    ) -> NDArray[np.float64]:
        spec = self._x_transform_spec if axis == "x" else self._y_transform_spec
        if spec is not None:
            return apply_transform(spec, values)
        display_transform = self._x_transform if axis == "x" else self._y_transform
        return self._apply_transform(values, display_transform)

    def _update_log_mode(self) -> None:
        """Configure pyqtgraph log mode based on current axis transforms.

        PlotItem.setLogMode updates PlotDataItem mapping, axis tick
        formatting, and the linked ViewBox state.  Calling ViewBox.setLogMode
        alone only updates range constraints and does not transform points.
        """
        self._plot_item.setLogMode(
            x=self._x_transform_spec is None and self._x_transform == "log10",
            y=self._y_transform_spec is None and self._y_transform == "log10",
        )

    def _create_gate_item(
        self,
        gate: GateSpec,
        gate_index: int | None = None,
        outline_color: str | None = None,
    ) -> Any:
        """Create a pyqtgraph geometry item for a gate."""
        from pyqtgraph import mkPen  # type: ignore[attr-defined]

        if not self._gate_matches_current_axes(gate):
            return None

        pen = mkPen(
            color=outline_color or self._style.gate_outline_color,
            width=2,
            style=Qt.DashLine,
        )

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
                movable=True,
                removable=False,
            )
            self._connect_gate_item_changed(rect, gate, gate_index)
            return rect

        if gate.gate_type == "polygon":
            if len(gate.coordinates) < 3:
                return None
            from pyqtgraph import PolyLineROI  # type: ignore[attr-defined]

            pts = list(gate.coordinates)
            poly = PolyLineROI(pts, pen=pen, closed=True, movable=True, removable=False)
            self._connect_gate_item_changed(poly, gate, gate_index)
            return poly

        if gate.gate_type == "ellipse":
            from pyqtgraph import EllipseROI  # type: ignore[attr-defined]

            values = gate.thresholds
            center_x = float(values.get("center_x", 0.0))
            center_y = float(values.get("center_y", 0.0))
            radius_x = abs(float(values.get("radius_x", 0.0)))
            radius_y = abs(float(values.get("radius_y", 0.0)))
            if radius_x <= 0.0 or radius_y <= 0.0:
                return None
            rotation = float(values.get("rotation", 0.0))
            ellipse = EllipseROI(
                [center_x - radius_x, center_y - radius_y],
                [2.0 * radius_x, 2.0 * radius_y],
                angle=np.degrees(rotation),
                pen=pen,
                movable=True,
                removable=False,
            )
            self._connect_gate_item_changed(ellipse, gate, gate_index)
            return ellipse

        # range / boolean gates do not have a 2D geometry overlay.
        return None

    def _gate_matches_current_axes(self, gate: GateSpec) -> bool:
        x_transform_id = gate.x_transform_id or gate.transform_id
        y_transform_id = gate.y_transform_id
        if x_transform_id is not None:
            if (
                self._x_transform_spec is None
                or self._x_transform_spec.id != x_transform_id
                or gate.x_scale != "linear"
            ):
                return False
        elif self._x_transform_spec is not None or gate.x_scale != self._x_transform:
            return False
        if gate.gate_type in {"rectangle", "polygon", "ellipse"}:
            if y_transform_id is not None:
                if (
                    self._y_transform_spec is None
                    or self._y_transform_spec.id != y_transform_id
                    or gate.y_scale != "linear"
                ):
                    return False
            elif self._y_transform_spec is not None or gate.y_scale != self._y_transform:
                return False
        return True

    def _update_transform_ticks(
        self,
        display_x: NDArray[np.float64],
        display_y: NDArray[np.float64],
    ) -> None:
        self._x_ticks = self._ticks_for_axis(self._x_transform_spec, display_x)
        self._y_ticks = self._ticks_for_axis(self._y_transform_spec, display_y)
        for axis_name, ticks in (("bottom", self._x_ticks), ("left", self._y_ticks)):
            axis = self._plot_item.getAxis(axis_name)
            if ticks:
                axis.setTicks([[(tick.coordinate, tick.label) for tick in ticks]])
            else:
                axis.setTicks(None)

    @staticmethod
    def _ticks_for_axis(
        spec: TransformSpec | None,
        display_values: NDArray[np.float64],
    ) -> tuple[TransformTick, ...]:
        if spec is None:
            return ()
        finite = display_values[np.isfinite(display_values)]
        if len(finite) == 0:
            return ()
        return generate_transform_ticks(
            spec,
            float(finite.min()),
            float(finite.max()),
        )

    def _connect_gate_item_changed(
        self,
        item: Any,
        gate: GateSpec,
        gate_index: int | None,
    ) -> None:
        if gate_index is None:
            return

        def callback(*_args: Any) -> None:
            self._emit_gate_geometry_changed(gate_index, gate, item)

        try:
            item.sigRegionChangeFinished.connect(callback)
            self._gate_item_callbacks[id(item)] = callback
        except Exception:
            logger.exception("Failed to connect gate ROI callback")

    def _emit_gate_geometry_changed(self, gate_index: int, gate: GateSpec, item: Any) -> None:
        updated_gate = self._gate_from_item(gate, item)
        if updated_gate is None:
            return
        for cb in self._gate_geometry_callbacks:
            invoke_callback(cb, gate_index, updated_gate)

    def _gate_from_item(self, gate: GateSpec, item: Any) -> GateSpec | None:
        if gate.gate_type == "rectangle":
            state = item.saveState()
            pos = state.get("pos", (0.0, 0.0))
            size = state.get("size", (0.0, 0.0))
            x_min = float(pos[0])
            y_min = float(pos[1])
            x_max = x_min + float(size[0])
            y_max = y_min + float(size[1])
            return replace(
                gate,
                thresholds={
                    "x_min": min(x_min, x_max),
                    "x_max": max(x_min, x_max),
                    "y_min": min(y_min, y_max),
                    "y_max": max(y_min, y_max),
                },
            )

        if gate.gate_type == "polygon":
            state = item.saveState()
            pos = state.get("pos", (0.0, 0.0))
            points = state.get("points", [])
            x0 = float(pos[0])
            y0 = float(pos[1])
            coordinates = tuple(
                (x0 + float(point[0]), y0 + float(point[1]))
                for point in points
            )
            if len(coordinates) < 3:
                return None
            return replace(gate, coordinates=coordinates)

        if gate.gate_type == "ellipse":
            state = item.saveState()
            pos = state.get("pos", (0.0, 0.0))
            size = state.get("size", (0.0, 0.0))
            width = abs(float(size[0]))
            height = abs(float(size[1]))
            if width <= 0.0 or height <= 0.0:
                return None
            return replace(
                gate,
                thresholds={
                    "center_x": float(pos[0]) + width / 2.0,
                    "center_y": float(pos[1]) + height / 2.0,
                    "radius_x": width / 2.0,
                    "radius_y": height / 2.0,
                    "rotation": float(state.get("angle", 0.0)) * np.pi / 180.0,
                },
            )

        return None

    def _clear_scatter(self) -> None:
        if self._scatter is not None:
            try:
                self._plot_item.removeItem(self._scatter)
            except Exception:
                pass
            self._scatter = None

    def _clear_histogram(self) -> None:
        if self._histogram_item is not None:
            try:
                self._plot_item.removeItem(self._histogram_item)
            except Exception:
                pass
            self._histogram_item = None

    def _clear_gates(self) -> None:
        items = self._gate_items
        self._gate_items = []
        for item in items:
            callback = self._gate_item_callbacks.pop(id(item), None)
            if callback is not None:
                try:
                    item.sigRegionChangeFinished.disconnect(callback)
                except (RuntimeError, TypeError):
                    logger.debug("Gate ROI callback was already disconnected", exc_info=True)
            self._dispose_plot_item(item)
        self._gate_item_callbacks.clear()
        self._hidden_gate_reasons.clear()

    def _dispose_plot_item(self, item: Any) -> None:
        """Remove a transient graphics item and defer destruction safely."""
        try:
            self._plot_item.removeItem(item)
        except (RuntimeError, TypeError):
            logger.debug("Plot item was already removed", exc_info=True)
        try:
            item.deleteLater()
        except (AttributeError, RuntimeError):
            logger.debug("Plot item could not be scheduled for deletion", exc_info=True)

    def _clear_preview(self) -> None:
        item = self._preview_item
        self._preview_item = None
        self._polygon_preview_vertices.clear()
        if item is not None:
            self._dispose_plot_item(item)

    def _set_preview_item(self, item: Any | None) -> None:
        if self._preview_item is item:
            return
        previous = self._preview_item
        self._preview_item = item
        if previous is not None:
            self._dispose_plot_item(previous)
        if item is not None:
            try:
                self._plot_item.addItem(item)
            except Exception:
                self._preview_item = None
                self._dispose_plot_item(item)
                raise

    def _update_rectangle_preview(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        from pyqtgraph import RectROI, mkPen  # type: ignore[attr-defined]

        x_min = min(start[0], end[0])
        y_min = min(start[1], end[1])
        width = abs(end[0] - start[0])
        height = abs(end[1] - start[1])
        if width <= 0 or height <= 0:
            return
        if isinstance(self._preview_item, RectROI):
            self._preview_item.setPos([x_min, y_min], update=False)
            self._preview_item.setSize([width, height], update=True)
            return
        rect = RectROI(
            [x_min, y_min],
            [width, height],
            pen=mkPen(color="#ffffff", width=1, style=Qt.DotLine),
            movable=False,
            removable=False,
        )
        self._set_preview_item(rect)

    def _update_polygon_preview(self) -> None:
        from pyqtgraph import PlotDataItem, mkPen  # type: ignore[attr-defined]

        if not self._polygon_preview_vertices:
            self._clear_preview()
            return
        x_vals = [p[0] for p in self._polygon_preview_vertices]
        y_vals = [p[1] for p in self._polygon_preview_vertices]
        if isinstance(self._preview_item, PlotDataItem):
            # Polygon clicks are already ViewBox coordinates.  In native log
            # mode those coordinates are log10 values, so allowing PlotItem to
            # propagate log mode here would transform the preview a second time.
            self._preview_item.setLogMode(False, False)
            self._preview_item.setData(x_vals, y_vals)
            return
        item = PlotDataItem(
            x_vals,
            y_vals,
            pen=mkPen(color="#ffffff", width=1, style=Qt.DotLine),
            symbol="o",
            symbolSize=5,
            symbolBrush=QColor("#ffffff"),
        )
        self._set_preview_item(item)
        # PlotItem propagates its current log mode when a PlotDataItem is
        # inserted.  Gate preview vertices must remain in ViewBox coordinates.
        item.setLogMode(False, False)

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
            (low, high) range values in the same space as ``data``.
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

    def _robust_range_for_axis(
        self,
        data: NDArray[np.float64],
        transform: AxisTransform,
    ) -> tuple[float, float]:
        """Compute display range for one axis, respecting its transform.

        For ``log10`` axes the ViewBox ``setXRange``/``setYRange``
        interpret arguments in log10-space.  This method computes
        percentiles on the positive-only subset and converts the
        bounds to log10-space so that the ViewBox displays correctly.

        For ``asinh`` and ``linear`` the raw percentile bounds are
        returned unchanged.

        Returns:
            (low, high) in the coordinate space expected by the ViewBox
            for the given transform.
        """
        if transform == "log10":
            # Only positive values are valid in log space.
            positive = data[data > 0]
            if len(positive) == 0:
                return (1.0, 10.0)

            low, high = self._robust_range(positive)
            # Ensure strictly positive floor.
            low = max(low, 1e-300)
            # Convert to log10-space for ViewBox.
            return (float(np.log10(low)), float(np.log10(high)))

        # linear and asinh: ViewBox expects data-space values.
        return self._robust_range(data)

    def _auto_range(self) -> None:
        """Set the view range using robust percentile-based bounds.

        When an axis is in log10 mode, ``setXRange``/``setYRange``
        interpret their arguments in log10-space.  Therefore the
        percentile bounds must be log10-transformed before passing them
        to the ViewBox.  Non-positive values are excluded from the
        percentile calculation for log axes.
        """
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

            x_low, x_high = self._robust_range_for_axis(x_arr, self._x_transform)
            y_low, y_high = self._robust_range_for_axis(y_arr, self._y_transform)

            self._set_view_ranges(vb, (x_low, x_high), (y_low, y_high), padding=0.02)
        else:
            self._setting_view_range = True
            try:
                vb.autoRange(padding=0.02)
            finally:
                self._setting_view_range = False

    def _set_full_range_internal(self) -> None:
        """Reset viewport to full data range using all finite display points.

        Uses the cached raw data from the last ``plot_events`` call and
        applies the same per-axis log-space handling as ``_auto_range``.
        """
        vb = self._view_box()
        if vb is None:
            return

        if self._cached_x is None or self._cached_y is None:
            vb.autoRange(padding=0.02)
            return

        x_arr = np.asarray(self._cached_x, dtype=np.float64)
        y_arr = np.asarray(self._cached_y, dtype=np.float64)

        if self._x_transform_spec is not None:
            x_arr = self._apply_axis_transform(x_arr, "x")
        if self._y_transform_spec is not None:
            y_arr = self._apply_axis_transform(y_arr, "y")

        x_low, x_high = self._full_range_for_axis(x_arr, self._x_transform)
        y_low, y_high = self._full_range_for_axis(y_arr, self._y_transform)

        self._set_view_ranges(vb, (x_low, x_high), (y_low, y_high), padding=0.02)

    def _apply_manual_range(self) -> None:
        vb = self._view_box()
        if vb is None or self._manual_view_range is None:
            return
        x_range, y_range = self._manual_view_range
        self._set_view_ranges(vb, x_range, y_range, padding=0.0)

    def _set_view_ranges(
        self,
        vb: ViewBox,
        x_range: tuple[float, float],
        y_range: tuple[float, float],
        padding: float,
    ) -> None:
        self._setting_view_range = True
        try:
            vb.setXRange(x_range[0], x_range[1], padding=padding)
            vb.setYRange(y_range[0], y_range[1], padding=padding)
        finally:
            self._setting_view_range = False

    def _on_view_range_changed(self, *_args: Any) -> None:
        if self._setting_view_range:
            return
        current = self.view_range()
        if current is None:
            return
        self._range_mode = "manual"
        self._manual_view_range = current

    def _full_range_for_axis(
        self,
        data: NDArray[np.float64],
        transform: AxisTransform,
    ) -> tuple[float, float]:
        """Compute full display range for one axis using all finite values.

        For ``log10`` axes, non-positive values are excluded and bounds
        are converted to log10-space.
        """
        if transform == "log10":
            positive = data[data > 0]
            if len(positive) == 0:
                return (1.0, 10.0)
            finite = positive[np.isfinite(positive)]
            if len(finite) == 0:
                return (1.0, 10.0)
            low = max(float(finite.min()), 1e-300)
            high = float(finite.max())
            if high <= low:
                high = low * 10.0
            return (float(np.log10(low)), float(np.log10(high)))

        finite = data[np.isfinite(data)]
        if len(finite) == 0:
            return (0.0, 1.0)
        low = float(finite.min())
        high = float(finite.max())
        if high <= low:
            high = low + 1.0
        return (low, high)

    def _view_box(self) -> ViewBox | None:
        """Return the ViewBox of the PlotItem.

        The PlotItem created by addPlot() has a .vb attribute that is the
        ViewBox controlling axis ranges and labels.
        """
        try:
            return self._plot_item.vb  # type: ignore[attr-defined]
        except Exception:
            return None

    # -- mouse event handlers ------------------------------------------------

    def _get_data_position(self, event: Any) -> tuple[float, float] | None:
        """Extract data coordinates from a pyqtgraph mouse event."""
        vb = self._view_box()
        if vb is None:
            return None
        try:
            if hasattr(event, "scenePos"):
                pos = event.scenePos()
            else:
                # In pyqtgraph 0.14.0, event.pos is a method, not a property.
                pos = event.pos()
            view_pos = vb.mapSceneToView(pos)
            return (float(view_pos.x()), float(view_pos.y()))
        except Exception:
            return None

    def _on_scene_mouse_click(self, event: Any) -> None:
        """Handle scene-level mouse clicks for polygon gate creation."""
        if self._active_gate_creation != "polygon":
            return

        data_pos = self._get_data_position(event)
        if data_pos is None:
            return

        if event.button() != Qt.LeftButton:
            return

        try:
            is_double = bool(event.double())
        except Exception:
            is_double = False

        for cb in self._click_callbacks:
            invoke_callback(cb, data_pos[0], data_pos[1], is_double)

        event.accept()

    def _on_mouse_click(self, event: Any) -> None:
        """Delegate ViewBox mouse clicks to pyqtgraph defaults."""
        self._default_mouse_click_event(event)

    def _on_mouse_drag(self, event: Any) -> None:
        """Handle mouse drag for rectangle gate creation."""
        if self._active_gate_creation != "rectangle":
            self._default_mouse_drag_event(event)
            return

        data_pos = self._get_data_position(event)
        if data_pos is None:
            event.accept()
            return

        if event.isStart():
            self._drag_start = data_pos
        elif event.isFinish():
            drag_start = self._drag_start
            self._drag_start = None
            self._clear_preview()
            if drag_start is not None:
                for cb in self._click_callbacks:
                    invoke_callback(
                        cb,
                        drag_start[0],
                        drag_start[1],
                        False,
                        dragging=False,
                        rect_end_x=data_pos[0],
                        rect_end_y=data_pos[1],
                    )
        else:
            if self._drag_start is not None:
                self._update_rectangle_preview(self._drag_start, data_pos)
            # During drag, notify callbacks with current drag state
            for cb in self._click_callbacks:
                invoke_callback(
                    cb, data_pos[0], data_pos[1], False, dragging=True
                )

        event.accept()

    # -- marginal histograms (private) ---------------------------------------

    def _update_marginal_histograms(self) -> None:
        """Update marginal histograms if enabled, clear them otherwise."""
        if self._marginal_enabled:
            self._setup_marginal_plots()
            self._render_marginal_x()
            self._render_marginal_y()
        else:
            self._clear_marginal_histograms()

    def _render_marginal_x(self) -> None:
        """Render the top marginal histogram for the X axis."""
        if self._cached_marginal_x is None:
            return

        marginal_x = np.asarray(self._cached_marginal_x, dtype=np.float64)
        values_plot = self._apply_axis_transform(marginal_x, "x")
        valid = np.isfinite(values_plot)
        if self._x_transform_spec is None and self._x_transform == "log10":
            valid &= values_plot > 0
        values_plot = values_plot[valid]

        if len(values_plot) == 0:
            self._clear_marginal_x()
            return

        counts, bin_edges = np.histogram(values_plot, bins=self._histogram_bins)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
        bin_widths = bin_edges[1:] - bin_edges[:-1]

        from pyqtgraph import BarGraphItem  # type: ignore[attr-defined]

        self._clear_marginal_x()
        self._marginal_x_item = BarGraphItem(
            x=bin_centers,
            height=counts,
            width=bin_widths,
            brush=self._make_brush(self._style.dot_color, self._style.dot_opacity),
        )
        if self._marginal_x_plot is not None:
            self._marginal_x_plot.setLogMode(
                x=self._x_transform_spec is None and self._x_transform == "log10",
                y=False,
            )
            self._marginal_x_plot.addItem(self._marginal_x_item)

    def _render_marginal_y(self) -> None:
        """Render the right marginal histogram for the Y axis."""
        if self._cached_marginal_y is None:
            return

        marginal_y = np.asarray(self._cached_marginal_y, dtype=np.float64)
        values_plot = self._apply_axis_transform(marginal_y, "y")
        valid = np.isfinite(values_plot)
        if self._y_transform_spec is None and self._y_transform == "log10":
            valid &= values_plot > 0
        values_plot = values_plot[valid]

        if len(values_plot) == 0:
            self._clear_marginal_y()
            return

        counts, bin_edges = np.histogram(values_plot, bins=self._histogram_bins)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
        bin_widths = bin_edges[1:] - bin_edges[:-1]

        from pyqtgraph import BarGraphItem  # type: ignore[attr-defined]

        self._clear_marginal_y()
        self._marginal_y_item = BarGraphItem(
            x0=0,
            y=bin_centers,
            height=bin_widths,
            width=counts,
            brush=self._make_brush(self._style.dot_color, self._style.dot_opacity),
        )
        if self._marginal_y_plot is not None:
            self._marginal_y_plot.setLogMode(
                x=False,
                y=self._y_transform_spec is None and self._y_transform == "log10",
            )
            self._marginal_y_plot.addItem(self._marginal_y_item)

    def _clear_marginal_histograms(self) -> None:
        """Remove marginal histogram plots and their items."""
        self._clear_marginal_x()
        self._clear_marginal_y()
        if self._marginal_x_plot is not None:
            try:
                self._glw.removeItem(self._marginal_x_plot)
            except Exception:
                pass
            self._marginal_x_plot = None
        if self._marginal_y_plot is not None:
            try:
                self._glw.removeItem(self._marginal_y_plot)
            except Exception:
                pass
            self._marginal_y_plot = None

    def _clear_marginal_x(self) -> None:
        if self._marginal_x_item is not None:
            try:
                if self._marginal_x_plot is not None:
                    self._marginal_x_plot.removeItem(self._marginal_x_item)
            except Exception:
                pass
            self._marginal_x_item = None

    def _clear_marginal_y(self) -> None:
        if self._marginal_y_item is not None:
            try:
                if self._marginal_y_plot is not None:
                    self._marginal_y_plot.removeItem(self._marginal_y_item)
            except Exception:
                pass
            self._marginal_y_item = None

    def _setup_marginal_plots(self) -> None:
        """Create marginal histogram sub-plots if they don't already exist.

        Layout:
          marginal_x (top)
          main plot  (center)
          marginal_y (right)
        """
        if self._marginal_x_plot is not None and self._marginal_y_plot is not None:
            return

        main_vb = self._view_box()

        self._marginal_x_plot = self._glw.addPlot(
            row=0, col=0,
        )
        self._marginal_x_plot.showAxis("bottom", False)
        self._marginal_x_plot.showAxis("left", False)
        self._marginal_x_plot.showAxis("right", False)
        self._marginal_x_plot.hideButtons()

        # Marginal Y plot on the right of the main plot.
        self._marginal_y_plot = self._glw.addPlot(
            row=1, col=1,
        )
        self._marginal_y_plot.showAxis("bottom", False)
        self._marginal_y_plot.showAxis("left", False)
        self._marginal_y_plot.showAxis("top", False)
        self._marginal_y_plot.hideButtons()

        # Link ViewBoxes for synchronized pan/zoom.
        if main_vb is not None:
            try:
                self._marginal_x_plot.vb.setXLink(main_vb)
                self._marginal_y_plot.vb.setYLink(main_vb)
            except Exception:
                pass

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._status_banner = QLabel()
        self._status_banner.setObjectName("plotStatusBanner")
        self._status_banner.setStyleSheet(
            "QLabel { padding: 3px; color: #7a3e00; background: #fff0d0; }"
        )
        self._status_banner.setVisible(False)
        layout.addWidget(self._status_banner)

        # Create the pyqtgraph layout widget.
        self._glw = GraphicsLayoutWidget()
        self._glw.setObjectName("plotGraphicsLayout")
        self._glw.setWindowTitle("")

        # addPlot() returns a PlotItem with .plot(), .vb, etc.
        self._plot_item = self._glw.addPlot()

        # Callback storage for mouse events.
        self._click_callbacks: list[Any] = []
        self._drag_start: tuple[float, float] | None = None
        self._active_gate_creation: InteractiveGateType | None = None

        # Wire up mouse events via the ViewBox.
        vb = self._view_box()
        if vb is not None:
            self._default_mouse_click_event = vb.mouseClickEvent
            self._default_mouse_drag_event = vb.mouseDragEvent
            vb.mouseDragEvent = self._on_mouse_drag  # type: ignore[assignment]
            vb.sigRangeChanged.connect(self._on_view_range_changed)

        self._glw.scene().sigMouseClicked.connect(self._on_scene_mouse_click)
        self._glw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._glw.customContextMenuRequested.connect(self._show_context_menu)

        # Apply initial style (background, grid, etc.)
        self._apply_style()

        layout.addWidget(self._glw)

    def _show_context_menu(self, position: QPoint) -> None:
        """Expose display-only appearance commands from the plot area."""
        if self._interaction_mode != "pan" or self._active_gate_creation is not None:
            return
        menu = self._build_context_menu()
        menu.exec(self._glw.mapToGlobal(position))

    def _build_context_menu(self) -> QMenu:
        """Build the plot appearance menu for tests and keyboard integration."""
        menu = QMenu(self)
        menu.setObjectName("plotAppearanceContextMenu")

        def add_action(label: str, action_id: str) -> QAction:
            action = menu.addAction(label)
            action.setObjectName(action_id)
            action.setToolTip("Display-only; does not rerun the analysis pipeline")
            action.triggered.connect(
                lambda _checked=False, value=action_id: self.appearance_requested.emit(value)
            )
            return action

        add_action("Plot Appearance...", "plotAppearance")
        add_action("Background Color...", "plotBackgroundColor")
        add_action("Edit Title...", "plotTitle")
        add_action("Axis Labels...", "plotAxisLabels")
        add_action("Fonts...", "plotFonts")

        legend_menu = menu.addMenu("Legend")
        legend_menu.setObjectName("plotLegendMenu")
        show_legend = legend_menu.addAction("Show Legend")
        show_legend.setCheckable(True)
        show_legend.setChecked(True)
        show_legend.setObjectName("plotShowLegend")
        show_legend.triggered.connect(
            lambda _checked=False: self.appearance_requested.emit("plotLegend")
        )
        position_menu = legend_menu.addMenu("Position")
        position_menu.setObjectName("plotLegendPositionMenu")
        for position_name in ("right", "left", "top", "bottom", "inside"):
            position_action = position_menu.addAction(position_name.title())
            position_action.setObjectName(f"plotLegendPosition{position_name.title()}")
            position_action.triggered.connect(
                lambda _checked=False, value=position_name:
                self.appearance_requested.emit(f"plotLegendPosition:{value}")
            )

        add_action("Default Event Style...", "plotDefaultEventStyle")
        add_action("Reset View Appearance", "plotResetAppearance")
        return menu
