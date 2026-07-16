from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.fcs_io import write_fcs_file
from flowdesk_core.models import GateSpec
from flowdesk_core.overrides import gate_version_hash
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.project_commands import RebaseGateOverrideCommand
from flowdesk_qt.main_window import MainWindow

pytestmark = [pytest.mark.gui, pytest.mark.gui_e2e]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _wait_for_worker(window: MainWindow) -> None:
  worker = window._worker
  assert worker is not None
  loop = QEventLoop()
  worker.finished.connect(loop.quit)
  QTimer.singleShot(5000, loop.quit)
  loop.exec()
  assert worker.isRunning() is False


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
    assert window._plot_widget._scatter is not None

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
      assert window._plot_widget._scatter is not None
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
