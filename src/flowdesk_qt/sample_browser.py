"""Sample browser widget.

Displays a list of FCS sample files and allows the user to select one for
analysis.  Delegates all FCS I/O to ``flowdesk_core.fcs_io``.
"""

from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk_core.fcs_io import FcsFileInfo, FcsIoError, read_fcs_info
from flowdesk_core.file_fingerprint import (
    FileFingerprint,
    compare_file_fingerprints,
    compute_file_fingerprint,
)
from flowdesk_core.models import ChannelSpec
from flowdesk_qt.diagnostics import invoke_callback

_CHANNEL_COLUMNS = (
    ("id", "Stable ID"),
    ("name", "$PnN"),
    ("short_name", "$PnS"),
    ("detector", "Detector"),
    ("stain", "Stain"),
    ("unit", "Unit"),
    ("fcs_parameter_index", "FCS index"),
    ("gain", "Gain (PnG)"),
    ("exponent", "Exponent (PnE)"),
    ("range", "Range (PnR)"),
)
_DEFAULT_COLUMNS = {"name", "short_name", "detector", "stain", "fcs_parameter_index"}

# ---------------------------------------------------------------------------
# Per-sample metadata model (GUI-side only, no scientific logic)
# ---------------------------------------------------------------------------


class _SampleInfo:
    """Lightweight holder for a loaded sample's metadata."""

    __slots__ = ("id", "name", "path", "info", "fingerprint", "status")

    def __init__(
        self,
        sample_id: str,
        name: str,
        path: str,
        info: FcsFileInfo,
        fingerprint: FileFingerprint | None = None,
        status: str = "match",
    ) -> None:
        self.id = sample_id
        self.name = name
        self.path = path
        self.info = info
        self.fingerprint = fingerprint
        self.status = status


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

    def add_project_samples(self, samples: list[dict[str, Any]]) -> int:
        """Restore project samples, retaining IDs and missing-file placeholders."""
        added = 0
        for sample in samples:
            if self._add_project_sample(sample):
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
        for index in range(self._list_widget.count()):
            if self._list_widget.item(index).data(Qt.UserRole) == sample_id:
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
        item = self._list_widget.currentItem()
        if item is None:
            return None
        sample_id = str(item.data(Qt.UserRole))
        idx = next((i for i, sample in enumerate(self._samples) if sample.id == sample_id), -1)
        if idx < 0:
            return None
        removed = self._samples.pop(idx)
        if removed.path:
            self._known_paths.discard(Path(removed.path).resolve())
        self._refresh_channel_statuses()
        self._rebuild_sample_list()

        # Auto-select next sample or clear selection.
        if self._samples:
            self._list_widget.setCurrentRow(min(idx, len(self._samples) - 1))
        else:
            self._selected_index = -1
            self._clear_channel_table()

        # Notify callbacks about removal.
        for cb in self._removed_callbacks:
            invoke_callback(cb, removed)

        return removed

    def set_channel_column_visible(self, key: str, visible: bool) -> None:
        """Show or hide one channel metadata column by stable key."""
        column = next((i for i, (name, _) in enumerate(_CHANNEL_COLUMNS) if name == key), -1)
        if column < 0:
            raise KeyError(key)
        self._channel_table.setColumnHidden(column, not visible)
        action = self._column_actions.get(key)
        if action is not None and action.isChecked() != visible:
            action.setChecked(visible)

    def reconnect_sample(
        self,
        sample_id: str,
        path: str | Path,
        allow_mismatch: bool = False,
    ) -> tuple[bool, str]:
        """Reconnect a sample, requiring explicit approval for identity changes."""
        sample = next((value for value in self._samples if value.id == sample_id), None)
        if sample is None:
            return False, "sample not found"
        candidate_path = Path(path).resolve()
        try:
            candidate_info = read_fcs_info(candidate_path)
            candidate_fingerprint = compute_file_fingerprint(candidate_path)
        except Exception as exc:
            return False, str(exc)

        fingerprint_matches = sample.fingerprint is None or compare_file_fingerprints(
            sample.fingerprint, candidate_fingerprint
        ).content_matches
        expected_ids = tuple(channel.id for channel in sample.info.channels)
        candidate_ids = tuple(channel.id for channel in candidate_info.channels)
        metadata_matches = expected_ids == candidate_ids
        if not (fingerprint_matches and metadata_matches) and not allow_mismatch:
            details = (
                f"content hash: {'match' if fingerprint_matches else 'DIFFERENT'}; "
                f"channel identity/order: {'match' if metadata_matches else 'DIFFERENT'}"
            )
            return False, details

        if sample.path:
            self._known_paths.discard(Path(sample.path).resolve())
        sample.path = str(candidate_path)
        sample.info = candidate_info
        sample.fingerprint = candidate_fingerprint
        sample.status = "match"
        self._known_paths.add(candidate_path)
        self._refresh_channel_statuses()
        self._rebuild_sample_list(selected_id=sample.id)
        for callback in self._reconnected_callbacks:
            invoke_callback(callback, sample)
        return True, "content hash and channel metadata accepted"

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

    def on_sample_reconnected(self, callback: Any) -> None:
        """Register a callback invoked after a reconnect is accepted."""
        self._reconnected_callbacks.append(callback)

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
            fingerprint = compute_file_fingerprint(resolved)
        except FcsIoError:
            return False
        except Exception:
            return False

        sample_name = resolved.stem
        # Stable unique id: stem + first 8 hex chars of sha1 of resolved path.
        path_hash = hashlib.sha1(str(resolved).encode()).hexdigest()[:8]
        sample_id = f"{sample_name}_{path_hash}"

        self._known_paths.add(resolved)
        si = _SampleInfo(sample_id, sample_name, str(resolved), info, fingerprint)
        self._samples.append(si)
        self._refresh_channel_statuses()
        self._rebuild_sample_list()
        return True

    def _add_project_sample(self, sample: dict[str, Any]) -> bool:
        sample_id = str(sample.get("id", ""))
        if not sample_id or any(existing.id == sample_id for existing in self._samples):
            return False
        path = Path(str(sample.get("path", "")))
        expected = None
        fingerprint_data = sample.get("fingerprint")
        if isinstance(fingerprint_data, dict):
            try:
                expected = FileFingerprint.from_mapping(fingerprint_data)
            except ValueError:
                expected = None
        stored_channels = tuple(
            ChannelSpec(**{
                field.name: channel[field.name]
                for field in fields(ChannelSpec)
                if field.name in channel
            })
            for channel in sample.get("channels", [])
            if isinstance(channel, dict)
        )
        placeholder = FcsFileInfo("", "", "", "", 0, len(stored_channels), stored_channels, {})
        info = placeholder
        status = "missing"
        candidate_fingerprint = expected
        if path.is_file():
            try:
                candidate_info = read_fcs_info(path)
                actual = compute_file_fingerprint(path)
                candidate_fingerprint = expected or actual
                hash_matches = expected is None or compare_file_fingerprints(
                    expected, actual
                ).content_matches
                channels_match = (
                    not stored_channels
                    or tuple(ch.id for ch in stored_channels)
                    == tuple(ch.id for ch in candidate_info.channels)
                )
                status = "match" if hash_matches and channels_match else "fingerprint mismatch"
                if status == "match":
                    info = candidate_info
            except Exception:
                status = "missing"
        si = _SampleInfo(
            sample_id,
            str(sample.get("name", sample_id)),
            str(path),
            info,
            candidate_fingerprint,
            status,
        )
        self._samples.append(si)
        if path.is_file():
            self._known_paths.add(path.resolve())
        self._refresh_channel_statuses()
        self._rebuild_sample_list()
        return True

    def _on_list_selection_changed(self) -> None:
        item = self._list_widget.currentItem()
        if item is None:
            self._selected_index = -1
            self._clear_channel_table()
            return

        sample_id = str(item.data(Qt.UserRole))
        self._selected_index = next(
            (index for index, sample in enumerate(self._samples) if sample.id == sample_id), -1
        )
        if self._selected_index < 0:
            return
        sample = self._samples[self._selected_index]
        self._populate_channel_table(sample.info)

        for cb in self._selection_callbacks:
            invoke_callback(cb, sample)

    def _populate_channel_table(self, info: FcsFileInfo) -> None:
        self._channel_table.setSortingEnabled(False)
        self._channel_table.setRowCount(len(info.channels))
        for row, ch in enumerate(info.channels):
            values = (
                ch.id, ch.name, ch.short_name, ch.detector, ch.stain, ch.unit,
                ch.fcs_parameter_index, ch.metadata.get("png", ""),
                ch.metadata.get("pne", ""), ch.metadata.get("pnr", ""),
            )
            for column, value in enumerate(values):
                text = "" if value is None else str(value)
                self._channel_table.setItem(row, column, QTableWidgetItem(text))
        self._channel_table.setSortingEnabled(True)

    def _refresh_channel_statuses(self) -> None:
        reference = next(
            (sample for sample in self._samples
             if sample.status not in {"missing", "fingerprint mismatch"}),
            None,
        )
        if reference is None:
            return
        reference_ids = tuple(channel.id for channel in reference.info.channels)
        for sample in self._samples:
            if sample.status in {"missing", "fingerprint mismatch"}:
                continue
            channel_ids = tuple(channel.id for channel in sample.info.channels)
            if channel_ids == reference_ids:
                sample.status = "match"
            elif set(channel_ids) == set(reference_ids):
                sample.status = "order differs"
            else:
                sample.status = "channel mismatch"

    def _rebuild_sample_list(self, selected_id: str | None = None) -> None:
        if selected_id is None and self._list_widget.currentItem() is not None:
            selected_id = str(self._list_widget.currentItem().data(Qt.UserRole))
        labels = {"match": "✓", "order differs": "↕", "channel mismatch": "≠",
                  "fingerprint mismatch": "!", "missing": "?"}
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        for sample in self._samples:
            item = QListWidgetItem(
                f"[{labels.get(sample.status, '!')}] {sample.name}  "
                f"({sample.info.event_count} events) — {sample.status}"
            )
            item.setData(Qt.UserRole, sample.id)
            item.setToolTip(sample.path)
            self._list_widget.addItem(item)
        self._list_widget.blockSignals(False)
        self._apply_filter(self._filter_edit.text())
        if selected_id is not None:
            self.select_sample(selected_id)

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold().strip()
        by_id = {sample.id: sample for sample in self._samples}
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            sample = by_id.get(str(item.data(Qt.UserRole)))
            haystack = ""
            if sample is not None:
                haystack = f"{sample.name} {sample.path} {sample.status}".casefold()
            item.setHidden(bool(needle) and needle not in haystack)

    def _sort_samples(self) -> None:
        selected = self.selected_sample()
        key = self._sort_combo.currentData()
        self._samples.sort(key=lambda sample: str(getattr(sample, key, "")).casefold())
        self._rebuild_sample_list(selected.id if selected is not None else None)

    def _clear_channel_table(self) -> None:
        self._channel_table.setRowCount(0)

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._selection_callbacks: list[Any] = []
        self._removed_callbacks: list[Any] = []
        self._reconnected_callbacks: list[Any] = []
        self.setObjectName("sampleBrowser")

        self._list_widget = QListWidget()
        self._list_widget.setObjectName("sampleList")
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)

        self._filter_edit = QLineEdit()
        self._filter_edit.setObjectName("sampleFilterEdit")
        self._filter_edit.setPlaceholderText("Filter samples…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("sampleSortCombo")
        self._sort_combo.addItem("Name", "name")
        self._sort_combo.addItem("Path", "path")
        self._sort_combo.addItem("Status", "status")
        self._sort_combo.currentIndexChanged.connect(lambda _index: self._sort_samples())

        self._channel_table = QTableWidget()
        self._channel_table.setObjectName("channelMetadataTable")
        self._channel_table.setColumnCount(len(_CHANNEL_COLUMNS))
        self._channel_table.setHorizontalHeaderLabels([label for _, label in _CHANNEL_COLUMNS])
        self._channel_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._channel_table.setSortingEnabled(True)

        self._column_button = QToolButton()
        self._column_button.setObjectName("channelColumnButton")
        self._column_button.setText("Columns")
        self._column_button.setPopupMode(QToolButton.InstantPopup)
        column_menu = QMenu(self._column_button)
        self._column_actions: dict[str, QAction] = {}
        for key, label in _CHANNEL_COLUMNS:
            action = QAction(label, column_menu)
            action.setObjectName(f"channelColumn_{key}")
            action.setCheckable(True)
            action.setChecked(key in _DEFAULT_COLUMNS)
            action.toggled.connect(
                lambda visible, column_key=key: self.set_channel_column_visible(column_key, visible)
            )
            column_menu.addAction(action)
            self._column_actions[key] = action
        self._column_button.setMenu(column_menu)
        for key, _ in _CHANNEL_COLUMNS:
            self.set_channel_column_visible(key, key in _DEFAULT_COLUMNS)

        self._btn_add = QPushButton("Add FCS Files...")
        self._btn_add.setObjectName("addFcsFilesButton")
        self._btn_add.clicked.connect(self._on_add_files)

        self._btn_remove = QPushButton("Remove Selected")
        self._btn_remove.setObjectName("removeSampleButton")
        self._btn_remove.clicked.connect(self._on_remove_selected)

        self._btn_reconnect = QPushButton("Reconnect…")
        self._btn_reconnect.setObjectName("reconnectSampleButton")
        self._btn_reconnect.clicked.connect(self._on_reconnect_selected)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Samples"))
        controls = QHBoxLayout()
        controls.addWidget(self._filter_edit)
        controls.addWidget(self._sort_combo)
        left_layout.addLayout(controls)
        left_layout.addWidget(self._list_widget)
        left_layout.addWidget(self._btn_add)
        left_layout.addWidget(self._btn_remove)
        left_layout.addWidget(self._btn_reconnect)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        metadata_header = QHBoxLayout()
        metadata_header.addWidget(QLabel("Channel Metadata"))
        metadata_header.addWidget(self._column_button)
        right_layout.addLayout(metadata_header)
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

    def _on_reconnect_selected(self) -> None:
        sample = self.selected_sample()
        if sample is None:
            QMessageBox.information(self, "No sample selected", "Select a sample to reconnect.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Reconnect FCS sample", sample.path, "FCS files (*.fcs);;All files (*)"
        )
        if not path:
            return
        accepted, details = self.reconnect_sample(sample.id, path)
        if accepted:
            return
        answer = QMessageBox.question(
            self,
            "Input identity mismatch",
            f"The selected file does not match the stored sample.\n\n{details}\n\n"
            "Reconnect anyway and replace the stored identity?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.reconnect_sample(sample.id, path, allow_mismatch=True)
