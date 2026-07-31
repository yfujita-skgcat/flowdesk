"""Debounced latest-wins scheduling for canonical processed display requests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.processed_display import (
  ProcessedDisplayRequest,
  ProcessedDisplayResult,
)

DisplayExecutor = Callable[
  [Mapping[str, Any], ProcessedDisplayRequest], ProcessedDisplayResult
]


class _DisplaySignals(QObject):
  completed = Signal(object)
  failed = Signal(object, object)


class _DisplayRunnable(QRunnable):
  def __init__(
    self,
    project: Mapping[str, Any],
    request: ProcessedDisplayRequest,
    executor: DisplayExecutor,
    signals: _DisplaySignals,
  ) -> None:
    super().__init__()
    self.setAutoDelete(True)
    self.project = project
    self.request = request
    self.executor = executor
    # QObject lifetime/affinity belongs to the scheduler's GUI thread.  The
    # QRunnable itself is auto-deleted by QThreadPool on a worker thread.
    self.signals = signals

  def run(self) -> None:
    try:
      result = self.executor(self.project, self.request)
    except Exception as exc:  # pragma: no cover - delivered through Qt signal
      self.signals.failed.emit(self.request, exc)
    else:
      self.signals.completed.emit(result)


class ProcessedDisplayScheduler(QObject):
  """Run immutable core display work off the GUI thread with coalescing."""

  display_ready = Signal(object)
  display_failed = Signal(object, object)

  def __init__(
    self,
    parent: QObject | None = None,
    *,
    debounce_ms: int = 75,
    executor: DisplayExecutor | None = None,
  ) -> None:
    super().__init__(parent)
    self._executor = executor or self._run_display
    self._default_runner: PipelineRunner | None = None
    self._default_runner_project_key: str | None = None
    self._timer = QTimer(self)
    self._timer.setSingleShot(True)
    self._timer.setInterval(debounce_ms)
    self._timer.timeout.connect(self._start_pending)
    self._pool = QThreadPool(self)
    self._pool.setMaxThreadCount(1)
    self._pending: tuple[Mapping[str, Any], ProcessedDisplayRequest] | None = None
    self._active: _DisplayRunnable | None = None
    self._closed = False

  def schedule(
    self, project: Mapping[str, Any], request: ProcessedDisplayRequest
  ) -> None:
    if self._closed:
      raise RuntimeError("processed display scheduler is closed")
    self._pending = (deepcopy(dict(project)), request)
    self._timer.start()

  def cancel_pending(self) -> None:
    self._timer.stop()
    self._pending = None

  def shutdown(self) -> None:
    if self._closed:
      return
    self._closed = True
    self.cancel_pending()
    self._pool.waitForDone()
    self._active = None
    self._default_runner = None
    self._default_runner_project_key = None

  def _start_pending(self) -> None:
    if self._closed or self._active is not None or self._pending is None:
      return
    project, request = self._pending
    self._pending = None
    signals = _DisplaySignals(self)
    runnable = _DisplayRunnable(project, request, self._executor, signals)
    runnable.signals.completed.connect(self._on_completed)
    runnable.signals.failed.connect(self._on_failed)
    self._active = runnable
    self._pool.start(runnable)

  def _on_completed(self, result: ProcessedDisplayResult) -> None:
    self._active = None
    if not self._closed:
      self.display_ready.emit(result)
    self._start_pending()

  def _on_failed(self, request: ProcessedDisplayRequest, error: Exception) -> None:
    self._active = None
    if not self._closed:
      self.display_failed.emit(request, error)
    self._start_pending()

  def _run_display(
    self,
    project: Mapping[str, Any], request: ProcessedDisplayRequest
  ) -> ProcessedDisplayResult:
    project_key = hashlib.sha256(
      json.dumps(project, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    if project_key != self._default_runner_project_key:
      self._default_runner = PipelineRunner(project)
      self._default_runner_project_key = project_key
    assert self._default_runner is not None
    return self._default_runner.prepare_display_sample(request)
