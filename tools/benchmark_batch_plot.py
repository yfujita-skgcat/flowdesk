#!/usr/bin/env python3
"""Benchmark sequential and bounded-thread Batch Plot rendering.

This benchmark exercises the renderer-neutral core writers with deterministic
prepared sample layers. It is a diagnostic tool, not a CI timing threshold.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

import numpy as np

from flowdesk_core.batch_plot_export import run_batch_plot_export
from flowdesk_core.execution_control import (
  ExecutionBackend,
  ExecutionControl,
  ExecutionOptions,
)
from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_export import (
  prepare_plot_export,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution


class _RunResult(TypedDict):
  backend: str
  elapsed_seconds: float
  output_bytes: int
  status: str
  execution: Mapping[str, Any] | None


def run_batch_plot_benchmark(
  *,
  sample_count: int = 8,
  event_count: int = 5_000,
  max_workers: int = 2,
  seed: int = 1729,
) -> dict[str, object]:
  """Return timing and output-size diagnostics for serial and thread backends."""
  if sample_count < 1 or event_count < 1 or max_workers < 1:
    raise ValueError("sample_count, event_count, and max_workers must be positive")
  rng = np.random.default_rng(seed)
  samples = [
    {"id": f"s{index + 1}", "name": f"Sample {index + 1}", "path": f"s{index + 1}.fcs"}
    for index in range(sample_count)
  ]
  prepared = {
    sample["id"]: prepare_plot_export(
      "benchmark-view",
      "scatter",
      ({
        "source_id": sample["id"],
        "sample_id": sample["id"],
        "population_id": "all_events",
        "display_name": sample["name"],
        "visible": True,
      },),
      (OverlaySourceResolution(sample["id"], "compatible"),),
    )
    for sample in samples
  }
  layers = {
    sample["id"]: {
      sample["id"]: (
        tuple(np.clip(rng.normal(0.5, 0.18, event_count), 0.0, 1.0)),
        tuple(np.clip(rng.normal(0.5, 0.18, event_count), 0.0, 1.0)),
      ),
    }
    for sample in samples
  }
  spec = BatchPlotExportSpec(
    id="batch-benchmark",
    name="Batch benchmark",
    formats=("png", "svg", "pdf"),
    width=640,
    height=480,
    vector_scatter_mode="compact_vector",
  )

  def render(
    sample: Mapping[str, str], path: Path, options: BatchPlotExportSpec
  ) -> None:
    sample_id = sample["id"]
    prepared_plot = prepared[sample_id]
    prepared_layers = layers[sample_id]
    if path.suffix == ".png":
      write_plot_png(
        path, prepared_plot, layers=prepared_layers,
        width=options.width, height=options.height, options=options,
      )
    elif path.suffix == ".svg":
      write_plot_svg(path, prepared_plot, layers=prepared_layers, options=options)
    elif path.suffix == ".pdf":
      write_plot_pdf(
        path, prepared_plot, layers=prepared_layers,
        width=options.width, height=options.height, options=options,
      )
    else:
      raise ValueError(path.suffix)

  def run(backend: ExecutionBackend) -> _RunResult:
    with tempfile.TemporaryDirectory(prefix=f"flowdesk-batch-{backend}-") as directory:
      output_dir = Path(directory)
      control = ExecutionControl(options=ExecutionOptions(
        backend=backend, max_workers=max_workers,
      ))
      started = time.perf_counter()
      report = run_batch_plot_export(
        spec,
        samples,
        output_dir,
        render,
        estimate_render_bytes=lambda: max(
          (len(x) + len(y)) * 8
          for sample_layers in layers.values()
          for x, y in sample_layers.values()
        ) * 4,
        execution_control=control,
      )
      elapsed = time.perf_counter() - started
      output_bytes = sum(
        path.stat().st_size
        for path in output_dir.iterdir()
        if path.is_file() and not path.name.endswith(".json")
      )
      return {
        "backend": backend,
        "elapsed_seconds": elapsed,
        "output_bytes": output_bytes,
        "status": report.status,
        "execution": report.execution_provenance,
      }

  serial = run("sequential")
  threaded = run("thread")
  return {
    "sample_count": sample_count,
    "event_count": event_count,
    "max_workers": max_workers,
    "seed": seed,
    "sequential": serial,
    "thread": threaded,
    "thread_speedup": (
      serial["elapsed_seconds"] / threaded["elapsed_seconds"]
      if threaded["elapsed_seconds"] else None
    ),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--samples", type=int, default=8)
  parser.add_argument("--events", type=int, default=5_000)
  parser.add_argument("--max-workers", type=int, default=2)
  parser.add_argument("--seed", type=int, default=1729)
  parser.add_argument("--output", type=Path)
  args = parser.parse_args()
  result = run_batch_plot_benchmark(
    sample_count=args.samples,
    event_count=args.events,
    max_workers=args.max_workers,
    seed=args.seed,
  )
  rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
  if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
  print(rendered, end="")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
