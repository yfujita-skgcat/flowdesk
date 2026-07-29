"""Qt-independent runtime controls for long-running Flowdesk operations.

These controls deliberately describe execution only.  They are not part of a
persisted project definition and must never change the scientific pipeline.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import Literal

from flowdesk_core.errors import FlowdeskError

ExecutionBackend = Literal["sequential", "thread"]
ProgressSink = Callable[["ProgressEvent"], None]


class ExecutionCancelled(FlowdeskError):
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


@dataclass(frozen=True)
class ExecutionResolution:
  """Resolved bounded-worker policy recorded for one runtime operation.

  This is runtime provenance, not a persisted project setting.  ``estimated`` is
  a conservative worst selected-sample in-flight estimate, so a memory limit
  bounds concurrent sample work rather than attempting to consume every CPU.
  """

  backend: ExecutionBackend
  requested_max_workers: int
  effective_max_workers: int
  selected_sample_count: int
  available_cpu_count: int
  memory_budget_bytes: int | None
  estimated_sample_bytes: int
  numeric_inner_threads: int
  limiting_factors: tuple[str, ...] = ()

  def to_mapping(self) -> dict[str, object]:
    """Return stable report-ready execution provenance."""
    return {
      "backend": self.backend,
      "requested_max_workers": self.requested_max_workers,
      "effective_max_workers": self.effective_max_workers,
      "selected_sample_count": self.selected_sample_count,
      "available_cpu_count": self.available_cpu_count,
      "memory_budget_bytes": self.memory_budget_bytes,
      "estimated_sample_bytes": self.estimated_sample_bytes,
      "numeric_inner_threads": self.numeric_inner_threads,
      "limiting_factors": list(self.limiting_factors),
    }


_NUMERIC_THREAD_ENVIRONMENT_KEYS = (
  "OMP_NUM_THREADS",
  "OPENBLAS_NUM_THREADS",
  "MKL_NUM_THREADS",
  "NUMEXPR_NUM_THREADS",
)


def numeric_library_inner_thread_count(
  environment: dict[str, str] | None = None,
) -> int:
  """Return a conservative native numeric-library thread count.

  Unset, malformed, and non-positive values mean the library has not declared
  an outer-thread-relevant limit, so the runtime uses one for this policy.
  """
  values = environment if environment is not None else os.environ
  counts: list[int] = []
  for key in _NUMERIC_THREAD_ENVIRONMENT_KEYS:
    raw = values.get(key)
    if raw is None:
      continue
    try:
      count = int(raw)
    except ValueError:
      continue
    if count > 0:
      counts.append(count)
  return max(counts, default=1)


def resolve_execution_workers(
  options: ExecutionOptions,
  *,
  selected_sample_count: int,
  estimated_sample_bytes: int,
  available_cpu_count: int | None = None,
  numeric_inner_threads: int | None = None,
) -> ExecutionResolution:
  """Resolve a bounded worker count without assuming all CPUs are usable."""
  if selected_sample_count < 0:
    raise ValueError("selected_sample_count must not be negative")
  if estimated_sample_bytes < 0:
    raise ValueError("estimated_sample_bytes must not be negative")
  cpu_count = max(1, available_cpu_count or os.cpu_count() or 1)
  inner_threads = max(
    1,
    numeric_inner_threads
    if numeric_inner_threads is not None else numeric_library_inner_thread_count(),
  )
  sample_bound = max(1, selected_sample_count)
  factors: list[str] = []
  if options.backend == "sequential":
    factors.append("backend_sequential")
    return ExecutionResolution(
      backend=options.backend,
      requested_max_workers=options.max_workers,
      effective_max_workers=1,
      selected_sample_count=selected_sample_count,
      available_cpu_count=cpu_count,
      memory_budget_bytes=options.memory_budget_bytes,
      estimated_sample_bytes=estimated_sample_bytes,
      numeric_inner_threads=inner_threads,
      limiting_factors=tuple(factors),
    )

  limits = [options.max_workers, sample_bound, cpu_count]
  if options.max_workers <= min(sample_bound, cpu_count):
    factors.append("requested_max_workers")
  if sample_bound <= min(options.max_workers, cpu_count):
    factors.append("selected_sample_count")
  if cpu_count <= min(options.max_workers, sample_bound):
    factors.append("available_cpu_count")
  if inner_threads > 1:
    outer_thread_limit = max(1, cpu_count // inner_threads)
    limits.append(outer_thread_limit)
    if outer_thread_limit <= min(limits):
      factors.append("numeric_inner_threads")
  if options.memory_budget_bytes is not None and estimated_sample_bytes > 0:
    memory_limit = max(1, options.memory_budget_bytes // estimated_sample_bytes)
    limits.append(memory_limit)
    if memory_limit <= min(limits):
      factors.append("memory_budget")
  effective = max(1, min(limits))
  return ExecutionResolution(
    backend=options.backend,
    requested_max_workers=options.max_workers,
    effective_max_workers=effective,
    selected_sample_count=selected_sample_count,
    available_cpu_count=cpu_count,
    memory_budget_bytes=options.memory_budget_bytes,
    estimated_sample_bytes=estimated_sample_bytes,
    numeric_inner_threads=inner_threads,
    limiting_factors=tuple(dict.fromkeys(factors)),
  )


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
  _operation_sequence: int = field(default=0, init=False, repr=False)

  def begin_operation(self, operation: str) -> str:
    """Return a fresh coordinator-owned identifier for one runtime operation."""
    if not operation:
      raise ValueError("operation must not be empty")
    self._operation_sequence += 1
    return f"{operation}:{self._operation_sequence}"

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
