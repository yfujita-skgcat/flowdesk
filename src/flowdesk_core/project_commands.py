"""Reversible, definition-only project mutations.

Commands in this module operate on JSON-compatible project manifests.  They
never capture execution results, NumPy arrays, or membership masks; only the
affected gate definitions are retained for undo/redo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from flowdesk_core.gating_strategy import GatingStrategyError, ordered_gates
from flowdesk_core.models import GateSpec, GatingStrategySpec

ProjectState = dict[str, Any]


class ProjectCommandError(ValueError):
  """Raised when a project mutation is invalid or cannot be applied."""


def _gate_from_data(value: GateSpec | dict[str, Any]) -> GateSpec:
  if isinstance(value, GateSpec):
    return value
  try:
    return GateSpec(**dict(value))
  except (TypeError, ValueError) as exc:
    raise ProjectCommandError(f"invalid gate definition: {exc}") from exc


def _gate_data(value: GateSpec | dict[str, Any]) -> dict[str, Any]:
  return asdict(_gate_from_data(value))


def _strategy_gates(state: ProjectState, strategy_id: str) -> list[dict[str, Any]]:
  strategies = state.get("gating_strategies_data", {})
  strategy = strategies.get(strategy_id)
  if not isinstance(strategy, dict):
    raise ProjectCommandError(f"unknown gating strategy: {strategy_id!r}")
  gates = strategy.get("gates", [])
  if not isinstance(gates, list):
    raise ProjectCommandError(f"strategy {strategy_id!r} gates must be an array")
  return deepcopy(gates)


def _replace_strategy_gates(
  state: ProjectState,
  strategy_id: str,
  gates: list[dict[str, Any]],
) -> ProjectState:
  candidate = deepcopy(state)
  strategy = candidate["gating_strategies_data"][strategy_id]
  strategy["gates"] = deepcopy(gates)
  try:
    parsed = tuple(_gate_from_data(gate) for gate in gates)
    ordered_gates(
      GatingStrategySpec(
        id=strategy_id,
        name=str(strategy.get("name", strategy_id)),
        gates=parsed,
        root_population_id=str(strategy.get("root_population_id", "all_events")),
      )
    )
  except (GatingStrategyError, ProjectCommandError) as exc:
    raise ProjectCommandError(str(exc)) from exc
  return candidate


class ProjectCommand(ABC):
  """A validated, reversible mutation of project definitions."""

  type: str = "project_mutation"
  invalidation_reason: str = "Project definitions changed"

  @abstractmethod
  def apply(self, state: ProjectState) -> ProjectState:
    """Return a new state after applying this command."""

  @abstractmethod
  def undo(self, state: ProjectState) -> ProjectState:
    """Return a new state with this command reversed."""


class _GateListCommand(ProjectCommand):
  strategy_id: str

  def _updated(
    self,
    state: ProjectState,
    gates: list[dict[str, Any]],
  ) -> ProjectState:
    return _replace_strategy_gates(state, self.strategy_id, gates)


class CreateGateCommand(_GateListCommand):
  type = "gate.create"

  def __init__(self, strategy_id: str, gate: GateSpec | dict[str, Any]) -> None:
    self.strategy_id = strategy_id
    self.gate = _gate_data(gate)
    self._validate_gate(self.gate)

  def _validate_gate(self, gate: dict[str, Any]) -> None:
    if not gate.get("id"):
      raise ProjectCommandError("gate id must not be empty")

  def apply(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    if any(gate.get("id") == self.gate["id"] for gate in gates):
      raise ProjectCommandError(f"duplicate gate id: {self.gate['id']!r}")
    return self._updated(state, [*gates, self.gate])

  def undo(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    remaining = [gate for gate in gates if gate.get("id") != self.gate["id"]]
    if len(remaining) == len(gates):
      raise ProjectCommandError(f"gate not found: {self.gate['id']!r}")
    return self._updated(state, remaining)


class EditGateCommand(_GateListCommand):
  type = "gate.edit"

  def __init__(
    self,
    strategy_id: str,
    gate_id: str,
    gate: GateSpec | dict[str, Any],
  ) -> None:
    self.strategy_id = strategy_id
    self.gate_id = gate_id
    self.gate = (
      _gate_data(gate) if isinstance(gate, GateSpec) else deepcopy(dict(gate))
    )
    if self.gate.get("id") != gate_id:
      raise ProjectCommandError("edited gate id must match gate_id")
    self._before: dict[str, Any] | None = None

  def apply(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    index = next((i for i, gate in enumerate(gates) if gate.get("id") == self.gate_id), -1)
    if index < 0:
      raise ProjectCommandError(f"gate not found: {self.gate_id!r}")
    self._before = deepcopy(gates[index])
    updated = deepcopy(gates[index])
    updated.update(deepcopy(self.gate))
    updated["id"] = self.gate_id
    gates[index] = updated
    return self._updated(state, gates)

  def undo(self, state: ProjectState) -> ProjectState:
    if self._before is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    gates = _strategy_gates(state, self.strategy_id)
    index = next((i for i, gate in enumerate(gates) if gate.get("id") == self.gate_id), -1)
    if index < 0:
      raise ProjectCommandError(f"gate not found: {self.gate_id!r}")
    gates[index] = deepcopy(self._before)
    return self._updated(state, gates)


class RenameGateCommand(EditGateCommand):
  type = "gate.rename"

  def __init__(self, strategy_id: str, gate_id: str, name: str) -> None:
    if not name.strip():
      raise ProjectCommandError("gate name must not be empty")
    self._name = name.strip()
    super().__init__(strategy_id, gate_id, {"id": gate_id, "name": self._name})

  def apply(self, state: ProjectState) -> ProjectState:
    current = next(
      (gate for gate in _strategy_gates(state, self.strategy_id) if gate.get("id") == self.gate_id),
      None,
    )
    if current is None:
      raise ProjectCommandError(f"gate not found: {self.gate_id!r}")
    return super().apply(state)


class DeleteGateCommand(_GateListCommand):
  type = "gate.delete"

  def __init__(self, strategy_id: str, gate_id: str) -> None:
    self.strategy_id = strategy_id
    self.gate_id = gate_id
    self._deleted: dict[str, Any] | None = None
    self._index = -1

  def apply(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    self._index = next((i for i, gate in enumerate(gates) if gate.get("id") == self.gate_id), -1)
    if self._index < 0:
      raise ProjectCommandError(f"gate not found: {self.gate_id!r}")
    dependents = [
      gate.get("id")
      for gate in gates
      if gate.get("parent_population_id") == self.gate_id
      or self.gate_id in gate.get("thresholds", {}).get("source_ids", [])
    ]
    if dependents:
      raise ProjectCommandError(
        f"gate {self.gate_id!r} is referenced by: {', '.join(dependents)}"
      )
    self._deleted = deepcopy(gates.pop(self._index))
    return self._updated(state, gates)

  def undo(self, state: ProjectState) -> ProjectState:
    if self._deleted is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    gates = _strategy_gates(state, self.strategy_id)
    if any(gate.get("id") == self.gate_id for gate in gates):
      raise ProjectCommandError(f"duplicate gate id: {self.gate_id!r}")
    gates.insert(min(self._index, len(gates)), deepcopy(self._deleted))
    return self._updated(state, gates)


class ReparentGateCommand(EditGateCommand):
  type = "gate.reparent"

  def __init__(self, strategy_id: str, gate_id: str, parent_id: str) -> None:
    self._parent_id = parent_id or "all_events"
    super().__init__(strategy_id, gate_id, {"id": gate_id, "name": gate_id})

  def apply(self, state: ProjectState) -> ProjectState:
    current = next(
      (gate for gate in _strategy_gates(state, self.strategy_id) if gate.get("id") == self.gate_id),
      None,
    )
    if current is None:
      raise ProjectCommandError(f"gate not found: {self.gate_id!r}")
    updated = deepcopy(current)
    updated["parent_population_id"] = self._parent_id
    self.gate = updated
    return super().apply(state)


class UndoStack:
  """Qt-independent undo/redo stack for project definition commands."""

  def __init__(
    self,
    state: ProjectState | None = None,
    on_changed: Callable[[ProjectState, str], None] | None = None,
  ) -> None:
    self._state = deepcopy(state or {})
    self._commands: list[ProjectCommand] = []
    self._index = 0
    self._clean_index = 0
    self._on_changed = on_changed

  @property
  def state(self) -> ProjectState:
    return deepcopy(self._state)

  @property
  def can_undo(self) -> bool:
    return self._index > 0

  @property
  def can_redo(self) -> bool:
    return self._index < len(self._commands)

  @property
  def is_dirty(self) -> bool:
    return self._index != self._clean_index

  def mark_clean(self) -> None:
    self._clean_index = self._index

  def execute(self, command: ProjectCommand) -> ProjectState:
    candidate = command.apply(self._state)
    del self._commands[self._index :]
    self._commands.append(command)
    self._index += 1
    self._state = candidate
    self._notify(command.invalidation_reason)
    return self.state

  def undo(self) -> ProjectState:
    if not self.can_undo:
      raise ProjectCommandError("nothing to undo")
    command = self._commands[self._index - 1]
    self._state = command.undo(self._state)
    self._index -= 1
    self._notify(f"Undo {command.type}")
    return self.state

  def redo(self) -> ProjectState:
    if not self.can_redo:
      raise ProjectCommandError("nothing to redo")
    command = self._commands[self._index]
    self._state = command.apply(self._state)
    self._index += 1
    self._notify(f"Redo {command.type}")
    return self.state

  def _notify(self, reason: str) -> None:
    if self._on_changed is not None:
      self._on_changed(self.state, reason)
