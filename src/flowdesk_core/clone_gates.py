"""Pure, reversible synchronization of shared gate geometry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from flowdesk_core.models import CloneSyncGroupSpec, CloneSyncResult, GateSpec


class CloneSyncError(ValueError):
  """Raised when clone synchronization cannot be applied safely."""


def sync_clone_gate(
  group: CloneSyncGroupSpec,
  gates_by_sample: Mapping[str, GateSpec | None],
) -> CloneSyncResult:
  leader = gates_by_sample.get(group.leader_sample_id)
  if leader is None or leader.id != group.gate_id:
    raise CloneSyncError("clone leader gate is missing or has a different ID")
  before = {
    sample_id: asdict(gates_by_sample[sample_id])
    for sample_id in group.sample_ids if gates_by_sample.get(sample_id) is not None
  }
  conflicts = tuple(
    sample_id for sample_id in group.sample_ids
    if sample_id != group.leader_sample_id
    and gates_by_sample.get(sample_id) is not None
    and asdict(gates_by_sample[sample_id]) != asdict(leader)
  )
  if conflicts and group.conflict_policy == "reject_conflict":
    raise CloneSyncError(f"clone conflicts require resolution: {', '.join(conflicts)}")
  after = {sample_id: asdict(leader) for sample_id in group.sample_ids}
  return CloneSyncResult(
    group_id=group.id, leader_sample_id=group.leader_sample_id,
    applied_sample_ids=tuple(
      sample_id for sample_id in group.sample_ids
      if sample_id != group.leader_sample_id
    ),
    conflict_sample_ids=conflicts, before=before, after=after,
  )


class CloneGateSyncCommand:
  """Undoable command carrying both pre- and post-sync geometry."""

  def __init__(self, result: CloneSyncResult) -> None:
    self.result = result

  def apply(self) -> dict[str, dict[str, Any]]:
    return {sample_id: dict(self.result.after[sample_id]) for sample_id in self.result.after}

  def undo(self) -> dict[str, dict[str, Any]]:
    return {sample_id: dict(self.result.before[sample_id]) for sample_id in self.result.before}
