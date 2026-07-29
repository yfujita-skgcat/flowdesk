"""Contracts for Qt-independent runtime execution controls."""

from __future__ import annotations

import importlib

import pytest

from flowdesk_core.execution_control import (
  CancellationToken,
  ExecutionCancelled,
  ExecutionControl,
  ExecutionOptions,
  ProgressEvent,
  numeric_library_inner_thread_count,
  resolve_execution_workers,
)


def test_execution_options_default_to_compatible_sequential_execution() -> None:
  options = ExecutionOptions()

  assert options.backend == "sequential"
  assert options.max_workers == 1
  assert options.memory_budget_bytes is None


def test_sequential_options_preserve_requested_worker_provenance() -> None:
  options = ExecutionOptions(max_workers=4)

  assert options.backend == "sequential"
  assert options.max_workers == 4


@pytest.mark.parametrize(
  ("kwargs", "message"),
  [
    ({"backend": "process"}, "backend"),
    ({"max_workers": 0}, "max_workers"),
    ({"memory_budget_bytes": 0}, "memory_budget_bytes"),
  ],
)
def test_execution_options_reject_invalid_runtime_values(
  kwargs: dict[str, object], message: str
) -> None:
  with pytest.raises(ValueError, match=message):
    ExecutionOptions(**kwargs)


def test_progress_events_are_monotonic_per_operation() -> None:
  received: list[ProgressEvent] = []
  control = ExecutionControl(progress_sink=received.append)

  first = ProgressEvent("run-1", "pipeline", "planning", 0, 2)
  second = ProgressEvent("run-1", "pipeline", "sample_gating", 1, 2)
  control.emit_progress(first)
  control.emit_progress(second)

  assert received == [first, second]
  with pytest.raises(ValueError, match="monotonic"):
    control.emit_progress(
      ProgressEvent("run-1", "pipeline", "sample_statistics", 0, 2)
    )
  with pytest.raises(ValueError, match="total_units"):
    control.emit_progress(
      ProgressEvent("run-1", "pipeline", "finalizing", 3, 2)
    )


def test_progress_callback_failure_is_not_silenced() -> None:
  def fail(_: ProgressEvent) -> None:
    raise RuntimeError("adapter failure")

  control = ExecutionControl(progress_sink=fail)
  with pytest.raises(RuntimeError, match="adapter failure"):
    control.emit_progress(ProgressEvent("run-1", "pipeline", "planning", 0, 1))


def test_cancellation_is_cooperative_and_typed() -> None:
  token = CancellationToken()
  token.raise_if_cancelled()
  token.cancel()

  assert token.is_cancelled()
  with pytest.raises(ExecutionCancelled):
    token.raise_if_cancelled()


def test_execution_control_has_no_qt_dependency() -> None:
  module = importlib.import_module("flowdesk_core.execution_control")

  assert not any(name.startswith(("PySide6", "pyqtgraph")) for name in module.__dict__)


def test_thread_worker_resolution_is_bounded_by_all_runtime_limits() -> None:
  resolution = resolve_execution_workers(
    ExecutionOptions(
      backend="thread", max_workers=8, memory_budget_bytes=500,
    ),
    selected_sample_count=3,
    estimated_sample_bytes=200,
    available_cpu_count=4,
    numeric_inner_threads=2,
  )

  assert resolution.backend == "thread"
  assert resolution.effective_max_workers == 2
  assert set(resolution.limiting_factors) >= {
    "memory_budget", "numeric_inner_threads",
  }
  assert resolution.to_mapping()["estimated_sample_bytes"] == 200


def test_sequential_worker_resolution_remains_one_even_when_requested_higher() -> None:
  resolution = resolve_execution_workers(
    ExecutionOptions(max_workers=8, memory_budget_bytes=500),
    selected_sample_count=4,
    estimated_sample_bytes=100,
    available_cpu_count=16,
    numeric_inner_threads=1,
  )

  assert resolution.effective_max_workers == 1
  assert resolution.limiting_factors == ("backend_sequential",)


def test_numeric_library_thread_detection_uses_largest_valid_setting() -> None:
  assert numeric_library_inner_thread_count({
    "OMP_NUM_THREADS": "2",
    "OPENBLAS_NUM_THREADS": "invalid",
    "MKL_NUM_THREADS": "4",
    "NUMEXPR_NUM_THREADS": "0",
  }) == 4
