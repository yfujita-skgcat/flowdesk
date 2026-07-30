"""Qt scheduler tests for revision-safe current-sample preview jobs."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import ChannelSpec, GateSpec
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.preview import PreviewRequest
from flowdesk_core.processed_display import ProcessedDisplayRequest
from flowdesk_core.sample import SampleData
from flowdesk_qt.main_window import MainWindow
from flowdesk_qt.preview_scheduler import PreviewScheduler
from flowdesk_qt.processed_display_scheduler import ProcessedDisplayScheduler

pytestmark = pytest.mark.gui


def _request(revision: int) -> PreviewRequest:
  sample = SampleData(
    sample_id="s1",
    events=np.array([[1.0]], dtype=np.float64),
    channels=(ChannelSpec(id="x", name="X"),),
  )
  return PreviewRequest(revision=revision, sample=sample)


def _display_request(revision: int, sample_id: str = "s1") -> ProcessedDisplayRequest:
  sample = SampleData(
    sample_id=sample_id,
    events=np.array([[1.0]], dtype=np.float64),
    channels=(ChannelSpec(id="x", name="X"),),
  )
  return ProcessedDisplayRequest(
    revision=revision,
    sample=sample,
    population_id="all_events",
    x_parameter_id="x",
  )


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


def test_scheduler_can_start_finished_interaction_without_debounce(qapp) -> None:
  received: list[int] = []

  def execute(_project, request):
    return SimpleNamespace(revision=request.revision)

  scheduler = PreviewScheduler(debounce_ms=10_000, executor=execute)
  scheduler.preview_ready.connect(lambda report: received.append(report.revision))
  try:
    scheduler.schedule({"revision": 1}, _request(1))
    scheduler.start_pending_now()
    _wait_until(qapp, lambda: received == [1])
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


def test_processed_display_scheduler_coalesces_pending_latest_request(qapp) -> None:
  first_started = threading.Event()
  release_first = threading.Event()
  calls: list[tuple[int, str]] = []
  received: list[tuple[int, str]] = []

  def execute(project, request):
    calls.append((request.revision, request.sample_id))
    assert project["nested"]["value"] == request.revision
    if request.revision == 1:
      first_started.set()
      assert release_first.wait(2.0)
    return request

  scheduler = ProcessedDisplayScheduler(debounce_ms=0, executor=execute)
  scheduler.display_ready.connect(
    lambda result: received.append((result.revision, result.sample_id))
  )
  first_project = {"nested": {"value": 1}}
  try:
    scheduler.schedule(first_project, _display_request(1, "a"))
    _wait_until(qapp, first_started.is_set)
    second_project = {"nested": {"value": 2}}
    scheduler.schedule(second_project, _display_request(2, "b"))
    scheduler.schedule({"nested": {"value": 3}}, _display_request(3, "c"))
    first_project["nested"]["value"] = 99
    second_project["nested"]["value"] = 99
    release_first.set()
    _wait_until(qapp, lambda: received == [(1, "a"), (3, "c")])
    assert calls == [(1, "a"), (3, "c")]
  finally:
    release_first.set()
    scheduler.shutdown()
    scheduler.deleteLater()


def test_main_window_processed_display_uses_latest_selected_sample(
  qapp, monkeypatch, tmp_path,
) -> None:
  paths = []
  for index in range(3):
    path = tmp_path / f"display-{index}.fcs"
    write_fcs_file(
      path,
      np.array([[float(index), 1.0], [float(index + 1), 2.0]]),
      ["X", "Y"],
    )
    paths.append(path)
  window = MainWindow()
  started = threading.Event()
  release = threading.Event()
  original_prepare = PipelineRunner.prepare_display_sample
  calls: list[str] = []

  def delayed_prepare(project, request):
    calls.append(request.sample_id)
    if request.sample_id == samples[1].id:
      started.set()
      assert release.wait(2.0)
    return original_prepare(PipelineRunner(project), request)

  try:
    assert window._sample_browser.add_samples_from_paths([str(path) for path in paths]) == 3
    samples = window._sample_browser.samples()
    assert window._sample_browser.select_sample(samples[0].id)
    _wait_until(qapp, lambda: bool(window._processed_display_cache))
    window._processed_display_scheduler._executor = delayed_prepare
    assert window._sample_browser.select_sample(samples[1].id)
    _wait_until(qapp, started.is_set)
    assert window._sample_browser.select_sample(samples[2].id)
    qapp.processEvents()
    assert window._current_sample_id == samples[2].id
    release.set()
    _wait_until(qapp, lambda: any(
      result.sample_id == samples[2].id
      for result in window._processed_display_cache.values()
    ))
    assert calls[-2:] == [samples[1].id, samples[2].id]
    assert window._plot_widget._rendered_x is not None
    np.testing.assert_allclose(window._plot_widget._rendered_x, [2.0, 3.0])
    stale_request = window._processed_display_request(
      window._sample_data[samples[1].id],
      window._channel_selector.x_channel_id(),
      window._channel_selector.y_channel_id(),
      window._active_plot_transform(window._channel_selector.x_channel_id()),
      window._active_plot_transform(window._channel_selector.y_channel_id()),
    )
    window._on_processed_display_failed(stale_request, RuntimeError("stale failure"))
    assert window._plot_widget._rendered_x is not None
    np.testing.assert_allclose(window._plot_widget._rendered_x, [2.0, 3.0])
  finally:
    release.set()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_main_window_bounds_processed_display_cache(qapp, tmp_path) -> None:
  paths = []
  for index in range(5):
    path = tmp_path / f"cache-{index}.fcs"
    write_fcs_file(
      path,
      np.array([[float(index), 1.0], [float(index + 1), 2.0]]),
      ["X", "Y"],
    )
    paths.append(path)
  window = MainWindow()
  try:
    assert window._sample_browser.add_samples_from_paths([str(path) for path in paths]) == 5
    for sample in window._sample_browser.samples():
      assert window._sample_browser.select_sample(sample.id)
      _wait_until(
        qapp,
        lambda sample_id=sample.id: any(
          result.sample_id == sample_id
          for result in window._processed_display_cache.values()
        ),
      )
    assert len(window._processed_display_cache) <= window._PROCESSED_DISPLAY_CACHE_MAX_ENTRIES
    assert window._processed_display_cache_bytes >= 0
    assert window._processed_display_cache_bytes <= window._PROCESSED_DISPLAY_CACHE_MAX_BYTES
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_main_window_uses_background_sample_load_for_large_input(
  qapp, tmp_path, monkeypatch,
) -> None:
  fcs_path = tmp_path / "large.fcs"
  events = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
  write_fcs_file(fcs_path, events, ["X", "Y"])
  window = MainWindow()
  monkeypatch.setattr(window, "_should_load_sample_async", lambda _sample: True)
  try:
    assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    assert sample.id not in window._sample_data
    _wait_until(qapp, lambda: sample.id in window._sample_data)
    _wait_until(qapp, lambda: window._plot_widget._rendered_x is not None)
    np.testing.assert_allclose(window._plot_widget._rendered_x, events[:, 0])
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_main_window_prefetches_adjacent_sample_without_replotting_active(
  qapp, tmp_path, monkeypatch,
) -> None:
  paths = []
  values = []
  for index in range(2):
    path = tmp_path / f"prefetch-{index}.fcs"
    events = np.array(
      [[float(index + 1), 2.0], [float(index + 3), 4.0]], dtype=np.float64
    )
    write_fcs_file(path, events, ["X", "Y"])
    paths.append(path)
    values.append(events)
  window = MainWindow()
  monkeypatch.setattr(window, "_should_load_sample_async", lambda _sample: True)
  try:
    assert window._sample_browser.add_samples_from_paths([str(path) for path in paths]) == 2
    samples = window._sample_browser.samples()
    assert window._sample_browser.select_sample(samples[0].id)
    _wait_until(qapp, lambda: samples[0].id in window._sample_data)
    _wait_until(qapp, lambda: window._plot_widget._rendered_x is not None)
    original_rendered_x = window._plot_widget._rendered_x.copy()

    window._start_adjacent_prefetch()
    _wait_until(qapp, lambda: samples[1].id in window._sample_data)
    np.testing.assert_allclose(window._plot_widget._rendered_x, original_rendered_x)

    assert window._sample_browser.select_sample(samples[1].id)
    _wait_until(qapp, lambda: np.array_equal(window._plot_widget._rendered_x, values[1][:, 0]))
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_main_window_integrates_current_sample_preview_into_results_workspace(
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
    assert not hasattr(window, "_current_sample_preview")
    assert window.findChild(QWidget, "currentSamplePreview") is None
    results_tree = window._results_workspace.tree()
    positive = results_tree.topLevelItem(0).child(0).child(0)
    assert positive.text(4) == "current"
    assert positive.data(0, Qt.UserRole + 4) == "active_sample_preview"
    assert "Batch results stale" not in positive.toolTip(0)

    window._on_population_selected("positive", sample.id)
    _wait_until(qapp, lambda: window._plot_widget._scatter is not None)
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
