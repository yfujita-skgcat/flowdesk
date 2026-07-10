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
    QVBoxLayout,
    QWidget,
)

AxisTransform = Literal["linear", "log10", "asinh"]

_TRANSFORM_OPTIONS: list[AxisTransform] = ["linear", "log10", "asinh"]


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

        Returns ``(x_preserved, y_preserved)`` so callers can report when a
        selection had to fall back because the new sample lacks that channel.
        Axis transform selections are not changed.
        """
        prev_x = self.x_channel() if preserve_selection else ""
        prev_y = self.y_channel() if preserve_selection else ""

        with QSignalBlocker(self._x_combo), QSignalBlocker(self._y_combo):
            self._x_combo.clear()
            self._y_combo.clear()
            self._x_combo.addItems(channels)
            self._y_combo.addItems(channels)

            x_preserved = False
            y_preserved = False
            if prev_x and prev_x in channels:
                self._x_combo.setCurrentText(prev_x)
                x_preserved = True
            elif len(channels) >= 1:
                self._x_combo.setCurrentIndex(0)

            if prev_y and prev_y in channels:
                self._y_combo.setCurrentText(prev_y)
                y_preserved = True
            elif len(channels) >= 2:
                self._y_combo.setCurrentIndex(1)
            elif len(channels) >= 1:
                self._y_combo.setCurrentIndex(0)

        self._on_any_changed()
        return (x_preserved, y_preserved)

    def x_channel(self) -> str:
        """Return the currently selected X channel name."""
        return self._x_combo.currentText()

    def y_channel(self) -> str:
        """Return the currently selected Y channel name."""
        return self._y_combo.currentText()

    def x_index(self) -> int:
        """Return the index of the X channel within the channel list."""
        return self._x_combo.currentIndex()

    def y_index(self) -> int:
        """Return the index of the Y channel within the channel list."""
        return self._y_combo.currentIndex()

    def set_selected_channels(self, x_channel: str, y_channel: str) -> None:
        """Restore channel selections when the named channels are available."""
        if self._x_combo.findText(x_channel) >= 0:
            self._x_combo.setCurrentText(x_channel)
        if self._y_combo.findText(y_channel) >= 0:
            self._y_combo.setCurrentText(y_channel)

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

    # -- signals (callback-based) --------------------------------------------

    def on_channel_changed(self, callback) -> None:
        """Register a callback invoked when X or Y selection changes.

        The callback receives ``(x_name: str, y_name: str)``.
        """
        self._change_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _on_any_changed(self) -> None:
        x = self.x_channel()
        y = self.y_channel()
        for cb in self._change_callbacks:
            try:
                cb(x, y)
            except Exception:
                pass

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._change_callbacks = []

        self._x_combo = QComboBox()
        self._y_combo = QComboBox()

        self._x_transform_combo = QComboBox()
        self._x_transform_combo.addItems(_TRANSFORM_OPTIONS)
        self._y_transform_combo = QComboBox()
        self._y_transform_combo.addItems(_TRANSFORM_OPTIONS)

        # Connect all change sources to the same callback.
        self._x_combo.currentTextChanged.connect(self._on_any_changed)
        self._y_combo.currentTextChanged.connect(self._on_any_changed)
        self._x_transform_combo.currentTextChanged.connect(self._on_any_changed)
        self._y_transform_combo.currentTextChanged.connect(self._on_any_changed)

        form = QFormLayout()
        form.addRow("X axis:", self._x_combo)
        form.addRow("Y axis:", self._y_combo)
        form.addRow("X scale:", self._x_transform_combo)
        form.addRow("Y scale:", self._y_transform_combo)

        box = QGroupBox("Plot Parameters")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
