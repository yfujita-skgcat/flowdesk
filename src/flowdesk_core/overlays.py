"""Core display preparation for overlays and backgating."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import BackgatingSpec, OverlaySpec


@dataclass(frozen=True)
class OverlayLayer:
  population_id: str
  bin_edges: NDArray[np.float64]
  values: NDArray[np.float64]
  finite_event_count: int
  diagnostic: dict[str, Any]


@dataclass(frozen=True)
class BackgatingLayer:
  population_id: str
  mask: NDArray[np.bool_]
  style: dict[str, Any]


def prepare_overlay_1d(
  spec: OverlaySpec,
  events: NDArray[np.float64],
  channel_names: list[str] | tuple[str, ...],
  report: ExecutionReport,
  sample_id: str,
) -> tuple[OverlayLayer, ...]:
  """Prepare histogram layers from report memberships, never by reevaluating gates."""
  try:
    index = tuple(channel_names).index(spec.parameter)
  except ValueError as exc:
    raise ValueError(f"overlay parameter is missing: {spec.parameter!r}") from exc
  layers: list[OverlayLayer] = []
  for population_id in spec.population_ids:
    mask = _membership(report, sample_id, population_id, len(events))
    finite = np.asarray(events[mask, index], dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
      edges = np.zeros(spec.bins + 1, dtype=np.float64)
      values = np.zeros(spec.bins, dtype=np.float64)
      diagnostic = {"code": "overlay_empty_population", "population_id": population_id}
    else:
      values, edges = np.histogram(finite, bins=spec.bins)
      values = values.astype(np.float64)
      if spec.normalization == "mode" and values.size:
        maximum = float(values.max())
        values = np.divide(values, maximum) if maximum else values
      elif spec.normalization == "unit_area":
        area = float(np.sum(values * np.diff(edges)))
        values = values / area if area else np.zeros_like(values)
      diagnostic = {"code": "overlay_prepared", "population_id": population_id}
    layers.append(OverlayLayer(population_id, edges, values, int(finite.size), diagnostic))
  return tuple(layers)


def prepare_backgating(
  spec: BackgatingSpec,
  report: ExecutionReport,
  sample_id: str,
) -> tuple[BackgatingLayer, ...]:
  """Project existing target/ancestor memberships without running gate geometry."""
  target = _membership(report, sample_id, spec.target_population_id, None)
  layers = [BackgatingLayer(spec.target_population_id, target, dict(spec.target_style))]
  for population_id in spec.ancestor_population_ids:
    ancestor = _membership(report, sample_id, population_id, len(target))
    if np.any(target & ~ancestor):
      raise ValueError(f"target population is not a subset of ancestor {population_id!r}")
    layers.append(BackgatingLayer(population_id, ancestor, dict(spec.ancestor_style)))
  return tuple(layers)


def _membership(
  report: ExecutionReport, sample_id: str, population_id: str, expected_length: int | None,
) -> NDArray[np.bool_]:
  matches = [
    item for item in report.population_membership
    if item.sample_id == sample_id and item.population_id == population_id
  ]
  if not matches:
    raise ValueError(f"membership is missing: {population_id!r}")
  mask = np.asarray(matches[0].mask, dtype=np.bool_)
  if expected_length is not None and len(mask) != expected_length:
    raise ValueError("membership length does not match event data")
  return mask
