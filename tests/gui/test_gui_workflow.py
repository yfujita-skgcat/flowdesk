from __future__ import annotations

import signal
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QPushButton

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_control import ExecutionCancelled, ExecutionOptions, ProgressEvent
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import GateSpec
from flowdesk_core.overrides import gate_version_hash
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.project_commands import RebaseGateOverrideCommand
from flowdesk_qt import _install_terminal_interrupt_handler
from flowdesk_qt.main_window import MainWindow

pytestmark = [pytest.mark.gui, pytest.mark.gui_e2e]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def test_terminal_interrupt_closes_window_and_quits_application(qapp, monkeypatch) -> None:
  window = MainWindow()
  close_calls: list[str] = []
  quit_calls: list[str] = []
  monkeypatch.setattr(window, "close", lambda: close_calls.append("close"))
  monkeypatch.setattr(qapp, "quit", lambda: quit_calls.append("quit"))
  installed: dict[str, object] = {}

  def fake_signal(signum, handler):
    installed["signum"] = signum
    installed["handler"] = handler
    return None

  monkeypatch.setattr("flowdesk_qt.signal.signal", fake_signal)
  monkeypatch.setattr("flowdesk_qt.signal.getsignal", lambda _signum: "previous")
  previous = _install_terminal_interrupt_handler(qapp, window)

  assert previous == "previous"
  assert installed["signum"] == signal.SIGINT
  handler = installed["handler"]
  assert callable(handler)
  handler(signal.SIGINT, None)
  handler(signal.SIGINT, None)

  assert close_calls == ["close"]
  assert quit_calls == ["quit"]
  window.deleteLater()


def _wait_for_worker(window: MainWindow) -> None:
  worker = window._worker
  assert worker is not None
  loop = QEventLoop()
  worker.finished.connect(loop.quit)
  QTimer.singleShot(5000, loop.quit)
  loop.exec()
  try:
    assert worker.isRunning() is False
  except RuntimeError:
    # MainWindow may release the completed QThread before this nested loop returns.
    pass


def _wait_for_scatter(window: MainWindow) -> None:
  for _ in range(200):
    if window._plot_widget._scatter is not None:
      return
    QTest.qWait(5)
  assert window._plot_widget._scatter is not None


def _wait_for_batch_worker(window: MainWindow) -> None:
  for _ in range(200):
    if window._batch_plot_worker is None:
      return
    QTest.qWait(5)
  assert window._batch_plot_worker is None


def test_batch_export_runs_in_worker_with_progress_surface(
  qapp, tmp_path: Path, gui_artifact_widgets: list[object], monkeypatch,
) -> None:
  window = MainWindow()
  gui_artifact_widgets.append(window)
  progress_seen: list[object] = []

  def fake_batch_command(
    _project_path: str,
    _export_id: str,
    _output_dir: str,
    *,
    execution_control,
    **_kwargs,
  ) -> int:
    execution_control.emit_progress(ProgressEvent(
      operation_id="batch:1",
      operation="batch_plot_export",
      phase="rendering",
      completed_units=1,
      total_units=2,
      sample_id="sample-1",
      output_path="sample-1.png",
    ))
    time.sleep(0.04)
    return 0

  monkeypatch.setattr("flowdesk_cli.batch_plot.batch_plot_command", fake_batch_command)
  try:
    window._project_path = tmp_path / "project.flowdesk"
    window._start_batch_plot_export("export-1", str(tmp_path / "output"))
    dialog = window.findChild(QDialog, "batchPlotProgressDialog")
    assert dialog is not None
    assert dialog.findChild(QProgressBar, "batchPlotProgressBar") is not None
    assert dialog.findChild(QLabel, "batchPlotProgressSummary") is not None
    assert dialog.findChild(QLabel, "batchPlotProgressCurrentItem") is not None
    assert dialog.findChild(QLabel, "batchPlotProgressDetails") is not None
    assert dialog.findChild(QPushButton, "batchPlotProgressCancelButton") is not None
    for _ in range(40):
      qapp.processEvents()
      summary = dialog.findChild(QLabel, "batchPlotProgressSummary")
      if summary is not None and "rendering" in summary.text():
        progress_seen.append(summary)
        break
      QTest.qWait(5)
    assert progress_seen
    _wait_for_batch_worker(window)
    assert window.action_batch_plot_export.isEnabled()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_batch_plot_worker_receives_runtime_execution_options(qapp) -> None:
  from flowdesk_qt.main_window import _BatchPlotExportWorker

  options = ExecutionOptions(
    backend="thread", max_workers=3, memory_budget_bytes=128 * 1024 * 1024,
  )
  worker = _BatchPlotExportWorker("project.flowdesk", "export", "output", options)
  try:
    assert worker._execution_control.options == options
  finally:
    worker.request_cancel()
    worker.deleteLater()


