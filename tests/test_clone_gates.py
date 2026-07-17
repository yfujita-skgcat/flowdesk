import pytest

from flowdesk_core.clone_gates import CloneGateSyncCommand, CloneSyncError, sync_clone_gate
from flowdesk_core.models import CloneSyncGroupSpec, GateSpec


def test_clone_leader_wins_and_undo_restores_geometry() -> None:
  leader = GateSpec(
    id="g", name="Gate", gate_type="range", x_parameter="X", thresholds={"min": 1.0}
  )
  other = GateSpec(id="g", name="Gate", gate_type="range", x_parameter="X", thresholds={"min": 2.0})
  group = CloneSyncGroupSpec(id="c", gate_id="g", sample_ids=("s1", "s2"), leader_sample_id="s1")
  result = sync_clone_gate(group, {"s1": leader, "s2": other})
  command = CloneGateSyncCommand(result)
  assert result.conflict_sample_ids == ("s2",)
  assert command.apply()["s2"]["thresholds"] == {"min": 1.0}
  assert command.undo()["s2"]["thresholds"] == {"min": 2.0}


def test_clone_reject_conflict_is_explicit() -> None:
  leader = GateSpec(
    id="g", name="Gate", gate_type="range", x_parameter="X", thresholds={"min": 1.0}
  )
  other = GateSpec(id="g", name="Gate", gate_type="range", x_parameter="X", thresholds={"min": 2.0})
  group = CloneSyncGroupSpec(
    id="c", gate_id="g", sample_ids=("s1", "s2"), leader_sample_id="s1",
    conflict_policy="reject_conflict",
  )
  with pytest.raises(CloneSyncError, match="conflicts"):
    sync_clone_gate(group, {"s1": leader, "s2": other})
