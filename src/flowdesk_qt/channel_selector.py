"""Channel selector widget.

Allows the user to choose X and Y parameters for a 2D plot, and to select
the axis transform (linear / log10 / asinh) for display.
Contains no scientific logic; merely exposes parameter choices.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.models import ChannelSpec
from flowdesk_qt.diagnostics import invoke_callback

AxisTransform = Literal["linear", "log10", "asinh"]

_TRANSFORM_OPTIONS: list[AxisTransform] = ["linear", "log10", "asinh"]

# Sentinel value for histogram mode. This string must not collide with any real
# FCS channel name (which are user-provided and typically short).
COUNT_CHANNEL = "__count__"
COUNT_DISPLAY = "Count"
DEFAULT_DISPLAY_MAX_POINTS = 20_000


class ChannelSelector(QWidget):
    """Two-combo-box widget for X/Y channel selection with axis transforms.

    Signals are emitted when either selection changes.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def set_channels(
        self,
        channels: list[str],
        preserve_selection: bool = True,
    ) -> tuple[bool, bool]:
        """Populate both combo boxes with *channels*.

        The Y axis combo also includes the display-only ``Count`` option,
        which switches the plot to 1D histogram mode.

        Returns ``(x_preserved, y_preserved)`` so callers can report when a
        selection had to fall back because the new sample lacks that channel.
        Axis transform selections are not changed.
        """
        return self.set_channel_specs(
            [ChannelSpec(id=name, name=name) for name in channels],
            preserve_selection=preserve_selection,
        )

    def set_channel_specs(
        self,
        channels: list[ChannelSpec] | tuple[ChannelSpec, ...],
        preserve_selection: bool = True,
    ) -> tuple[bool, bool]:
        """Populate selectors with display labels backed by stable channel IDs."""
        prev_x = self.x_channel_id() if preserve_selection else ""
        prev_y = self.y_channel_id() if preserve_selection else ""

        with QSignalBlocker(self._x_combo), QSignalBlocker(self._y_combo):
            self._x_combo.clear()
            self._y_combo.clear()
            for channel in channels:
                label = channel.name
                if channel.short_name and channel.short_name != channel.name:
                    label = f"{channel.short_name} [{channel.name}]"
                self._x_combo.addItem(label, channel.id)
                self._y_combo.addItem(label, channel.id)
            self._y_combo.addItem(COUNT_DISPLAY, COUNT_CHANNEL)

            x_index = self._x_combo.findData(prev_x)
            y_index = self._y_combo.findData(prev_y)
            x_preserved = prev_x != "" and x_index >= 0
            y_preserved = prev_y != "" and y_index >= 0
            if x_preserved:
                self._x_combo.setCurrentIndex(x_index)
            elif channels:
                self._x_combo.setCurrentIndex(0)

            if y_preserved:
                self._y_combo.setCurrentIndex(y_index)
            elif len(channels) >= 2:
                self._y_combo.setCurrentIndex(1)
            elif channels:
                self._y_combo.setCurrentIndex(0)

        self._on_any_changed()
        return (x_preserved, y_preserved)

    def x_channel(self) -> str:
        """Return the currently selected X channel name."""
        return self._x_combo.currentText()

    def x_channel_id(self) -> str:
        """Return the stable ID of the selected X channel."""
        return self._x_combo.currentData() or self._x_combo.currentText()

    def y_channel(self) -> str:
        """Return the currently selected Y channel name (display label)."""
        return self._y_combo.currentText()

    def y_channel_id(self) -> str:
        """Return the internal ID of the Y selection (may be COUNT_CHANNEL)."""
        return self._y_combo.currentData() or self._y_combo.currentText()

    def is_count_mode(self) -> bool:
        """Return True when Y axis is set to the Count (histogram) option."""
        return self.y_channel_id() == COUNT_CHANNEL

    def x_index(self) -> int:
        """Return the index of the X channel within the channel list."""
        return self._x_combo.currentIndex()

    def y_index(self) -> int:
        """Return the index of the Y channel within the channel list."""
        return self._y_combo.currentIndex()

    def set_selected_channels(self, x_channel: str, y_channel: str) -> None:
        """Restore channel selections when the named channels are available.

        If ``y_channel`` is ``COUNT_CHANNEL``, the Count option is selected.
        """
        x_index = self._x_combo.findData(x_channel)
        if x_index < 0:
            x_index = self._x_combo.findText(x_channel)
        if x_index >= 0:
            self._x_combo.setCurrentIndex(x_index)
        if y_channel == COUNT_CHANNEL:
            # Find the Count sentinel by its user data.
            for i in range(self._y_combo.count()):
                if self._y_combo.itemData(i) == COUNT_CHANNEL:
                    self._y_combo.setCurrentIndex(i)
                    break
        else:
            y_index = self._y_combo.findData(y_channel)
            if y_index < 0:
                y_index = self._y_combo.findText(y_channel)
            if y_index >= 0:
                self._y_combo.setCurrentIndex(y_index)

    # -- axis transform API --------------------------------------------------

    def x_transform(self) -> AxisTransform:
        """Return the currently selected X axis transform."""
        return self._x_transform_combo.currentText()  # type: ignore[return-value]

    def y_transform(self) -> AxisTransform:
        """Return the currently selected Y axis transform."""
        return self._y_transform_combo.currentText()  # type: ignore[return-value]

    def set_x_transform(self, transform: AxisTransform) -> None:
        """Set the X axis transform programmatically."""
        idx = self._x_transform_combo.findText(transform)
        if idx >= 0:
            self._x_transform_combo.setCurrentIndex(idx)

    def set_y_transform(self, transform: AxisTransform) -> None:
        """Set the Y axis transform programmatically."""
        idx = self._y_transform_combo.findText(transform)
        if idx >= 0:
            self._y_transform_combo.setCurrentIndex(idx)

    def set_y_transform_disabled(self, disabled: bool) -> None:
        """Enable or disable the Y transform combo box.

        When disabled (histogram mode), the Y transform has no effect.
        """
        self._y_transform_combo.setEnabled(not disabled)

    def set_analysis_transform_bound(self, x_bound: bool, y_bound: bool) -> None:
        """Lock legacy display-scale controls when formal coordinates are active."""
        with QSignalBlocker(self._x_transform_combo), QSignalBlocker(
            self._y_transform_combo
        ):
            if x_bound:
                self._x_transform_combo.setCurrentText("linear")
            if y_bound:
                self._y_transform_combo.setCurrentText("linear")
        self._x_transform_combo.setEnabled(not x_bound)
        self._y_transform_combo.setEnabled(not y_bound and not self.is_count_mode())

    def display_max_points(self) -> int:
        """Return the display-only scatter sampling limit; zero disables it."""
        return int(self._display_max_points_spin.value())

    def set_display_max_points(self, value: int) -> None:
        """Restore a non-negative display-only scatter sampling limit."""
        with QSignalBlocker(self._display_max_points_spin):
            self._display_max_points_spin.setValue(max(0, int(value)))

    # -- signals (callback-based) --------------------------------------------

    def on_channel_changed(self, callback) -> None:
        """Register a callback invoked when X or Y selection changes.

        The callback receives ``(x_name: str, y_name: str)``.
        """
        self._change_callbacks.append(callback)

    def on_display_max_points_changed(self, callback) -> None:
        """Register a callback receiving the display-only maximum point count."""
        self._display_max_points_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _on_any_changed(self) -> None:
        x = self.x_channel()
        y = self.y_channel()
        # Disable Y transform when in histogram (Count) mode.
        if self.is_count_mode():
            self._y_transform_combo.setEnabled(False)
        for cb in self._change_callbacks:
            invoke_callback(cb, x, y)

    def _on_display_max_points_changed(self, value: int) -> None:
        for callback in self._display_max_points_callbacks:
            invoke_callback(callback, int(value))

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._change_callbacks = []
        self._display_max_points_callbacks = []
        self.setObjectName("channelSelector")

        self._x_combo = QComboBox()
        self._x_combo.setObjectName("xChannelCombo")
        self._y_combo = QComboBox()
        self._y_combo.setObjectName("yChannelCombo")

        self._x_transform_combo = QComboBox()
        self._x_transform_combo.setObjectName("xTransformCombo")
        self._x_transform_combo.addItems(_TRANSFORM_OPTIONS)
        self._y_transform_combo = QComboBox()
        self._y_transform_combo.setObjectName("yTransformCombo")
        self._y_transform_combo.addItems(_TRANSFORM_OPTIONS)

        self._display_max_points_spin = QSpinBox()
        self._display_max_points_spin.setObjectName("displayMaxPointsSpinBox")
        self._display_max_points_spin.setRange(0, 10_000_000)
        self._display_max_points_spin.setSingleStep(5_000)
        self._display_max_points_spin.setValue(DEFAULT_DISPLAY_MAX_POINTS)
        self._display_max_points_spin.setSpecialValueText("0 (all events)")
        self._display_max_points_spin.setToolTip(
            "Maximum scatter points drawn per layer. Set to 0 to draw all events. "
            "Sampling can omit rare uncolored events; population colors are sampled "
            "separately. Gates and statistics always use all events."
        )

        # Connect all change sources to the same callback.
        self._x_combo.currentTextChanged.connect(self._on_any_changed)
        self._y_combo.currentTextChanged.connect(self._on_any_changed)
        self._x_transform_combo.currentTextChanged.connect(self._on_any_changed)
        self._y_transform_combo.currentTextChanged.connect(self._on_any_changed)
        self._display_max_points_spin.valueChanged.connect(
            self._on_display_max_points_changed
        )

        form = QFormLayout()
        form.addRow("X axis:", self._x_combo)
        form.addRow("Y axis:", self._y_combo)
        form.addRow("X scale:", self._x_transform_combo)
        form.addRow("Y scale:", self._y_transform_combo)
        form.addRow("Display max points:", self._display_max_points_spin)

        box = QGroupBox("Plot Parameters")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