def test_pipeline_worker_receives_runtime_execution_options(qapp) -> None:
  from flowdesk_qt.main_window import _PipelineWorker

  options = ExecutionOptions(
    backend="thread", max_workers=3, memory_budget_bytes=256 * 1024 * 1024,
  )
  worker = _PipelineWorker({}, (), execution_options=options)
  try:
    assert worker._execution_control.options == options
  finally:
    worker.request_cancel()
    worker.deleteLater()


def test_batch_export_cancel_requests_core_cancellation(
  qapp, tmp_path: Path, gui_artifact_widgets: list[object], monkeypatch,
) -> None:
  window = MainWindow()
  gui_artifact_widgets.append(window)
  cancellation_seen: list[bool] = []

  def fake_batch_command(
    _project_path: str,
    _export_id: str,
    _output_dir: str,
    *,
    execution_control,
    **_kwargs,
  ) -> int:
    deadline = time.monotonic() + 2.0
    while not execution_control.cancellation_token.is_cancelled():
      if time.monotonic() >= deadline:
        return 0
      time.sleep(0.005)
    cancellation_seen.append(True)
    return 1

  monkeypatch.setattr("flowdesk_cli.batch_plot.batch_plot_command", fake_batch_command)
  monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
  try:
    window._project_path = tmp_path / "project.flowdesk"
    window._start_batch_plot_export("export-1", str(tmp_path / "output"))
    dialog = window.findChild(QDialog, "batchPlotProgressDialog")
    assert dialog is not None
    cancel = dialog.findChild(QPushButton, "batchPlotProgressCancelButton")
    assert cancel is not None
    cancel.click()
    _wait_for_batch_worker(window)
    assert cancellation_seen == [True]
    assert window.action_batch_plot_export.isEnabled()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_window_close_cancels_batch_export_worker(
  qapp, tmp_path: Path, gui_artifact_widgets: list[object], monkeypatch,
) -> None:
  window = MainWindow()
  gui_artifact_widgets.append(window)
  cancellation_seen: list[bool] = []

  def fake_batch_command(
    _project_path: str,
    _export_id: str,
    _output_dir: str,
    *,
    execution_control,
    **_kwargs,
  ) -> int:
    while not execution_control.cancellation_token.is_cancelled():
      time.sleep(0.005)
    cancellation_seen.append(True)
    return 1

  monkeypatch.setattr("flowdesk_cli.batch_plot.batch_plot_command", fake_batch_command)
  monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
  try:
    window._project_path = tmp_path / "project.flowdesk"
    window._start_batch_plot_export("export-1", str(tmp_path / "output"))
    assert window._batch_plot_worker is not None
    window.close()
    qapp.processEvents()
    assert cancellation_seen == [True]
    assert window._batch_plot_worker is None
  finally:
    window.deleteLater()
    qapp.processEvents()


