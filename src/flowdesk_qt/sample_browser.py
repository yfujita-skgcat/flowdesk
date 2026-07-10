"""Sample browser widget.

Displays a list of FCS sample files and allows the user to select one for
analysis.  Delegates all FCS I/O to ``flowdesk_core.fcs_io``.
"""

from __future__ import annotations

import hashlib
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
        self._known_paths: set[Path] = set()
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

    def samples(self) -> list[_SampleInfo]:
        """Return all samples currently included in the session."""
        return list(self._samples)

    def clear_samples(self) -> None:
        """Remove all samples without emitting per-sample removal callbacks."""
        self._samples.clear()
        self._known_paths.clear()
        self._selected_index = -1
        self._list_widget.clear()
        self._clear_channel_table()

    def select_sample(self, sample_id: str) -> bool:
        """Select a sample by stable id and emit the normal selection callback."""
        for index, sample in enumerate(self._samples):
            if sample.id == sample_id:
                self._list_widget.setCurrentRow(index)
                return True
        return False

    def selected_channel_names(self) -> list[str]:
        """Return the channel names of the currently selected sample."""
        sample = self.selected_sample()
        if sample is None:
            return []
        return [ch.name for ch in sample.info.channels]

    def remove_selected_sample(self) -> _SampleInfo | None:
        """Remove the currently selected sample from the list.

        Returns the removed ``_SampleInfo``, or ``None`` if nothing was selected.
        Also auto-selects the next available sample (or clears selection).
        """
        idx = self._list_widget.currentRow()
        if idx < 0 or idx >= len(self._samples):
            return None

        removed = self._samples.pop(idx)
        self._known_paths.discard(Path(removed.path).resolve())
        item = self._list_widget.takeItem(idx)
        del item  # free Qt object

        # Auto-select next sample or clear selection.
        if self._samples:
            new_idx = min(idx, len(self._samples) - 1)
            self._list_widget.setCurrentRow(new_idx)
        else:
            self._selected_index = -1
            self._clear_channel_table()

        # Notify callbacks about removal.
        for cb in self._removed_callbacks:
            try:
                cb(removed)
            except Exception:
                pass

        return removed

    # -- signals (Qt-free, callback-based) -----------------------------------

    def on_sample_selected(self, callback: Any) -> None:
        """Register a callback invoked when a sample is selected.

        The callback receives a ``_SampleInfo`` instance.
        """
        self._selection_callbacks.append(callback)

    def on_sample_removed(self, callback: Any) -> None:
        """Register a callback invoked when a sample is removed.

        The callback receives a ``_SampleInfo`` instance of the removed sample.
        """
        self._removed_callbacks.append(callback)

    # -- private ------------------------------------------------------------

    def _add_single_file(self, path: str) -> bool:
        """Try to read FCS metadata and add to the list.

        Skips files whose resolved absolute path is already registered.
        Returns ``True`` if the sample was actually added.
        """
        resolved = Path(path).resolve()

        # Skip duplicates by resolved absolute path.
        if resolved in self._known_paths:
            return False

        try:
            info = read_fcs_info(path)
        except FcsIoError:
            return False
        except Exception:
            return False

        sample_name = resolved.stem
        # Stable unique id: stem + first 8 hex chars of sha1 of resolved path.
        path_hash = hashlib.sha1(str(resolved).encode()).hexdigest()[:8]
        sample_id = f"{sample_name}_{path_hash}"

        self._known_paths.add(resolved)
        si = _SampleInfo(sample_id, sample_name, str(resolved), info)
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
        self._removed_callbacks: list[Any] = []

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

        self._btn_remove = QPushButton("Remove Selected")
        self._btn_remove.clicked.connect(self._on_remove_selected)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Samples"))
        left_layout.addWidget(self._list_widget)
        left_layout.addWidget(self._btn_add)
        left_layout.addWidget(self._btn_remove)

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

    def _on_remove_selected(self) -> None:
        removed = self.remove_selected_sample()
        if removed is None:
            QMessageBox.information(
                self,
                "No sample selected",
                "Select a sample from the list before removing.",
            )
