#!/usr/bin/env python3
"""Measure the large-FCS asynchronous acquisition path used by prefetch."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path

try:
  import resource
except ImportError:  # pragma: no cover - Windows has no resource module
  resource = None  # type: ignore[assignment]

import numpy as np
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from flowdesk_core.fcs_io import read_fcs_sample, write_fcs_file
from flowdesk_qt.sample_load_scheduler import SampleLoadScheduler


def _wait_for_sample(scheduler: SampleLoadScheduler, path: Path) -> object:
  loop = QEventLoop()
  result: list[object] = []
  error: list[Exception] = []

  def loaded(_sample_id: str, sample: object) -> None:
    result.append(sample)
    loop.quit()

  def failed(_sample_id: str, exc: object) -> None:
    error.append(exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
    loop.quit()

  scheduler.sample_loaded.connect(loaded)
  scheduler.sample_failed.connect(failed)
  scheduler.schedule("benchmark", str(path))
  QTimer.singleShot(300_000, loop.quit)
  loop.exec()
  scheduler.sample_loaded.disconnect(loaded)
  scheduler.sample_failed.disconnect(failed)
  if error:
    raise error[0]
  if not result:
    raise TimeoutError("asynchronous FCS load did not complete")
  return result[0]


def run_prefetch_benchmark(
  *, events: int, seed: int, source_path: Path | None = None,
) -> dict[str, object]:
  if events < 1:
    raise ValueError("events must be positive")
  temp_root = (
    tempfile.TemporaryDirectory(prefix="flowdesk-prefetch-")
    if source_path is None else None
  )
  try:
    if source_path is None:
      rng = np.random.default_rng(seed)
      values = rng.lognormal(4.0, 0.6, size=(events, 4)).astype(np.float64)
      path = Path(temp_root.name) / "large.fcs"
      write_fcs_file(path, values, ["FSC-A", "SSC-A", "FL1-A", "FL2-A"])
    else:
      path = source_path.expanduser().resolve()
      if not path.is_file():
        raise FileNotFoundError(path)
    file_size = path.stat().st_size
    started = time.perf_counter()
    _info, synchronous = read_fcs_sample(path, "benchmark")
    synchronous_seconds = time.perf_counter() - started
    app = QCoreApplication.instance() or QCoreApplication([])
    scheduler = SampleLoadScheduler()
    try:
      started = time.perf_counter()
      asynchronous = _wait_for_sample(scheduler, path)
      asynchronous_seconds = time.perf_counter() - started
    finally:
      scheduler.shutdown()
      if QCoreApplication.instance() is app:
        app.processEvents()
    sync_hash = hashlib.sha256(synchronous.events.tobytes()).hexdigest()
    async_hash = hashlib.sha256(asynchronous.events.tobytes()).hexdigest()
    return {
      "events": events,
      "seed": seed,
      "source_path": str(path),
      "file_bytes": file_size,
      "synchronous_event_count": synchronous.event_count,
      "asynchronous_event_count": asynchronous.event_count,
      "async_threshold_bytes": 4 * 1024 * 1024,
      "uses_large_file_path": file_size >= 4 * 1024 * 1024,
      "synchronous_seconds": synchronous_seconds,
      "asynchronous_seconds": asynchronous_seconds,
      "event_count_match": synchronous.event_count == asynchronous.event_count,
      "raw_hash_match": sync_hash == async_hash,
      "raw_hash": sync_hash,
      "peak_rss_kib": (
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None else None
      ),
    }
  finally:
    if temp_root is not None:
      temp_root.cleanup()


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--events", type=int, default=300_000)
  parser.add_argument("--seed", type=int, default=1729)
  parser.add_argument("--path", type=Path, help="Measure an existing FCS instead of generating one")
  parser.add_argument("--output", type=Path)
  args = parser.parse_args()
  result = run_prefetch_benchmark(events=args.events, seed=args.seed, source_path=args.path)
  rendered = json.dumps(result, indent=2) + "\n"
  if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
  print(rendered, end="")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
