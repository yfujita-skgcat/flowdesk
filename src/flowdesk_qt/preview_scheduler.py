"""Debounced, latest-wins scheduling for current-sample previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.preview import PreviewReport, PreviewRequest

PreviewExecutor = Callable[[Mapping[str, Any], PreviewRequest], PreviewReport]


class _PreviewSignals(QObject):
  completed = Signal(object)
  failed = Signal(object, object)


class _PreviewRunnable(QRunnable):
  """Run one immutable preview snapshot without touching the GUI."""

  def __init__(
    self,
    project: Mapping[str, Any],
    request: PreviewRequest,
    executor: PreviewExecutor,
  ) -> None:
    super().__init__()
    self.setAutoDelete(True)
    self.project = project
    self.request = request
    self.executor = executor
    self.signals = _PreviewSignals()

  def run(self) -> None:
    try:
      report = self.executor(self.project, self.request)
    except Exception as exc:  # pragma: no cover - exercised through signal test
      self.signals.failed.emit(self.request, exc)
    else:
      self.signals.completed.emit(report)


class PreviewScheduler(QObject):
  """One-worker debounce/coalescing scheduler for current-sample previews."""

  preview_ready = Signal(object)
  preview_failed = Signal(object, object)

  def __init__(
    self,
    parent: QObject | None = None,
    *,
    debounce_ms: int = 300,
    executor: PreviewExecutor | None = None,
  ) -> None:
    super().__init__(parent)
    if not 0 <= debounce_ms <= 10_000:
      raise ValueError("preview debounce must be between 0 and 10000 ms")
    self._executor = executor or self._run_preview
    self._timer = QTimer(self)
    self._timer.setSingleShot(True)
    self._timer.setInterval(debounce_ms)
    self._timer.timeout.connect(self._start_pending)
    self._pool = QThreadPool(self)
    self._pool.setMaxThreadCount(1)
    self._pending: tuple[Mapping[str, Any], PreviewRequest] | None = None
    self._active: _PreviewRunnable | None = None
    self._latest_revision: int | None = None
    self._closed = False
    self._paused = False

  def schedule(
    self,
    project: Mapping[str, Any],
    request: PreviewRequest,
  ) -> None:
    """Replace pending work and start it after the debounce interval."""
    if self._closed:
      raise RuntimeError("preview scheduler is closed")
    self._latest_revision = (
      request.revision
      if self._latest_revision is None
      else max(self._latest_revision, request.revision)
    )
    # The runner also snapshots its input, but copying at submission makes the
    # worker contract explicit: it never reads a live GUI project dictionary.
    self._pending = (deepcopy(dict(project)), request)
    self._timer.start()

  def cancel_pending(self) -> None:
    """Cancel only work that has not started."""
    self._timer.stop()
    self._pending = None

  def suspend(self) -> None:
    """Pause new preview work while an authoritative batch is running."""
    self._paused = True
    self.cancel_pending()

  def resume(self) -> None:
    """Resume preview scheduling after the authoritative batch completes."""
    self._paused = False
    if self._pending is not None:
      self._timer.start()

  def shutdown(self) -> None:
    """Stop scheduling and wait for the one running job to finish safely."""
    if self._closed:
      return
    self._closed = True
    self.cancel_pending()
    self._pool.waitForDone()
    self._active = None

  def is_running(self) -> bool:
    """Return whether a preview job is currently executing."""
    return self._active is not None

  def has_pending(self) -> bool:
    """Return whether a debounced request is waiting to start."""
    return self._pending is not None

  def _start_pending(self) -> None:
    if (
      self._closed
      or self._paused
      or self._active is not None
      or self._pending is None
    ):
      return
    project, request = self._pending
    self._pending = None
    runnable = _PreviewRunnable(project, request, self._executor)
    runnable.signals.completed.connect(self._on_completed)
    runnable.signals.failed.connect(self._on_failed)
    self._active = runnable
    self._pool.start(runnable)

  def _on_completed(self, report: PreviewReport) -> None:
    self._active = None
    if self._closed:
      return
    if report.revision == self._latest_revision:
      self.preview_ready.emit(report)
    self._start_pending()

  def _on_failed(self, request: PreviewRequest, error: Exception) -> None:
    self._active = None
    if self._closed:
      return
    if request.revision == self._latest_revision:
      self.preview_failed.emit(request, error)
    self._start_pending()

  @staticmethod
  def _run_preview(
    project: Mapping[str, Any], request: PreviewRequest
  ) -> PreviewReport:
    return PipelineRunner(project).preview_sample(request)
