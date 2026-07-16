"""Progressively disclosed sample-group view for the workspace."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
  QHBoxLayout,
  QInputDialog,
  QListWidget,
  QListWidgetItem,
  QPushButton,
  QVBoxLayout,
  QWidget,
)


class GroupPanel(QWidget):
  """Read-only group overview shown only in advanced Group mode.

  Editing membership is deliberately deferred to the Group editor increment;
  this panel makes existing memberships visible without changing analysis.
  """

  groups_changed = Signal(list)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("groupPanel")
    self._list = QListWidget()
    self._list.setObjectName("groupList")
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
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(self._list)
    layout.addLayout(buttons)
    self.set_groups(())

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
