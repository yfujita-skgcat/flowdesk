#!/usr/bin/env python3
"""Measure opt-in interactive density-rendering costs without CI thresholds."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from flowdesk_core.density_colors import DensityColorConfig, estimate_density_colors
from flowdesk_qt.plot_widget import PlotWidget


def _fixture(point_count: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
  rng = np.random.default_rng(seed)
  core_count = max(1, round(point_count * 0.9))
  rare_count = point_count - core_count
  return (
    np.concatenate((rng.normal(0.0, 0.2, core_count), rng.normal(2.0, 0.05, rare_count))),
    np.concatenate((rng.normal(0.0, 0.2, core_count), rng.normal(2.0, 0.05, rare_count))),
  )


def _median_ms(values: list[float]) -> float:
  return float(np.median(np.asarray(values, dtype=np.float64)))


def run_benchmark(
  point_count: int,
  repeats: int,
  seed: int,
  density_workers: int = 1,
  density_memory_budget_bytes: int | None = None,
) -> dict[str, Any]:
  """Measure density estimation and cold PlotWidget rendering separately."""
  if point_count < 2:
    raise ValueError("point_count must be at least 2")
  if repeats < 1:
    raise ValueError("repeats must be positive")
  if density_workers < 1:
    raise ValueError("density_workers must be positive")
  if density_memory_budget_bytes is not None and density_memory_budget_bytes < 1:
    raise ValueError("density_memory_budget_bytes must be positive")
  app = QApplication.instance() or QApplication([])
  x_values, y_values = _fixture(point_count, seed)
  bounds = (
    float(x_values.min()), float(x_values.max()),
    float(y_values.min()), float(y_values.max()),
  )
  numeric_ms: list[float] = []
  plot_ms: list[float] = []
  cached_replot_ms: list[float] = []
  size_update_ms: list[float] = []
  opacity_update_ms: list[float] = []
  for _ in range(repeats):
    started = time.perf_counter()
    estimate_density_colors(
      x_values, y_values, x_values, y_values,
      bounds=bounds, logical_size=(512, 512),
      config=DensityColorConfig(
        histogram_workers=density_workers,
        histogram_memory_budget_bytes=density_memory_budget_bytes,
      ),
    )
    numeric_ms.append((time.perf_counter() - started) * 1000.0)
    widget = PlotWidget()
    try:
      started = time.perf_counter()
      widget.plot_events(x_values, y_values, density_coloring=True)
      app.processEvents()
      plot_ms.append((time.perf_counter() - started) * 1000.0)

      # MainWindow supplies this semantic identity.  Measure the common
      # gate/label-only replot separately from cold construction so it cannot
      # be mistaken for a density-kernel improvement.
      context = ("benchmark", "sample", "all_events", "x", "y")
      widget.plot_events(
        x_values, y_values,
        density_coloring=True, density_cache_context=context,
      )
      app.processEvents()
      started = time.perf_counter()
      widget.plot_events(
        x_values, y_values,
        density_coloring=True, density_cache_context=context,
      )
      app.processEvents()
      cached_replot_ms.append((time.perf_counter() - started) * 1000.0)

      # Density style updates retain the existing X/Y scatter data. Size can
      # use one scalar update; opacity still changes each resolved brush.
      started = time.perf_counter()
      widget.set_style(replace(widget.style(), dot_size=3.0))
      app.processEvents()
      size_update_ms.append((time.perf_counter() - started) * 1000.0)
      started = time.perf_counter()
      widget.set_style(replace(widget.style(), dot_opacity=0.4))
      app.processEvents()
      opacity_update_ms.append((time.perf_counter() - started) * 1000.0)
    finally:
      widget.close()
      widget.deleteLater()
      app.processEvents()
  return {
    "algorithm_version": "interactive_density_plot_benchmark.v1",
    "thresholds": None,
    "fixture": {"point_count": point_count, "seed": seed, "cold_widget": True},
    "density_runtime": {
      "requested_workers": density_workers,
      "memory_budget_bytes": density_memory_budget_bytes,
      "plot_widget_uses_default_density_config": True,
    },
    "environment": {
      "platform": platform.platform(),
      "python": sys.version,
      "numpy": np.__version__,
    },
    "measurements_ms": {
      "density_numeric": numeric_ms,
      "plot_events_total": plot_ms,
      "cached_density_replot": cached_replot_ms,
      "cached_density_size_update": size_update_ms,
      "cached_density_opacity_update": opacity_update_ms,
      "density_numeric_median": _median_ms(numeric_ms),
      "plot_events_total_median": _median_ms(plot_ms),
      "cached_density_replot_median": _median_ms(cached_replot_ms),
      "cached_density_size_update_median": _median_ms(size_update_ms),
      "cached_density_opacity_update_median": _median_ms(opacity_update_ms),
    },
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--points", type=int, default=20_000)
  parser.add_argument("--repeats", type=int, default=5)
  parser.add_argument("--seed", type=int, default=1729)
  parser.add_argument("--density-workers", type=int, default=1)
  parser.add_argument("--density-memory-budget-mib", type=int)
  parser.add_argument(
    "--output", type=Path, default=Path("artifacts/density-plot-benchmark.json"),
  )
  args = parser.parse_args()
  result = run_benchmark(
    args.points, args.repeats, args.seed, args.density_workers,
    None if args.density_memory_budget_mib is None
    else args.density_memory_budget_mib * 1024 * 1024,
  )
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
  print(json.dumps(result, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
