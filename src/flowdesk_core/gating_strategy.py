"""Gating strategy evaluation.

Runs a gating strategy on event data, evaluating gates in topological order
and building parent-child population hierarchy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.boolean_expression import (
  BooleanExpressionError,
  expression_for_gate,
  validate_expression,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.gates import apply_parent_mask, evaluate_gate
from flowdesk_core.models import (
  GateSpec,
  GatingStrategySpec,
  PopulationResult,
  TransformSpec,
)
from flowdesk_core.transforms import TransformError, apply_transform

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
      try:
        expression = expression_for_gate(gate.thresholds)
        references = validate_expression(
          expression,
          set(gate_by_id),
          root_id=strategy.root_population_id,
          owner_id=gate.id,
        )
      except BooleanExpressionError as exc:
        message = str(exc).replace("unknown id", "unknown source")
        raise GatingStrategyError(
          f"boolean gate {gate.id!r} expression invalid: {message}"
        ) from exc
      gate_dependencies.update(
        reference for reference in references
        if reference != strategy.root_population_id
      )
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
  *,
  transforms: Sequence[TransformSpec] = (),
  default_transform_ids: Mapping[str, str] | None = None,
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
    strategy,
    data,
    channel_names,
    transforms=transforms,
    default_transform_ids=default_transform_ids,
  )
  return results


def evaluate_gating_strategy_with_membership(
  strategy: GatingStrategySpec,
  data: NDArray[np.float64],
  channel_names: list[str],
  *,
  transforms: Sequence[TransformSpec] = (),
  default_transform_ids: Mapping[str, str] | None = None,
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
  transform_lookup = _transform_lookup(transforms)
  default_ids = dict(default_transform_ids or {})
  transformed_cache: dict[str, NDArray[np.float64]] = {}

  # Root population: all events.
  root_mask = np.ones(n_events, dtype=np.bool_)
  population_masks[strategy.root_population_id] = root_mask

  for gate in ordered_gates(strategy):
    if gate.gate_type == "boolean":
      x_values = np.zeros(n_events, dtype=np.float64)
      y_values: NDArray[np.float64] | None = None
    else:
      raw_x_values = _get_column(gate.x_parameter, data, channel_names)
      y_values = _get_column(gate.y_parameter, data, channel_names)
      if raw_x_values is None:
        raise GatingStrategyError(
          f"gate {gate.id!r} has no x_parameter defined"
        )
      x_values = _gate_axis_values(
        gate=gate,
        axis="x",
        values=raw_x_values,
        parameter=gate.x_parameter,
        scale=gate.x_scale,
        transform_id=gate.x_transform_id or gate.transform_id,
        transform_lookup=transform_lookup,
        default_transform_ids=default_ids,
        transformed_cache=transformed_cache,
      )
      if y_values is not None:
        y_values = _gate_axis_values(
          gate=gate,
          axis="y",
          values=y_values,
          parameter=gate.y_parameter,
          scale=gate.y_scale,
          transform_id=gate.y_transform_id,
          transform_lookup=transform_lookup,
          default_transform_ids=default_ids,
          transformed_cache=transformed_cache,
        )

    gate_mask = evaluate_gate(gate, x_values, y_values, population_masks)

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
    population_gate = gate_lookup.get(population_id)
    parent_frequency = None
    if population_gate is not None and population_gate.parent_population_id is not None:
      parent_count = int(
        population_masks[population_gate.parent_population_id].sum()
      )
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


def _transform_lookup(
  transforms: Sequence[TransformSpec],
) -> dict[str, TransformSpec]:
  lookup: dict[str, TransformSpec] = {}
  for transform in transforms:
    if transform.id in lookup:
      raise GatingStrategyError(
        f"duplicate transform id: {transform.id!r}"
      )
    lookup[transform.id] = transform
  return lookup


def _gate_axis_values(
  *,
  gate: GateSpec,
  axis: str,
  values: NDArray[np.float64],
  parameter: str | None,
  scale: str,
  transform_id: str | None,
  transform_lookup: Mapping[str, TransformSpec],
  default_transform_ids: Mapping[str, str],
  transformed_cache: dict[str, NDArray[np.float64]],
) -> NDArray[np.float64]:
  """Return one gate axis in its single persisted coordinate definition."""
  effective_id = transform_id
  if effective_id is None and parameter is not None:
    effective_id = default_transform_ids.get(parameter)
  if effective_id is None:
    return _apply_gate_axis_scale(values, scale)
  if scale != "linear":
    raise GatingStrategyError(
      f"gate {gate.id!r} {axis}-axis defines a double transform: "
      f"transform_id={effective_id!r} and legacy scale={scale!r}"
    )
  transform = transform_lookup.get(effective_id)
  if transform is None:
    raise GatingStrategyError(
      f"gate {gate.id!r} {axis}-axis references unknown transform: "
      f"{effective_id!r}"
    )
  if transform.role != "analysis":
    raise GatingStrategyError(
      f"gate {gate.id!r} references non-analysis transform {effective_id!r}"
    )
  if transform.parameter != parameter:
    raise GatingStrategyError(
      f"gate {gate.id!r} {axis}-parameter {parameter!r} does not match "
      f"transform {effective_id!r} parameter {transform.parameter!r}"
    )
  cached = transformed_cache.get(effective_id)
  if cached is not None:
    return cached
  try:
    transformed = apply_transform(transform, values)
  except TransformError as exc:
    raise GatingStrategyError(
      f"gate {gate.id!r} transform {effective_id!r} failed "
      f"with {exc.code}: {exc}"
    ) from exc
  transformed_cache[effective_id] = transformed
  return transformed


def _apply_gate_axis_scale(
  values: NDArray[np.float64], scale: str
) -> NDArray[np.float64]:
  """Return values in the coordinate scale stored by a geometric gate."""
  if scale == "linear":
    return values
  if scale == "asinh":
    return np.arcsinh(values)
  if scale == "log10":
    result = np.full(values.shape, np.nan, dtype=np.float64)
    positive = values > 0
    result[positive] = np.log10(values[positive])
    return result
  raise GatingStrategyError(f"unsupported gate axis scale: {scale!r}")


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
