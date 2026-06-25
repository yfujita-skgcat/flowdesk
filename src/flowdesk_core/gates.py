"""Gate definitions and minimal membership helpers."""

from __future__ import annotations

from flowdesk_core.models import GateSpec


def point_in_rectangle(gate: GateSpec, x: float, y: float) -> bool:
  """Return whether a point is inside a rectangle gate."""

  if gate.gate_type != "rectangle":
    raise ValueError("point_in_rectangle requires a rectangle gate")
  required = {"x_min", "x_max", "y_min", "y_max"}
  if not required.issubset(gate.thresholds):
    raise ValueError("rectangle gate requires x_min, x_max, y_min, and y_max")
  return (
    gate.thresholds["x_min"] <= x <= gate.thresholds["x_max"]
    and gate.thresholds["y_min"] <= y <= gate.thresholds["y_max"]
  )
