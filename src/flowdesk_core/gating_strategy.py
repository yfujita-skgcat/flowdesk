"""Gating strategy evaluation.

Runs a gating strategy on event data, evaluating gates in topological order
and building parent-child population hierarchy.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.gates import apply_parent_mask, evaluate_gate
from flowdesk_core.models import GateSpec, GatingStrategySpec, PopulationResult


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
  n_events = data.shape[0]

  # Build a lookup from gate id to GateSpec.
  gate_lookup: dict[str, GateSpec] = {}
  for g in strategy.gates:
    gate_lookup[g.id] = g

  # Evaluate gates in order, maintaining population masks.
  population_masks: dict[str, NDArray[np.bool_]] = {}

  # Root population: all events.
  root_mask = np.ones(n_events, dtype=np.bool_)
  population_masks[strategy.root_population_id] = root_mask

  # Track results.
  results: list[PopulationResult] = []

  for gate in ordered_gates(strategy):
    if gate.gate_type == "boolean":
      x_vals = np.zeros(n_events, dtype=np.float64)
      y_vals = None
    else:
      # Resolve x/y values from data.
      x_vals = _get_column(gate.x_parameter, data, channel_names)
      y_vals = _get_column(gate.y_parameter, data, channel_names)

      # x_vals is required for non-boolean gate types.
      if x_vals is None:
        raise GatingStrategyError(
          f"gate {gate.id!r} has no x_parameter defined"
        )

    # Evaluate the gate.
    gate_mask = evaluate_gate(gate, x_vals, y_vals, population_masks)

    # Apply parent population restriction.
    parent_id = gate.parent_population_id
    if parent_id is not None:
      if parent_id not in population_masks:
        raise GatingStrategyError(
          f"gate {gate.id!r} references unknown parent population: "
          f"{parent_id!r}"
        )
      gate_mask = apply_parent_mask(gate_mask, population_masks[parent_id])

    # Store under the gate's id (which also serves as population id).
    population_masks[gate.id] = gate_mask

    results.append(
      PopulationResult(
        sample_id="",  # filled by caller.
        population_id=gate.id,
        event_count=int(gate_mask.sum()),
        frequency_of_parent=None,  # computed below.
        frequency_of_total=float(gate_mask.sum()) / n_events
        if n_events > 0
        else 0.0,
      )
    )

  # Also emit root population result.
  root_result = PopulationResult(
    sample_id="",
    population_id=strategy.root_population_id,
    event_count=int(root_mask.sum()),
    frequency_of_parent=None,
    frequency_of_total=1.0,
  )
  results.insert(0, root_result)

  # Rebuild results with correct parent frequencies.
  # PopulationResult is frozen, so we rebuild with updated values.
  final_results: list[PopulationResult] = [root_result]

  for res in results[1:]:
    gspec: GateSpec | None = gate_lookup.get(res.population_id)
    parent_freq: float | None = None
    if gspec is not None:
      if gspec.parent_population_id is not None:
        parent_mask = population_masks.get(gspec.parent_population_id)
        if parent_mask is not None:
          parent_count = int(parent_mask.sum())
          if parent_count > 0:
            parent_freq = res.event_count / parent_count

    final_results.append(
      PopulationResult(
        sample_id=res.sample_id,
        population_id=res.population_id,
        event_count=res.event_count,
        frequency_of_parent=parent_freq,
        frequency_of_total=res.frequency_of_total,
      )
    )

  return final_results


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
