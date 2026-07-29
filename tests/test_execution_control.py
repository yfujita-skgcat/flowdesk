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
