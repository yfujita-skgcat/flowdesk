from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from flowdesk_cli.batch_plot import batch_plot_command, write_plot_svg
from flowdesk_core.models import ChannelSpec
from flowdesk_core.sample import SampleData
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION
from flowdesk_storage.project import save_project


def test_batch_plot_uses_canonical_derived_display_data(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-derived",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{
      "id": "s1", "path": "sample.fcs",
      "channels": [
        {"id": "signal", "name": "Signal", "metadata": {}},
        {"id": "reference", "name": "Reference", "metadata": {}},
      ],
    }],
    "derived_parameters": [{
      "id": "ratio_definition", "name": "Ratio", "output_channel_id": "ratio",
      "expression": "signal / reference", "source_stage": "raw",
      "input_parameters": ["signal", "reference"],
      "invalid_value_policy": "emit_nan_with_warning",
    }],
    "plot_views": [{
      "id": "derived-view", "plot_type": "scatter",
      "population_id": "all_events", "x_parameter": "ratio",
      "y_parameter": "signal", "rendering_downsample": {"max_points": 0},
    }],
    "batch_plot_exports": [{
      "id": "derived-export", "name": "Derived export", "target": "all",
      "plot_view_id": "derived-view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-derived.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1",
    np.array([[2.0, 1.0], [4.0, 0.0], [6.0, 3.0]], dtype=np.float64),
    (ChannelSpec(id="signal", name="Signal"), ChannelSpec(id="reference", name="Reference")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )

  output_dir = tmp_path / "exports"
  assert batch_plot_command(str(project_path), "derived-export", str(output_dir)) == 0
  output = next(output_dir.glob("*.svg"))
  assert output.stat().st_size > 0
  sidecar = json.loads(output.with_suffix(".svg.json").read_text(encoding="utf-8"))
  assert sidecar["plot_view_id"] == "derived-view"
  assert sidecar["sources"][0]["x_parameter_id"] == "ratio"
  assert sidecar["sources"][0]["y_parameter_id"] == "signal"
  assert sidecar["presentation"]["x_axis_display_label"] == "Ratio"
  assert sidecar["presentation"]["y_axis_display_label"] == "Signal"


def test_batch_plot_renders_manual_overlay_sources_in_order(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-overlay",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [
      {"id": "s1", "path": "a.fcs", "name": "A", "channels": []},
      {"id": "s2", "path": "b.fcs", "name": "B", "channels": []},
    ],
    "plot_views": [{
      "id": "overlay-view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "manual_overlay_sample_ids": ["s2"],
      "presentation": {"title": "Overlay", "source_styles": [
        {"source_id": "s2", "color": "#ff0000"},
      ]},
    }],
    "gating_strategies_data": {"default": {
      "id": "default", "name": "Default", "gates": [{
        "id": "gate-1", "name": "Gate", "gate_type": "rectangle",
        "x_parameter": "x", "y_parameter": "y",
        "thresholds": {"x_min": 1.0, "x_max": 2.0, "y_min": 1.0, "y_max": 2.0},
        "color": "#00ff00",
      }],
    }},
    "batch_plot_exports": [{
      "id": "overlay-export", "name": "Overlay export", "target": "explicit",
      "sample_ids": ["s1"], "plot_view_id": "overlay-view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-overlay.flowdesk"
  save_project(project_path, project)
  samples = {
    "s1": SampleData("s1", np.array([[1.0, 1.0], [2.0, 2.0]]),
                     (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y"))),
    "s2": SampleData("s2", np.array([[3.0, 3.0], [4.0, 4.0]]),
                     (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y"))),
  }
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": key, "path": f"{key}.fcs", "name": key.upper()}
                    for key in ("s1", "s2")],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample",
    lambda path, *_args: (None, samples[Path(path).stem]),
  )
  output_dir = tmp_path / "exports"
  assert batch_plot_command(str(project_path), "overlay-export", str(output_dir)) == 0
  text = next(output_dir.glob("*.svg")).read_text(encoding="utf-8")
  assert 'fill="#ff0000"' in text
  assert 'stroke="#00ff00"' in text
  metadata = json.loads(next(output_dir.glob("*.svg.json")).read_text(encoding="utf-8"))
  assert metadata["ordered_source_ids"] == ["s1", "s2"]


def test_batch_plot_applies_persisted_transform_once(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-transform",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{"id": "s1", "path": "sample.fcs", "channels": []}],
    "transforms": [{
      "id": "tx", "name": "X log", "transform_type": "log", "parameter": "x",
      "settings": {"base": 10.0, "invalid_value_policy": "to_nan"}, "role": "analysis",
    }],
    "plot_views": [{
      "id": "transform-view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "x_transform_id": "tx",
      "y_transform_id": None, "rendering_downsample": {"max_points": 0},
    }],
    "gating_strategies_data": {"default_strategy": {
      "id": "default_strategy", "name": "Default", "root_population_id": "all_events",
      "gates": [{
        "id": "gate-x", "name": "Gate", "gate_type": "rectangle",
        "parent_population_id": "all_events", "x_parameter": "x", "y_parameter": "y",
        "x_transform_id": "tx", "y_transform_id": None,
        "thresholds": {"x_min": 0.0, "x_max": 2.0, "y_min": 1.0, "y_max": 3.0},
      }],
    }},
    "batch_plot_exports": [{
      "id": "transform-export", "name": "Transform export", "target": "all",
      "plot_view_id": "transform-view", "formats": ["svg"],
    }],
  }
  project_path = tmp_path / "batch-transform.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1", np.array([[1.0, 1.0], [10.0, 2.0], [100.0, 3.0]]),
    (ChannelSpec(id="x", name="X"), ChannelSpec(id="y", name="Y")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )
  captured: dict[str, object] = {}
  def capture(*args, **kwargs):
    captured["layers"] = kwargs["layers"]
    return write_plot_svg(*args, **kwargs)

  monkeypatch.setattr("flowdesk_cli.batch_plot.write_plot_svg", capture)
  assert batch_plot_command(
    str(project_path), "transform-export", str(tmp_path / "exports")
  ) == 0
  layer = captured["layers"]["s1"]
  assert len(layer[0]) == 3
  assert layer[0] == (0.0, 0.5, 1.0)
  sidecar = json.loads(
    next((tmp_path / "exports").glob("*.svg.json")).read_text(encoding="utf-8")
  )
  assert len(sidecar["gate_overlays"]) == 1
  assert sidecar["gate_overlays"][0]["color"] == "#e00000"


def test_batch_plot_current_view_uses_persisted_labels_and_range(
  tmp_path: Path, monkeypatch
) -> None:
  project = {
    "project_id": "batch-current-view",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default"}],
    "samples": [{"id": "s1", "path": "sample.fcs", "channels": []}],
    "plot_views": [{
      "id": "view", "plot_type": "scatter", "population_id": "all_events",
      "x_parameter": "x", "y_parameter": "y", "rendering_downsample": {"max_points": 0},
      "display_scene": {
        "x_axis_label": "FITC B525-A", "y_axis_label": "APC R660-A",
        "view_range": [[0.0, 4.0], [0.0, 4.0]],
      },
    }],
    "batch_plot_exports": [{
      "id": "export", "name": "Export", "target": "all", "plot_view_id": "view",
      "formats": ["svg"], "layout_policy": "current_view",
    }],
  }
  project_path = tmp_path / "batch-current-view.flowdesk"
  save_project(project_path, project)
  sample = SampleData(
    "s1", np.array([[1.0, 1.0], [2.0, 2.0], [8.0, 8.0]]),
    (ChannelSpec(id="x", name="FL1-A"), ChannelSpec(id="y", name="FL3-A")),
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.resolve_sample_paths",
    lambda *_args: [{"id": "s1", "path": "sample.fcs", "name": "Sample"}],
  )
  monkeypatch.setattr(
    "flowdesk_cli.batch_plot.read_fcs_sample", lambda *_args: (None, sample)
  )
  captured: dict[str, object] = {}

  def capture(*args, **kwargs):
    captured["layers"] = kwargs["layers"]
    return write_plot_svg(*args, **kwargs)

  monkeypatch.setattr("flowdesk_cli.batch_plot.write_plot_svg", capture)
  assert batch_plot_command(str(project_path), "export", str(tmp_path / "exports")) == 0
  assert captured["layers"]["s1"] == ((0.25, 0.5), (0.25, 0.5))
  sidecar = json.loads(
    next((tmp_path / "exports").glob("*.svg.json")).read_text(encoding="utf-8")
  )
  assert sidecar["presentation"]["x_axis_display_label"] == "FITC B525-A"
  assert sidecar["presentation"]["y_axis_display_label"] == "APC R660-A"
