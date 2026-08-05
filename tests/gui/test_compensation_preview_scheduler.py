"""Qt lifecycle and latest-wins tests for compensation preview scheduling."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from PySide6.QtTest import QTest

from flowdesk_core.compensation_preview import (
  CompensationPreviewRequest,
  CompensationPreviewResult,
)
from flowdesk_core.models import CompensationMatrixSpec
from flowdesk_qt.compensation_preview_scheduler import CompensationPreviewScheduler

pytestmark = pytest.mark.gui


def _request(revision: int) -> CompensationPreviewRequest:
  matrix = CompensationMatrixSpec(
    id=f"candidate-{revision}",
    name="candidate",
    source="user_defined",
    channels=("A", "B"),
    matrix=((1.0, 0.0), (0.0, 1.0)),
  )
  return CompensationPreviewRequest(
    revision=revision,
    sample_id="sample",
    events=np.array([[1.0, 2.0]], dtype=np.float64),
    channel_ids=("A", "B"),
    population_mask=np.array([True]),
    candidate_matrix=matrix,
    source_channel_id="A",
    receiving_channel_id="B",
  )


def _wait_until(qapp, predicate) -> None:
  for _ in range(200):
    if predicate():
      return
    QTest.qWait(5)
  assert predicate()


def test_scheduler_keeps_only_latest_pending_request(qapp) -> None:
  calls: list[int] = []
  received: list[int] = []

  def execute(request: CompensationPreviewRequest) -> CompensationPreviewResult:
    calls.append(request.revision)
    return _result(request)

  scheduler = CompensationPreviewScheduler(debounce_ms=20, executor=execute)
  scheduler.preview_ready.connect(
    lambda request, _result: received.append(request.revision)
  )
  try:
    scheduler.schedule(_request(1))
    scheduler.schedule(_request(2))
    scheduler.schedule(_request(3))
    _wait_until(qapp, lambda: received == [3])
    assert calls == [3]
  finally:
    scheduler.shutdown()
    scheduler.deleteLater()


def test_scheduler_runs_one_active_job_then_latest_pending(qapp) -> None:
  started = threading.Event()
  release = threading.Event()
  calls: list[int] = []
  received: list[int] = []

  def execute(request: CompensationPreviewRequest) -> CompensationPreviewResult:
    calls.append(request.revision)
    if request.revision == 1:
      started.set()
      assert release.wait(2.0)
    return _result(request)

  scheduler = CompensationPreviewScheduler(debounce_ms=0, executor=execute)
  scheduler.preview_ready.connect(
    lambda request, _result: received.append(request.revision)
  )
  try:
    scheduler.schedule(_request(1))
    _wait_until(qapp, started.is_set)
    scheduler.schedule(_request(2))
    scheduler.schedule(_request(3))
    release.set()
    _wait_until(qapp, lambda: received == [1, 3])
    assert calls == [1, 3]
  finally:
    release.set()
    scheduler.shutdown()
    scheduler.deleteLater()


def _result(request: CompensationPreviewRequest) -> CompensationPreviewResult:
  values = np.array([1.0], dtype=np.float64)
  return CompensationPreviewResult(
    revision=request.revision,
    sample_id=request.sample_id,
    source_matrix_id=None,
    candidate_matrix_id=request.candidate_matrix.id,
    source_channel_id=request.source_channel_id,
    receiving_channel_id=request.receiving_channel_id,
    display_event_indices=np.array([0]),
    uncompensated_x=values,
    uncompensated_y=values,
    compensated_x=values,
    compensated_y=values,
    x_transform_id=None,
    y_transform_id=None,
    axis_limits=(1.0, 1.0, 1.0, 1.0),
    full_event_count=1,
    population_event_count=1,
  )
