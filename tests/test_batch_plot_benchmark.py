from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _benchmark_module():
  path = Path(__file__).parents[1] / "tools" / "benchmark_batch_plot.py"
  spec = importlib.util.spec_from_file_location("flowdesk_batch_benchmark", path)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_project_benchmark_compares_hashes_and_isolates_backends(tmp_path, monkeypatch) -> None:
  module = _benchmark_module()
  project = tmp_path / "project.flowdesk"
  project.write_text("placeholder", encoding="utf-8")

  def fake_run(project_path, export_id, output_dir, backend, max_workers, memory_budget_mib):
    assert project_path == project
    assert export_id == "export"
    assert max_workers == 2
    assert memory_budget_mib == 128
    return {
      "backend": backend,
      "elapsed_seconds": 2.0 if backend == "sequential" else 1.0,
      "status": "success",
      "return_code": 0,
      "output_hashes": {"plot.png": "same"},
      "output_bytes": 10,
      "execution": {"backend": backend},
      "peak_rss_bytes": 100,
      "open_file_count_after": 4,
      "stderr_tail": "",
    }

  monkeypatch.setattr(module, "_run_project_backend", fake_run)
  result = module.run_project_batch_plot_benchmark(
    project=project, export_id="export", max_workers=2, memory_budget_mib=128,
  )

  assert result["output_names_match"] is True
  assert result["output_hashes_match"] is True
  assert result["thread_speedup"] == 2.0
  assert result["memory_budget_mib"] == 128


def test_representative_project_copy_adds_scientific_stages(tmp_path) -> None:
  module = _benchmark_module()
  project = tmp_path / "project.flowdesk"
  project.mkdir()
  (tmp_path / "sample.fcs").write_bytes(b"fixture")
  (project / "manifest.json").write_text(json.dumps({
    "samples": [{
      "id": "s1",
      "path": "../sample.fcs",
      "channels": [
        {"id": "fsc", "name": "FSC-A"},
        {"id": "ssc", "name": "SSC-A"},
      ],
    }],
    "gating_strategies_data": {
      "default": {"gates": [{"id": "gate1"}]},
    },
  }), encoding="utf-8")

  copied = module._prepare_representative_project(project, tmp_path / "copy")
  manifest = json.loads((copied / "manifest.json").read_text(encoding="utf-8"))
  assert Path(manifest["samples"][0]["path"]).is_absolute()
  assert manifest["default_compensation_matrix_id"] == (
    "benchmark_identity_compensation"
  )
  assert manifest["derived_parameters"][0]["source_stage"] == "compensated"
  assert manifest["statistics"][0]["population_id"] == "gate1"
