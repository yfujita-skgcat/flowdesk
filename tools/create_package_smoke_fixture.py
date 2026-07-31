"""Create a small deterministic project and FCS fixture for package CI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from flowdesk_core.fcs_io import read_fcs_info, write_fcs_file

EXPORT_ID = "package-smoke-export"


def create_fixture(output_dir: Path) -> tuple[Path, Path, str]:
  """Write a self-contained project bundle and its referenced FCS file."""
  output_dir.mkdir(parents=True, exist_ok=True)
  fcs_path = output_dir / "sample.fcs"
  project_path = output_dir / "project.flowdesk"

  rng = np.random.default_rng(1729)
  events = np.column_stack((
    rng.lognormal(mean=5.0, sigma=0.35, size=256),
    rng.lognormal(mean=5.2, sigma=0.4, size=256),
    rng.lognormal(mean=4.5, sigma=0.3, size=256),
    rng.lognormal(mean=4.7, sigma=0.3, size=256),
  )).astype(np.float64)
  channel_names = ["FSC-A", "SSC-A", "FL1-A", "FL2-A"]
  write_fcs_file(fcs_path, events, channel_names)
  info = read_fcs_info(fcs_path)
  channels = [
    {
      "id": channel.id,
      "name": channel.name,
      "short_name": channel.short_name,
      "detector": channel.detector,
      "unit": channel.unit,
      "metadata": dict(channel.metadata),
      "fcs_parameter_index": channel.fcs_parameter_index,
      "stain": channel.stain,
    }
    for channel in info.channels
  ]
  channel_by_name = {channel["name"]: channel["id"] for channel in channels}
  sample_id = "package_sample"
  view_id = "package-smoke-view"
  manifest = {
    "project_id": "package_smoke_project",
    "project_version": "1.8.0",
    "pipeline_version": "0.1",
    "samples": [{
      "id": sample_id,
      "name": "Package smoke sample",
      "path": "../sample.fcs",
      "channels": channels,
    }],
    "gating_strategies_data": {},
    "execution_profiles": [{
      "id": "default",
      "sample_selector": "all",
      "gating_strategy_id": None,
    }],
    "transforms": [],
    "batch_plot_exports": [{
      "id": EXPORT_ID,
      "name": "Package smoke export",
      "target": "all",
      "sample_ids": [],
      "group_id": None,
      "plot_view_id": view_id,
      "formats": ["png"],
      "width": 640,
      "height": 480,
      "dpi": 96,
      "raster_resolution_mode": "legacy_pixel_dimensions",
      "vector_scatter_mode": "hybrid_raster",
      "hybrid_scatter_dpi": 300,
      "max_workers": 1,
      "memory_budget_mib": None,
      "density_workers": 1,
      "density_memory_budget_mib": None,
      "aspect_1_to_1": False,
      "layout_policy": "current_view",
      "include_title": True,
      "include_axis_labels": True,
      "include_ticks": True,
      "include_gates": False,
      "include_legend": False,
      "include_status_banner": False,
      "filename_template": "{sample_title}",
      "collision_policy": "replace",
      "strict": True,
    }],
    "plot_views": [{
      "id": view_id,
      "population_id": "all_events",
      "x_parameter": channel_by_name["FSC-A"],
      "y_parameter": channel_by_name["SSC-A"],
      "x_transform_id": None,
      "y_transform_id": None,
      "plot_type": "scatter",
      "manual_overlay_sample_ids": [],
      "manual_overlay_colors": {},
      "overlay_mode": "manual_only",
      "rendering_downsample": {"max_points": 0},
      "display_scene": {},
      "presentation": {},
    }],
  }
  project_path.mkdir(parents=True, exist_ok=True)
  (project_path / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
  )
  return project_path, fcs_path, EXPORT_ID


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output-dir", type=Path, required=True)
  args = parser.parse_args()
  project, fcs, export_id = create_fixture(args.output_dir)
  print(f"project={project}")
  print(f"fcs={fcs}")
  print(f"export-id={export_id}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
