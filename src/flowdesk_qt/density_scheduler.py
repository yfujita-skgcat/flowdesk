"""Latest-wins scheduling for renderer-neutral density colour calculation.

The worker in this module owns only NumPy arrays and the core density
estimator.  It never creates or mutates Qt/pyqtgraph objects.  The GUI thread
receives an immutable result and is responsible for applying brushes to the
existing scatter item.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from flowdesk_core.density_colors import DensityColorResult, estimate_density_colors


@dataclass(frozen=True)
class DensityColorRequest:
  """Immutable display-only input for one density field calculation."""

  key: tuple[object, ...]
  input_x: NDArray[np.float64]
  input_y: NDArray[np.float64]
  query_x: NDArray[np.float64]
  query_y: NDArray[np.float64]
  bounds: tuple[float, float, float, float]
  logical_size: tuple[int, int] = (512, 512)


@dataclass(frozen=True)
class DensityColorResponse:
  """A density result tagged with the semantic request key."""

  key: tuple[object, ...]
  result: DensityColorResult


DensityExecutor = Callable[[DensityColorRequest], DensityColorResult]


class _DensitySignals(QObject):
  completed = Signal(object)
  failed = Signal(object, object)


class _DensityRunnable(QRunnable):
  def __init__(
    self,
    request: DensityColorRequest,
    executor: DensityExecutor,
    signals: _DensitySignals,
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
      self.signals.completed.emit(
        DensityColorResponse(self.request.key, result)
      )


class DensityColorScheduler(QObject):
  """Run one density calculation at a time and keep only the newest pending one."""

  density_ready = Signal(object)
  density_failed = Signal(object, object)

  def __init__(
    self,
    parent: QObject | None = None,
    *,
    debounce_ms: int = 0,
    executor: DensityExecutor | None = None,
  ) -> None:
    super().__init__(parent)
    if not 0 <= debounce_ms <= 10_000:
      raise ValueError("density debounce must be between 0 and 10000 ms")
    self._executor = executor or self._run_density
    self._timer = QTimer(self)
    self._timer.setSingleShot(True)
    self._timer.setInterval(debounce_ms)
    self._timer.timeout.connect(self._start_pending)
    self._pool = QThreadPool(self)
    self._pool.setMaxThreadCount(1)
    self._pending: DensityColorRequest | None = None
    self._active: _DensityRunnable | None = None
    self._closed = False

  def schedule(self, request: DensityColorRequest) -> None:
    """Replace pending work with a defensive snapshot and schedule it."""
    if self._closed:
      raise RuntimeError("density scheduler is closed")
    self._pending = DensityColorRequest(
      key=request.key,
      input_x=_readonly_copy(request.input_x),
      input_y=_readonly_copy(request.input_y),
      query_x=_readonly_copy(request.query_x),
      query_y=_readonly_copy(request.query_y),
      bounds=request.bounds,
      logical_size=request.logical_size,
    )
    self._timer.start()

  def cancel_pending(self) -> None:
    """Cancel work which has not entered the worker thread."""
    self._timer.stop()
    self._pending = None

  def shutdown(self) -> None:
    """Stop new work and wait for the active numerical job to finish."""
    if self._closed:
      return
    self._closed = True
    self.cancel_pending()
    self._pool.waitForDone()
    self._active = None

  def is_running(self) -> bool:
    return self._active is not None

  def _start_pending(self) -> None:
    if self._closed or self._active is not None or self._pending is None:
      return
    request = self._pending
    self._pending = None
    signals = _DensitySignals(self)
    runnable = _DensityRunnable(request, self._executor, signals)
    signals.completed.connect(self._on_completed)
    signals.failed.connect(self._on_failed)
    self._active = runnable
    self._pool.start(runnable)

  def _on_completed(self, response: DensityColorResponse) -> None:
    self._active = None
    if not self._closed:
      self.density_ready.emit(response)
    self._start_pending()

  def _on_failed(
    self, request: DensityColorRequest, error: Exception
  ) -> None:
    self._active = None
    if not self._closed:
      self.density_failed.emit(request, error)
    self._start_pending()

  @staticmethod
  def _run_density(request: DensityColorRequest) -> DensityColorResult:
    return estimate_density_colors(
      request.input_x,
      request.input_y,
      request.query_x,
      request.query_y,
      bounds=request.bounds,
      logical_size=request.logical_size,
    )


def _readonly_copy(values: NDArray[np.float64]) -> NDArray[np.float64]:
  if not values.flags.writeable:
    return values
  copied = np.array(values, dtype=np.float64, copy=True, order="C")
  copied.setflags(write=False)
  return copied
