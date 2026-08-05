"""Latest-wins asynchronous scheduler for compensation candidate previews."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from flowdesk_core.compensation_preview import (
  CompensationPreviewRequest,
  CompensationPreviewResult,
  prepare_compensation_preview,
)

PreviewExecutor = Callable[
  [CompensationPreviewRequest], CompensationPreviewResult
]


class _PreviewSignals(QObject):
  completed = Signal(object, object)
  failed = Signal(object, object)


class _PreviewRunnable(QRunnable):
  def __init__(
    self,
    request: CompensationPreviewRequest,
    executor: PreviewExecutor,
    signals: _PreviewSignals,
  ) -> None:
    super().__init__()
    self.setAutoDelete(True)
    self.request = request
    self.executor = executor
    self.signals = signals

  def run(self) -> None:
    try:
      result = self.executor(self.request)
    except Exception as exc:  # pragma: no cover - delivered through Qt signal
      self.signals.failed.emit(self.request, exc)
    else:
      self.signals.completed.emit(self.request, result)


class CompensationPreviewScheduler(QObject):
  """Run one immutable candidate preview at a time and keep only the latest pending one."""

  preview_ready = Signal(object, object)
  preview_failed = Signal(object, object)

  def __init__(
    self,
    parent: QObject | None = None,
    *,
    debounce_ms: int = 75,
    executor: PreviewExecutor | None = None,
  ) -> None:
    super().__init__(parent)
    if debounce_ms < 0:
      raise ValueError("compensation preview debounce must be non-negative")
    self._executor = executor or prepare_compensation_preview
    self._timer = QTimer(self)
    self._timer.setSingleShot(True)
    self._timer.setInterval(debounce_ms)
    self._timer.timeout.connect(self._start_pending)
    self._pool = QThreadPool(self)
    self._pool.setMaxThreadCount(1)
    self._pending: CompensationPreviewRequest | None = None
    self._active: _PreviewRunnable | None = None
    self._closed = False

  @property
  def active(self) -> bool:
    """Whether a preview job is currently running."""
    return self._active is not None

  @property
  def pending(self) -> CompensationPreviewRequest | None:
    """Return the latest pending request, if any."""
    return self._pending

  def schedule(self, request: CompensationPreviewRequest) -> None:
    if self._closed:
      raise RuntimeError("compensation preview scheduler is closed")
    self._pending = request
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

  def _start_pending(self) -> None:
    if self._closed or self._active is not None or self._pending is None:
      return
    request = self._pending
    self._pending = None
    signals = _PreviewSignals(self)
    runnable = _PreviewRunnable(request, self._executor, signals)
    signals.completed.connect(self._on_completed)
    signals.failed.connect(self._on_failed)
    self._active = runnable
    self._pool.start(runnable)

  def _on_completed(
    self,
    request: CompensationPreviewRequest,
    result: CompensationPreviewResult,
  ) -> None:
    self._active = None
    if not self._closed:
      self.preview_ready.emit(request, result)
    self._start_pending()

  def _on_failed(
    self, request: CompensationPreviewRequest, error: Exception
  ) -> None:
    self._active = None
    if not self._closed:
      self.preview_failed.emit(request, error)
    self._start_pending()


__all__ = ["CompensationPreviewScheduler"]
