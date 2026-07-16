"""Tests for definition-only project commands and undo/redo."""

from __future__ import annotations

import copy

import pytest

from flowdesk_core.models import GateSpec
from flowdesk_core.project_commands import (
  CopyGateOverrideToSelectedCommand,
  CopySubtreeAnalysisCommand,
  CopySubtreeCommand,
  CreateGateCommand,
  DeleteGateCommand,
  DuplicateGateCommand,
  ProjectCommandError,
  PromoteGateOverrideCommand,
  RebaseGateOverrideCommand,
  ResetGateOverrideCommand,
  RenameGateCommand,
  ReparentGateCommand,
  UndoStack,
)


def _state() -> dict:
  return {
    "gating_strategies_data": {
      "strategy": {
        "id": "strategy",
        "name": "Strategy",
        "root_population_id": "all_events",
        "gates": [],
      }
    },
    "execution_report": {"membership": "must-not-be-captured"},
  }


def _gate(gate_id: str, parent: str = "all_events") -> GateSpec:
  return GateSpec(
    id=gate_id,
    name=gate_id.title(),
    gate_type="range",
    parent_population_id=parent,
    x_parameter="X",
    thresholds={"min": 1.0},
  )


def test_undo_redo_restores_exact_definitions_and_clean_marker() -> None:
  initial = _state()
  stack = UndoStack(initial)
  stack.mark_clean()
  stack.execute(CreateGateCommand("strategy", _gate("cells")))
  assert stack.is_dirty
  stack.mark_clean()
  stack.execute(RenameGateCommand("strategy", "cells", "Cells renamed"))
  renamed = stack.state
  assert renamed["gating_strategies_data"]["strategy"]["gates"][0]["name"] == "Cells renamed"
  stack.undo()
  restored = stack.state
  assert restored["gating_strategies_data"]["strategy"]["gates"][0]["name"] == "Cells"
  assert not stack.is_dirty
  stack.redo()
  assert stack.is_dirty
  assert stack.state == renamed


def test_invalid_delete_and_reparent_are_atomic_and_not_history() -> None:
  stack = UndoStack(_state())
  stack.execute(CreateGateCommand("strategy", _gate("cells")))
  stack.execute(CreateGateCommand("strategy", _gate("child", "cells")))
  before = stack.state
  index = stack._index
  with pytest.raises(ProjectCommandError, match="referenced"):
    stack.execute(DeleteGateCommand("strategy", "cells"))
  assert stack.state == before
  assert stack._index == index
  with pytest.raises(ProjectCommandError, match="cycle"):
    stack.execute(ReparentGateCommand("strategy", "cells", "child"))
  assert stack.state == before
  assert stack._index == index


def test_commands_capture_definitions_not_runtime_arrays() -> None:
  state = _state()
  state["runtime_events"] = [1, 2, 3]
  stack = UndoStack(copy.deepcopy(state))
  stack.execute(CreateGateCommand("strategy", _gate("cells")))
  command = stack._commands[0]
  assert not hasattr(command, "runtime_events")
  assert stack.state["runtime_events"] == [1, 2, 3]


def test_duplicate_and_subtree_copy_remap_references_and_undo() -> None:
  stack = UndoStack(_state())
  stack.execute(CreateGateCommand("strategy", _gate("cells")))
  stack.execute(CreateGateCommand("strategy", _gate("positive", "cells")))
  stack.execute(
    DuplicateGateCommand("strategy", "positive", "positive-copy", name="Positive copy")
  )
  copied = stack.state["gating_strategies_data"]["strategy"]["gates"][-1]
  assert copied["id"] == "positive-copy"
  assert copied["parent_population_id"] == "cells"
  stack.undo()
  assert all(
    gate["id"] != "positive-copy"
    for gate in stack.state["gating_strategies_data"]["strategy"]["gates"]
  )
  stack.execute(
    CopySubtreeCommand(
      "strategy",
      "cells",
      {"cells": "cells-copy", "positive": "positive-copy"},
      target_parent_id="all_events",
    )
  )
  gates = stack.state["gating_strategies_data"]["strategy"]["gates"]
  copied_cells = next(gate for gate in gates if gate["id"] == "cells-copy")
  copied_positive = next(gate for gate in gates if gate["id"] == "positive-copy")
  assert copied_cells["parent_population_id"] == "all_events"
  assert copied_positive["parent_population_id"] == "cells-copy"
  stack.undo()
  assert all(
    gate["id"] not in {"cells-copy", "positive-copy"}
    for gate in stack.state["gating_strategies_data"]["strategy"]["gates"]
  )


