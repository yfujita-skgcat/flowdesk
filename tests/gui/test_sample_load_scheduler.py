from __future__ import annotations

import threading

import pytest
from PySide6.QtTest import QTest

from flowdesk_core.models import ChannelSpec
from flowdesk_core.sample import SampleData
from flowdesk_qt.sample_load_scheduler import SampleLoadScheduler

pytestmark = pytest.mark.gui


def _wait_until(qapp, predicate) -> None:
  for _ in range(200):
    if predicate():
      return
    QTest.qWait(5)
  assert predicate()


def test_sample_load_scheduler_keeps_latest_pending_request(qapp, monkeypatch) -> None:
  first_started = threading.Event()
  release_first = threading.Event()
  loaded: list[str] = []

  def read_sample(path, sample_id):
    if sample_id == "a":
      first_started.set()
      assert release_first.wait(2.0)
    return None, SampleData(
      sample_id,
      [[1.0]],
      (ChannelSpec(id="x", name="X"),),
    )

  monkeypatch.setattr("flowdesk_qt.sample_load_scheduler.read_fcs_sample", read_sample)
  scheduler = SampleLoadScheduler()
  scheduler.sample_loaded.connect(lambda sample_id, _sample: loaded.append(sample_id))
  try:
    scheduler.schedule("a", "a.fcs")
    _wait_until(qapp, first_started.is_set)
    scheduler.schedule("b", "b.fcs")
    scheduler.schedule("c", "c.fcs")
    release_first.set()
    _wait_until(qapp, lambda: loaded == ["a", "c"])
  finally:
    release_first.set()
    scheduler.shutdown()
    scheduler.deleteLater()
