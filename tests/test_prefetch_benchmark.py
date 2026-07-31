"""Acquisition benchmark contract for the large-FCS prefetch path."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _benchmark_module():
  path = Path(__file__).parents[1] / "tools" / "benchmark_prefetch.py"
  spec = importlib.util.spec_from_file_location("flowdesk_prefetch_benchmark", path)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_prefetch_benchmark_preserves_raw_events_and_counts() -> None:
  result = _benchmark_module().run_prefetch_benchmark(events=1_000, seed=7)
  assert result["event_count_match"] is True
  assert result["raw_hash_match"] is True
  assert result["events"] == 1_000
  assert result["synchronous_seconds"] >= 0
  assert result["asynchronous_seconds"] >= 0
