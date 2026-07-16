"""Tests for definition-only project commands and undo/redo."""

from __future__ import annotations

import copy

import pytest

from flowdesk_core.models import GateSpec
from flowdesk_core.project_commands import (
  CreateGateCommand,
  DeleteGateCommand,
  ProjectCommandError,
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