def test_cross_strategy_subtree_copy_is_atomic() -> None:
  state = _state()
  state["gating_strategies_data"]["target-a"] = {
    "id": "target-a", "name": "Target A", "gates": []
  }
  state["gating_strategies_data"]["target-b"] = {
    "id": "target-b", "name": "Target B", "gates": []
  }
  stack = UndoStack(state)
  stack.execute(CreateGateCommand("strategy", _gate("cells")))
  command = CopySubtreeAnalysisCommand(
    "strategy",
    "cells",
    ("target-a", "target-b"),
    {
      "target-a": {"cells": "cells-a"},
      "target-b": {"cells": "cells-b"},
    },
    scope="sample",
  )
  stack.execute(command)
  assert stack.state["gating_strategies_data"]["target-a"]["gates"][0]["id"] == "cells-a"
  assert stack.state["gating_strategies_data"]["target-b"]["gates"][0]["id"] == "cells-b"
  stack.undo()
  assert stack.state["gating_strategies_data"]["target-a"]["gates"] == []
  bad = CopySubtreeAnalysisCommand(
    "strategy",
    "cells",
    ("target-a", "target-b"),
    {"target-a": {"cells": "cells-a"}, "target-b": {}},
  )
  before = stack.state
  with pytest.raises(ProjectCommandError, match="id_map"):
    stack.execute(bad)
  assert stack.state == before


def test_group_subtree_copy_preflights_channel_mapping_atomically() -> None:
  state = _state()
  state["gating_strategies_data"]["target-a"] = {
    "id": "target-a", "name": "Target A", "gates": []
  }
  stack = UndoStack(state)
  source = _gate("cells")
  source = GateSpec(**{**source.__dict__, "x_parameter": "CD3", "y_parameter": "CD19"})
  stack.execute(CreateGateCommand("strategy", source))
  before = stack.state
  command = CopySubtreeAnalysisCommand(
    "strategy", "cells", ("target-a",), {"target-a": {"cells": "cells-a"}},
    target_channel_ids={"target-a": ["CD3"]},
    scope="group",
  )
  with pytest.raises(ProjectCommandError, match="channel mapping"):
    stack.execute(command)
  assert stack.state == before


def _override_state() -> dict:
  state = _state()
  state["gating_strategies_data"]["strategy"]["gates"] = [{
    "id": "cells", "name": "Cells", "gate_type": "range",
    "parent_population_id": "all_events", "x_parameter": "X",
    "thresholds": {"min": 0.0, "max": 10.0},
  }]
  from flowdesk_core.overrides import gate_version_hash
  state["gate_overrides"] = [{
    "id": "cells-s1", "sample_id": "s1", "base_gate_id": "cells",
    "base_version_hash": gate_version_hash(state["gating_strategies_data"]["strategy"]["gates"][0]),
    "geometry_mode": "delta", "thresholds": {"min": 2.0},
    "author": "analyst", "created_at": "2026-07-16T00:00:00+00:00",
    "reason": "cleanup", "gate_purpose": "technical_cleanup",
  }]
  return state


def test_override_commands_are_separate_and_undoable() -> None:
  stack = UndoStack(_override_state())
  stack.execute(CopyGateOverrideToSelectedCommand("cells-s1", ["s2"]))
  assert stack.state["gate_overrides"][-1]["sample_id"] == "s2"
  stack.undo()
  stack.execute(RebaseGateOverrideCommand("strategy", "cells-s1"))
  stack.execute(ResetGateOverrideCommand("cells-s1"))
  assert stack.state["gate_overrides"] == []
  stack.undo()
  assert stack.state["gate_overrides"][0]["id"] == "cells-s1"


def test_comparison_critical_promotion_requires_warning_and_audit() -> None:
  state = _override_state()
  state["gate_overrides"][0]["gate_purpose"] = "comparison_critical"
  stack = UndoStack(state)
  with pytest.raises(ProjectCommandError, match="comparison-critical"):
    stack.execute(PromoteGateOverrideCommand("strategy", "cells-s1"))
  stack.execute(PromoteGateOverrideCommand(
    "strategy", "cells-s1", confirm_comparison_critical=True,
    audit_record={"reason": "reviewed by analyst"},
  ))
  assert stack.state["gate_overrides"] == []
  assert stack.state["gate_override_audit"][0]["reason"] == "reviewed by analyst"
  assert stack.state["gating_strategies_data"]["strategy"]["gates"][0]["thresholds"]["min"] == 2.0
