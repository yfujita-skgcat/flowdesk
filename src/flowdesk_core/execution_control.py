"""Qt-independent runtime controls for long-running Flowdesk operations.

These controls deliberately describe execution only.  They are not part of a
persisted project definition and must never change the scientific pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import Literal

ExecutionBackend = Literal["sequential", "thread"]
ProgressSink = Callable[["ProgressEvent"], None]


class ExecutionCancelled(Exception):
  """Raised at a cooperative cancellation checkpoint.

  Callers must not publish an incomplete authoritative result after receiving
  this outcome.  A later increment will define the pipeline and export
  checkpoints that call :meth:`CancellationToken.raise_if_cancelled`.
  """


@dataclass(frozen=True)
class ExecutionOptions:
  """Non-persisted executor and memory policy for one operation."""

  backend: ExecutionBackend = "sequential"
  max_workers: int = 1
  memory_budget_bytes: int | None = None

  def __post_init__(self) -> None:
    if self.backend not in ("sequential", "thread"):
      raise ValueError("backend must be 'sequential' or 'thread'")
    if self.max_workers < 1:
      raise ValueError("max_workers must be positive")
    if self.memory_budget_bytes is not None and self.memory_budget_bytes < 1:
      raise ValueError("memory_budget_bytes must be positive when set")


class CancellationToken:
  """Thread-safe cooperative cancellation request owned by one operation."""

  def __init__(self) -> None:
    self._event = Event()

  def cancel(self) -> None:
    """Request cancellation without forcefully interrupting active work."""
    self._event.set()

  def is_cancelled(self) -> bool:
    """Return whether cancellation has been requested."""
    return self._event.is_set()

  def raise_if_cancelled(self) -> None:
    """Raise the typed cancellation outcome at a safe checkpoint."""
    if self.is_cancelled():
      raise ExecutionCancelled("execution cancelled")


@dataclass(frozen=True)
class ProgressEvent:
  """An immutable, adapter-neutral progress update."""

  operation_id: str
  operation: Literal["pipeline", "batch_plot_export", "display_prefetch"]
  phase: str
  completed_units: int
  total_units: int
  sample_id: str | None = None
  output_path: str | None = None
  message: str | None = None

  def __post_init__(self) -> None:
    if not self.operation_id:
      raise ValueError("operation_id must not be empty")
    if not self.phase:
      raise ValueError("phase must not be empty")
    if self.completed_units < 0:
      raise ValueError("completed_units must not be negative")
    if self.total_units < 0:
      raise ValueError("total_units must not be negative")
    if self.completed_units > self.total_units:
      raise ValueError("completed_units must not exceed total_units")


@dataclass
class ExecutionControl:
  """One operation's optional execution policy, cancellation, and progress."""

  options: ExecutionOptions = field(default_factory=ExecutionOptions)
  cancellation_token: CancellationToken = field(default_factory=CancellationToken)
  progress_sink: ProgressSink | None = None
  _last_completed_by_operation: dict[str, int] = field(
    default_factory=dict, init=False, repr=False
  )
  _total_by_operation: dict[str, int] = field(
    default_factory=dict, init=False, repr=False
  )

  def emit_progress(self, event: ProgressEvent) -> None:
    """Validate and deliver an ordered event on the coordinator thread.

    Callback errors are intentionally propagated; hiding a broken GUI/CLI
    adapter as a successful scientific run would make operation state unclear.
    """
    previous = self._last_completed_by_operation.get(event.operation_id)
    if previous is not None and event.completed_units < previous:
      raise ValueError("progress completed_units must be monotonic")
    previous_total = self._total_by_operation.get(event.operation_id)
    if previous_total is not None and event.total_units != previous_total:
      raise ValueError("progress total_units must remain stable")
    self._last_completed_by_operation[event.operation_id] = event.completed_units
    self._total_by_operation[event.operation_id] = event.total_units
    if self.progress_sink is not None:
      self.progress_sink(event)
