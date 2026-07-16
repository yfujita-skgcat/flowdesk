"""Progressively disclosed sample-group view for the workspace."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtWidgets import (
  QHBoxLayout,
  QInputDialog,
  QListWidget,
  QListWidgetItem,
  QPushButton,
  QVBoxLayout,
  QWidget,
)


class _SampleListWidget(QListWidget):
  def __init__(self) -> None:
    super().__init__()
    self.setObjectName("groupSampleList")
    self.setDragEnabled(True)
    self.setDragDropMode(QListWidget.DragOnly)


class _GroupListWidget(QListWidget):
  sample_dropped = Signal(str, str)

  def __init__(self) -> None:
    super().__init__()
    self.setObjectName("groupList")
    self.setAcceptDrops(True)
    self.setDropIndicatorShown(True)

  def dropMimeData(self, index: int, data: QMimeData, action) -> bool:
    item = self.item(index) or self.currentItem()
    sample_id = data.text().strip()
    group_id = "" if item is None else str(item.data(0x0100))
    if not sample_id or not group_id:
      return False
    self.sample_dropped.emit(group_id, sample_id)
    return True


class GroupPanel(QWidget):
  """Group overview and explicit membership drag/drop editor."""

  groups_changed = Signal(list)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("groupPanel")
    self._list = _GroupListWidget()
    self._sample_list = _SampleListWidget()
    self._groups: list[dict[str, Any]] = []
    self._add_button = QPushButton("Add")
    self._add_button.setObjectName("addGroupButton")
    self._rename_button = QPushButton("Rename")
    self._rename_button.setObjectName("renameGroupButton")
    self._delete_button = QPushButton("Delete")
    self._delete_button.setObjectName("deleteGroupButton")
    buttons = QHBoxLayout()
    buttons.addWidget(self._add_button)
    buttons.addWidget(self._rename_button)
    buttons.addWidget(self._delete_button)
    self._add_button.clicked.connect(self._add_group)
    self._rename_button.clicked.connect(self._rename_group)
    self._delete_button.clicked.connect(self._delete_group)
    self._list.sample_dropped.connect(self.add_sample_to_group)
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(self._sample_list)
    layout.addWidget(self._list)
    layout.addLayout(buttons)
    self.set_groups(())

  def set_sample_ids(self, sample_ids: Sequence[str]) -> None:
    """Set sample IDs available as drag sources."""
    self._sample_list.clear()
    for sample_id in sample_ids:
      self._sample_list.addItem(QListWidgetItem(str(sample_id)))

  def add_sample_to_group(self, group_id: str, sample_id: str) -> bool:
    """Add one explicit membership and emit the project mutation."""
    for group in self._groups:
      if group.get("id") != group_id:
        continue
      members = group.setdefault("sample_ids", [])
      if not isinstance(members, list):
        members = []
        group["sample_ids"] = members
      if sample_id not in members:
        members.append(sample_id)
        self._emit_groups()
      return True
    return False

  def set_groups(self, groups: Sequence[Mapping[str, Any]]) -> None:
    """Render persisted groups and their explicit/rule membership summary."""
    self._groups = [dict(group) for group in groups]
    self._list.clear()
    for group in self._groups:
      group_id = str(group.get("id", ""))
      name = str(group.get("name", group_id))
      role = str(group.get("role", "user"))
      members = group.get("sample_ids", [])
      member_count = len(members) if isinstance(members, list) else 0
      rule = " + dynamic rule" if group.get("membership_rule") else ""
      item = QListWidgetItem(f"{name} [{role}] — {member_count} explicit{rule}")
      item.setData(0x0100, group_id)
      self._list.addItem(item)

  def _emit_groups(self) -> None:
    self.groups_changed.emit([dict(group) for group in self._groups])
    self.set_groups(self._groups)

  def _add_group(self) -> None:
    name, accepted = QInputDialog.getText(self, "Add Group", "Group name:")
    name = name.strip()
    if not accepted or not name:
      return
    existing = {str(group.get("id")) for group in self._groups}
    group_id = _unique_id(name, existing)
    self._groups.append({
      "id": group_id,
      "name": name,
      "role": "user",
      "sample_ids": [],
      "membership_rule": None,
    })
    self._emit_groups()

  def _rename_group(self) -> None:
    row = self._list.currentRow()
    if row < 0 or row >= len(self._groups):
      return
    current = str(self._groups[row].get("name", ""))
    name, accepted = QInputDialog.getText(
      self, "Rename Group", "Group name:", text=current
    )
    name = name.strip()
    if accepted and name:
      self._groups[row]["name"] = name
      self._emit_groups()

  def _delete_group(self) -> None:
    row = self._list.currentRow()
    if row < 0 or row >= len(self._groups):
      return
    if self._groups[row].get("id") == "all-samples":
      return
    del self._groups[row]
    self._emit_groups()


def _unique_id(name: str, existing: set[str]) -> str:
  base = "".join(char.lower() if char.isalnum() else "-" for char in name)
  base = "-".join(part for part in base.split("-") if part) or "group"
  candidate = base
  suffix = 2
  while candidate in existing:
    candidate = f"{base}-{suffix}"
    suffix += 1
  return candidate
