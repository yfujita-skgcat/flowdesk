"""Deterministic pipeline benchmark fixture contracts."""

from __future__ import annotations

from flowdesk_core.execution_control import ExecutionOptions
from flowdesk_core.pipeline_benchmark import (
  PipelineBenchmarkProfile,
  deterministic_pipeline_samples,
  pipeline_input_fingerprint,
  run_pipeline_benchmark,
)


def test_pipeline_fixture_is_deterministic_and_raw_events_are_immutable() -> None:
  profile = PipelineBenchmarkProfile("test", events_per_sample=24, sample_count=2)
  first = deterministic_pipeline_samples(profile, seed=7)
  second = deterministic_pipeline_samples(profile, seed=7)

  assert pipeline_input_fingerprint(first) == pipeline_input_fingerprint(second)
  assert all(not sample.events.flags.writeable for sample in first)
  assert [sample.event_count for sample in first] == [24, 24]


def test_pipeline_benchmark_records_stage_boundaries_without_thresholds() -> None:
  profile = PipelineBenchmarkProfile("test", events_per_sample=24, sample_count=2)

  result = run_pipeline_benchmark(
    profile, repeats=2, seed=7, options=ExecutionOptions()
  )

  assert result["thresholds"] is None
  assert result["fixture"]["generated_event_data_persisted"] is False
  assert result["fixture"]["expected_root_counts"] == {
    "sample-1": 24,
    "sample-2": 24,
  }
  assert len(result["stage_boundaries_ms"]["canonical_pipeline"]) == 2
  assert result["execution"]["effective_workers"] == 1
  assert len(set(result["report_hashes"])) == 1
