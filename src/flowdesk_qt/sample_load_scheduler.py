"""Latest-wins background loading for large FCS display inputs."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from flowdesk_core.fcs_io import read_fcs_sample


class _LoadSignals(QObject):
  loaded = Signal(str, str, object)
  failed = Signal(str, str, object)


class _LoadRunnable(QRunnable):
  def __init__(self, sample_id: str, path: str, signals: _LoadSignals) -> None:
    super().__init__()
    self.setAutoDelete(True)
    self.sample_id = sample_id
    self.path = path
    self.signals = signals

  def run(self) -> None:
    try:
      _info, sample = read_fcs_sample(self.path, self.sample_id)
    except Exception as exc:  # pragma: no cover - delivered through Qt signal
      self.signals.failed.emit(self.sample_id, self.path, exc)
    else:
      self.signals.loaded.emit(self.sample_id, self.path, sample)


class SampleLoadScheduler(QObject):
  """Load at most one large FCS in the worker pool and keep the newest request."""

  sample_loaded = Signal(str, object)
  sample_failed = Signal(str, object)

  def __init__(self, parent: QObject | None = None) -> None:
    super().__init__(parent)
    self._pool = QThreadPool(self)
    self._pool.setMaxThreadCount(1)
    self._timer = QTimer(self)
    self._timer.setSingleShot(True)
    self._timer.timeout.connect(self._start_pending)
    self._pending: tuple[str, str] | None = None
    self._active: tuple[str, str] | None = None
    self._closed = False

  def schedule(self, sample_id: str, path: str) -> None:
    if self._closed:
      raise RuntimeError("sample load scheduler is closed")
    request = (sample_id, path)
    if self._active == request or self._pending == request:
      return
    self._pending = (sample_id, path)
    self._timer.start(0)

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
    sample_id, path = self._pending
    self._pending = None
    self._active = (sample_id, path)
    signals = _LoadSignals(self)
    signals.loaded.connect(self._on_loaded)
    signals.failed.connect(self._on_failed)
    self._pool.start(_LoadRunnable(sample_id, path, signals))

  def _on_loaded(self, sample_id: str, path: str, sample: object) -> None:
    if self._active != (sample_id, path):
      return
    self._active = None
    superseded = self._pending is not None and self._pending[0] == sample_id
    if not self._closed and not superseded:
      self.sample_loaded.emit(sample_id, sample)
    self._start_pending()

  def _on_failed(self, sample_id: str, path: str, error: Exception) -> None:
    if self._active != (sample_id, path):
      return
    self._active = None
    superseded = self._pending is not None and self._pending[0] == sample_id
    if not self._closed and not superseded:
      self.sample_failed.emit(sample_id, error)
    self._start_pending()
