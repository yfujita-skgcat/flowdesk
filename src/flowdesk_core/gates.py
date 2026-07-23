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

from flowdesk_core.boolean_expression import (
  BooleanExpressionError,
  evaluate_expression,
  expression_for_gate,
)
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

  if gate.gate_type == "ellipse":
    return _eval_ellipse(gate, x_values, y_values)

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

  try:
    x_min = float(gate.thresholds["x_min"])
    x_max = float(gate.thresholds["x_max"])
    y_min = float(gate.thresholds["y_min"])
    y_max = float(gate.thresholds["y_max"])
  except (TypeError, ValueError) as exc:
    raise GateError("rectangle thresholds must be finite numbers") from exc
  if not all(np.isfinite(value) for value in (x_min, x_max, y_min, y_max)):
    raise GateError("rectangle thresholds must be finite numbers")
  if x_min > x_max or y_min > y_max:
    raise GateError("rectangle bounds must be ordered and non-degenerate")

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
    try:
      vmin = float(gate.thresholds["min"])
    except (TypeError, ValueError) as exc:
      raise GateError("range thresholds must be finite numbers") from exc
    if not np.isfinite(vmin):
      raise GateError("range thresholds must be finite numbers")
    result = result & (x >= vmin)

  if "max" in gate.thresholds:
    try:
      vmax = float(gate.thresholds["max"])
    except (TypeError, ValueError) as exc:
      raise GateError("range thresholds must be finite numbers") from exc
    if not np.isfinite(vmax):
      raise GateError("range thresholds must be finite numbers")
    result = result & (x <= vmax)

  if "min" in gate.thresholds and "max" in gate.thresholds and vmin > vmax:
    raise GateError("range bounds must be ordered and non-degenerate")

  return result


# ---------------------------------------------------------------------------
# Ellipse gate
# ---------------------------------------------------------------------------


def _eval_ellipse(
  gate: GateSpec,
  x: NDArray[np.float64],
  y: NDArray[np.float64] | None,
) -> NDArray[np.bool_]:
  """Evaluate an inclusive rotated ellipse in stored data coordinates."""
  if y is None:
    raise GateError("ellipse gate requires y_values")
  required = {"center_x", "center_y", "radius_x", "radius_y"}
  if not required.issubset(gate.thresholds):
    raise GateError(
      "ellipse gate requires center_x, center_y, radius_x, and radius_y"
    )
  try:
    center_x = float(gate.thresholds["center_x"])
    center_y = float(gate.thresholds["center_y"])
    radius_x = float(gate.thresholds["radius_x"])
    radius_y = float(gate.thresholds["radius_y"])
    rotation = float(gate.thresholds.get("rotation", 0.0))
  except (TypeError, ValueError) as exc:
    raise GateError("ellipse thresholds must be finite numbers") from exc
  if not all(np.isfinite(value) for value in (
    center_x, center_y, radius_x, radius_y, rotation
  )):
    raise GateError("ellipse thresholds must be finite numbers")
  if radius_x <= 0 or radius_y <= 0:
    raise GateError("ellipse radii must be greater than zero")

  cos_rotation = np.cos(rotation)
  sin_rotation = np.sin(rotation)
  dx = x - center_x
  dy = y - center_y
  local_x = cos_rotation * dx + sin_rotation * dy
  local_y = -sin_rotation * dx + cos_rotation * dy
  value = (local_x / radius_x) ** 2 + (local_y / radius_y) ** 2
  return np.asarray(np.isfinite(value) & (value <= 1.0), dtype=np.bool_)


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
  if not np.isfinite(vertices).all():
    raise GateError("polygon coordinates must be finite numbers")
  area = 0.5 * abs(float(np.sum(
    vertices[:, 0] * np.roll(vertices[:, 1], -1)
    - vertices[:, 1] * np.roll(vertices[:, 0], -1)
  )))
  if area <= 1e-12:
    raise GateError("polygon geometry must have non-zero area")

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
  result: NDArray[np.bool_] = np.logical_or(inside, on_edge)
  return result


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

  try:
    expression = expression_for_gate(gate.thresholds)
    return evaluate_expression(expression, boolean_masks)
  except BooleanExpressionError as exc:
    raise GateError(f"boolean expression evaluation failed: {exc}") from exc


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
