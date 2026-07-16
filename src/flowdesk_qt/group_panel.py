"""Progressively disclosed sample-group view for the workspace."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class GroupPanel(QWidget):
  """Read-only group overview shown only in advanced Group mode.

  Editing membership is deliberately deferred to the Group editor increment;
  this panel makes existing memberships visible without changing analysis.
  """

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setObjectName("groupPanel")
    self._list = QListWidget()
    self._list.setObjectName("groupList")
    layout = QVBoxLayout(self)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(self._list)
    self.set_groups(())

  def set_groups(self, groups: Sequence[Mapping[str, Any]]) -> None:
    """Render persisted groups and their explicit/rule membership summary."""
    self._list.clear()
    for group in groups:
      group_id = str(group.get("id", ""))
      name = str(group.get("name", group_id))
      role = str(group.get("role", "user"))
      members = group.get("sample_ids", [])
      member_count = len(members) if isinstance(members, list) else 0
      rule = " + dynamic rule" if group.get("membership_rule") else ""
      item = QListWidgetItem(f"{name} [{role}] — {member_count} explicit{rule}")
      item.setData(0x0100, group_id)
      self._list.addItem(item)

