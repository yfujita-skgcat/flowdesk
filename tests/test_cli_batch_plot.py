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
    "samples": [{
      "id": "s1", "path": "sample.fcs",
      "channels": [
        {"id": "signal", "name": "Signal", "metadata": {}},
        {"id": "reference", "name": "Reference", "metadata": {}},
      ],
    }],
    "execution_profiles": [{"id": "default", "name": "Default"}],
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
