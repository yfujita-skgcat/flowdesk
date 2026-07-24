from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from flowdesk_cli.batch_plot import batch_plot_command
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
