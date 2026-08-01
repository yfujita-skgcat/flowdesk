"""Sample browser widget.

Displays a list of FCS sample files and allows the user to select one for
analysis.  Delegates all FCS I/O to ``flowdesk_core.fcs_io``.
"""

from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
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
    QSizePolicy,
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

DEFAULT_OVERLAY_SAMPLE_COLOR = "#4c78a8"

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


class _SampleListWidget(QListWidget):
  """List widget exposing keyboard and internal drag reordering."""

  order_changed = Signal(list)
  move_requested = Signal(int)

  def keyPressEvent(self, event) -> None:
    if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
      if event.key() == Qt.Key.Key_Up:
        self.move_requested.emit(-1)
        event.accept()
        return
      if event.key() == Qt.Key.Key_Down:
        self.move_requested.emit(1)
        event.accept()
        return
    super().keyPressEvent(event)

  def dropEvent(self, event) -> None:
    before = [
      str(self.item(index).data(Qt.ItemDataRole.UserRole))
      for index in range(self.count())
    ]
    super().dropEvent(event)
    after = [
      str(self.item(index).data(Qt.ItemDataRole.UserRole))
      for index in range(self.count())
    ]
    if before != after:
      self.order_changed.emit(after)


# ---------------------------------------------------------------------------
# SampleBrowser widget
# ---------------------------------------------------------------------------


