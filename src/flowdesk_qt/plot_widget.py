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
import re
from collections.abc import Mapping
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from numpy.typing import NDArray
from pyqtgraph import GraphicsLayoutWidget, ScatterPlotItem
from pyqtgraph.graphicsItems.ViewBox import ViewBox  # type: ignore[attr-defined]
from PySide6.QtCore import QMarginsF, QPoint, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from flowdesk_core.density_colors import estimate_density_colors
from flowdesk_core.models import GateSpec, TransformSpec
from flowdesk_core.plot_presentation import resolve_presentation_layers
from flowdesk_core.transforms import (
    TransformError,
    TransformTick,
    apply_transform,
    generate_log_ticks,
    generate_transform_ticks,
    validate_transform,
)
from flowdesk_qt.density_scheduler import (
    DensityColorRequest,
    DensityColorResponse,
    DensityColorScheduler,
)
from flowdesk_qt.diagnostics import invoke_callback
from flowdesk_qt.plot_style import PlotStyleSettings

logger = logging.getLogger(__name__)

AxisTransform = Literal["linear", "log10", "asinh"]
InteractiveGateType = Literal["rectangle", "polygon"]
InteractionMode = Literal["pan", "select", "gate"]
RangeMode = Literal["robust_auto", "full_auto", "manual"]
TickPolicy = Literal["auto", "decades", "one_two_five", "legacy_auto"]

# ---------------------------------------------------------------------------
# PlotWidget
# ---------------------------------------------------------------------------


