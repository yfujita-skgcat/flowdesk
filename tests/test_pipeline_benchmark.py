"""Deterministic pipeline benchmark fixture contracts."""

from __future__ import annotations

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_control import ExecutionControl, ExecutionOptions
from flowdesk_core.pipeline_benchmark import (
  PipelineBenchmarkProfile,
  deterministic_pipeline_samples,
  pipeline_input_fingerprint,
  pipeline_scientific_report_hash,
  run_pipeline_benchmark,
)
from flowdesk_core.pipeline_runner import PipelineRunner


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
  assert result["execution"]["effective_max_workers"] == 1
  assert len(set(result["report_hashes"])) == 1


def test_pipeline_benchmark_records_resolved_thread_provenance() -> None:
  profile = PipelineBenchmarkProfile("test", events_per_sample=24, sample_count=2)

  result = run_pipeline_benchmark(
    profile,
    options=ExecutionOptions(backend="thread", max_workers=2),
  )

  assert result["execution"]["backend"] == "thread"
  assert result["execution"]["requested_max_workers"] == 2
  assert 1 <= result["execution"]["effective_max_workers"] <= 2


def test_pipeline_scientific_hash_excludes_runtime_worker_provenance() -> None:
  profile = PipelineBenchmarkProfile("test", events_per_sample=24, sample_count=2)
  samples = deterministic_pipeline_samples(profile, seed=7)
  project = {
    "project_id": "benchmark-test",
    "samples": [{"id": sample.sample_id} for sample in samples],
    "execution_profiles": [{"id": "default", "sample_selector": "all"}],
  }
  sequential = PipelineRunner(project).run_samples(ExecutionContext(), samples)
  threaded = PipelineRunner(project).run_samples(
    ExecutionContext(execution_control=ExecutionControl(options=ExecutionOptions(
      backend="thread", max_workers=2,
    ))),
    samples,
  )

  assert pipeline_scientific_report_hash(sequential) == pipeline_scientific_report_hash(threaded)
