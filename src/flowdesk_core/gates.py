"""Gate definitions and vectorized membership helpers.

Gates operate on full event data (numpy arrays), never on display-downsampled
data. Gate coordinates are stored in data coordinates or transformed data
coordinates, never screen pixels.

Boundary semantics:
  - Rectangle and range gates are **inclusive** on all boundaries.
  - Polygon gates use ray-casting. Points exactly on an edge are considered
    **inside**.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import GateSpec

BooleanOp = Literal["and", "or", "not"]


class GateError(FlowdeskError):
  """Raised when a gate definition or evaluation is invalid."""


# ---------------------------------------------------------------------------
# Scalar helpers (backward compatible)
# ---------------------------------------------------------------------------


def point_in_rectangle(gate: GateSpec, x: float, y: float) -> bool:
  """Return whether a point is inside a rectangle gate.

  Boundaries are inclusive.
  """
  if gate.gate_type != "rectangle":
    raise GateError("point_in_rectangle requires a rectangle gate")
  required = {"x_min", "x_max", "y_min", "y_max"}
  if not bool(required.issubset(gate.thresholds)):
    raise GateError(
      "rectangle gate requires x_min, x_max, y_min, and y_max in thresholds"
    )
  return bool(
    float(gate.thresholds["x_min"]) <= x <= float(gate.thresholds["x_max"])
    and float(gate.thresholds["y_min"]) <= y <= float(gate.thresholds["y_max"])
  )


# ---------------------------------------------------------------------------
# Vectorized gate evaluation
# ---------------------------------------------------------------------------


def evaluate_gate(
  gate: GateSpec,
  x_values: NDArray[np.float64],
  y_values: NDArray[np.float64] | None = None,
  boolean_masks: dict[str, NDArray[np.bool_]] | None = None,
) -> NDArray[np.bool_]:
  """Evaluate a gate on event data, returning a boolean membership mask.

  Args:
    gate: Gate definition.
    x_values: 1-D array of the x-parameter values (or single parameter for
              range gates).
    y_values: 1-D array of the y-parameter values (required for rectangle and
              polygon gates).
    boolean_masks: Dict mapping population/gate IDs to their boolean masks.
                   Required for boolean gates.

  Returns:
    Boolean array of length ``len(x_values)``.

  Raises:
    GateError: If the gate type is unknown or required data is missing.
  """

  if gate.gate_type == "rectangle":
    return _eval_rectangle(gate, x_values, y_values)

  if gate.gate_type == "range":
    return _eval_range(gate, x_values)

  if gate.gate_type == "polygon":
    return _eval_polygon(gate, x_values, y_values)

  if gate.gate_type == "boolean":
    return _eval_boolean(gate, boolean_masks)

  raise GateError(f"unknown gate type: {gate.gate_type!r}")


# ---------------------------------------------------------------------------
# Rectangle gate
# ---------------------------------------------------------------------------


def _eval_rectangle(
  gate: GateSpec,
  x: NDArray[np.float64],
  y: NDArray[np.float64] | None,
) -> NDArray[np.bool_]:
  """Inclusive rectangle membership."""
  if y is None:
    raise GateError("rectangle gate requires y_values")

  required = {"x_min", "x_max", "y_min", "y_max"}
  if not bool(required.issubset(gate.thresholds)):
    raise GateError(
      "rectangle gate requires x_min, x_max, y_min, and y_max in thresholds"
    )

  x_min = float(gate.thresholds["x_min"])
  x_max = float(gate.thresholds["x_max"])
  y_min = float(gate.thresholds["y_min"])
  y_max = float(gate.thresholds["y_max"])

  return (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)


# ---------------------------------------------------------------------------
# Range gate (single parameter)
# ---------------------------------------------------------------------------


def _eval_range(
  gate: GateSpec,
  x: NDArray[np.float64],
) -> NDArray[np.bool_]:
  """Inclusive range membership on a single parameter.

  Thresholds: ``min`` and/or ``max``. Either may be omitted for open-ended
  ranges.
  """
  result = np.ones(len(x), dtype=np.bool_)

  if "min" in gate.thresholds:
    vmin = float(gate.thresholds["min"])
    result = result & (x >= vmin)

  if "max" in gate.thresholds:
    vmax = float(gate.thresholds["max"])
    result = result & (x <= vmax)

  return result


# ---------------------------------------------------------------------------
# Polygon gate (ray-casting algorithm)
# ---------------------------------------------------------------------------


def _eval_polygon(
  gate: GateSpec,
  x: NDArray[np.float64],
  y: NDArray[np.float64] | None,
) -> NDArray[np.bool_]:
  """Polygon membership via ray-casting.

  Points exactly on an edge are considered inside.
  The polygon vertices are taken from ``gate.coordinates``.
  """
  if y is None:
    raise GateError("polygon gate requires y_values")

  if len(gate.coordinates) < 3:
    raise GateError("polygon gate requires at least 3 vertices")

  vertices = np.array(gate.coordinates, dtype=np.float64)

  # Vectorized ray-casting: cast ray to +infinity in x direction.
  result = _point_in_polygon_vectorized(x, y, vertices)
  return result


def _point_in_polygon_vectorized(
  px: NDArray[np.float64],
  py: NDArray[np.float64],
  vertices: NDArray[np.float64],
) -> NDArray[np.bool_]:
  """Ray-casting point-in-polygon test, vectorized over query points.

  Uses the crossing-number algorithm. A point on an edge is counted as inside.

  For each edge (yi->yj), the edge crosses the ray if one endpoint is strictly
  above py and the other is at or below py (or vice-versa). The intersection
  x-coordinate is computed and compared to px.
  """
  n_verts = len(vertices)
  crossings = np.zeros(len(px), dtype=np.int64)

  for i in range(n_verts):
    j = (i + 1) % n_verts
    xi, yi = vertices[i]
    xj, yj = vertices[j]

    # Standard crossing-number straddle test:
    # Edge crosses the ray if (yi > py) != (yj > py).
    above_i = yi > py
    above_j = yj > py
    straddle = above_i ^ above_j

    if straddle.any():
      # Compute x-coordinate of intersection.
      dy = yj - yi
      if dy != 0:
        x_intersect = xi + (py - yi) / dy * (xj - xi)
        is_right = x_intersect > px
        crossings += (straddle & is_right).astype(np.int64)

  # Also check if point is on any edge (inclusive boundary).
  on_edge = _point_on_polygon_edge(px, py, vertices)

  inside = (crossings % 2 == 1).astype(np.bool_)
  return inside | on_edge


def _point_on_polygon_edge(
  px: NDArray[np.float64],
  py: NDArray[np.float64],
  vertices: NDArray[np.float64],
) -> NDArray[np.bool_]:
  """Check if any query point lies exactly on a polygon edge.

  Uses cross-product approach: point P is on segment AB iff
  cross(AP, AB) == 0 and dot(AP, AB) is within [0, |AB|^2].
  """
  n_verts = len(vertices)
  on_any = np.zeros(len(px), dtype=np.bool_)

  # Expand to (n_points, 2) for vectorized ops.
  pts = np.stack([px, py], axis=1)  # (n, 2)

  for i in range(n_verts):
    j = (i + 1) % n_verts
    a = vertices[i]
    b = vertices[j]
    ab = b - a
    ap = pts - a  # (n, 2)

    # Cross product (2D): ap_x * ab_y - ap_y * ab_x
    cross = ap[:, 0] * ab[1] - ap[:, 1] * ab[0]

    # Dot product: ap . ab
    dot = ap[:, 0] * ab[0] + ap[:, 1] * ab[1]
    ab_sq = ab[0] ** 2 + ab[1] ** 2

    on_segment = (
      (np.abs(cross) < 1e-12)
      & (dot >= -1e-12)
      & (dot <= ab_sq + 1e-12)
    )
    on_any = on_any | on_segment

  return on_any


# ---------------------------------------------------------------------------
# Boolean gate
# ---------------------------------------------------------------------------


def _eval_boolean(
  gate: GateSpec,
  boolean_masks: dict[str, NDArray[np.bool_]] | None,
) -> NDArray[np.bool_]:
  """Boolean combination of existing population/gate masks.

  Thresholds must contain:
    - ``operation``: one of "and", "or", "not"
    - ``source_ids``: list of gate/population IDs to combine
  """
  if boolean_masks is None:
    raise GateError("boolean gate requires boolean_masks")

  op = gate.thresholds.get("operation")
  if op not in ("and", "or", "not"):
    raise GateError(
      f"boolean gate operation must be 'and', 'or', or 'not', got {op!r}"
    )

  source_ids = gate.thresholds.get("source_ids", [])
  if not source_ids:
    raise GateError("boolean gate requires at least one source_id")

  masks = []
  for sid in source_ids:
    if sid not in boolean_masks:
      raise GateError(
        f"boolean gate references unknown id: {sid!r}"
      )
    masks.append(boolean_masks[sid])

  if op == "and":
    result = masks[0]
    for m in masks[1:]:
      result = result & m
    return result

  if op == "or":
    result = masks[0]
    for m in masks[1:]:
      result = result | m
    return result

  # op == "not" -- negate the first (and only) mask.
  return ~masks[0]


# ---------------------------------------------------------------------------
# Parent population masking
# ---------------------------------------------------------------------------


def apply_parent_mask(
  child_mask: NDArray[np.bool_],
  parent_mask: NDArray[np.bool_],
) -> NDArray[np.bool_]:
  """Restrict a child gate to events that are in the parent population.

  This implements the parent-child hierarchy: a child gate only counts
  events that are already inside the parent population.
  """
  return child_mask & parent_mask