class PlotWidget(QWidget):
    """2D scatter plot with gate overlay and axis transform support.

    The widget renders points, axis labels, and gate geometries.
    All coordinates are in data space, never screen pixels.
  """

    appearance_requested = Signal(str)
    view_range_requested = Signal()
    export_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plotWidget")
        self._scatter: ScatterPlotItem | None = None
        self._population_scatter_items: list[tuple[Any, str]] = []
        self._event_colors: NDArray[np.str_] | None = None
        self._density_color_cache: dict[tuple[object, ...], NDArray[np.str_]] = {}
        # QBrush objects are presentation-only.  Reuse the last per-event
        # brush payload when the semantic colors and opacity are unchanged;
        # rebuilding thousands of Python/Qt wrappers otherwise dominates
        # style-only density updates.
        self._density_brush_cache: tuple[
            NDArray[np.str_], float, list[QBrush]
        ] | None = None
        # The data-bearing scatter item is expensive to rebuild for density
        # presentation because pyqtgraph receives one resolved style per event.
        # Keep its semantic identity separately from the numeric color cache so
        # a replot which only changes labels/gates can retain the existing item.
        self._density_render_key: tuple[object, ...] | None = None
        self._density_input: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None
        self._density_cache_context: tuple[object, ...] | None = None
        self._density_coloring_active = False
        self._density_pending_key: tuple[object, ...] | None = None
        # Density scheduling is lazy: the common uniform/population path does
        # not allocate a thread pool merely because a PlotWidget exists.
        self._density_scheduler: DensityColorScheduler | None = None
        self._gate_items: list[Any] = []
        self._retired_plot_items: list[Any] = []
        self._gate_item_callbacks: dict[int, Any] = {}
        self._hidden_gate_reasons: list[str] = []
        self._preview_item: Any | None = None
        self._gate_geometry_callbacks: list[Any] = []
        self._x_label: str = ""
        self._y_label: str = ""
        self._max_display_points: int = 20_000
        self._displayed_event_count: int = 0
        self._input_event_count: int = 0
        self._display_sampling_active: bool = False
        self._rendered_x: NDArray[np.float64] | None = None
        self._rendered_y: NDArray[np.float64] | None = None
        self._mouse_callbacks: list[Any] = []
        # Axis transform state (display-only, defaults to linear).
        self._x_transform: AxisTransform = "linear"
        self._y_transform: AxisTransform = "linear"
        self._applied_log_mode: tuple[bool, bool] | None = None
        self._x_transform_spec: TransformSpec | None = None
        self._y_transform_spec: TransformSpec | None = None
        self._x_ticks: tuple[TransformTick, ...] = ()
        self._y_ticks: tuple[TransformTick, ...] = ()
        self._tick_policy: TickPolicy = "auto"
        # Display style settings (display-only, never affects analysis).
        self._style: PlotStyleSettings = PlotStyleSettings()
        self._axis_label_text_style: dict[str, str] = {
            "font-family": "DejaVu Sans",
            "font-size": "14pt",
            "font-weight": "bold",
        }
        self._export_metadata: dict[str, Any] | None = None
        self._export_resolution_scale = 1.0
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
        """Set the legacy display downsample mode.

        ``1`` disables sampling; values greater than one retain the historical
        10,000-point display cap. New callers should use
        :meth:`set_max_display_points`.
        """
        self.set_max_display_points(0 if factor <= 1 else 10_000)

    def set_max_display_points(self, max_points: int) -> None:
        """Set the display-only scatter limit; zero draws every finite event."""
        if (
            isinstance(max_points, bool)
            or not isinstance(max_points, int)
            or max_points < 0
        ):
            raise ValueError("display max points must be a non-negative integer")
        self._max_display_points = max_points

    def max_display_points(self) -> int:
        return self._max_display_points

    def canvas_size(self) -> tuple[int, int]:
        """Return the logical size available to the plot layout.

        ``PlotWidget`` may also contain a status banner above the plot.  Its
        outer widget size therefore is not necessarily the size used by
        pyqtgraph for axes, title, grid, and scatter items.  Batch export
        should use the embedded ``GraphicsLayoutWidget`` dimensions so the
        same layout receives the same logical canvas.
        """
        width = int(self._glw.width())
        height = int(self._glw.height())
        if width > 0 and height > 0:
            return width, height
        # A widget can be queried before its parent layout has been polished
        # (notably during tests and initial window construction).  Preserve a
        # useful fallback without exposing zero-sized export controls.
        return max(1, int(self.width())), max(1, int(self.height()))

    def plot_area_margins(self) -> tuple[float, float, float, float]:
        """Return the ViewBox margins within the logical plot canvas.

        The tuple is ``(left, top, right, bottom)`` in logical Qt pixels.  It
        captures the space consumed by the live axis labels, tick labels,
        title, and pyqtgraph layout.  Export scene metadata can reuse these
        margins without depending on Qt at render time.
        """
        canvas_width, canvas_height = self.canvas_size()
        try:
            view_rect = self._plot_item.vb.sceneBoundingRect()
            top_left = self._glw.mapFromScene(view_rect.topLeft())
            bottom_right = self._glw.mapFromScene(view_rect.bottomRight())
            left = max(0.0, float(top_left.x()))
            top = max(0.0, float(top_left.y()))
            right = max(0.0, float(canvas_width - bottom_right.x()))
            bottom = max(0.0, float(canvas_height - bottom_right.y()))
            if left + right < canvas_width and top + bottom < canvas_height:
                return left, top, right, bottom
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return (60.0, 50.0, 20.0, 60.0)

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
        if style == self._style:
            return
        previous = self._style
        self._style = style
        self._apply_style(previous)

    def style(self) -> PlotStyleSettings:
        """Return the current display style settings."""
        return self._style

    def set_presentation(
        self,
        presentation: dict[str, Any] | None,
        *,
        title_override: str | None = None,
        title_colors: tuple[str, ...] | list[str] | None = None,
    ) -> None:
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
        title = str(value.get("title", "")) if title_override is None else title_override
        title_lines = title.splitlines() or [title]
        if title_colors and len(title_colors) >= len(title_lines):
            title_markup = "<br/>".join(
                f'<span style="color:{escape(str(color))}">{escape(line)}</span>'
                for line, color in zip(title_lines, title_colors, strict=False)
            )
        else:
            title_markup = escape(title).replace("\n", "<br/>")
        title_font = value.get("title_font", {})
        if isinstance(title_font, dict):
            family = str(title_font.get("family", "DejaVu Sans"))
            size = float(title_font.get("size", 14.0))
            weight = str(title_font.get("weight", "bold"))
        else:
            family = str(getattr(title_font, "family", "DejaVu Sans"))
            size = float(getattr(title_font, "size", 14.0))
            weight = str(getattr(title_font, "weight", "bold"))
        self._plot_item.setTitle(
            title_markup,
            family=family,
            size=f"{size:g}pt",
            bold=weight == "bold",
            color=self._foreground_color(str(value.get("background_color", "#ffffff"))),
        )
        title_qfont = QFont(family)
        title_qfont.setPointSizeF(size)
        title_qfont.setBold(weight == "bold")
        title_height = max(
            30,
            QFontMetrics(title_qfont).height() * len(title_lines) + 8,
        )
        # pyqtgraph's PlotItem.setTitle() fixes this row to 30 px.  Increase
        # it after setting the HTML title so every overlay-title line remains
        # inside the plot layout rather than being clipped at the top.
        self._plot_item.titleLabel.setMaximumHeight(title_height)
        self._plot_item.layout.setRowFixedHeight(0, title_height)
        self._axis_label_text_style = self._label_font_style(value.get("axis_label_font"))
        self._set_axis_labels(
            str(value.get("x_axis_display_label") or self._x_label),
            str(value.get("y_axis_display_label") or self._y_label),
        )
        style_updates: dict[str, Any] = {}
        for key in ("background_color", "gate_outline_color"):
            if isinstance(value.get(key), str) and value[key]:
                style_updates[key] = value[key]
        if isinstance(value.get("single_color"), str) and value["single_color"]:
            style_updates["dot_color"] = value["single_color"]
        if value.get("single_dot_size") is not None:
            style_updates["dot_size"] = float(value["single_dot_size"])
        tick_font = value.get("tick_font", {})
        if isinstance(tick_font, dict):
            style_updates.update({
                "tick_font_family": str(tick_font.get("family", "DejaVu Sans")),
                "tick_font_size": float(tick_font.get("size", 12.0)),
                "tick_font_weight": str(tick_font.get("weight", "bold")),
            })
        elif tick_font is not None:
            style_updates.update({
                "tick_font_family": str(getattr(tick_font, "family", "DejaVu Sans")),
                "tick_font_size": float(getattr(tick_font, "size", 12.0)),
                "tick_font_weight": str(getattr(tick_font, "weight", "bold")),
            })
        if value.get("axis_line_width") is not None:
            style_updates["axis_line_width"] = float(value["axis_line_width"])
        if value.get("show_grid") is not None:
            style_updates["show_grid"] = bool(value["show_grid"])
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
        self._refresh_ticks_for_current_view()

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

    def axis_display_labels(self) -> tuple[str, str]:
        """Return the resolved labels currently visible on the two plot axes."""
        try:
            bottom = str(self._plot_item.getAxis("bottom").labelText or self._x_label)
            left = str(self._plot_item.getAxis("left").labelText or self._y_label)
            return bottom, left
        except Exception:
            return self._x_label, self._y_label

    def set_axis_labels(self, x_label: str, y_label: str) -> None:
        """Update labels without replacing the current event rendering."""
        self._x_label = str(x_label)
        self._y_label = str(y_label)
        self._update_labels()

    def axis_range_input_hint(self, axis: Literal["x", "y"]) -> str:
        """Describe the numeric coordinate system used by range entry."""
        transform = self._x_transform if axis == "x" else self._y_transform
        if (self._x_transform_spec if axis == "x" else self._y_transform_spec) is None \
            and transform == "log10":
            return "log10 exponent (4 means 10⁴)"
        return "display coordinate"

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

    def tick_policy(self) -> TickPolicy:
        return self._tick_policy

    def set_tick_policy(self, policy: TickPolicy) -> None:
        """Select readable log ticks or restore historical auto ticks."""
        if policy not in {"auto", "decades", "one_two_five", "legacy_auto"}:
            raise ValueError(f"unsupported tick policy: {policy!r}")
        self._tick_policy = policy
        if policy == "legacy_auto":
            self._x_ticks = ()
            self._y_ticks = ()
            self._plot_item.getAxis("bottom").setTicks(None)
            self._plot_item.getAxis("left").setTicks(None)
        else:
            self._refresh_ticks_for_current_view()

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
            "input_event_count": self._input_event_count,
            "displayed_event_count": self._displayed_event_count,
            "display_max_points": self._max_display_points,
            "display_sampling_active": self._display_sampling_active,
        }

    def has_rendered_data(self) -> bool:
        """Return whether a committed event rendering is currently visible."""
        return self._rendered_x is not None and self._rendered_y is not None

    def plot_events(
        self,
        x_data: NDArray[np.float64],
        y_data: NDArray[np.float64],
        x_label: str = "",
        y_label: str = "",
        marginal_x_data: NDArray[np.float64] | None = None,
        marginal_y_data: NDArray[np.float64] | None = None,
        event_colors: NDArray[np.str_] | list[str] | None = None,
        density_coloring: bool = False,
        density_cache_context: tuple[object, ...] | None = None,
        density_async: bool = False,
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

        # Remove NaN/Inf for plotting safety (does not affect analysis data).
        self._input_event_count = len(x_plot)
        valid = np.isfinite(x_plot) & np.isfinite(y_plot)
        if self._x_transform_spec is None and self._x_transform == "log10":
            valid &= x_plot > 0
        if self._y_transform_spec is None and self._y_transform == "log10":
            valid &= y_plot > 0
        self._excluded_event_count = int(len(x_plot) - np.count_nonzero(valid))
        x_plot = x_plot[valid]
        y_plot = y_plot[valid]
        density_x = x_plot
        density_y = y_plot
        if colors_plot is not None:
            colors_plot = colors_plot[valid]
        sample_indices = self._display_sample_indices(
            len(x_plot), self._max_display_points, colors_plot
        )
        self._display_sampling_active = sample_indices is not None
        if sample_indices is not None:
            x_plot = x_plot[sample_indices]
            y_plot = y_plot[sample_indices]
            if colors_plot is not None:
                colors_plot = colors_plot[sample_indices]
        self._density_input = (density_x, density_y) if density_coloring else None
        self._density_cache_context = density_cache_context if density_coloring else None
        self._density_coloring_active = density_coloring
        if not density_coloring:
            if self._density_scheduler is not None:
                self._density_scheduler.cancel_pending()
            self._density_pending_key = None
        self._displayed_event_count = len(x_plot)
        self._rendered_x = x_plot
        self._rendered_y = y_plot

        density_key = (
            self._density_color_key(density_x, density_y, x_plot, y_plot)
            if density_coloring else None
        )
        reuse_density_scatter = (
            density_key is not None
            and density_key == self._density_render_key
            and isinstance(self._scatter, ScatterPlotItem)
            and not self._population_scatter_items
        )
        if not reuse_density_scatter:
            self._event_colors = colors_plot

        self._is_histogram_mode = False
        self._clear_histogram()
        if not reuse_density_scatter:
            self._clear_scatter()
        # Density colors replace both the uniform and population-color presentation.
        # Do not submit an intermediate scatter item here: _refresh_density_colors()
        # creates the final item after the density colors have been resolved.
        if density_coloring:
            if not reuse_density_scatter:
                self._event_colors = None
        elif colors_plot is None:
            self._scatter = self._plot_uniform_scatter(
                x_plot, y_plot, self._style.dot_color, self._style.dot_opacity
            )
        else:
            for color in np.unique(colors_plot):
                color_mask = colors_plot == color
                item = self._plot_uniform_scatter(
                    x_plot[color_mask], y_plot[color_mask], str(color),
                    self._style.dot_opacity,
                )
                self._population_scatter_items.append((item, str(color)))
            self._scatter = (
                self._population_scatter_items[0][0]
                if self._population_scatter_items else None
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
        self._refresh_ticks_for_current_view()
        if density_coloring and not reuse_density_scatter:
            if density_async and density_key is not None:
                self._schedule_density_colors(density_key)
            else:
                self._refresh_density_colors()

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
        self._rendered_x = None
        self._rendered_y = None
        self._input_event_count = 0
        self._displayed_event_count = 0
        self._display_sampling_active = False
        self._event_colors = None
        self._density_color_cache.clear()
        self._density_brush_cache = None
        self._density_render_key = None
        self._density_input = None
        self._density_cache_context = None
        self._density_coloring_active = False
        self._density_pending_key = None
        if self._density_scheduler is not None:
            self._density_scheduler.cancel_pending()
        self._is_histogram_mode = False
        self._update_labels()

    def release_transient_items(self) -> None:
        """Disconnect and dispose Qt items that can retain Python callbacks."""
        self._clear_gates()
        self._clear_preview()

    def ensure_density_colors(self) -> None:
        """Resolve pending density colors before a synchronous export."""
        if self._density_pending_key is not None:
            if self._density_scheduler is not None:
                self._density_scheduler.cancel_pending()
            self._refresh_density_colors()

    def shutdown_density_scheduler(self) -> None:
        """Wait for numerical density work before the owning window is destroyed."""
        if self._density_scheduler is not None:
            self._density_scheduler.shutdown()

    def closeEvent(self, event: Any) -> None:
        """Break ROI callback cycles before Qt destroys the graphics scene."""
        self.shutdown_density_scheduler()
        self.release_transient_items()
        super().closeEvent(event)

    def plot_overlay_layers(self, layers: list[Any] | tuple[Any, ...]) -> None:
        """Display prepared core overlay layers with persisted styles."""
        self.clear_overlay_layers()
        for layer in layers:
            style = dict(getattr(layer, "style", {}))
            x_values = np.asarray(layer.x)
            y_values = np.asarray(layer.y)
            sample_indices = self._display_sample_indices(
                len(x_values), self._max_display_points
            )
            if sample_indices is not None:
                x_values = x_values[sample_indices]
                y_values = y_values[sample_indices]
            item = self._plot_item.plot(
                x_values,
                y_values,
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

        The selected gate gets a contrast-safe solid pen and a subtle
        translucent fill; all others revert to the style-defined dashed
        outline. This is an editing-only indication.
        """
        from pyqtgraph import mkPen  # type: ignore[attr-defined]
        from PySide6.QtGui import QBrush, QColor

        s = self._style
        default_pen = mkPen(
            color=s.gate_outline_color,
            width=2,
            style=Qt.DashLine,
        )
        selected_color = self._contrast_gate_color()
        highlight_pen = mkPen(
            color=selected_color,
            width=3,
            style=Qt.SolidLine,
        )
        selected_brush_color = QColor(selected_color)
        selected_brush_color.setAlphaF(0.12)
        selected_brush = QBrush(selected_brush_color)
        default_brush_color = QColor(s.gate_fill_color)
        default_brush_color.setAlphaF(max(0.0, min(1.0, s.gate_fill_opacity)))
        default_brush = QBrush(default_brush_color)

        for idx, item in enumerate(self._gate_items):
            try:
                if idx == index:
                    item.setPen(highlight_pen)
                    if hasattr(item, "setBrush"):
                        item.setBrush(selected_brush)
                else:
                    item.setPen(default_pen)
                    if hasattr(item, "setBrush"):
                        item.setBrush(default_brush)
            except Exception:
                pass

    def _contrast_gate_color(self) -> str:
        """Return the editing highlight color with background contrast."""
        background = QColor(self._style.background_color)
        return "#0057b8" if background.lightness() >= 128 else "#ffd400"

    def export_png(
        self,
        path: str | Path,
        width: int | None = None,
        height: int | None = None,
        aspect_1_to_1: bool = False,
        export_options: Mapping[str, object] | None = None,
        resolution_scale: float = 1.0,
    ) -> None:
        """Render the current plot widget to a PNG file.

        This exports the display state only.  It does not run analysis,
        change event data, or affect gate membership.
        """
        self.ensure_density_colors()
        original_size = self.size()
        self._export_resolution_scale = max(0.01, float(resolution_scale))
        visibility = self._begin_export_visibility(export_options)
        export_view_range = self.view_range()
        original_aspect = self._begin_export_aspect(aspect_1_to_1)
        resized = width is not None or height is not None
        frozen_ticks: tuple[tuple[Any, Any], ...] = ()
        cosmetic_pens: tuple[tuple[Any, QPen, QPen], ...] = ()
        try:
            if resized:
                if width is None:
                    width = max(1, original_size.width())
                if height is None:
                    height = max(1, original_size.height())
                self.resize(max(1, width), max(1, height))
            self._restore_export_view_range(export_view_range)
            frozen_ticks = self._begin_export_tick_levels()
            cosmetic_pens = self._begin_export_cosmetic_pens()

            image = self._export_raster_image(QImage.Format_ARGB32)
            image.fill(Qt.white)
            painter = QPainter(image)
            try:
                self.render(painter, QPoint(0, 0))
            finally:
                painter.end()
            self._set_export_density(image)

            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(out_path), "PNG"):
                raise OSError(f"failed to write PNG plot: {out_path}")
            metadata = dict(self._export_metadata or {})
            metadata.update({
                "format": "PNG",
                "aspect_1_to_1": aspect_1_to_1,
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
            self._end_export_cosmetic_pens(cosmetic_pens)
            self._end_export_tick_levels(frozen_ticks)
            self._export_resolution_scale = 1.0
            self._end_export_aspect(original_aspect)
            self._end_export_visibility(visibility)
            if resized:
                self.resize(original_size)

    def export_jpg(
        self,
        path: str | Path,
        width: int | None = None,
        height: int | None = None,
        aspect_1_to_1: bool = False,
        export_options: Mapping[str, object] | None = None,
        resolution_scale: float = 1.0,
    ) -> None:
        """Render the current display-only scene to a JPEG file."""
        self.ensure_density_colors()
        original_size = self.size()
        self._export_resolution_scale = max(0.01, float(resolution_scale))
        visibility = self._begin_export_visibility(export_options)
        export_view_range = self.view_range()
        original_aspect = self._begin_export_aspect(aspect_1_to_1)
        resized = width is not None or height is not None
        frozen_ticks: tuple[tuple[Any, Any], ...] = ()
        cosmetic_pens: tuple[tuple[Any, QPen, QPen], ...] = ()
        try:
            if resized:
                width = width or max(1, original_size.width())
                height = height or max(1, original_size.height())
                self.resize(max(1, width), max(1, height))
            self._restore_export_view_range(export_view_range)
            frozen_ticks = self._begin_export_tick_levels()
            cosmetic_pens = self._begin_export_cosmetic_pens()
            image = self._export_raster_image(QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.white)
            painter = QPainter(image)
            try:
                self.render(painter, QPoint(0, 0))
            finally:
                painter.end()
            self._set_export_density(image)
            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(out_path), "JPEG", quality=95):
                raise OSError(f"failed to write JPEG plot: {out_path}")
            metadata = dict(self._export_metadata or {})
            metadata.update({
                "format": "JPEG",
                "aspect_1_to_1": aspect_1_to_1,
                "display_state": self.display_state(),
                "scientific_note": "display export; does not contain analytical statistics",
            })
            out_path.with_suffix(out_path.suffix + ".json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        finally:
            self._end_export_cosmetic_pens(cosmetic_pens)
            self._end_export_tick_levels(frozen_ticks)
            self._export_resolution_scale = 1.0
            self._end_export_aspect(original_aspect)
            self._end_export_visibility(visibility)
            if resized:
                self.resize(original_size)

    def export_vector(
        self,
        path: str | Path,
        format_name: Literal["SVG", "PDF"],
        aspect_1_to_1: bool = False,
        width: int | None = None,
        height: int | None = None,
        export_options: Mapping[str, object] | None = None,
        resolution_scale: float = 1.0,
    ) -> None:
        """Export the display-only scene as SVG/PDF and write a metadata sidecar."""
        self.ensure_density_colors()
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        original_size = self.size()
        self._export_resolution_scale = max(0.01, float(resolution_scale))
        visibility = self._begin_export_visibility(export_options)
        export_view_range = self.view_range()
        resized = width is not None or height is not None
        original_aspect = self._begin_export_aspect(aspect_1_to_1)
        try:
            if resized:
                width = width or max(1, original_size.width())
                height = height or max(1, original_size.height())
                self.resize(max(1, width), max(1, height))
            self._restore_export_view_range(export_view_range)
            if format_name == "SVG":
                device = QSvgGenerator()
                device.setFileName(str(out_path))
                device.setSize(self.size())
            else:
                device = QPdfWriter(str(out_path))
                # The vector canvas uses PDF points as logical units.
                device.setResolution(72)
                # Match the logical export canvas instead of scaling the plot
                # into an A4 page.  This keeps PDF and PNG coordinates equal.
                device.setPageSize(QPageSize(
                    QSizeF(self.width() / 72.0, self.height() / 72.0),
                    QPageSize.Unit.Inch,
                ))
                device.setPageMargins(QMarginsF(0, 0, 0, 0))
            painter = QPainter(device)
            try:
                self.render(painter, QPoint(0, 0))
            finally:
                painter.end()
            metadata = dict(self._export_metadata or {})
            metadata.update({
              "format": format_name,
              "aspect_1_to_1": aspect_1_to_1,
              "display_state": self.display_state(),
              "scientific_note": "display export; does not contain analytical statistics",
            })
            out_path.with_suffix(out_path.suffix + ".json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        finally:
            self._export_resolution_scale = 1.0
            self._end_export_aspect(original_aspect)
            self._end_export_visibility(visibility)
            if resized:
                self.resize(original_size)

    def _begin_export_visibility(
        self, options: Mapping[str, object] | None
    ) -> dict[str, object]:
        """Temporarily apply export-only visibility without changing plot state."""
        options = options or {}
        title = self._plot_item.titleLabel
        bottom_axis = self._plot_item.getAxis("bottom")
        left_axis = self._plot_item.getAxis("left")
        state: dict[str, object] = {
            "title_visible": title.isVisible(),
            "bottom_label": getattr(bottom_axis, "labelText", ""),
            "left_label": getattr(left_axis, "labelText", ""),
            "gate_visible": tuple(item.isVisible() for item in self._gate_items),
            "status_visible": self._status_banner.isVisible()
            if self._status_banner is not None else False,
            "gate_visuals": self._begin_export_gate_visuals(),
        }
        if options.get("include_title") is False:
            title.setVisible(False)
        if options.get("include_axis_labels") is False:
            self._set_axis_labels("", "")
        if options.get("include_ticks") is False:
            bottom_axis.setStyle(showValues=False)
            left_axis.setStyle(showValues=False)
        if options.get("include_gates") is False:
            for item in self._gate_items:
                item.setVisible(False)
        if options.get("include_status_banner") is False and self._status_banner is not None:
            self._status_banner.setVisible(False)
        return state

    def _set_export_density(self, image: QImage) -> None:
        """Set PNG/JPEG density metadata when a resolved canvas is attached."""
        canvas = (self._export_metadata or {}).get("export_canvas", {})
        try:
            dpi = int(canvas.get("dpi", 96))
        except (AttributeError, TypeError, ValueError):
            dpi = 96
        dots_per_meter = max(1, round(dpi / 0.0254))
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)

    def _export_raster_image(self, image_format: QImage.Format) -> QImage:
        """Create a high-density device with the widget's logical dimensions."""
        scale = self._export_resolution_scale
        image = QImage(
            QSize(
                max(1, round(self.width() * scale)),
                max(1, round(self.height() * scale)),
            ),
            image_format,
        )
        image.setDevicePixelRatio(scale)
        return image

    def _begin_export_tick_levels(self) -> tuple[tuple[Any, Any], ...]:
        """Freeze logical-canvas tick density before high-density painting."""
        if self._export_resolution_scale == 1.0:
            return ()
        QApplication.processEvents()
        state: list[tuple[Any, Any]] = []
        for axis_name in ("bottom", "left"):
            axis = self._plot_item.getAxis(axis_name)
            original = axis._tickLevels
            state.append((axis, original))
            if original is not None:
                continue
            length = axis.width() if axis_name == "bottom" else axis.height()
            levels = axis.tickValues(axis.range[0], axis.range[1], max(1.0, length))
            ticks = []
            for spacing, values in levels:
                labels = axis.tickStrings(
                    values, axis.autoSIPrefixScale * axis.scale, spacing
                )
                ticks.append(list(zip(values, labels, strict=False)))
            axis.setTicks(ticks)
        return tuple(state)

    @staticmethod
    def _end_export_tick_levels(state: tuple[tuple[Any, Any], ...]) -> None:
        for axis, original in state:
            axis.setTicks(original)

    def _begin_export_cosmetic_pens(self) -> tuple[tuple[Any, QPen, QPen], ...]:
        """Scale cosmetic pens for a high-density paint device."""
        scale = self._export_resolution_scale
        if scale == 1.0:
            return ()
        state: list[tuple[Any, QPen, QPen]] = []
        for axis_name in ("bottom", "left", "top", "right"):
            axis = self._plot_item.getAxis(axis_name)
            original_pen = axis.pen()
            original_tick_pen = axis.tickPen()
            pen = QPen(original_pen)
            pen.setWidthF(max(1.0, original_pen.widthF()) * scale)
            tick_pen = QPen(original_tick_pen)
            tick_pen.setWidthF(max(1.0, original_tick_pen.widthF()) * scale)
            axis.setPen(pen)
            axis.setTickPen(tick_pen)
            state.append((axis, original_pen, original_tick_pen))
        return tuple(state)

    @staticmethod
    def _end_export_cosmetic_pens(
        state: tuple[tuple[Any, QPen, QPen], ...]
    ) -> None:
        for axis, pen, tick_pen in state:
            axis.setPen(pen)
            axis.setTickPen(tick_pen)

    def _end_export_visibility(self, state: dict[str, object]) -> None:
        if not state:
            return
        self._plot_item.titleLabel.setVisible(bool(state["title_visible"]))
        self._set_axis_labels(
            str(state["bottom_label"]), str(state["left_label"]),
        )
        self._plot_item.getAxis("bottom").setStyle(showValues=True)
        self._plot_item.getAxis("left").setStyle(showValues=True)
        gate_visible = cast(tuple[bool, ...], state["gate_visible"])
        for item, visible in zip(self._gate_items, gate_visible, strict=False):
            item.setVisible(bool(visible))
        gate_visuals = cast(
            tuple[tuple[Any, tuple[bool, ...]], ...], state["gate_visuals"]
        )
        self._end_export_gate_visuals(gate_visuals)
        if self._status_banner is not None:
            self._status_banner.setVisible(bool(state["status_visible"]))

    def _begin_export_gate_visuals(self) -> tuple[tuple[Any, tuple[bool, ...]], ...]:
        """Hide ROI editing handles and use publication-friendly solid outlines."""
        from pyqtgraph import mkPen  # type: ignore[attr-defined]

        state: list[tuple[Any, tuple[bool, ...]]] = []
        for item in self._gate_items:
            try:
                original_pen = item.pen() if callable(item.pen) else item.pen
                color = original_pen.color()
                width = (
                    max(1.0, float(original_pen.widthF()))
                    * self._export_resolution_scale
                )
                item.setPen(mkPen(color=color, width=width, style=Qt.SolidLine))
            except Exception:
                original_pen = None
            handles = []
            try:
                handles = list(item.getHandles())
            except Exception:
                handles = []
            handle_visibility: list[bool] = []
            for handle in handles:
                try:
                    handle_visibility.append(bool(handle.isVisible()))
                    handle.setVisible(False)
                except Exception:
                    handle_visibility.append(False)
            state.append((original_pen, tuple(handle_visibility)))
        return tuple(state)

    def _end_export_gate_visuals(
        self, state: tuple[tuple[Any, tuple[bool, ...]], ...]
    ) -> None:
        for item, (original_pen, handle_visibility) in zip(
            self._gate_items, state, strict=False
        ):
            if original_pen is not None:
                try:
                    item.setPen(original_pen)
                except Exception:
                    pass
            try:
                handles = list(item.getHandles())
            except Exception:
                handles = []
            for handle, visible in zip(handles, handle_visibility, strict=False):
                try:
                    handle.setVisible(visible)
                except Exception:
                    pass

    def _begin_export_aspect(self, enabled: bool) -> tuple[bool, float] | None:
        if not enabled:
            return None
        vb = self._view_box()
        if vb is None:
            return None
        state = vb.state
        original = (bool(state.get("aspectLocked", False)), float(state.get("aspectRatio", 1.0)))
        vb.setAspectLocked(True, ratio=1.0)
        return original

    def _end_export_aspect(self, original: tuple[bool, float] | None) -> None:
        if original is None:
            return
        vb = self._view_box()
        if vb is not None:
            vb.setAspectLocked(original[0], ratio=original[1])

    def _restore_export_view_range(
        self,
        view_range: tuple[tuple[float, float], tuple[float, float]] | None,
    ) -> None:
        """Keep the GUI data range when export layout/aspect changes size."""
        if view_range is None:
            return
        vb = self._view_box()
        if vb is None:
            return
        try:
            # A locked ViewBox rejects a range whose aspect does not match the
            # resized export canvas. The GUI range is authoritative for
            # current-view export, so temporarily unlock during the render.
            if bool(vb.state.get("aspectLocked", False)):
                vb.setAspectLocked(False)
            vb.setRange(
                xRange=view_range[0], yRange=view_range[1], padding=0,
                disableAutoRange=True,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Could not restore export ViewBox range", exc_info=True)

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

    def _plot_uniform_scatter(
        self,
        x_values: NDArray[np.float64],
        y_values: NDArray[np.float64],
        color: str,
        opacity: float,
    ) -> Any:
        """Draw one uniform-color layer without pyqtgraph per-point styles."""
        return self._plot_item.plot(
            x_values,
            y_values,
            pen=None,
            symbolPen=None,
            symbol="o",
            symbolSize=self._style.dot_size,
            pxMode=True,
            symbolBrush=self._make_brush(color, opacity),
        )

    @staticmethod
    def _display_sample_indices(
        event_count: int,
        max_points: int,
        colors: NDArray[np.str_] | None = None,
    ) -> NDArray[np.int64] | None:
        """Select deterministic display indices, stratified by resolved color."""
        if max_points <= 0 or event_count <= max_points:
            return None
        if colors is None:
            return np.linspace(0, event_count - 1, max_points, dtype=np.int64)

        unique_colors, inverse, counts = np.unique(
            colors, return_inverse=True, return_counts=True
        )
        group_count = len(unique_colors)
        ideal = counts.astype(np.float64) * (max_points / event_count)
        quotas = np.floor(ideal).astype(np.int64)
        minimum = 1 if max_points >= group_count else 0
        if minimum:
            quotas = np.maximum(quotas, minimum)
        quotas = np.minimum(quotas, counts)

        while int(quotas.sum()) > max_points:
            candidates = np.flatnonzero(quotas > minimum)
            if len(candidates) == 0:
                break
            excess = quotas[candidates] - ideal[candidates]
            quotas[candidates[int(np.argmax(excess))]] -= 1
        while int(quotas.sum()) < max_points:
            candidates = np.flatnonzero(quotas < counts)
            if len(candidates) == 0:
                break
            deficit = ideal[candidates] - quotas[candidates]
            quotas[candidates[int(np.argmax(deficit))]] += 1

        selected: list[NDArray[np.int64]] = []
        for group_index, quota in enumerate(quotas):
            if quota <= 0:
                continue
            group_indices = np.flatnonzero(inverse == group_index)
            positions = np.linspace(
                0, len(group_indices) - 1, int(quota), dtype=np.int64
            )
            selected.append(group_indices[positions])
        if not selected:
            return np.empty(0, dtype=np.int64)
        return np.sort(np.concatenate(selected)).astype(np.int64, copy=False)

    def _apply_style(self, previous: PlotStyleSettings | None = None) -> None:
        """Apply current style settings to the plot display.

        This updates background, grid, scatter appearance, and gate colors
        without reloading data or recomputing gates.
        """
        s = self._style

        from pyqtgraph import mkPen  # type: ignore[attr-defined]
        axis_pen = mkPen(
            color=self._foreground_color(s.background_color),
            width=s.axis_line_width,
        )
        tick_font = QFont(s.tick_font_family, round(s.tick_font_size))
        tick_font.setBold(s.tick_font_weight == "bold")
        for axis_name in ("bottom", "left"):
            axis = self._plot_item.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
            axis.setStyle(tickFont=tick_font, tickLength=6)
            if not hasattr(axis, "_flowdesk_original_tick_strings"):
                original_tick_strings = axis.tickStrings
                axis._flowdesk_original_tick_strings = original_tick_strings

                def formatted_tick_strings(
                    values: list[float],
                    scale: float,
                    spacing: float,
                    original=original_tick_strings,
                    current_axis_name=axis_name,
                    current_axis=axis,
                ) -> list[str]:
                    labels = [
                        self._format_tick_label(label)
                        for label in original(values, scale, spacing)
                    ]
                    return self._fit_tick_labels(
                        current_axis_name, values, labels, current_axis
                    )

                axis.tickStrings = formatted_tick_strings

        # A closed frame matches exported plots while retaining labels and ticks
        # only on the conventional bottom/left axes.
        for axis_name in ("top", "right"):
            self._plot_item.showAxis(axis_name, show=True)
            axis = self._plot_item.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
            axis.setStyle(showValues=False, tickLength=0)

        # ViewBox holds event pixels while GraphicsLayoutWidget holds title,
        # axis labels, and tick labels.  They must share a background so
        # contrast-safe text cannot disappear in the surrounding margin.
        vb = self._view_box()
        if vb is not None and (
            previous is None or previous.background_color != s.background_color
        ):
            vb.setBackgroundColor(s.background_color)
            self._glw.setBackground(s.background_color)

        # Grid
        if previous is None or previous.show_grid != s.show_grid:
            if s.show_grid:
                self._plot_item.showGrid(True, True, alpha=0.15)
            else:
                self._plot_item.showGrid(False, False)

        # Re-apply scatter brush/size if scatter exists
        scatter_style_changed = previous is None or (
            previous.dot_size != s.dot_size
            or previous.dot_color != s.dot_color
            or previous.dot_opacity != s.dot_opacity
        )
        if self._scatter is not None and scatter_style_changed:
            if self._density_coloring_active:
                # Density colors are already resolved for this semantic
                # display identity. Dot-color is deliberately ignored by the
                # density mode. Update only the changed per-spot presentation
                # field: re-sending X/Y through setData is expensive for a
                # large scatter and is not required for size or opacity.
                if not isinstance(self._scatter, ScatterPlotItem):
                    self._refresh_density_colors()
                elif previous is None or previous.dot_size != s.dot_size:
                    self._scatter.setSize(s.dot_size)
                if (
                    previous is None
                    or previous.dot_opacity != s.dot_opacity
                ):
                    if self._event_colors is not None:
                        self._scatter.setBrush(self._density_brushes())
            elif self._population_scatter_items:
                for item, color in self._population_scatter_items:
                    item.setSymbolSize(s.dot_size)
                    item.setSymbolBrush(self._make_brush(color, s.dot_opacity))
            else:
                self._scatter.setSymbolSize(s.dot_size)
                self._scatter.setSymbolBrush(
                    self._make_brush(s.dot_color, s.dot_opacity)
                )

        # Re-apply gate overlay colors
        gate_style_changed = previous is None or (
            previous.gate_outline_color != s.gate_outline_color
            or previous.gate_fill_color != s.gate_fill_color
            or previous.gate_fill_opacity != s.gate_fill_opacity
        )
        if gate_style_changed:
            self._refresh_gate_colors()

    @staticmethod
    def _foreground_color(background_color: str) -> str:
        """Choose a readable monochrome foreground for a plot background."""
        color = QColor(background_color)
        if not color.isValid():
            return "#000000"
        luminance = (
            0.2126 * color.red()
            + 0.7152 * color.green()
            + 0.0722 * color.blue()
        )
        return "#000000" if luminance >= 128 else "#e8e8e8"

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
        mode = (
            self._x_transform_spec is None and self._x_transform == "log10",
            self._y_transform_spec is None and self._y_transform == "log10",
        )
        # PlotItem.setLogMode() rebuilds existing scatter data even when the
        # requested flags are unchanged.  Avoid that hidden per-event work on
        # a gate/label-only replot; a changed transform still always updates
        # the pyqtgraph mode before the plot is displayed.
        if mode == self._applied_log_mode:
            return
        self._plot_item.setLogMode(x=mode[0], y=mode[1])
        self._applied_log_mode = mode

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
                pen=pen,
                movable=True,
                removable=False,
            )
            # EllipseROI rotates around its local origin by default.  Keep the
            # data-space center fixed so the displayed ellipse and the core
            # gate (which uses pos + size / 2 as its center) remain identical.
            ellipse.setAngle(np.degrees(rotation), center=(0.5, 0.5))
            self._connect_gate_item_changed(ellipse, gate, gate_index)
            return ellipse

        # range / boolean gates do not have a 2D geometry overlay.
        return None

    def _gate_matches_current_axes(self, gate: GateSpec) -> bool:
        x_transform_id = gate.x_transform_id
        y_transform_id = gate.y_transform_id
        if x_transform_id is not None:
            if (
                self._x_transform_spec is None
                or self._x_transform_spec.id != x_transform_id
            ):
                return False
        elif self._x_transform_spec is not None or self._x_transform != "linear":
            return False
        if gate.gate_type in {"rectangle", "polygon", "ellipse"}:
            if y_transform_id is not None:
                if (
                    self._y_transform_spec is None
                    or self._y_transform_spec.id != y_transform_id
                ):
                    return False
            elif self._y_transform_spec is not None or self._y_transform != "linear":
                return False
        return True

    def _update_transform_ticks(
        self,
        display_x: NDArray[np.float64],
        display_y: NDArray[np.float64],
    ) -> None:
        self._x_ticks = self._ticks_for_axis(self._x_transform_spec, display_x, "x")
        self._y_ticks = self._ticks_for_axis(self._y_transform_spec, display_y, "y")
        for axis_name, ticks in (("bottom", self._x_ticks), ("left", self._y_ticks)):
            axis = self._plot_item.getAxis(axis_name)
            if ticks:
                major = [tick for tick in ticks if tick.level == "major"]
                minor = [tick for tick in ticks if tick.level == "minor"]
                coordinates = [tick.coordinate for tick in major]
                labels = self._fit_tick_labels(
                    axis_name, coordinates,
                    [self._format_tick_label(tick.label) for tick in major], axis,
                )
                levels = [[
                    (tick.coordinate, label)
                    for tick, label in zip(major, labels, strict=True)
                ]]
                if minor:
                    levels.append([(tick.coordinate, "") for tick in minor])
                axis.setTicks(levels)
            else:
                axis.setTicks(None)

    def _ticks_for_axis(
        self,
        spec: TransformSpec | None,
        display_values: NDArray[np.float64],
        axis_name: Literal["x", "y"],
    ) -> tuple[TransformTick, ...]:
        finite = display_values[np.isfinite(display_values)]
        if len(finite) == 0:
            return ()
        if self._tick_policy == "legacy_auto":
            return ()
        policy = "one_two_five" if self._tick_policy == "one_two_five" else self._tick_policy
        if spec is None:
            transform = self._x_transform if axis_name == "x" else self._y_transform
            if transform != "log10":
                return ()
            return generate_log_ticks(float(finite.min()), float(finite.max()), policy)
        return generate_transform_ticks(
            spec,
            float(finite.min()),
            float(finite.max()),
            policy,
        )

    def _refresh_ticks_for_current_view(self) -> None:
        if self._tick_policy == "legacy_auto":
            return
        view = self.view_range()
        if view is None or self._cached_x is None or self._cached_y is None:
            return
        x_range, y_range = view
        x_values = np.array(x_range, dtype=np.float64)
        y_values = np.array(y_range, dtype=np.float64)
        if self._x_transform_spec is None and self._x_transform == "log10":
            x_values = np.power(10.0, x_values)
        if self._y_transform_spec is None and self._y_transform == "log10":
            y_values = np.power(10.0, y_values)
        self._update_transform_ticks(x_values, y_values)

    @staticmethod
    def _format_tick_label(label: str) -> str:
        """Render scientific exponents as Unicode superscripts in Qt axes."""
        match = re.fullmatch(
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))e([+-]?\d+)",
            label.strip(),
            re.I,
        )
        if match is None:
            return label
        mantissa, exponent = match.groups()
        superscript = str(int(exponent)).translate(str.maketrans(
            "0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺"
        ))
        if float(mantissa) == 1.0:
            return f"10{superscript}"
        return f"{mantissa} × 10{superscript}"

    def _fit_tick_labels(
        self,
        axis_name: str,
        coordinates: list[float],
        labels: list[str],
        axis: Any,
    ) -> list[str]:
        """Hide labels that cannot fit without changing tick coordinates."""
        if len(labels) < 2:
            return labels
        dimension = axis.width() if axis_name == "bottom" else axis.height()
        if dimension <= 0:
            return labels
        try:
            view_range = self._view_box().viewRange()[0 if axis_name == "bottom" else 1]
            low, high = float(view_range[0]), float(view_range[1])
            span = abs(high - low)
            if span <= 0:
                return labels
            font = axis.style.get("tickFont", QFont())
            metrics = QFontMetrics(font)
            widths = [metrics.horizontalAdvance(label) for label in labels]
            positions = [abs(float(value) - low) / span * dimension for value in coordinates]
        except Exception:
            return labels

        result = ["" for _ in labels]
        previous_index = 0
        result[0] = labels[0]
        for index in range(1, len(labels)):
            required = (widths[previous_index] + widths[index]) / 2.0 + 6.0
            if abs(positions[index] - positions[previous_index]) >= required:
                result[index] = labels[index]
                previous_index = index
        return result

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
            size = state.get("size", (0.0, 0.0))
            width = abs(float(size[0]))
            height = abs(float(size[1]))
            if width <= 0.0 or height <= 0.0:
                return None
            center = item.mapToParent(width / 2.0, height / 2.0)
            return replace(
                gate,
                thresholds={
                    "center_x": float(center.x()),
                    "center_y": float(center.y()),
                    "radius_x": width / 2.0,
                    "radius_y": height / 2.0,
                    "rotation": float(state.get("angle", 0.0)) * np.pi / 180.0,
                },
            )

        return None

    def _clear_scatter(self) -> None:
        self._density_render_key = None
        if self._population_scatter_items:
            for item, _color in self._population_scatter_items:
                try:
                    self._plot_item.removeItem(item)
                except Exception:
                    pass
            self._population_scatter_items.clear()
            self._scatter = None
        elif self._scatter is not None:
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
        self._reset_scene_interaction(item)
        try:
            self._plot_item.removeItem(item)
        except (RuntimeError, TypeError):
            logger.debug("Plot item was already removed", exc_info=True)
        # pyqtgraph's GraphicsScene can retain the item as ``acceptedItem``
        # until the current mouse drag finishes. Deleting it during that drag
        # makes the next mouseMoveEvent dereference a dead Shiboken wrapper.
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            if item not in self._retired_plot_items:
                self._retired_plot_items.append(item)
            QTimer.singleShot(50, self._dispose_retired_plot_items)
            return
        self._delete_plot_item(item)

    def _reset_scene_interaction(self, item: Any) -> None:
        """Drop pyqtgraph hover/drag references before removing an ROI.

        GraphicsScene keeps the last hover event and uses it to preselect a
        drag item on the next mouse move. Clearing the scene item while that
        event still points at the ROI leaves a dead Shiboken wrapper in
        ``acceptedItem``.
        """
        try:
            scene = self._plot_item.scene()
        except (AttributeError, RuntimeError):
            return
        if scene is None:
            return
        if getattr(scene, "lastHoverEvent", None) is not None:
            scene.lastHoverEvent = None
        if getattr(scene, "dragItem", None) is item:
            scene.dragItem = None
            scene.dragButtons = []
            scene.clickEvents = []
            scene.lastDrag = None

    def _dispose_retired_plot_items(self) -> None:
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            QTimer.singleShot(50, self._dispose_retired_plot_items)
            return
        items = self._retired_plot_items
        self._retired_plot_items = []
        for item in items:
            self._delete_plot_item(item)

    @staticmethod
    def _delete_plot_item(item: Any) -> None:
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
        from PySide6.QtGui import QColor

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
        preview_color = QColor(self._contrast_gate_color())
        rect = RectROI(
            [x_min, y_min],
            [width, height],
            pen=mkPen(color=preview_color, width=2, style=Qt.DotLine),
            movable=False,
            removable=False,
        )
        self._set_preview_item(rect)

    def _update_polygon_preview(self) -> None:
        from pyqtgraph import PlotDataItem, mkPen  # type: ignore[attr-defined]
        from PySide6.QtGui import QColor

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
        preview_color = QColor(self._contrast_gate_color())
        item = PlotDataItem(
            x_vals,
            y_vals,
            pen=mkPen(color=preview_color, width=2, style=Qt.DotLine),
            symbol="o",
            symbolSize=5,
            symbolBrush=preview_color,
        )
        self._set_preview_item(item)
        # PlotItem propagates its current log mode when a PlotDataItem is
        # inserted.  Gate preview vertices must remain in ViewBox coordinates.
        item.setLogMode(False, False)

    def _update_labels(self) -> None:
        # setLabel lives on PlotItem, not on ViewBox.
        self._set_axis_labels(self._x_label, self._y_label)

    @staticmethod
    def _label_font_style(value: Any) -> dict[str, str]:
        """Convert a resolved axis-label font into pyqtgraph CSS options."""
        if isinstance(value, dict):
            family = str(value.get("family", "DejaVu Sans"))
            size = float(value.get("size", 14.0))
            weight = str(value.get("weight", "bold"))
        else:
            family = str(getattr(value, "family", "DejaVu Sans"))
            size = float(getattr(value, "size", 14.0))
            weight = str(getattr(value, "weight", "bold"))
        return {
            "font-family": family,
            "font-size": f"{size:g}pt",
            "font-weight": weight,
        }

    def _set_axis_labels(self, x_label: str, y_label: str) -> None:
        """Set axis labels while retaining the resolved presentation font."""
        label_color = self._foreground_color(self._style.background_color)
        self._plot_item.setLabel(
            "bottom", x_label, color=label_color, **self._axis_label_text_style,
        )
        self._plot_item.setLabel(
            "left", y_label, color=label_color, **self._axis_label_text_style,
        )
        # Keep labels visible after pyqtgraph recalculates the layout.  Some
        # style/range updates can otherwise leave the text item hidden even
        # though ``labelText`` still contains the correct channel name.
        for axis_name, label in (("bottom", x_label), ("left", y_label)):
            axis = self._plot_item.getAxis(axis_name)
            axis.showLabel(bool(label))
            if getattr(axis, "label", None) is not None:
                axis.label.setVisible(bool(label))

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

        # Use all rendered layers, not only the first population-color layer.
        x_data = self._rendered_x
        y_data = self._rendered_y

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
        self._refresh_ticks_for_current_view()

    def _refresh_density_colors(self) -> None:
        """Assign stable colors from the full transformed display population."""
        if not self._density_coloring_active or self._density_input is None:
            return
        if self._rendered_x is None or self._rendered_y is None:
            return
        input_x, input_y = self._density_input
        if not len(input_x):
            return
        x_min, x_max = float(np.min(input_x)), float(np.max(input_x))
        y_min, y_max = float(np.min(input_y)), float(np.max(input_y))
        if x_min >= x_max or y_min >= y_max:
            return
        # Density is a property of the selected transformed population, not
        # the current camera. A fixed logical grid keeps colors invariant
        # across pan, zoom, resize, and screen DPI changes.
        logical_size = (512, 512)
        key = self._density_color_key(
            input_x, input_y, self._rendered_x, self._rendered_y
        )
        if key is None:
            return
        colors = self._density_color_cache.get(key)
        if colors is None:
            colors = estimate_density_colors(
                input_x, input_y, self._rendered_x, self._rendered_y,
                bounds=(x_min, x_max, y_min, y_max), logical_size=logical_size,
            ).colors
            self._density_color_cache = {key: colors}
        self._apply_density_colors(colors, key)

    def _schedule_density_colors(self, key: tuple[object, ...]) -> None:
        """Submit renderer-neutral density work without touching Qt in the worker."""
        if self._density_input is None or self._rendered_x is None or self._rendered_y is None:
            return
        input_x, input_y = self._density_input
        if not len(input_x) or not len(self._rendered_x):
            return
        x_min, x_max = float(np.min(input_x)), float(np.max(input_x))
        y_min, y_max = float(np.min(input_y)), float(np.max(input_y))
        if x_min >= x_max or y_min >= y_max:
            return
        cached = self._density_color_cache.get(key)
        if cached is not None:
            self._apply_density_colors(cached, key)
            return
        self._density_pending_key = key
        try:
            scheduler = self._get_density_scheduler()
            scheduler.schedule(
                DensityColorRequest(
                    key=key,
                    input_x=input_x,
                    input_y=input_y,
                    query_x=self._rendered_x,
                    query_y=self._rendered_y,
                    bounds=(x_min, x_max, y_min, y_max),
                    logical_size=(512, 512),
                )
            )
        except RuntimeError as exc:
            self._density_pending_key = None
            self.set_status_banner(f"Density colors unavailable: {exc}")

    def _get_density_scheduler(self) -> DensityColorScheduler:
        if self._density_scheduler is None:
            scheduler = DensityColorScheduler(self)
            scheduler.density_ready.connect(self._on_density_ready)
            scheduler.density_failed.connect(self._on_density_failed)
            self._density_scheduler = scheduler
        return self._density_scheduler

    def _on_density_ready(self, response: DensityColorResponse) -> None:
        """Apply only the latest semantic result on the GUI thread."""
        if not self._density_coloring_active or self._density_input is None:
            return
        if self._density_pending_key != response.key:
            return
        if self._rendered_x is None or self._rendered_y is None:
            return
        current_key = self._density_color_key(
            self._density_input[0], self._density_input[1],
            self._rendered_x, self._rendered_y,
        )
        if current_key != response.key:
            return
        colors = np.asarray(response.result.colors, dtype=str)
        if len(colors) != len(self._rendered_x):
            return
        self._density_color_cache = {response.key: colors}
        self._density_pending_key = None
        self._apply_density_colors(colors, response.key)

    def _on_density_failed(
        self, request: DensityColorRequest, error: Exception
    ) -> None:
        if self._density_pending_key != request.key:
            return
        self._density_pending_key = None
        self.set_status_banner(f"Density colors unavailable: {error}")

    def _apply_density_colors(
        self, colors: NDArray[np.str_], key: tuple[object, ...]
    ) -> None:
        """Apply colors to an existing scatter with minimal Qt payload."""
        if self._rendered_x is None or self._rendered_y is None:
            return
        self._event_colors = colors
        brushes = self._density_brushes(colors)
        if self._population_scatter_items or (
            self._scatter is not None
            and not isinstance(self._scatter, ScatterPlotItem)
        ):
            self._clear_scatter()
        if self._scatter is None:
            self._scatter = ScatterPlotItem()
            self._plot_item.addItem(self._scatter)
        if self._scatter.data is None or len(self._scatter.data) != len(self._rendered_x):
            self._scatter.setData(
                x=self._rendered_x,
                y=self._rendered_y,
                pen=None,
                brush=brushes,
                size=self._style.dot_size,
                symbol="o",
                pxMode=True,
            )
        else:
            self._scatter.setBrush(brushes)
            self._scatter.setSize(self._style.dot_size)
        self._density_render_key = key

    def _density_brushes(
        self,
        colors: NDArray[np.str_] | None = None,
    ) -> list[QBrush]:
        """Return opacity-adjusted brushes without rebuilding scatter X/Y data."""
        resolved_colors = self._event_colors if colors is None else colors
        if resolved_colors is None:
            return []
        opacity = float(self._style.dot_opacity)
        cached = self._density_brush_cache
        if (
            cached is not None
            and cached[0] is resolved_colors
            and cached[1] == opacity
        ):
            return cached[2]
        brushes_by_color = {
            str(color): self._make_brush(str(color), opacity)
            for color in np.unique(resolved_colors)
        }
        brushes = [brushes_by_color[str(color)] for color in resolved_colors]
        self._density_brush_cache = (resolved_colors, opacity, brushes)
        return brushes

    def _density_color_key(
        self,
        input_x: NDArray[np.float64],
        input_y: NDArray[np.float64],
        rendered_x: NDArray[np.float64],
        rendered_y: NDArray[np.float64],
    ) -> tuple[object, ...] | None:
        """Return the semantic identity of a whole-population density field.

        The main window supplies a processed-display identity that changes for
        every relevant sample/population/axis/transform/revision/display-selection
        edit.  Direct widget callers fall back to array identity.  Viewport,
        widget size, DPI, labels, and gate geometry deliberately do not enter
        this key because they do not define density.
        """
        if not len(input_x) or not len(rendered_x):
            return None
        x_min, x_max = float(np.min(input_x)), float(np.max(input_x))
        y_min, y_max = float(np.min(input_y)), float(np.max(input_y))
        if x_min >= x_max or y_min >= y_max:
            return None
        logical_size = (512, 512)
        return (
            self._density_cache_context
            if self._density_cache_context is not None
            else (id(input_x), id(input_y), id(rendered_x), id(rendered_y)),
            len(input_x), len(rendered_x),
            (x_min, x_max, y_min, y_max), logical_size,
        )

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
        if self._is_range_drag(event):
            self._on_range_drag(event)
            return
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

    @staticmethod
    def _is_range_drag(event: Any) -> bool:
        try:
            button = event.button()
            modifiers = event.modifiers()
        except Exception:
            return False
        return button == Qt.LeftButton and bool(modifiers & Qt.ControlModifier)

    def _on_range_drag(self, event: Any) -> None:
        """Match the historical ViewBox right-drag zoom gesture.

        PyQtGraph scales continuously around the button-down position.  This
        intentionally does not implement box zoom: Ctrl+left is a replacement
        for the old right-drag interaction, including its direction and anchor.
        """
        vb = self._view_box()
        if vb is None:
            event.accept()
            return
        try:
            screen_delta = event.screenPos() - event.lastScreenPos()
            dx = -float(screen_delta.x())
            dy = float(screen_delta.y())
            mouse_enabled = np.asarray(vb.state["mouseEnabled"], dtype=np.float64)
            mask = mouse_enabled.copy()
            if vb.state["aspectLocked"] is not False:
                mask[0] = 0.0
            scale = ((mask * 0.02) + 1.0) ** np.array([dx, dy])
            button_down = event.buttonDownPos(Qt.LeftButton)
            center = vb.mapSceneToView(button_down)
            vb.scaleBy(x=scale[0], y=scale[1], center=(center.x(), center.y()))
            vb.sigRangeChangedManually.emit(vb.state["mouseEnabled"])
        except Exception:
            logger.exception("Ctrl+left range zoom failed")
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
        self._range_drag_start: tuple[float, float] | None = None
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

        export_menu = menu.addMenu("Export")
        export_menu.setObjectName("plotExportMenu")
        for label, format_name in (
            ("PNG", "PNG"), ("JPEG", "JPEG"), ("SVG", "SVG"), ("PDF", "PDF"),
        ):
            action = export_menu.addAction(label)
            action.setObjectName(f"plotExport{format_name.title()}Action")
            action.triggered.connect(
                lambda _checked=False, value=format_name: self.export_requested.emit(value)
            )
        batch_action = export_menu.addAction("Batch Plot Export...")
        batch_action.setObjectName("plotExportBatchAction")
        batch_action.triggered.connect(
            lambda _checked=False: self.export_requested.emit("BATCH")
        )

        add_action("Plot Appearance...", "plotAppearance")

        range_menu = menu.addMenu("View Range")
        range_menu.setObjectName("plotViewRangeMenu")
        range_action = range_menu.addAction("Set numeric range...")
        range_action.setObjectName("plotSetNumericRange")
        range_action.triggered.connect(
            lambda _checked=False: self.view_range_requested.emit()
        )

        ticks_menu = menu.addMenu("Axis Ticks")
        ticks_menu.setObjectName("plotAxisTicksMenu")
        tick_choices = (
            ("Auto (recommended)", "auto"),
            ("Decades only", "decades"),
            ("1–2–5 labels", "one_two_five"),
            ("Legacy automatic", "legacy_auto"),
        )
        for label, policy in tick_choices:
            action = ticks_menu.addAction(label)
            action.setObjectName(f"plotAxisTicks{policy.title().replace('_', '')}")
            action.setCheckable(True)
            action.setChecked(self._tick_policy == policy)
            action.triggered.connect(
                lambda _checked=False, value=policy:
                self.appearance_requested.emit(f"axisTicks:{value}")
            )

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

        add_action("Reset View Appearance", "plotResetAppearance")
        return menu