def test_load_gate_run_and_match_headless(
  qapp,
  tmp_path: Path,
  gui_artifact_widgets: list[object],
) -> None:
  fcs_path = tmp_path / "workflow.fcs"
  events = np.array(
    [[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]],
    dtype=np.float64,
  )
  write_fcs_file(fcs_path, events, ["X", "Y"])
  window = MainWindow()
  gui_artifact_widgets.append(window)
  try:
    window.show()
    assert window._sample_browser.add_samples_from_paths([str(fcs_path)]) == 1
    sample = window._sample_browser.samples()[0]
    assert window._sample_browser.select_sample(sample.id)
    assert window._event_data[sample.id].shape == (4, 2)
    assert window._channel_selector.x_channel() == "X"
    _wait_for_scatter(window)

    gate = GateSpec(
      id="positive",
      name="positive",
      gate_type="range",
      parent_population_id="all_events",
      x_parameter=sample.info.channels[0].id,
      thresholds={"min": 2.0},
    )
    window._gate_editor.set_gates([gate])
    manifest = window._build_project_manifest()
    typed_samples = tuple(window._sample_data.values())

    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()

    gui_report = window._population_tree.last_report()
    assert gui_report is not None
    assert window._population_tree._table.rowCount() == 2
    assert window._worker is None

    headless_report = PipelineRunner(manifest).run_samples(
      ExecutionContext(), typed_samples
    )
    gui_counts = {
      result.population_id: result.event_count
      for result in gui_report.population_results
    }
    headless_counts = {
      result.population_id: result.event_count
      for result in headless_report.population_results
    }
    assert gui_counts == headless_counts == {"all_events": 4, "positive": 3}
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_sample_navigation_preserves_population_axes_scales_and_viewport(
  qapp,
  tmp_path: Path,
) -> None:
  first = tmp_path / "first.fcs"
  second = tmp_path / "second.fcs"
  events = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
  write_fcs_file(first, events, ["X", "Y"])
  write_fcs_file(second, events * 2.0, ["X", "Y"])
  window = MainWindow()
  try:
    window._sample_browser.add_samples_from_paths([str(first), str(second)])
    samples = window._sample_browser.samples()
    window._sample_browser.select_sample(samples[0].id)
    window._selected_population_id = "population/path"
    window._channel_selector.set_selected_channels("X", "Y")
    window._channel_selector.set_x_transform("log10")
    window._channel_selector.set_y_transform("asinh")
    viewport = ((10.0, 20.0), (30.0, 40.0))
    window._plot_widget.set_manual_view_range(*viewport)
    window._navigate_sample(1)
    qapp.processEvents()


    assert window._current_sample_id == samples[1].id
    assert window._selected_population_id == "population/path"
    assert window._channel_selector.x_channel() == "X"
    assert window._channel_selector.y_channel() == "Y"
    assert window._channel_selector.x_transform() == "log10"
    assert window._channel_selector.y_transform() == "asinh"
    assert window._plot_widget.view_range() == viewport
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_run_without_samples_reports_error(
  qapp,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  messages: list[str] = []
  monkeypatch.setattr(
    "flowdesk_qt.main_window.QMessageBox.information",
    lambda _parent, _title, message: messages.append(message),
  )
  window = MainWindow()
  try:
    window._on_run_pipeline()
    assert messages == ["No samples loaded. Open a directory or files first."]
    assert window._worker is None
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_pipeline_exception_releases_worker(
  qapp,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fcs_path = tmp_path / "error.fcs"
  write_fcs_file(
    fcs_path,
    np.array([[1.0, 2.0]], dtype=np.float64),
    ["X", "Y"],
  )
  critical: list[str] = []
  monkeypatch.setattr(
    "flowdesk_qt.main_window.QMessageBox.critical",
    lambda _parent, _title, message: critical.append(message),
  )

  def fail_run(*_args, **_kwargs):
    raise RuntimeError("synthetic pipeline failure")

  monkeypatch.setattr(PipelineRunner, "run_samples", fail_run)
  window = MainWindow()
  try:
    window._sample_browser.add_samples_from_paths([str(fcs_path)])
    window._sample_browser.select_sample(window._sample_browser.samples()[0].id)
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    assert critical == ["synthetic pipeline failure"]
    assert "Pipeline error: synthetic pipeline failure" in window.statusBar().currentMessage()
    assert window._worker is None
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_cancel_pipeline_keeps_previous_results_stale(
  qapp,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fcs_path = tmp_path / "cancel.fcs"
  write_fcs_file(
    fcs_path,
    np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64),
    ["X", "Y"],
  )
  window = MainWindow()
  try:
    window._sample_browser.add_samples_from_paths([str(fcs_path)])
    window._sample_browser.select_sample(window._sample_browser.samples()[0].id)
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    previous = window._population_tree.last_report()
    assert previous is not None

    def wait_for_cancel(_runner, context, _samples):
      control = context.execution_control
      assert control is not None
      control.emit_progress(ProgressEvent(
        "test-pipeline", "pipeline", "sample_gating", 0, 1, "sample-1"
      ))
      while not control.cancellation_token.is_cancelled():
        time.sleep(0.005)
      raise ExecutionCancelled("execution cancelled")

    monkeypatch.setattr(PipelineRunner, "run_samples", wait_for_cancel)
    window._on_run_pipeline()
    assert window.action_cancel_pipeline.isEnabled()
    QTest.qWait(60)
    assert not window._pipeline_progress.isHidden()
    assert "Pipeline: sample_gating (sample-1) 0/1" in window.statusBar().currentMessage()
    window.action_cancel_pipeline.trigger()
    _wait_for_worker(window)
    qapp.processEvents()

    assert window._population_tree.last_report() is previous
    assert window._results_stale is True
    assert "Pipeline cancelled" in window.statusBar().currentMessage()
    assert window.action_run_pipeline.isEnabled()
    assert not window.action_cancel_pipeline.isEnabled()
    assert window._pipeline_progress.isHidden()
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_channel_mismatch_is_visible_but_does_not_use_shared_column_order(
  qapp,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  first = tmp_path / "first.fcs"
  second = tmp_path / "second.fcs"
  write_fcs_file(
    first,
    np.array([[1.0, 10.0], [3.0, 20.0]], dtype=np.float64),
    ["X", "Y"],
  )
  write_fcs_file(
    second,
    np.array([[10.0, 1.0], [20.0, 3.0]], dtype=np.float64),
    ["Y", "X"],
  )
  window = MainWindow()
  try:
    window._sample_browser.add_samples_from_paths([str(first), str(second)])
    x_id = window._sample_browser.samples()[0].info.channels[0].id
    window._gate_editor.set_gates([
      GateSpec(
        id="x_positive",
        name="X positive",
        gate_type="range",
        parent_population_id="all_events",
        x_parameter=x_id,
        thresholds={"min": 2.0},
      )
    ])
    window._sample_browser.select_sample(window._sample_browser.samples()[0].id)
    assert window._sample_browser.samples()[1].status == "order differs"
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    report = window._population_tree.last_report()
    assert report is not None
    assert {
      (result.sample_id, result.population_id): result.event_count
      for result in report.population_results
    } == {
      (window._sample_browser.samples()[0].id, "all_events"): 2,
      (window._sample_browser.samples()[0].id, "x_positive"): 1,
      (window._sample_browser.samples()[1].id, "all_events"): 2,
      (window._sample_browser.samples()[1].id, "x_positive"): 1,
    }
    assert window._worker is None
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.real_fcs
def test_switching_real_fcs_samples_updates_xy_ranges(
  qapp,
  gui_artifact_widgets: list[object],
) -> None:
  """Exercise every local FCS and verify sample-specific viewport behavior."""
  paths = sorted(DATA_DIR.glob("*.fcs"))
  if len(paths) < 2:
    pytest.skip("requires at least two external FCS files under data/")

  window = MainWindow()
  gui_artifact_widgets.append(window)
  try:
    window.resize(1200, 800)
    window.show()
    assert window._sample_browser.add_samples_from_paths(
      [str(path) for path in paths]
    ) == len(paths)

    samples = window._sample_browser.samples()
    common_channels = set(channel.name for channel in samples[0].info.channels)
    for sample in samples[1:]:
      common_channels.intersection_update(
        channel.name for channel in sample.info.channels
      )
    assert {"FSC-A", "SSC-A"}.issubset(common_channels)

    robust_ranges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    full_ranges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for sample in samples:
      assert window._sample_browser.select_sample(sample.id)
      window._channel_selector.set_selected_channels("FSC-A", "SSC-A")
      qapp.processEvents()


      assert window._current_sample_id == sample.id
      assert window._channel_selector.x_channel() == "FSC-A"
      assert window._channel_selector.y_channel() == "SSC-A"
      _wait_for_scatter(window)
      data = window._event_data[sample.id]
      assert data.flags.writeable is False

      window._plot_widget.set_robust_range()
      qapp.processEvents()
      robust = window._plot_widget.view_range()
      assert robust is not None
      x_index = window._channel_names.index("FSC-A")
      y_index = window._channel_names.index("SSC-A")
      x_low, x_high = np.nanpercentile(data[:, x_index], [0.5, 99.5])
      y_low, y_high = np.nanpercentile(data[:, y_index], [0.5, 99.5])
      assert robust[0][0] <= x_low < x_high <= robust[0][1]
      assert robust[1][0] <= y_low < y_high <= robust[1][1]
      robust_ranges.append(robust)

      window._plot_widget.set_full_range()
      qapp.processEvents()
      full = window._plot_widget.view_range()
      assert full is not None
      assert full[0][0] <= np.nanmin(data[:, x_index])
      assert full[0][1] >= np.nanmax(data[:, x_index])
      assert full[1][0] <= np.nanmin(data[:, y_index])
      assert full[1][1] >= np.nanmax(data[:, y_index])
      full_ranges.append(full)

      for axis_range in (*robust, *full):
        assert np.isfinite(axis_range).all()
        assert axis_range[0] < axis_range[1]

      # Return to automatic mode before selecting the next sample.
      window._plot_widget.set_robust_range()

    assert len({tuple(np.round(np.ravel(value), 6)) for value in robust_ranges}) > 1
    assert len({tuple(np.round(np.ravel(value), 6)) for value in full_ranges}) > 1

    manual = ((100_000.0, 200_000.0), (300_000.0, 400_000.0))
    window._plot_widget.set_manual_view_range(*manual)
    assert window._sample_browser.select_sample(samples[0].id)
    qapp.processEvents()
    assert window._plot_widget.range_mode() == "manual"
    assert np.allclose(window._plot_widget.view_range(), manual)
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_technical_override_gui_report_matches_headless_report(
  qapp,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fcs_path = tmp_path / "override.fcs"
  write_fcs_file(
    fcs_path,
    np.array([[0.0, 0.0], [2.0, 1.0], [3.0, 2.0], [4.0, 3.0]], dtype=np.float64),
    ["X", "Y"],
  )
  window = MainWindow()
  try:
    monkeypatch.setattr(
      "flowdesk_qt.main_window.QMessageBox.critical",
      lambda *_args: None,
    )
    window._sample_browser.add_samples_from_paths([str(fcs_path)])
    sample = window._sample_browser.samples()[0]
    window._sample_browser.select_sample(sample.id)
    gate = GateSpec(
      id="positive", name="Positive", gate_type="range",
      parent_population_id="all_events", x_parameter=sample.info.channels[0].id,
      thresholds={"min": 2.0, "max": 4.0},
    )
    window._gate_editor.set_gates([gate])
    window._gate_overrides = [{
      "id": "positive-sample-override", "sample_id": sample.id,
      "base_gate_id": gate.id, "base_version_hash": gate_version_hash(gate),
      "geometry_mode": "delta", "thresholds": {"min": 4.0},
      "author": "analyst", "created_at": "2026-07-17T00:00:00+00:00",
      "reason": "technical cleanup", "gate_purpose": "technical_cleanup",
    }]
    window._override_undo_stack = __import__(
      "flowdesk_core.project_commands", fromlist=["UndoStack"]
    ).UndoStack({"gate_overrides": window._gate_overrides})
    preflight_manifest = window._build_project_manifest()
    assert preflight_manifest["gate_overrides"][0]["base_version_hash"] == gate_version_hash(
      preflight_manifest["gating_strategies_data"]["default_strategy"]["gates"][0]
    )
    preflight_report = PipelineRunner(preflight_manifest).run_samples(
      ExecutionContext(), tuple(window._sample_data.values())
    )
    assert next(
      result.event_count for result in preflight_report.population_results
      if result.population_id == "positive"
    ) == 1
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()

    gui_report = window._population_tree.last_report()
    assert gui_report is not None
    headless_report = PipelineRunner(window._build_project_manifest()).run_samples(
      ExecutionContext(), tuple(window._sample_data.values())
    )
    gui_counts = {
      result.population_id: result.event_count
      for result in gui_report.population_results
      if result.sample_id == sample.id
    }
    headless_counts = {
      result.population_id: result.event_count
      for result in headless_report.population_results
      if result.sample_id == sample.id
    }
    assert gui_counts == headless_counts == {"all_events": 4, "positive": 1}
    assert window._display_gates()[0].thresholds["min"] == 4.0
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_comparison_warning_and_stale_rebase_are_visible_in_gui(
  qapp,
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fcs_path = tmp_path / "warning.fcs"
  write_fcs_file(fcs_path, np.array([[1.0], [2.0]], dtype=np.float64), ["X"])
  window = MainWindow()
  critical: list[str] = []
  try:
    monkeypatch.setattr(
      "flowdesk_qt.main_window.QMessageBox.critical",
      lambda _parent, _title, message: critical.append(message),
    )
    window._sample_browser.add_samples_from_paths([str(fcs_path)])
    sample = window._sample_browser.samples()[0]
    window._sample_browser.select_sample(sample.id)
    gate = GateSpec(
      id="gate", name="Gate", gate_type="range",
      parent_population_id="all_events", x_parameter=sample.info.channels[0].id,
      thresholds={"min": 1.0, "max": 2.0},
    )
    window._gate_editor.set_gates([gate])
    override = {
      "id": "critical", "sample_id": sample.id, "base_gate_id": gate.id,
      "base_version_hash": gate_version_hash(gate), "geometry_mode": "delta",
      "thresholds": {"min": 2.0}, "author": "analyst",
      "created_at": "2026-07-17T00:00:00+00:00", "reason": "comparison",
      "gate_purpose": "comparison_critical",
    }
    window._gate_overrides = [override]
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    assert window._population_tree.last_report() is not None
    diagnostic_codes = {
      window._diagnostics_panel._table.item(row, 1).text()
      for row in range(window._diagnostics_panel._table.rowCount())
      if window._diagnostics_panel._table.item(row, 1) is not None
    }
    assert "comparison_critical_override" in diagnostic_codes

    stale = dict(override, base_version_hash="stale")
    window._gate_overrides = [stale]
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    assert critical and "stale_override" in critical[-1]

    manifest = window._build_project_manifest()
    rebased_state = RebaseGateOverrideCommand(
      "default_strategy", "critical"
    ).apply({
      "gating_strategies_data": manifest["gating_strategies_data"],
      "gate_overrides": [stale],
    })
    window._gate_overrides = rebased_state["gate_overrides"]
    window._on_run_pipeline()
    _wait_for_worker(window)
    qapp.processEvents()
    assert window._population_tree.last_report() is not None
    assert window._worker is None
  finally:
    window.close()
    window.deleteLater()
    qapp.processEvents()
