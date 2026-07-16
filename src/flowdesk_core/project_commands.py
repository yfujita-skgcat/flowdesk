"""Reversible, definition-only project mutations.

Commands in this module operate on JSON-compatible project manifests.  They
never capture execution results, NumPy arrays, or membership masks; only the
affected gate definitions are retained for undo/redo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from flowdesk_core.gating_strategy import GatingStrategyError, ordered_gates
from flowdesk_core.models import GateOverrideSpec, GateSpec, GatingStrategySpec
from flowdesk_core.overrides import (
  GateOverrideError,
  gate_version_hash,
  override_spec_from_mapping,
  resolve_gate_overrides,
)

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
    if self._before is None:
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


class DuplicateGateCommand(_GateListCommand):
  """Duplicate one gate definition with an explicit stable new ID."""

  type = "gate.duplicate"

  def __init__(
    self,
    strategy_id: str,
    source_gate_id: str,
    new_gate_id: str,
    *,
    name: str | None = None,
    parent_id: str | None = None,
  ) -> None:
    if not new_gate_id:
      raise ProjectCommandError("duplicate gate id must not be empty")
    self.strategy_id = strategy_id
    self.source_gate_id = source_gate_id
    self.new_gate_id = new_gate_id
    self.name = name
    self.parent_id = parent_id
    self._inserted: dict[str, Any] | None = None

  def apply(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    source = next((gate for gate in gates if gate.get("id") == self.source_gate_id), None)
    if source is None:
      raise ProjectCommandError(f"gate not found: {self.source_gate_id!r}")
    if any(gate.get("id") == self.new_gate_id for gate in gates):
      raise ProjectCommandError(f"duplicate gate id: {self.new_gate_id!r}")
    duplicate = deepcopy(source)
    duplicate["id"] = self.new_gate_id
    if self.name is not None:
      duplicate["name"] = self.name
    if self.parent_id is not None:
      duplicate["parent_population_id"] = self.parent_id
    self._inserted = deepcopy(duplicate)
    return self._updated(state, [*gates, duplicate])

  def undo(self, state: ProjectState) -> ProjectState:
    if self._inserted is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    gates = _strategy_gates(state, self.strategy_id)
    remaining = [gate for gate in gates if gate.get("id") != self.new_gate_id]
    if len(remaining) == len(gates):
      raise ProjectCommandError(f"gate not found: {self.new_gate_id!r}")
    return self._updated(state, remaining)


class CopySubtreeCommand(_GateListCommand):
  """Copy a gate and descendants, remapping all internal references."""

  type = "gate.copy_subtree"

  def __init__(
    self,
    strategy_id: str,
    source_gate_id: str,
    id_map: dict[str, str],
    *,
    target_parent_id: str | None = None,
  ) -> None:
    if not id_map or source_gate_id not in id_map:
      raise ProjectCommandError("id_map must include the source gate")
    if len(set(id_map.values())) != len(id_map):
      raise ProjectCommandError("copied gate IDs must be unique")
    self.strategy_id = strategy_id
    self.source_gate_id = source_gate_id
    self.id_map = dict(id_map)
    self.target_parent_id = target_parent_id
    self._inserted_ids: tuple[str, ...] | None = None

  def apply(self, state: ProjectState) -> ProjectState:
    gates = _strategy_gates(state, self.strategy_id)
    by_id = {gate.get("id"): gate for gate in gates}
    if self.source_gate_id not in by_id:
      raise ProjectCommandError(f"gate not found: {self.source_gate_id!r}")
    descendants = {
      gate_id
      for gate_id in by_id
      if self._is_descendant(gate_id, by_id)
    }
    subtree_ids = {self.source_gate_id, *descendants}
    missing = subtree_ids - set(self.id_map)
    if missing:
      raise ProjectCommandError(f"id_map missing subtree gate(s): {sorted(missing)}")
    if any(gate_id in by_id for gate_id in self.id_map.values()):
      raise ProjectCommandError("copied gate ID already exists")
    copied: list[dict[str, Any]] = []
    for gate in gates:
      old_id = gate.get("id")
      if old_id not in subtree_ids:
        continue
      value = deepcopy(gate)
      value["id"] = self.id_map[old_id]
      parent_id = value.get("parent_population_id")
      if old_id == self.source_gate_id and self.target_parent_id is not None:
        value["parent_population_id"] = self.target_parent_id
      elif parent_id in self.id_map:
        value["parent_population_id"] = self.id_map[parent_id]
      thresholds = value.get("thresholds", {})
      source_ids = thresholds.get("source_ids")
      if isinstance(source_ids, (list, tuple)):
        thresholds["source_ids"] = [
          self.id_map.get(source_id, source_id) for source_id in source_ids
        ]
      copied.append(value)
    self._inserted_ids = tuple(value["id"] for value in copied)
    return self._updated(state, [*gates, *copied])

  def _is_descendant(self, gate_id: str, by_id: dict[str, dict[str, Any]]) -> bool:
    current = by_id[gate_id].get("parent_population_id")
    seen: set[str] = set()
    while current and current != "all_events":
      if current in seen:
        raise ProjectCommandError("gate hierarchy cycle detected")
      seen.add(current)
      if current == self.source_gate_id:
        return True
      parent = by_id.get(current)
      if parent is None:
        return False
      current = parent.get("parent_population_id")
    return False

  def undo(self, state: ProjectState) -> ProjectState:
    if self._inserted_ids is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    copied = set(self._inserted_ids)
    gates = _strategy_gates(state, self.strategy_id)
    remaining = [gate for gate in gates if gate.get("id") not in copied]
    if len(remaining) + len(copied) != len(gates):
      raise ProjectCommandError("copied subtree definition is missing")
    return self._updated(state, remaining)


class CopySubtreeAnalysisCommand(ProjectCommand):
  """Atomically copy one subtree into multiple resolved target strategies."""

  type = "gate.copy_subtree_analysis"

  def __init__(
    self,
    source_strategy_id: str,
    source_gate_id: str,
    target_strategy_ids: list[str] | tuple[str, ...],
    id_maps: dict[str, dict[str, str]],
    *,
    target_parent_ids: dict[str, str] | None = None,
    target_channel_ids: dict[str, tuple[str, ...] | list[str]] | None = None,
    scope: str = "group",
  ) -> None:
    if scope not in {"population", "sample", "group"}:
      raise ProjectCommandError(f"invalid copy scope: {scope!r}")
    if not target_strategy_ids:
      raise ProjectCommandError("at least one target strategy is required")
    self.source_strategy_id = source_strategy_id
    self.source_gate_id = source_gate_id
    self.target_strategy_ids = tuple(target_strategy_ids)
    self.id_maps = deepcopy(id_maps)
    self.target_parent_ids = dict(target_parent_ids or {})
    self.target_channel_ids = {
      target_id: frozenset(channel_ids)
      for target_id, channel_ids in (target_channel_ids or {}).items()
    }
    self.scope = scope
    self._before: dict[str, list[dict[str, Any]]] | None = None

  def apply(self, state: ProjectState) -> ProjectState:
    source_gates = _strategy_gates(state, self.source_strategy_id)
    source_by_id = {gate.get("id"): gate for gate in source_gates}
    if self.source_gate_id not in source_by_id:
      raise ProjectCommandError(f"gate not found: {self.source_gate_id!r}")
    subtree = self._subtree(source_gates)
    candidates: dict[str, list[dict[str, Any]]] = {}
    before: dict[str, list[dict[str, Any]]] = {}
    for target_id in self.target_strategy_ids:
      target_gates = _strategy_gates(state, target_id)
      mapping = self.id_maps.get(target_id, {})
      required = {gate.get("id") for gate in subtree}
      if required - set(mapping):
        raise ProjectCommandError(
          f"id_map for {target_id!r} misses: {sorted(required - set(mapping))}"
        )
      new_ids = [mapping[gate.get("id")] for gate in subtree]
      if len(set(new_ids)) != len(new_ids):
        raise ProjectCommandError(f"copied gate IDs for {target_id!r} are not unique")
      if any(gate.get("id") in new_ids for gate in target_gates):
        raise ProjectCommandError(f"copied gate ID already exists in {target_id!r}")
      copied = self._remap_subtree(subtree, mapping)
      available_channels = self.target_channel_ids.get(target_id)
      if available_channels is not None:
        missing_channels = sorted({
          parameter
          for gate in copied
          for parameter in (gate.get("x_parameter"), gate.get("y_parameter"))
          if parameter and parameter not in available_channels
        })
        if missing_channels:
          raise ProjectCommandError(
            f"channel mapping for {target_id!r} misses: {missing_channels}"
          )
      if target_id in self.target_parent_ids:
        copied[0]["parent_population_id"] = self.target_parent_ids[target_id]
      before[target_id] = target_gates
      candidates[target_id] = [*target_gates, *copied]
    candidate_state = deepcopy(state)
    for target_id, gates in candidates.items():
      candidate_state = _replace_strategy_gates(candidate_state, target_id, gates)
    self._before = before
    return candidate_state

  def undo(self, state: ProjectState) -> ProjectState:
    if self._before is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    candidate = deepcopy(state)
    for target_id, gates in self._before.items():
      candidate = _replace_strategy_gates(candidate, target_id, gates)
    return candidate

  def _subtree(self, gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = {self.source_gate_id}
    changed = True
    while changed:
      changed = False
      for gate in gates:
        if gate.get("parent_population_id") in selected and gate.get("id") not in selected:
          selected.add(gate.get("id"))
          changed = True
    return [gate for gate in gates if gate.get("id") in selected]

  def _remap_subtree(
    self,
    subtree: list[dict[str, Any]],
    mapping: dict[str, str],
  ) -> list[dict[str, Any]]:
    copied = []
    for gate in subtree:
      value = deepcopy(gate)
      old_id = value["id"]
      value["id"] = mapping[old_id]
      parent_id = value.get("parent_population_id")
      if parent_id in mapping:
        value["parent_population_id"] = mapping[parent_id]
      thresholds = value.get("thresholds", {})
      source_ids = thresholds.get("source_ids")
      if isinstance(source_ids, (list, tuple)):
        thresholds["source_ids"] = [
          mapping.get(source_id, source_id) for source_id in source_ids
        ]
      copied.append(value)
    return copied


def _override_data(state: ProjectState) -> list[dict[str, Any]]:
  values = state.get("gate_overrides", [])
  if not isinstance(values, list):
    raise ProjectCommandError("gate_overrides must be an array")
  return deepcopy(values)


def _replace_overrides(state: ProjectState, values: list[dict[str, Any]]) -> ProjectState:
  candidate = deepcopy(state)
  candidate["gate_overrides"] = deepcopy(values)
  return candidate


class _OverrideCommand(ProjectCommand):
  """Base class for explicit, definition-only sample override commands."""

  def __init__(self) -> None:
    self._before: ProjectState | None = None

  def undo(self, state: ProjectState) -> ProjectState:
    if self._before is None:
      raise ProjectCommandError("cannot undo a command that was not applied")
    return deepcopy(self._before)


class CreateGateOverrideCommand(_OverrideCommand):
  """Create one explicit sample-local override after typed validation."""

  type = "gate_override.create"

  def __init__(self, override: Mapping[str, Any] | GateOverrideSpec) -> None:
    super().__init__()
    self.override = (
      asdict(override)
      if isinstance(override, GateOverrideSpec)
      else deepcopy(dict(override))
    )

  def apply(self, state: ProjectState) -> ProjectState:
    values = _override_data(state)
    try:
      override = override_spec_from_mapping(self.override)
    except GateOverrideError as exc:
      raise ProjectCommandError(str(exc)) from exc
    if any(value.get("id") == override.id for value in values):
      raise ProjectCommandError(f"override ID already exists: {override.id!r}")
    if any(
      value.get("sample_id") == override.sample_id
      and value.get("base_gate_id") == override.base_gate_id
      and value.get("enabled", True)
      for value in values
    ):
      raise ProjectCommandError(
        "override already exists for sample "
        f"{override.sample_id!r} and gate {override.base_gate_id!r}"
      )
    self._before = deepcopy(state)
    return _replace_overrides(state, [*values, deepcopy(self.override)])


class ResetGateOverrideCommand(_OverrideCommand):
  """Remove one explicit override and resolve the sample back to group geometry."""

  type = "gate_override.reset_to_group"

  def __init__(self, override_id: str) -> None:
    super().__init__()
    self.override_id = override_id

  def apply(self, state: ProjectState) -> ProjectState:
    values = _override_data(state)
    if not any(value.get("id") == self.override_id for value in values):
      raise ProjectCommandError(f"override not found: {self.override_id!r}")
    self._before = deepcopy(state)
    return _replace_overrides(
      state, [value for value in values if value.get("id") != self.override_id]
    )


class RebaseGateOverrideCommand(_OverrideCommand):
  """Explicitly point an override at the current shared gate version."""

  type = "gate_override.rebase"

  def __init__(self, strategy_id: str, override_id: str) -> None:
    super().__init__()
    self.strategy_id = strategy_id
    self.override_id = override_id

  def apply(self, state: ProjectState) -> ProjectState:
    values = _override_data(state)
    target = next((value for value in values if value.get("id") == self.override_id), None)
    if target is None:
      raise ProjectCommandError(f"override not found: {self.override_id!r}")
    gates = _strategy_gates(state, self.strategy_id)
    gate = next((value for value in gates if value.get("id") == target.get("base_gate_id")), None)
    if gate is None:
      raise ProjectCommandError(f"base gate not found: {target.get('base_gate_id')!r}")
    candidate = deepcopy(target)
    candidate["base_version_hash"] = gate_version_hash(gate)
    self._before = deepcopy(state)
    return _replace_overrides(
      state, [candidate if value.get("id") == self.override_id else value for value in values]
    )


class CopyGateOverrideToSelectedCommand(_OverrideCommand):
  """Copy one explicit override to selected samples with new stable IDs."""

  type = "gate_override.copy_to_selected"

  def __init__(self, override_id: str, target_sample_ids: list[str] | tuple[str, ...]) -> None:
    super().__init__()
    if not target_sample_ids:
      raise ProjectCommandError("at least one target sample is required")
    self.override_id = override_id
    self.target_sample_ids = tuple(target_sample_ids)

  def apply(self, state: ProjectState) -> ProjectState:
    values = _override_data(state)
    source = next((value for value in values if value.get("id") == self.override_id), None)
    if source is None:
      raise ProjectCommandError(f"override not found: {self.override_id!r}")
    existing = {value.get("id") for value in values}
    targets = {(value.get("sample_id"), value.get("base_gate_id")) for value in values}
    copied: list[dict[str, Any]] = []
    for sample_id in self.target_sample_ids:
      new_id = f"{self.override_id}:{sample_id}"
      if new_id in existing or (sample_id, source.get("base_gate_id")) in targets:
        raise ProjectCommandError(f"override already exists for sample {sample_id!r}")
      value = deepcopy(source)
      value["id"] = new_id
      value["sample_id"] = sample_id
      copied.append(value)
      existing.add(new_id)
      targets.add((sample_id, source.get("base_gate_id")))
    self._before = deepcopy(state)
    return _replace_overrides(state, [*values, *copied])


class PromoteGateOverrideCommand(_OverrideCommand):
  """Promote one sample geometry to shared strategy geometry with audit evidence."""

  type = "gate_override.promote_to_group"

  def __init__(
    self,
    strategy_id: str,
    override_id: str,
    *,
    confirm_comparison_critical: bool = False,
    audit_record: Mapping[str, Any] | None = None,
  ) -> None:
    super().__init__()
    self.strategy_id = strategy_id
    self.override_id = override_id
    self.confirm_comparison_critical = confirm_comparison_critical
    self.audit_record = dict(audit_record or {})

  def apply(self, state: ProjectState) -> ProjectState:
    values = _override_data(state)
    target = next((value for value in values if value.get("id") == self.override_id), None)
    if target is None:
      raise ProjectCommandError(f"override not found: {self.override_id!r}")
    override = override_spec_from_mapping(target)
    if override.gate_purpose == "comparison_critical" and (
      not self.confirm_comparison_critical or not self.audit_record.get("reason")
    ):
      raise ProjectCommandError(
        "comparison-critical promotion requires confirmation and audit reason"
      )
    strategy = PipelineRunnerStrategy.from_state(state, self.strategy_id)
    try:
      resolved = resolve_gate_overrides(strategy, override.sample_id, (override,))
    except GateOverrideError as exc:
      raise ProjectCommandError(str(exc)) from exc
    gates = [asdict(gate) for gate in resolved.gates]
    candidate = deepcopy(state)
    candidate["gating_strategies_data"][self.strategy_id]["gates"] = gates
    candidate["gate_overrides"] = [value for value in values if value.get("id") != self.override_id]
    audit = list(candidate.get("gate_override_audit", []))
    audit.append({"action": self.type, "override_id": self.override_id, **self.audit_record})
    candidate["gate_override_audit"] = audit
    self._before = deepcopy(state)
    return candidate


class PipelineRunnerStrategy:
  """Small local strategy loader to keep override commands GUI-independent."""

  @staticmethod
  def from_state(state: ProjectState, strategy_id: str) -> GatingStrategySpec:
    strategy = state.get("gating_strategies_data", {}).get(strategy_id)
    if not isinstance(strategy, dict):
      raise ProjectCommandError(f"unknown gating strategy: {strategy_id!r}")
    gates = tuple(_gate_from_data(value) for value in strategy.get("gates", []))
    return GatingStrategySpec(
      id=strategy_id, name=str(strategy.get("name", strategy_id)), gates=gates,
      root_population_id=str(strategy.get("root_population_id", "all_events")),
    )


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
