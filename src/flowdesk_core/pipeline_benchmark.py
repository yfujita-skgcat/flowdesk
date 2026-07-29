"""Deterministic, opt-in baseline measurement for canonical pipelines.

This module creates synthetic immutable :class:`SampleData` only at runtime.
It does not write generated events or FCS files into the repository. Pipeline
execution policy is explicit so sequential and bounded-thread measurements can
be compared without claiming a display or export speedup.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np

try:
  import resource
except ImportError:  # pragma: no cover - Windows does not provide resource.
  resource = None  # type: ignore[assignment]

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import ChannelSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.sample import SampleData


@dataclass(frozen=True)
class PipelineBenchmarkProfile:
  """Deterministic synthetic workload shape, never persisted as event data."""

  name: str
  events_per_sample: int
  sample_count: int
  channel_count: int = 4

  def __post_init__(self) -> None:
    if self.events_per_sample < 1:
      raise ValueError("events_per_sample must be positive")
    if self.sample_count < 1:
      raise ValueError("sample_count must be positive")
    if self.channel_count < 1:
      raise ValueError("channel_count must be positive")


PIPELINE_BENCHMARK_PROFILES: dict[str, PipelineBenchmarkProfile] = {
  "small": PipelineBenchmarkProfile("small", 100_000, 8),
  "medium": PipelineBenchmarkProfile("medium", 1_000_000, 8),
  "large": PipelineBenchmarkProfile("large", 10_000_000, 2),
}


def deterministic_pipeline_samples(
  profile: PipelineBenchmarkProfile, *, seed: int = 1729
) -> tuple[SampleData, ...]:
  """Return immutable samples with a stable input fingerprint.

  Every sample contains the same number of finite events, so the expected
  fallback root-population count is ``events_per_sample``.  The fixture
  includes a broad and a compact cluster to exercise normal numeric arrays
  without inventing a biological gate or result policy.
  """
  channels = tuple(
    ChannelSpec(id=f"channel_{index + 1}", name=f"Channel {index + 1}")
    for index in range(profile.channel_count)
  )
  samples: list[SampleData] = []
  for sample_index in range(profile.sample_count):
    rng = np.random.default_rng(seed + sample_index)
    broad = rng.lognormal(
      mean=4.0 + sample_index * 0.01,
      sigma=0.55,
      size=(profile.events_per_sample, profile.channel_count),
    )
    compact_count = max(1, profile.events_per_sample // 10)
    broad[:compact_count] = rng.lognormal(
      mean=6.0 + sample_index * 0.01,
      sigma=0.12,
      size=(compact_count, profile.channel_count),
    )
    samples.append(SampleData(f"sample-{sample_index + 1}", broad, channels))
  return tuple(samples)


def pipeline_benchmark_project(samples: Sequence[SampleData]) -> dict[str, Any]:
  """Return the minimal canonical project for the supplied sample IDs."""
  return {
    "project_id": "pipeline-benchmark",
    "pipeline_version": "benchmark.v1",
    "samples": [{"id": sample.sample_id} for sample in samples],
    "execution_profiles": [{
      "id": "default",
      "sample_selector": "all",
      "gating_strategy_id": None,
    }],
  }


def pipeline_input_fingerprint(samples: Sequence[SampleData]) -> str:
  """Hash event bytes and channel identity without serializing generated data."""
  digest = hashlib.sha256()
  for sample in samples:
    digest.update(sample.sample_id.encode("utf-8"))
    digest.update(np.ascontiguousarray(sample.events).tobytes())
    for channel in sample.channels:
      digest.update(channel.id.encode("utf-8"))
  return digest.hexdigest()


def _peak_rss_kib() -> int | None:
  if resource is None:
    return None
  return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def pipeline_scientific_report_hash(report: ExecutionReport) -> str:
  """Hash report scientific content without runtime executor provenance."""
  scientific_report = replace(report, execution_provenance={})
  return hashlib.sha256(repr(scientific_report).encode("utf-8")).hexdigest()


def benchmark_environment() -> dict[str, Any]:
  """Return non-invasive environment provenance without importing Qt."""
  try:
    qt_version: str | None = importlib.metadata.version("PySide6")
  except importlib.metadata.PackageNotFoundError:
    qt_version = None
  return {
    "platform": platform.platform(),
    "python": sys.version,
    "numpy": np.__version__,
    "pyside6": qt_version,
    "logical_cpu_count": os.cpu_count(),
  }


def run_pipeline_benchmark(
  profile: PipelineBenchmarkProfile,
  *,
  repeats: int = 1,
  seed: int = 1729,
  options: ExecutionOptions | None = None,
) -> dict[str, Any]:
  """Measure fixture construction and whole canonical pipeline separately.

  The resulting report carries the resolved worker/memory policy.  This
  benchmark measures canonical analysis only; it does not claim a display or
  rendering speedup.
  """
  if repeats < 1:
    raise ValueError("repeats must be positive")
  resolved_options = options or ExecutionOptions()
  started = time.perf_counter()
  samples = deterministic_pipeline_samples(profile, seed=seed)
  fixture_ms = (time.perf_counter() - started) * 1000.0
  project = pipeline_benchmark_project(samples)
  input_fingerprint = pipeline_input_fingerprint(samples)
  expected_root_counts = {
    sample.sample_id: profile.events_per_sample for sample in samples
  }
  elapsed_ms: list[float] = []
  report_hashes: list[str] = []
  execution_provenance: dict[str, Any] | None = None
  for _ in range(repeats):
    started = time.perf_counter()
    report = PipelineRunner(project).run_samples(
      ExecutionContext(
        execution_profile_id="default",
        execution_control=ExecutionControl(options=resolved_options),
      ),
      samples,
    )
    elapsed_ms.append((time.perf_counter() - started) * 1000.0)
    root_counts = {
      result.sample_id: result.event_count
      for result in report.population_results
      if result.population_id == "all_events"
    }
    if root_counts != expected_root_counts:
      raise RuntimeError("benchmark root population counts changed")
    if execution_provenance is None:
      execution_provenance = dict(report.execution_provenance)
    elif report.execution_provenance != execution_provenance:
      raise RuntimeError("benchmark execution resolution changed between repeats")
    report_hashes.append(pipeline_scientific_report_hash(report))
  return {
    "algorithm_version": "pipeline_benchmark.v1",
    "thresholds": None,
    "profile": asdict(profile),
    "fixture": {
      "seed": seed,
      "input_fingerprint": input_fingerprint,
      "expected_root_counts": expected_root_counts,
      "generated_event_data_persisted": False,
    },
    "environment": benchmark_environment(),
    "execution": execution_provenance or {},
    "stage_boundaries_ms": {
      "fixture_construction": fixture_ms,
      "canonical_pipeline": elapsed_ms,
      "canonical_pipeline_median": float(np.median(np.asarray(elapsed_ms))),
    },
    "peak_rss_kib": _peak_rss_kib(),
    "report_hashes": report_hashes,
  }
