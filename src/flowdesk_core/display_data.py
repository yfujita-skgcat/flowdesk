"""GUI-independent preparation of reproducible plot display data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PlotViewSpec


@dataclass(frozen=True)
class DisplayData:
  """Prepared display aggregate; never used for scientific membership/statistics."""

  plot_type: str
  x: NDArray[np.float64]
  y: NDArray[np.float64]
  values: NDArray[np.float64]
  x_edges: NDArray[np.float64]
  y_edges: NDArray[np.float64]
  diagnostics: tuple[dict[str, Any], ...] = ()


def prepare_display_data(
  view: PlotViewSpec,
  events: NDArray[np.float64],
  channel_names: list[str] | tuple[str, ...],
  report: ExecutionReport | None = None,
  *,
  sample_id: str | None = None,
  parameter_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> DisplayData:
  """Prepare a view from full events and report membership, with deterministic bins."""
  names = tuple(channel_names)
  try:
    x_index = names.index(view.x_parameter)
  except ValueError as exc:
    raise ValueError(f"display X parameter is missing: {view.x_parameter!r}") from exc
  if events.ndim != 2 or events.shape[1] != len(names):
    raise ValueError("display events and channel names do not align")
  mask = np.ones(len(events), dtype=np.bool_)
  if view.population_id != "all_events" and (report is None or sample_id is None):
    raise ValueError(f"display population membership is missing: {view.population_id!r}")
  if report is not None and sample_id is not None and view.population_id != "all_events":
    memberships = [
      item for item in report.population_membership
      if item.sample_id == sample_id and item.population_id == view.population_id
    ]
    if not memberships:
      raise ValueError(f"display population membership is missing: {view.population_id!r}")
    mask = np.asarray(memberships[0].mask, dtype=np.bool_)
  selected_x = np.asarray(events[mask, x_index], dtype=np.float64)
  finite_x = selected_x[np.isfinite(selected_x)]
  x_meta = dict((parameter_metadata or {}).get(view.x_parameter, {}))
  diagnostics = [{
    "code": "display_nonfinite_excluded", "event_count": int(len(selected_x)),
    "finite_event_count": int(len(finite_x)),
    "parameter_id": view.x_parameter,
    "expression": x_meta.get("expression"),
    "source_stage": x_meta.get("source_stage"),
    "transform_id": view.x_transform_id,
    "invalid_reason_counts": _invalid_reason_counts(selected_x),
  }]
  if view.plot_type in {"histogram", "cdf"}:
    if view.plot_type == "cdf":
      ordered = np.sort(finite_x)
      return DisplayData("cdf", ordered, np.linspace(0.0, 1.0, len(ordered), endpoint=True),
                         np.empty(0), np.empty(0), np.empty(0), tuple(diagnostics))
    bins = _bins(view, 1)[0]
    counts, edges = _histogram(finite_x, bins)
    return DisplayData("histogram", (edges[:-1] + edges[1:]) / 2.0, counts,
                       np.empty(0), edges, np.empty(0), tuple(diagnostics))
  if not view.y_parameter:
    raise ValueError(f"plot type {view.plot_type!r} requires y_parameter")
  try:
    y_index = names.index(view.y_parameter)
  except ValueError as exc:
    raise ValueError(f"display Y parameter is missing: {view.y_parameter!r}") from exc
  selected_y = np.asarray(events[mask, y_index], dtype=np.float64)
  pair = np.isfinite(selected_x) & np.isfinite(selected_y)
  if np.any(~np.isfinite(selected_y)):
    diagnostics.append({
      "code": "display_nonfinite_excluded",
      "event_count": int(len(selected_y)),
      "finite_event_count": int(np.count_nonzero(np.isfinite(selected_y))),
      "parameter_id": view.y_parameter,
      "expression": (parameter_metadata or {}).get(view.y_parameter, {}).get("expression"),
      "source_stage": (parameter_metadata or {}).get(view.y_parameter, {}).get("source_stage"),
      "transform_id": view.y_transform_id,
      "invalid_reason_counts": _invalid_reason_counts(selected_y),
    })
  x_values, y_values = selected_x[pair], selected_y[pair]
  if view.plot_type in {"scatter", "dot"}:
    max_points = int(view.rendering_downsample.get("max_points", 20_000))
    if max_points > 0 and len(x_values) > max_points:
      indices = np.linspace(0, len(x_values) - 1, max_points, dtype=np.int64)
      x_values = x_values[indices]
      y_values = y_values[indices]
      diagnostics.append({
        "code": "display_points_sampled",
        "source_event_count": int(np.count_nonzero(pair)),
        "displayed_event_count": int(len(x_values)),
        "max_points": max_points,
        "method": "deterministic_even_spacing.v1",
      })
    return DisplayData(
      view.plot_type, x_values, y_values, np.empty(0), np.empty(0), np.empty(0),
      tuple(diagnostics),
    )
  bins_x, bins_y = _bins(view, 2)
  density, x_edges, y_edges = np.histogram2d(x_values, y_values, bins=(bins_x, bins_y))
  return DisplayData(
    view.plot_type, x_edges, y_edges, density, x_edges, y_edges, tuple(diagnostics),
  )


def _bins(view: PlotViewSpec, dimensions: int) -> tuple[int, ...]:
  value = view.aggregation.get("bins", (64,) * dimensions)
  if isinstance(value, int):
    value = (value,) * dimensions
  if len(value) != dimensions or any(isinstance(item, bool) or int(item) < 1 for item in value):
    raise ValueError("plot aggregation bins must be positive")
  return tuple(int(item) for item in value)


def _histogram(
  values: NDArray[np.float64], bins: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
  if values.size == 0:
    return np.zeros(bins, dtype=np.float64), np.zeros(bins + 1, dtype=np.float64)
  counts, edges = np.histogram(values, bins=bins)
  return np.asarray(counts, dtype=np.float64), np.asarray(edges, dtype=np.float64)


def _invalid_reason_counts(values: NDArray[np.float64]) -> dict[str, int]:
  """Classify omitted coordinates without converting them into valid values."""
  return {
    "nan": int(np.count_nonzero(np.isnan(values))),
    "positive_inf": int(np.count_nonzero(np.isposinf(values))),
    "negative_inf": int(np.count_nonzero(np.isneginf(values))),
  }
