"""Qt scheduler tests for revision-safe current-sample preview jobs."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtTest import QTest

from flowdesk_core.models import ChannelSpec
from flowdesk_core.preview import PreviewRequest
from flowdesk_core.sample import SampleData
from flowdesk_qt.preview_scheduler import PreviewScheduler

pytestmark = pytest.mark.gui


def _request(revision: int) -> PreviewRequest:
  sample = SampleData(
    sample_id="s1",
    events=np.array([[1.0]], dtype=np.float64),
    channels=(ChannelSpec(id="x", name="X"),),
  )
  return PreviewRequest(revision=revision, sample=sample)


def _wait_until(qapp, predicate) -> None:
  for _ in range(200):
    if predicate():
      return
    QTest.qWait(5)
  assert predicate()


def test_scheduler_coalesces_repeated_edits_to_latest_pending_revision(qapp) -> None:
  calls: list[int] = []
  received: list[int] = []

  def execute(_project, request):
    calls.append(request.revision)
    return SimpleNamespace(revision=request.revision)

  scheduler = PreviewScheduler(debounce_ms=20, executor=execute)
  scheduler.preview_ready.connect(lambda report: received.append(report.revision))
  try:
    scheduler.schedule({"revision": 1}, _request(1))
    scheduler.schedule({"revision": 2}, _request(2))
    scheduler.schedule({"revision": 3}, _request(3))
    _wait_until(qapp, lambda: received == [3])
    assert calls == [3]
  finally:
    scheduler.shutdown()
    scheduler.deleteLater()


def test_scheduler_discards_out_of_order_obsolete_completion(qapp) -> None:
  first_started = threading.Event()
  release_first = threading.Event()
  calls: list[int] = []
  received: list[int] = []

  def execute(_project, request):
    calls.append(request.revision)
    if request.revision == 1:
      first_started.set()
      assert release_first.wait(2.0)
    return SimpleNamespace(revision=request.revision)

  scheduler = PreviewScheduler(debounce_ms=0, executor=execute)
  scheduler.preview_ready.connect(lambda report: received.append(report.revision))
  try:
    scheduler.schedule({"revision": 1}, _request(1))
    _wait_until(qapp, first_started.is_set)
    scheduler.schedule({"revision": 2}, _request(2))
    release_first.set()
    _wait_until(qapp, lambda: received == [2])
    assert calls == [1, 2]
  finally:
    scheduler.shutdown()
    scheduler.deleteLater()


def test_scheduler_copies_project_snapshot_and_shuts_down_cleanly(qapp) -> None:
  captured: list[dict] = []

  def execute(project, request):
    captured.append(project)
    return SimpleNamespace(revision=request.revision)

  scheduler = PreviewScheduler(debounce_ms=0, executor=execute)
  project = {"gates": [{"id": "g", "threshold": 1.0}]}
  try:
    scheduler.schedule(project, _request(1))
    project["gates"][0]["threshold"] = 9.0
    _wait_until(qapp, lambda: len(captured) == 1)
    assert captured[0]["gates"][0]["threshold"] == 1.0
  finally:
    scheduler.shutdown()
    assert not scheduler.is_running()
    assert not scheduler.has_pending()
    with pytest.raises(RuntimeError, match="closed"):
      scheduler.schedule({}, _request(2))
    scheduler.deleteLater()
