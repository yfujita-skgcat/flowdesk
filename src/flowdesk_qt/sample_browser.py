"""Sample browser widget.

Displays a list of FCS sample files and allows the user to select one for
analysis.  Delegates all FCS I/O to ``flowdesk_core.fcs_io``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.fcs_io import FcsFileInfo, FcsIoError, read_fcs_info

# ---------------------------------------------------------------------------
# Per-sample metadata model (GUI-side only, no scientific logic)
# ---------------------------------------------------------------------------


class _SampleInfo:
    """Lightweight holder for a loaded sample's metadata."""

    __slots__ = ("id", "name", "path", "info")

    def __init__(
        self,
        sample_id: str,
        name: str,
        path: str,
        info: FcsFileInfo,
    ) -> None:
        self.id = sample_id
        self.name = name
        self.path = path
        self.info = info


# ---------------------------------------------------------------------------
# SampleBrowser widget
# ---------------------------------------------------------------------------


class SampleBrowser(QWidget):
    """Left-pane widget that lists samples and shows channel metadata.

    Signals:
      sample_selected: Emitted when the user selects a sample.
          Payload is ``_SampleInfo``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: list[_SampleInfo] = []
        self._selected_index: int = -1
        self._build_ui()

    # -- public API ----------------------------------------------------------

    def add_samples_from_directory(
        self,
        directory: str | Path,
    ) -> int:
        """Scan *directory* for ``.fcs`` files and add them to the list.

        Returns the number of samples successfully added.
        """
        dirpath = Path(directory)
        added = 0
        for f in sorted(dirpath.glob("*.fcs")):
            if self._add_single_file(str(f)):
                added += 1
        return added

    def add_samples_from_paths(
        self,
        paths: list[str],
    ) -> int:
        """Add FCS files from explicit paths.

        Returns the number of samples successfully added.
        """
        added = 0
        for p in paths:
            if self._add_single_file(p):
                added += 1
        return added

    def selected_sample(self) -> _SampleInfo | None:
        """Return the currently selected sample, or ``None``."""
        if 0 <= self._selected_index < len(self._samples):
            return self._samples[self._selected_index]
        return None

    def selected_channel_names(self) -> list[str]:
        """Return the channel names of the currently selected sample."""
        sample = self.selected_sample()
        if sample is None:
            return []
        return [ch.name for ch in sample.info.channels]

    # -- signals (Qt-free, callback-based) -----------------------------------

    def on_sample_selected(self, callback: Any) -> None:
        """Register a callback invoked when a sample is selected.

        The callback receives a ``_SampleInfo`` instance.
        """
        self._selection_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _add_single_file(self, path: str) -> bool:
        """Try to read FCS metadata and add to the list."""
        try:
            info = read_fcs_info(path)
        except FcsIoError:
            return False
        except Exception:
            return False

        sample_name = Path(path).stem
        sample_id = sample_name  # simple id for now
        si = _SampleInfo(sample_id, sample_name, path, info)
        self._samples.append(si)
        self._list_widget.addItem(f"{sample_name}  ({info.event_count} events)")
        return True

    def _on_list_selection_changed(self) -> None:
        indexes = self._list_widget.currentRow()
        if indexes < 0:
            self._selected_index = -1
            self._clear_channel_table()
            return

        self._selected_index = indexes
        sample = self._samples[indexes]
        self._populate_channel_table(sample.info)

        for cb in self._selection_callbacks:
            try:
                cb(sample)
            except Exception:
                pass

    def _populate_channel_table(self, info: FcsFileInfo) -> None:
        self._channel_table.setRowCount(len(info.channels))
        for row, ch in enumerate(info.channels):
            self._channel_table.setItem(row, 0, QTableWidgetItem(ch.name))
            self._channel_table.setItem(row, 1, QTableWidgetItem(str(ch.metadata.get("png", ""))))
            self._channel_table.setItem(row, 2, QTableWidgetItem(str(ch.metadata.get("pne", ""))))
            self._channel_table.setItem(row, 3, QTableWidgetItem(str(ch.metadata.get("pnr", ""))))

    def _clear_channel_table(self) -> None:
        self._channel_table.setRowCount(0)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._selection_callbacks: list[Any] = []

        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)

        self._channel_table = QTableWidget()
        self._channel_table.setColumnCount(4)
        self._channel_table.setHorizontalHeaderLabels(
            [
                "Channel",
                "Gain (png)",
                "Exponent (pne)",
                "Range (pnr)",
            ]
        )
        self._channel_table.setEditTriggers(QTableWidget.NoEditTriggers)

        self._btn_add = QPushButton("Add FCS Files...")
        self._btn_add.clicked.connect(self._on_add_files)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Samples"))
        left_layout.addWidget(self._list_widget)
        left_layout.addWidget(self._btn_add)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Channel Metadata"))
        right_layout.addWidget(self._channel_table)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select FCS files",
            "",
            "FCS files (*.fcs);;All files (*)",
        )
        if paths:
            count = self.add_samples_from_paths(paths)
            if count == 0:
                QMessageBox.warning(
                    self,
                    "No samples added",
                    "None of the selected files could be read as valid FCS files.",
                )
