"""Qt scheduler tests for revision-safe current-sample preview jobs."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest

from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import ChannelSpec, GateSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.preview import PreviewRequest
from flowdesk_core.sample import SampleData
from flowdesk_qt.main_window import MainWindow
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


def test_scheduler_shutdown_waits_for_running_job_and_ignores_late_signal(qapp) -> None:
  started = threading.Event()
  release = threading.Event()
  received: list[int] = []

  def execute(_project, request):
    started.set()
    assert release.wait(2.0)
    return SimpleNamespace(revision=request.revision)

  scheduler = PreviewScheduler(debounce_ms=0, executor=execute)
  scheduler.preview_ready.connect(lambda report: received.append(report.revision))
  try:
    scheduler.schedule({}, _request(1))
    _wait_until(qapp, started.is_set)
    threading.Timer(0.05, release.set).start()
    scheduler.shutdown()
    assert scheduler._pool.activeThreadCount() == 0
    assert received == []
  finally:
    release.set()
    scheduler.deleteLater()


def test_main_window_presents_current_sample_preview_after_gate_edit(
  qapp,
  tmp_path,
) -> None:
  fcs_path = tmp_path / "preview.fcs"
  write_fcs_file(
    fcs_path,
    np.array(
      [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
      dtype=np.float64,
    ),
    ["X", "Y"],
  )
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    gate = GateSpec(
      id="positive",
      name="positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter=sample.info.channels[0].id,
      thresholds={"min": 2.0},
    )
    window._gate_editor.set_gates([gate])
    window._on_run_pipeline()
    worker = window._worker
    assert worker is not None
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    qapp.processEvents()


    updated = GateSpec(
      id="positive",
      name="positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter=sample.info.channels[0].id,
      thresholds={"min": 3.0},
    )
    window._gate_editor.update_gate(0, updated)
    for _ in range(200):
      if window.preview_status == "current":
        break
      QTest.qWait(5)

    assert window.preview_status == "current"
    assert window._preview_report is not None
    assert window._current_sample_preview._sample.text() == sample.id
    assert "Preview — current sample only" in (
      window._current_sample_preview._status.text()
    )
    assert "Batch results stale" in window._current_sample_preview._status.text()

    window._on_population_selected("positive", sample.id)
    qapp.processEvents()
    assert window.display_population_id == "positive"
    assert len(window._plot_widget._scatter.xData) == 2
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_batch_report_from_obsolete_definition_is_discarded(
  qapp,
  monkeypatch,
  tmp_path,
) -> None:
  fcs_path = tmp_path / "obsolete-batch.fcs"
  write_fcs_file(
    fcs_path,
    np.array([[0.0, 0.0], [2.0, 1.0], [3.0, 2.0]], dtype=np.float64),
    ["X", "Y"],
  )
  original_run_samples = PipelineRunner.run_samples

  def slow_run_samples(self, *args, **kwargs):
    time.sleep(0.1)
    return original_run_samples(self, *args, **kwargs)

  monkeypatch.setattr(PipelineRunner, "run_samples", slow_run_samples)
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    gate = GateSpec(
      id="positive",
      name="positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter=sample.info.channels[0].id,
      thresholds={"min": 2.0},
    )
    window._gate_editor.set_gates([gate])
    window._on_run_pipeline()
    QTimer.singleShot(
      20,
      lambda: window._gate_editor.update_gate(
        0,
        GateSpec(
          id="positive",
          name="positive",
          gate_type="range",
          parent_population_id="all_events",
          x_parameter=sample.info.channels[0].id,
          thresholds={"min": 3.0},
        ),
      ),
    )
    worker = window._worker
    assert worker is not None
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    qapp.processEvents()

    assert window.analysis_revision > worker.revision
    assert window._population_tree.last_report() is None
    assert window._results_stale is True
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
