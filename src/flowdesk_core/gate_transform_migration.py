"""Explicit gate coordinate migration with full-event membership comparison."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.gating_strategy import evaluate_gating_strategy_with_membership
from flowdesk_core.models import GateSpec, GatingStrategySpec, TransformSpec
from flowdesk_core.transforms import TransformError, apply_transform, inverse_transform


class GateTransformMigrationError(FlowdeskError):
  """Raised when gate coordinates cannot be migrated without guessing."""

  def __init__(self, code: str, message: str) -> None:
    self.code = code
    super().__init__(message)


@dataclass(frozen=True)
class GateTransformMigrationPreview:
  """Full-event comparison of one source gate and one migration candidate."""

  source_gate: GateSpec
  candidate_gate: GateSpec
  source_event_count: int
  candidate_event_count: int
  gained_event_count: int
  lost_event_count: int
  mapping_kind: Literal[
    "exact_axis_monotonic", "vertex_reprojection_approximation"
  ]
  scientifically_equivalent: bool


def build_gate_transform_migration_candidate(
  gate: GateSpec,
  *,
  transforms: Sequence[TransformSpec],
  target_x_transform: TransformSpec | None = None,
  target_y_transform: TransformSpec | None = None,
) -> GateSpec:
  """Reproject persisted gate coordinates into explicitly selected transforms.

  Rectangle and range boundaries are one-dimensional monotonic boundaries.
  Polygon vertices are reprojected individually and must be presented as an
  approximation because straight edges in different coordinate systems are
  not generally the same event-space boundary.
  """
  if gate.gate_type not in {"rectangle", "range", "polygon"}:
    raise GateTransformMigrationError(
      "unsupported_gate_type",
      f"gate type {gate.gate_type!r} has no geometric transform migration",
    )
  lookup = _transform_lookup(transforms)
  _validate_target(gate.x_parameter, target_x_transform, "x")
  _validate_target(gate.y_parameter, target_y_transform, "y")

  x_mapper = _axis_mapper(
    gate.x_transform_id,
    target_x_transform,
    lookup,
  )
  y_mapper = _axis_mapper(
    gate.y_transform_id,
    target_y_transform,
    lookup,
  )

  thresholds = dict(gate.thresholds)
  coordinates = gate.coordinates
  if gate.gate_type == "rectangle":
    x_bounds = sorted(x_mapper(np.array([
      float(thresholds["x_min"]), float(thresholds["x_max"])
    ], dtype=np.float64)))
    y_bounds = sorted(y_mapper(np.array([
      float(thresholds["y_min"]), float(thresholds["y_max"])
    ], dtype=np.float64)))
    thresholds.update(
      x_min=float(x_bounds[0]),
      x_max=float(x_bounds[1]),
      y_min=float(y_bounds[0]),
      y_max=float(y_bounds[1]),
    )
  elif gate.gate_type == "range":
    names = [name for name in ("min", "max") if name in thresholds]
    if names:
      mapped = sorted(x_mapper(np.array(
        [float(thresholds[name]) for name in names], dtype=np.float64
      )))
      for name, value in zip(names, mapped, strict=True):
        thresholds[name] = float(value)
  else:
    if len(coordinates) < 3:
      raise GateTransformMigrationError(
        "invalid_gate_coordinates", "polygon requires at least three vertices"
      )
    x_values = x_mapper(np.array([point[0] for point in coordinates]))
    y_values = y_mapper(np.array([point[1] for point in coordinates]))
    coordinates = tuple(
      (float(x), float(y)) for x, y in zip(x_values, y_values, strict=True)
    )

  return replace(
    gate,
    x_transform_id=(
      target_x_transform.id if target_x_transform is not None
      else gate.x_transform_id
    ),
    y_transform_id=(
      target_y_transform.id if target_y_transform is not None
      else gate.y_transform_id
    ),
    thresholds=thresholds,
    coordinates=coordinates,
  )


def preview_gate_transform_migration(
  gate: GateSpec,
  data: NDArray[np.float64],
  channel_names: list[str],
  *,
  transforms: Sequence[TransformSpec],
  target_x_transform: TransformSpec | None = None,
  target_y_transform: TransformSpec | None = None,
  parent_mask: NDArray[np.bool_] | None = None,
) -> GateTransformMigrationPreview:
  """Compare source and candidate membership on every supplied event."""
  candidate = build_gate_transform_migration_candidate(
    gate,
    transforms=transforms,
    target_x_transform=target_x_transform,
    target_y_transform=target_y_transform,
  )
  source_mask = _standalone_gate_mask(gate, data, channel_names, transforms)
  candidate_mask = _standalone_gate_mask(
    candidate, data, channel_names, transforms
  )
  if parent_mask is not None:
    if parent_mask.shape != (data.shape[0],):
      raise GateTransformMigrationError(
        "parent_mask_shape_mismatch",
        "parent population mask must align with the full event array",
      )
    source_mask = source_mask & parent_mask
    candidate_mask = candidate_mask & parent_mask
  approximate = gate.gate_type == "polygon"
  return GateTransformMigrationPreview(
    source_gate=gate,
    candidate_gate=candidate,
    source_event_count=int(source_mask.sum()),
    candidate_event_count=int(candidate_mask.sum()),
    gained_event_count=int((candidate_mask & ~source_mask).sum()),
    lost_event_count=int((source_mask & ~candidate_mask).sum()),
    mapping_kind=(
      "vertex_reprojection_approximation"
      if approximate else "exact_axis_monotonic"
    ),
    scientifically_equivalent=not approximate,
  )


def _standalone_gate_mask(
  gate: GateSpec,
  data: NDArray[np.float64],
  channel_names: list[str],
  transforms: Sequence[TransformSpec],
) -> NDArray[np.bool_]:
  standalone = replace(gate, parent_population_id="all_events")
  strategy = GatingStrategySpec(
    id="gate_transform_migration_preview",
    name="Gate transform migration preview",
    gates=(standalone,),
  )
  _results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channel_names, transforms=transforms
  )
  return masks[gate.id]


def _transform_lookup(
  transforms: Sequence[TransformSpec],
) -> dict[str, TransformSpec]:
  lookup: dict[str, TransformSpec] = {}
  for transform in transforms:
    if transform.id in lookup:
      raise GateTransformMigrationError(
        "duplicate_transform_id", f"duplicate transform id: {transform.id!r}"
      )
    lookup[transform.id] = transform
  return lookup


def _validate_target(
  parameter: str | None,
  target: TransformSpec | None,
  axis: str,
) -> None:
  if target is None:
    return
  if target.role != "analysis" or target.parameter != parameter:
    raise GateTransformMigrationError(
      "target_transform_parameter_mismatch",
      f"{axis}-axis parameter {parameter!r} does not match target transform "
      f"{target.id!r} parameter {target.parameter!r}",
    )


def _axis_mapper(
  source_transform_id: str | None,
  target: TransformSpec | None,
  lookup: dict[str, TransformSpec],
) -> Callable[[NDArray[np.float64]], NDArray[np.float64]]:
  if target is None:
    return lambda values: values.copy()

  def mapper(values: NDArray[np.float64]) -> NDArray[np.float64]:
    if source_transform_id is not None:
      source = lookup.get(source_transform_id)
      if source is None:
        raise GateTransformMigrationError(
          "unknown_source_transform",
          f"source gate references unknown transform {source_transform_id!r}",
        )
      try:
        raw = inverse_transform(source, values)
      except TransformError as exc:
        code = (
          "source_transform_inverse_unavailable"
          if exc.code == "transform_inverse_unavailable"
          else "source_transform_inverse_failed"
        )
        raise GateTransformMigrationError(code, str(exc)) from exc
    else:
      raise GateTransformMigrationError(
        "missing_source_transform",
        "gate migration requires a formal source transform ID",
      )
    try:
      mapped = apply_transform(target, raw)
    except TransformError as exc:
      raise GateTransformMigrationError(
        "target_transform_failed", str(exc)
      ) from exc
    if not np.all(np.isfinite(mapped)):
      raise GateTransformMigrationError(
        "nonfinite_migrated_coordinate",
        "gate boundary maps to a non-finite target coordinate",
      )
    return mapped

  return mapper