class SampleBrowser(QWidget):
    """Left-pane widget that lists samples and manages sample selection.

    Signals:
      sample_selected: Emitted when the user selects a sample.
          Payload is ``_SampleInfo``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: list[_SampleInfo] = []
        self._display_names: dict[str, str] = {}
        self._selected_index: int = -1
        self._known_paths: set[Path] = set()
        self._manual_overlay_sample_ids: set[str] = set()
        self._manual_overlay_colors: dict[str, str] = {}
        self._overlay_roles: dict[str, str] = {}
        self._comparison_sets: list[dict[str, object]] = []
        self._comparison_role_colors: dict[str, str] = {
            "reference": "#377eb8",
            "target": "#e67e22",
            "positive_control": "#2ca02c",
            "negative_control": "#7f7f7f",
        }
        self._overlay_mode = "manual_only"
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

    def overlay_color(self, sample_id: str) -> str:
        """Return the color used for a sample's overlay row and dots."""
        explicit = self._manual_overlay_colors.get(sample_id)
        if explicit:
            return explicit
        return DEFAULT_OVERLAY_SAMPLE_COLOR

    def set_display_names(self, names: dict[str, str]) -> None:
        """Apply display-only sample titles while retaining immutable sample names."""
        normalized = dict(names)
        if normalized == self._display_names:
            return
        self._display_names = normalized
        self._rebuild_sample_list()

    def clear_samples(self) -> None:
        """Remove all samples without emitting per-sample removal callbacks."""
        self._samples.clear()
        self._known_paths.clear()
        self._selected_index = -1
        self._list_widget.clear()

    def overlay_state(self) -> dict[str, object]:
        """Return display-only manual overlay state for the current plot view."""
        return {
            "manual_overlay_sample_ids": sorted(self._manual_overlay_sample_ids),
            "manual_overlay_colors": dict(self._manual_overlay_colors),
            "overlay_roles": dict(self._overlay_roles),
            "comparison_sets": [dict(value) for value in self._comparison_sets],
            "comparison_role_colors": dict(self._comparison_role_colors),
            "overlay_mode": self._overlay_mode,
        }

    def set_overlay_state(
        self,
        sample_ids: list[str] | tuple[str, ...],
        colors: dict[str, str] | None = None,
        roles: dict[str, str] | None = None,
        comparison_sets: list[dict[str, object]] | None = None,
        overlay_mode: str = "manual_only",
        role_colors: dict[str, str] | None = None,
    ) -> None:
        """Restore manual overlay state without changing active sample selection."""
        known = {sample.id for sample in self._samples}
        self._manual_overlay_sample_ids = set(sample_ids) & known
        self._manual_overlay_colors = {
            sample_id: color
            for sample_id, color in (colors or {}).items()
            if sample_id in self._manual_overlay_sample_ids
        }
        self._overlay_roles = {
            sample_id: role for sample_id, role in (roles or {}).items() if sample_id in known
        }
        self._comparison_sets = [dict(value) for value in (comparison_sets or [])]
        if role_colors:
            self._comparison_role_colors.update(role_colors)
        self._overlay_mode = overlay_mode if overlay_mode in {
            "manual_only", "manual_plus_comparison", "comparison_only"
        } else "manual_only"
        if hasattr(self, "_overlay_mode_combo"):
            index = self._overlay_mode_combo.findData(self._overlay_mode)
            if index >= 0:
                self._overlay_mode_combo.blockSignals(True)
                self._overlay_mode_combo.setCurrentIndex(index)
                self._overlay_mode_combo.blockSignals(False)
        self._rebuild_sample_list()

    def comparison_overlay_sample_ids(self, active_sample_id: str | None) -> set[str]:
        if self._overlay_mode not in {"manual_plus_comparison", "comparison_only"}:
            return set()
        for definition in self._comparison_sets:
            members = definition.get("members", [])
            member_ids = {
                str(member.get("sample_id")) for member in members if isinstance(member, dict)
            }
            if active_sample_id in member_ids:
                return member_ids - {active_sample_id}
        return set()

    def on_overlay_changed(self, callback: Any) -> None:
        self._overlay_callbacks.append(callback)

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
        """Remove the current selection and return its first removed sample."""
        removed = self.remove_selected_samples()
        return removed[0] if removed else None

    def remove_selected_samples(self) -> list[_SampleInfo]:
        """Remove all selected samples in one list update."""
        selected_ids = {
            str(item.data(Qt.UserRole))
            for item in self._list_widget.selectedItems()
            if item.data(Qt.UserRole) is not None
        }
        if not selected_ids:
            return []
        removed = [sample for sample in self._samples if sample.id in selected_ids]
        if not removed:
            return []
        removed_index = min(
            index for index, sample in enumerate(self._samples)
            if sample.id in selected_ids
        )
        self._samples = [sample for sample in self._samples if sample.id not in selected_ids]
        for sample in removed:
            if sample.path:
                self._known_paths.discard(Path(sample.path).resolve())
        self._manual_overlay_sample_ids.difference_update(selected_ids)
        for sample_id in selected_ids:
            self._manual_overlay_colors.pop(sample_id, None)
            self._overlay_roles.pop(sample_id, None)
        for comparison in self._comparison_sets:
            members = comparison.get("members", [])
            comparison["members"] = [
                member for member in members
                if not isinstance(member, dict)
                or str(member.get("sample_id")) not in selected_ids
            ]
        self._comparison_sets = [
            comparison for comparison in self._comparison_sets
            if len(comparison.get("members", [])) >= 2
        ]
        self._selected_index = -1
        self._refresh_channel_statuses()
        next_index = min(removed_index, len(self._samples) - 1)
        next_id = self._samples[next_index].id if self._samples else None
        self._rebuild_sample_list(selected_id=next_id)
        for removed_sample in removed:
            for callback in self._removed_callbacks:
                invoke_callback(callback, removed_sample)
        for callback in self._batch_removed_callbacks:
            invoke_callback(callback, removed)
        self._emit_overlay_state()
        return removed

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

    def on_samples_removed(self, callback: Any) -> None:
        """Register a callback invoked once for a multi-sample removal."""
        self._batch_removed_callbacks.append(callback)

    def on_sample_reconnected(self, callback: Any) -> None:
        """Register a callback invoked after a reconnect is accepted."""
        self._reconnected_callbacks.append(callback)

    def on_samples_reordered(self, callback: Any) -> None:
        """Register a callback after the canonical sample order changes."""
        self._reordered_callbacks.append(callback)

    def move_selected_sample(self, delta: int) -> bool:
        """Move only the current sample by one canonical-order position."""
        selected = self.selected_sample()
        if selected is None or delta not in {-1, 1}:
            return False
        index = next(
            (index for index, sample in enumerate(self._samples)
             if sample.id == selected.id), -1
        )
        target = index + delta
        if index < 0 or not (0 <= target < len(self._samples)):
            return False
        order = [sample.id for sample in self._samples]
        order[index], order[target] = order[target], order[index]
        return self.reorder_samples(order)

    def reorder_samples(self, ordered_ids: list[str]) -> bool:
        """Apply a complete stable-ID order and notify the owning window."""
        current_ids = [sample.id for sample in self._samples]
        if sorted(ordered_ids) != sorted(current_ids) or ordered_ids == current_ids:
            return False
        selected = self.selected_sample()
        selected_id = selected.id if selected is not None else None
        selected_ids = {
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._list_widget.selectedItems()
        }
        by_id = {sample.id: sample for sample in self._samples}
        self._samples = [by_id[sample_id] for sample_id in ordered_ids]
        self._selected_index = -1
        self._rebuild_sample_list(
            selected_id=selected_id,
            selected_ids=selected_ids,
        )
        for callback in self._reordered_callbacks:
            invoke_callback(callback, list(ordered_ids))
        return True

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
            return

        sample_id = str(item.data(Qt.UserRole))
        self._selected_index = next(
            (index for index, sample in enumerate(self._samples) if sample.id == sample_id), -1
        )
        if self._selected_index < 0:
            return
        sample = self._samples[self._selected_index]
        for cb in self._selection_callbacks:
            invoke_callback(cb, sample)
        self._update_overlay_row_states()

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

    def _rebuild_sample_list(
        self,
        selected_id: str | None = None,
        selected_ids: set[str] | None = None,
    ) -> None:
        if selected_id is None and self._list_widget.currentItem() is not None:
            selected_id = str(self._list_widget.currentItem().data(Qt.UserRole))
        labels = {"match": "✓", "order differs": "↕", "channel mismatch": "≠",
                  "fingerprint mismatch": "!", "missing": "?"}
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        selected_ids = selected_ids or ({selected_id} if selected_id else set())
        for sample in self._samples:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, sample.id)
            item.setSelected(sample.id in selected_ids)
            display_name = self._display_names.get(sample.id, sample.name)
            item.setToolTip(
                f"{display_name} ({sample.name})\n{sample.path}\n"
                f"{sample.info.event_count} events — {sample.status}"
            )
            self._list_widget.addItem(item)
            row = QWidget()
            row.setObjectName(f"sampleRow_{sample.id}")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            row_layout.setSpacing(4)
            overlay = QCheckBox()
            overlay.setObjectName(f"overlayCheck_{sample.id}")
            overlay.setFixedWidth(28)
            overlay.setAccessibleName(f"Overlay {sample.name}")
            overlay.setToolTip("Add this sample as a manual overlay")
            overlay.setChecked(sample.id in self._manual_overlay_sample_ids)
            active = self.selected_sample()
            if active is not None and active.id == sample.id:
                overlay.setChecked(False)
                overlay.setEnabled(False)
                overlay.setToolTip("Active sample is not drawn as its own overlay")
            overlay.toggled.connect(
                lambda checked, sample_id=sample.id: self._set_manual_overlay(sample_id, checked)
            )
            swatch = QPushButton()
            swatch.setObjectName(f"overlayColor_{sample.id}")
            swatch.setAccessibleName(f"Overlay color {sample.name}")
            swatch.setToolTip("Choose overlay source color")
            swatch.setFixedWidth(24)
            explicit_color = self._manual_overlay_colors.get(sample.id)
            self._set_swatch_style(swatch, explicit_color)
            if explicit_color is None:
                swatch.setToolTip(
                    "No overlay color selected; automatic color will be used"
                )
            swatch.clicked.connect(
                lambda _checked=False, sample_id=sample.id:
                self._choose_overlay_color(sample_id)
            )
            # Keep the row compact enough for the navigational pane.  The
            # event count, path, and full status remain available in the
            # item's tooltip (and are intentionally not part of analysis
            # state).
            name = QLabel(f"[{labels.get(sample.status, '!')}] {display_name}")
            name.setObjectName(f"sampleName_{sample.id}")
            name.setToolTip(item.toolTip())
            name.setWordWrap(False)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            relation = QLabel(self._overlay_roles.get(sample.id, "manual"))
            relation.setObjectName(f"overlayRelation_{sample.id}")
            relation.setFixedWidth(68)
            relation.setToolTip("Overlay relation or diagnostic status")
            if active is not None and active.id == sample.id:
                swatch.setEnabled(False)
                swatch.setToolTip(
                    "Active sample uses the base-layer event style; "
                    "choose an overlay color on a different sample"
                )
                relation.setText("active")
            row_layout.addWidget(overlay)
            row_layout.addWidget(swatch)
            row_layout.addWidget(name, 1)
            row_layout.addWidget(relation)
            item.setSizeHint(QSize(0, 30))
            self._list_widget.setItemWidget(item, row)
        self._list_widget.blockSignals(False)
        self._apply_filter(self._filter_edit.text())
        if selected_id is not None:
            self.select_sample(selected_id)
        self._update_overlay_row_states()

    def _set_swatch_style(self, button: QPushButton, color: str | None) -> None:
        if color:
            button.setStyleSheet(
                f"QPushButton {{ background-color: {color}; border: 1px solid #555; }}"
            )
        else:
            button.setStyleSheet(
                "QPushButton { background-color: transparent; "
                "border: 2px dashed #777; }"
            )

    def _update_overlay_row_states(self) -> None:
        active = self.selected_sample()
        for index, sample in enumerate(self._samples):
            row = self._list_widget.itemWidget(self._list_widget.item(index))
            if row is None:
                continue
            checkbox = row.findChild(QCheckBox)
            if checkbox is None:
                continue
            checkbox.blockSignals(True)
            is_active = active is not None and active.id == sample.id
            checkbox.setEnabled(not is_active)
            checkbox.setChecked(
                False if is_active else sample.id in self._manual_overlay_sample_ids
            )
            checkbox.setToolTip(
                "Active sample is not drawn as its own overlay"
                if is_active else "Add this sample as a manual overlay"
            )
            checkbox.blockSignals(False)
            swatch = row.findChild(QPushButton, f"overlayColor_{sample.id}")
            if swatch is not None:
                swatch.setEnabled(not is_active)
                swatch.setToolTip(
                    "Active sample uses the base-layer event style; "
                    "choose an overlay color on a different sample"
                    if is_active else "Choose overlay source color"
                )
            relation = row.findChild(QLabel, f"overlayRelation_{sample.id}")
            if relation is not None:
                relation.setText(
                    "active" if is_active else self._overlay_roles.get(sample.id, "manual")
                )

    def _set_manual_overlay(self, sample_id: str, enabled: bool) -> None:
        active = self.selected_sample()
        if active is not None and active.id == sample_id:
            enabled = False
        if enabled:
            self._manual_overlay_sample_ids.add(sample_id)
        else:
            self._manual_overlay_sample_ids.discard(sample_id)
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _show_sample_context_menu(self, position) -> None:
        item = self._list_widget.itemAt(position)
        if item is None:
            return
        sample_id = str(item.data(Qt.UserRole) or "")
        if not sample_id:
            return
        menu = QMenu(self)
        selected_ids = [
            str(value.data(Qt.UserRole)) for value in self._list_widget.selectedItems()
        ]
        if len(selected_ids) >= 2:
            pair_action = menu.addAction("Pair Selected Samples...")
            pair_action.setObjectName("pairSelectedSamplesAction")
            pair_action.triggered.connect(
                lambda: self._create_comparison_set(selected_ids)
            )
            create_action = menu.addAction("Create Comparison Set...")
            create_action.setObjectName("createComparisonSetAction")
            create_action.triggered.connect(
                lambda: self._create_comparison_set(selected_ids)
            )
            add_action = menu.addAction("Add to Comparison Set...")
            add_action.setObjectName("addToComparisonSetAction")
            add_action.triggered.connect(
                lambda: self._add_to_latest_comparison_set(selected_ids)
            )
            menu.addSeparator()
        if self._comparison_sets:
            edit_action = menu.addAction("Edit Comparison Relation...")
            edit_action.setObjectName("editComparisonRelationAction")
            edit_action.triggered.connect(lambda: self._emit_overlay_state())
            remove_action = menu.addAction("Remove from Comparison Set")
            remove_action.setObjectName("removeFromComparisonSetAction")
            remove_action.triggered.connect(
                lambda: self._remove_from_comparison_sets(sample_id)
            )
        persistent = menu.addAction("Use as Persistent Overlay")
        persistent.setObjectName("persistentOverlayAction")
        persistent.triggered.connect(
            lambda: self._set_manual_overlay(sample_id, True)
        )
        role_menu = menu.addMenu("Set Overlay Role")
        for role in ("Positive control", "Negative control", "Reference"):
            role_action = role_menu.addAction(role)
            role_action.setObjectName("overlayRole" + role.replace(" ", ""))
            role_value = role.lower().replace(" ", "_")
            role_action.triggered.connect(
                lambda _checked=False, value=role_value:
                self._set_overlay_role(sample_id, value)
            )
        clear_role = menu.addAction("Clear Overlay Role")
        clear_role.setObjectName("clearOverlayRoleAction")
        clear_role.triggered.connect(lambda: self._set_overlay_role(sample_id, None))
        clear_color = menu.addAction("Clear Overlay Color")
        clear_color.setObjectName("clearOverlayColorAction")
        clear_color.setEnabled(sample_id in self._manual_overlay_colors)
        clear_color.triggered.connect(lambda: self._clear_overlay_color(sample_id))
        menu.exec(self._list_widget.viewport().mapToGlobal(position))

    def _set_overlay_mode(self, _index: int) -> None:
        self._overlay_mode = str(self._overlay_mode_combo.currentData())
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _emit_overlay_state(self) -> None:
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _add_to_latest_comparison_set(self, sample_ids: list[str]) -> None:
        if not self._comparison_sets:
            self._create_comparison_set(sample_ids)
            return
        members = self._comparison_sets[-1].setdefault("members", [])
        existing = {
            str(member.get("sample_id")) for member in members if isinstance(member, dict)
        }
        for sample_id in sample_ids:
            if sample_id not in existing:
                members.append({"sample_id": sample_id, "role": "target"})
        self._emit_overlay_state()

    def _remove_from_comparison_sets(self, sample_id: str) -> None:
        for comparison in self._comparison_sets:
            members = comparison.get("members", [])
            comparison["members"] = [
                member for member in members
                if not isinstance(member, dict) or member.get("sample_id") != sample_id
            ]
        self._comparison_sets = [
            comparison for comparison in self._comparison_sets
            if len(comparison.get("members", [])) >= 2
        ]
        self._emit_overlay_state()

    def _create_comparison_set(self, sample_ids: list[str]) -> None:
        members = [
            {"sample_id": sample_id, "role": "reference" if index == 0 else "target"}
            for index, sample_id in enumerate(dict.fromkeys(sample_ids))
        ]
        if len(members) < 2:
            return
        comparison_id = f"comparison_{len(self._comparison_sets) + 1:03d}"
        self._comparison_sets.append({
            "id": comparison_id,
            "name": comparison_id,
            "members": members,
        })
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _set_overlay_role(self, sample_id: str, role: str | None) -> None:
        if role is None:
            self._overlay_roles.pop(sample_id, None)
        else:
            self._overlay_roles[sample_id] = role
        self._rebuild_sample_list()
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _choose_overlay_color(self, sample_id: str) -> None:
        color = QColorDialog.getColor(
            QColor(self.overlay_color(sample_id)),
            self,
            "Overlay Color",
        )
        if not color.isValid():
            return
        self._manual_overlay_colors[sample_id] = color.name().lower()
        self._rebuild_sample_list()
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

    def _clear_overlay_color(self, sample_id: str) -> None:
        """Remove only the explicit manual color override for one sample."""
        if sample_id not in self._manual_overlay_colors:
            return
        self._manual_overlay_colors.pop(sample_id)
        self._rebuild_sample_list()
        for callback in self._overlay_callbacks:
            invoke_callback(callback, self.overlay_state())

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
        if key == "manual":
            return
        self._samples.sort(key=lambda sample: str(getattr(sample, key, "")).casefold())
        self._rebuild_sample_list(selected.id if selected is not None else None)
        for callback in self._reordered_callbacks:
            invoke_callback(callback, [sample.id for sample in self._samples])

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._selection_callbacks: list[Any] = []
        self._removed_callbacks: list[Any] = []
        self._batch_removed_callbacks: list[Any] = []
        self._reconnected_callbacks: list[Any] = []
        self._reordered_callbacks: list[Any] = []
        self._overlay_callbacks: list[Any] = []
        self.setObjectName("sampleBrowser")

        self._list_widget = _SampleListWidget()
        self._list_widget.setObjectName("sampleList")
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list_widget.setDragEnabled(True)
        self._list_widget.setAcceptDrops(True)
        self._list_widget.setDropIndicatorShown(True)
        self._list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self._list_widget.order_changed.connect(self.reorder_samples)
        self._list_widget.move_requested.connect(self.move_selected_sample)
        self._list_widget.currentRowChanged.connect(self._on_list_selection_changed)
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(
            self._show_sample_context_menu
        )
        self._sample_header = QWidget()
        self._sample_header.setObjectName("sampleListHeader")
        header_layout = QHBoxLayout(self._sample_header)
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(4)
        ov_header = QLabel("Ov")
        ov_header.setObjectName("sampleHeaderOv")
        ov_header.setFixedWidth(28)
        col_header = QLabel("Col")
        col_header.setObjectName("sampleHeaderCol")
        col_header.setFixedWidth(24)
        name_header = QLabel("Name")
        name_header.setObjectName("sampleHeaderName")
        rel_header = QLabel("Rel")
        rel_header.setObjectName("sampleHeaderRel")
        rel_header.setFixedWidth(68)
        header_layout.addWidget(ov_header)
        header_layout.addWidget(col_header)
        header_layout.addWidget(name_header, 1)
        header_layout.addWidget(rel_header)

        self._filter_edit = QLineEdit()
        self._filter_edit.setObjectName("sampleFilterEdit")
        self._filter_edit.setPlaceholderText("Filter samples…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("sampleSortCombo")
        self._sort_combo.addItem("Manual", "manual")
        self._sort_combo.addItem("Name", "name")
        self._sort_combo.addItem("Path", "path")
        self._sort_combo.addItem("Status", "status")
        self._sort_combo.currentIndexChanged.connect(lambda _index: self._sort_samples())

        self._btn_add = QPushButton("Add FCS Files...")
        self._btn_add.setObjectName("addFcsFilesButton")
        self._btn_add.clicked.connect(self._on_add_files)

        self._btn_remove = QPushButton("Remove Selected")
        self._btn_remove.setObjectName("removeSampleButton")
        self._btn_remove.clicked.connect(self._on_remove_selected)

        self._btn_reconnect = QPushButton("Reconnect…")
        self._btn_reconnect.setObjectName("reconnectSampleButton")
        self._btn_reconnect.clicked.connect(self._on_reconnect_selected)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Samples"))
        mode_label = QLabel("Overlay mode:")
        self._overlay_mode_combo = QComboBox()
        self._overlay_mode_combo.setObjectName("overlayModeSelector")
        self._overlay_mode_combo.addItem("Manual only", "manual_only")
        self._overlay_mode_combo.addItem(
            "Manual + comparison set", "manual_plus_comparison"
        )
        self._overlay_mode_combo.setMinimumWidth(0)
        self._overlay_mode_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._overlay_mode_combo.currentIndexChanged.connect(self._set_overlay_mode)
        controls = QHBoxLayout()
        controls.addWidget(self._filter_edit)
        controls.addWidget(self._sort_combo)
        left_layout.addLayout(controls)
        mode_controls = QHBoxLayout()
        mode_controls.addWidget(mode_label)
        mode_controls.addWidget(self._overlay_mode_combo)
        left_layout.addLayout(mode_controls)
        left_layout.addWidget(self._sample_header)
        left_layout.addWidget(self._list_widget)
        left_layout.addWidget(self._btn_add)
        left_layout.addWidget(self._btn_remove)
        left_layout.addWidget(self._btn_reconnect)

        layout = QVBoxLayout(self)
        layout.addWidget(left)

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
        removed = self.remove_selected_samples()
        if not removed:
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
