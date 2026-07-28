"""Deterministic benchmark and release-acceptance helpers for scatter export."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

import numpy as np

try:
  import resource
except ImportError:  # pragma: no cover - exercised on Windows
  resource = None  # type: ignore[assignment]

from flowdesk_core.models import BatchPlotExportSpec, PlotPresentationSpec, SourceStyleSpec
from flowdesk_core.plot_export import prepare_plot_export, write_plot_pdf, write_plot_svg
from flowdesk_core.plot_presentation import OverlaySourceResolution

BENCHMARK_COUNTS = (1_000, 5_000, 20_000, 100_000, 1_000_000)


@dataclass(frozen=True)
class ScatterBenchmarkMeasurement:
  count: int
  mode: str
  bytes_written: int
  elapsed_ms: float
  peak_rss_kib: int | None
  svg_use_count: int
  svg_path_count: int
  pdf_form_count: int
  pdf_image_count: int
  rendered_event_count: int
  layer_hash: str

  def to_mapping(self) -> dict[str, Any]:
    return asdict(self)


def deterministic_scatter_fixture(
  count: int, *, seed: int = 1729, profile: str = "mixed"
) -> tuple[dict[str, tuple[tuple[float, ...], tuple[float, ...]]], str]:
  """Create stable sparse/dense/overlap/multi-source points and an input hash."""
  if count < 1:
    raise ValueError("benchmark count must be positive")
  rng = np.random.default_rng(seed + count)
  if profile == "sparse":
    x, y = rng.random(count), rng.random(count)
  elif profile == "dense":
    x = np.clip(rng.normal(0.5, 0.025, count), 0.0, 1.0)
    y = np.clip(rng.normal(0.5, 0.025, count), 0.0, 1.0)
  elif profile == "overlap":
    x, y = np.full(count, 0.5), np.full(count, 0.5)
  elif profile == "mixed":
    x = np.clip(rng.normal(0.45, 0.18, count), 0.0, 1.0)
    y = np.clip(rng.normal(0.55, 0.16, count), 0.0, 1.0)
  else:
    raise ValueError(f"unknown benchmark profile {profile!r}")
  split = max(1, count // 20)
  layers = {
    "source-main": (tuple(float(value) for value in x[:-split]), tuple(float(value) for value in y[:-split])),
    "source-rare": (tuple(float(value) for value in x[-split:]), tuple(float(value) for value in y[-split:])),
  }
  canonical = json.dumps(layers, sort_keys=True, separators=(",", ":")).encode("utf-8")
  return layers, hashlib.sha256(canonical).hexdigest()


def _prepared_fixture() -> tuple[Any, PlotPresentationSpec]:
  source_ids = ("source-main", "source-rare")
  sources = tuple({
    "source_id": source_id, "sample_id": source_id, "population_id": "all_events",
    "display_name": source_id, "visible": True,
  } for source_id in source_ids)
  prepared = prepare_plot_export(
    "benchmark-view", "scatter", sources,
    tuple(OverlaySourceResolution(source_id, "compatible") for source_id in source_ids),
  )
  presentation = PlotPresentationSpec(source_styles=(
    SourceStyleSpec("source-main", color="#4c78a8", alpha=0.60, marker_size=1.5),
    SourceStyleSpec("source-rare", color="#e45756", alpha=0.35, marker_size=1.5),
  ))
  return prepared, presentation


def measure_scatter_mode(
  count: int, mode: str, *, profile: str = "mixed", hybrid_scatter_dpi: int = 96
) -> ScatterBenchmarkMeasurement:
  layers, layer_hash = deterministic_scatter_fixture(count, profile=profile)
  prepared, presentation = _prepared_fixture()
  options = BatchPlotExportSpec(
    id=f"benchmark-{mode}", name="benchmark", formats=("svg", "pdf"),
    width=320, height=240, vector_scatter_mode=mode, hybrid_scatter_dpi=hybrid_scatter_dpi,
  )
  with TemporaryDirectory(prefix="flowdesk-vector-benchmark-") as temporary:
    root = Path(temporary)
    svg_path, pdf_path = root / "plot.svg", root / "plot.pdf"
    started = time.perf_counter()
    write_plot_svg(svg_path, prepared, presentation, layers, options=options)
    write_plot_pdf(pdf_path, prepared, presentation, layers, options=options)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    svg_data, pdf_data = svg_path.read_bytes(), pdf_path.read_bytes()
  peak_rss_kib = (
    None if resource is None else int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
  )
  return ScatterBenchmarkMeasurement(
    count, mode, len(svg_data) + len(pdf_data), elapsed_ms, peak_rss_kib,
    svg_data.count(b"<use "), svg_data.count(b"<path "),
    pdf_data.count(b"/Subtype /Form"), pdf_data.count(b"/Subtype /Image"), count, layer_hash,
  )


def run_scatter_benchmark(
  counts: Sequence[int] = BENCHMARK_COUNTS, *, profile: str = "mixed", hybrid_scatter_dpi: int = 96
) -> dict[str, Any]:
  """Run all explicit modes and return a baseline without regression thresholds."""
  measurements = [
    measure_scatter_mode(int(count), mode, profile=profile, hybrid_scatter_dpi=hybrid_scatter_dpi)
    for count in counts for mode in ("full_vector", "compact_vector", "hybrid_raster")
  ]
  by_count: dict[str, list[dict[str, Any]]] = {}
  for measurement in measurements:
    by_count.setdefault(str(measurement.count), []).append(measurement.to_mapping())
  return {
    "algorithm_version": "vector_scatter_benchmark.v1", "profile": profile,
    "counts": [int(value) for value in counts], "thresholds": None,
    "measurements": by_count,
  }


def release_acceptance_invariants(
  measurements: Sequence[ScatterBenchmarkMeasurement],
) -> dict[str, Any]:
  """Check representation-only invariants shared by all three modes."""
  grouped: dict[int, list[ScatterBenchmarkMeasurement]] = {}
  for measurement in measurements:
    grouped.setdefault(measurement.count, []).append(measurement)
  failures: list[dict[str, Any]] = []
  for count, group in grouped.items():
    if len({item.layer_hash for item in group}) != 1:
      failures.append({"count": count, "code": "layer_hash_changed"})
    if {item.rendered_event_count for item in group} != {count}:
      failures.append({"count": count, "code": "rendered_event_count_changed"})
  return {"status": "failed" if failures else "ok", "failures": failures}
