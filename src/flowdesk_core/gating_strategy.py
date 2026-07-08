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


def evaluate_gating_strategy(
  strategy: GatingStrategySpec,
  data: NDArray[np.float64],
  channel_names: list[str],
) -> list[PopulationResult]:
  """Evaluate a gating strategy on event data.

  Gates are evaluated in the order they appear in ``strategy.gates``.
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

  for gate in strategy.gates:
    # Resolve x/y values from data.
    x_vals = _get_column(gate.x_parameter, data, channel_names)
    y_vals = _get_column(gate.y_parameter, data, channel_names)

    # x_vals is required for all gate types.
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
