"""Gating strategy evaluation.

Runs a gating strategy on event data, evaluating gates in topological order
and building parent-child population hierarchy.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.gates import apply_parent_mask, evaluate_gate
from flowdesk_core.models import (
  GateSpec,
  GatingStrategySpec,
  PopulationResult,
)

# ---------------------------------------------------------------------------
# Type alias for membership masks dict
# ---------------------------------------------------------------------------

PopulationMaskDict = dict[str, NDArray[np.bool_]]


class GatingStrategyError(FlowdeskError):
  """Raised when a gating strategy cannot be evaluated."""


def ordered_gates(strategy: GatingStrategySpec) -> tuple[GateSpec, ...]:
  """Validate *strategy* and return gates in dependency order.

  Parent populations and boolean sources are dependencies. The original gate
  order is retained whenever two gates are otherwise independent.
  """
  gate_by_id: dict[str, GateSpec] = {}
  original_order: dict[str, int] = {}
  for index, gate in enumerate(strategy.gates):
    if not gate.id:
      raise GatingStrategyError("gate id must not be empty")
    if gate.id == strategy.root_population_id:
      raise GatingStrategyError(
        f"gate id conflicts with root population: {gate.id!r}"
      )
    if gate.id in gate_by_id:
      raise GatingStrategyError(f"duplicate gate id: {gate.id!r}")
    gate_by_id[gate.id] = gate
    original_order[gate.id] = index

  dependencies: dict[str, set[str]] = {}
  for gate in strategy.gates:
    gate_dependencies: set[str] = set()
    parent_id = gate.parent_population_id
    if parent_id and parent_id != strategy.root_population_id:
      if parent_id not in gate_by_id:
        raise GatingStrategyError(
          f"gate {gate.id!r} references unknown parent population: {parent_id!r}"
        )
      gate_dependencies.add(parent_id)

    if gate.gate_type == "boolean":
      operation = gate.thresholds.get("operation")
      if operation not in {"and", "or", "not"}:
        raise GatingStrategyError(
          f"boolean gate {gate.id!r} has invalid operation: {operation!r}"
        )
      source_ids = gate.thresholds.get("source_ids")
      if not isinstance(source_ids, (list, tuple)):
        raise GatingStrategyError(
          f"boolean gate {gate.id!r} source_ids must be an array"
        )
      required_count = 1 if operation == "not" else 2
      if len(source_ids) < required_count:
        raise GatingStrategyError(
          f"boolean gate {gate.id!r} requires at least {required_count} source id(s)"
        )
      if operation == "not" and len(source_ids) != 1:
        raise GatingStrategyError(
          f"boolean NOT gate {gate.id!r} requires exactly one source id"
        )
      for source_id in source_ids:
        if source_id == strategy.root_population_id:
          continue
        if source_id not in gate_by_id:
          raise GatingStrategyError(
            f"boolean gate {gate.id!r} references unknown source: {source_id!r}"
          )
        gate_dependencies.add(source_id)
    dependencies[gate.id] = gate_dependencies

  remaining = {gate_id: set(deps) for gate_id, deps in dependencies.items()}
  result: list[GateSpec] = []
  while remaining:
    ready = sorted(
      (gate_id for gate_id, deps in remaining.items() if not deps),
      key=original_order.__getitem__,
    )
    if not ready:
      cycle_ids = sorted(remaining, key=original_order.__getitem__)
      raise GatingStrategyError(
        f"gate dependency cycle detected: {', '.join(cycle_ids)}"
      )
    for gate_id in ready:
      result.append(gate_by_id[gate_id])
      del remaining[gate_id]
    for deps in remaining.values():
      deps.difference_update(ready)

  return tuple(result)


def evaluate_gating_strategy(
  strategy: GatingStrategySpec,
  data: NDArray[np.float64],
  channel_names: list[str],
) -> list[PopulationResult]:
  """Evaluate a gating strategy on event data.

  Gates are validated and evaluated in dependency order.
  The root population (``strategy.root_population_id``) contains all events.

  Args:
    strategy: Gating strategy with gates and hierarchy.
    data: 2-D array of shape ``(n_events, n_channels)``.
    channel_names: Column names aligned with ``data`` columns.

  Returns:
    List of ``PopulationResult`` for each population (including root).
  """
  results, _ = evaluate_gating_strategy_with_membership(
    strategy, data, channel_names
  )
  return results


def evaluate_gating_strategy_with_membership(
  strategy: GatingStrategySpec,
  data: NDArray[np.float64],
  channel_names: list[str],
) -> tuple[list[PopulationResult], PopulationMaskDict]:
  """Evaluate a gating strategy and return both results and membership masks.

  This is the membership-aware variant of ``evaluate_gating_strategy``.
  The returned masks are full-length boolean arrays aligned with the input
  event data, made read-only before being returned.

  Args:
    strategy: Gating strategy with gates and hierarchy.
    data: 2-D array of shape ``(n_events, n_channels)``.
    channel_names: Column names aligned with ``data`` columns.

  Returns:
    A tuple of:
      - List of ``PopulationResult`` for each population (including root).
      - Dict mapping population IDs to read-only boolean membership masks.
  """
  n_events = data.shape[0]
  population_masks: PopulationMaskDict = {}
  gate_lookup = {gate.id: gate for gate in strategy.gates}

  # Root population: all events.
  root_mask = np.ones(n_events, dtype=np.bool_)
  population_masks[strategy.root_population_id] = root_mask

  for gate in ordered_gates(strategy):
    if gate.gate_type == "boolean":
      x_vals = np.zeros(n_events, dtype=np.float64)
      y_vals = None
    else:
      x_vals = _get_column(gate.x_parameter, data, channel_names)
      y_vals = _get_column(gate.y_parameter, data, channel_names)
      if x_vals is None:
        raise GatingStrategyError(
          f"gate {gate.id!r} has no x_parameter defined"
        )

    gate_mask = evaluate_gate(gate, x_vals, y_vals, population_masks)

    parent_id = gate.parent_population_id
    if parent_id is not None:
      if parent_id not in population_masks:
        raise GatingStrategyError(
          f"gate {gate.id!r} references unknown parent population: "
          f"{parent_id!r}"
        )
      gate_mask = apply_parent_mask(gate_mask, population_masks[parent_id])

    population_masks[gate.id] = gate_mask

  population_results: list[PopulationResult] = []
  for population_id, mask in population_masks.items():
    gate = gate_lookup.get(population_id)
    parent_frequency = None
    if gate is not None and gate.parent_population_id is not None:
      parent_count = int(population_masks[gate.parent_population_id].sum())
      if parent_count > 0:
        parent_frequency = int(mask.sum()) / parent_count
    population_results.append(
      PopulationResult(
        sample_id="",
        population_id=population_id,
        event_count=int(mask.sum()),
        frequency_of_parent=parent_frequency,
        frequency_of_total=(
          1.0
          if population_id == strategy.root_population_id
          else (int(mask.sum()) / n_events if n_events else 0.0)
        ),
      )
    )

  for mask in population_masks.values():
    mask.setflags(write=False)

  return population_results, population_masks


def _get_column(
  param_name: str | None,
  data: NDArray[np.float64],
  channel_names: list[str],
) -> NDArray[np.float64] | None:
  """Extract a column by parameter name."""
  if param_name is None:
    return None
  if param_name not in channel_names:
    raise GatingStrategyError(
      f"parameter {param_name!r} not found in channel names: {channel_names}"
    )
  col_idx = channel_names.index(param_name)
  return data[:, col_idx]
