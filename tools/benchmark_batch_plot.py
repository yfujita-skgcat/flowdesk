#!/usr/bin/env python3
"""Benchmark sequential and bounded-thread Batch Plot rendering.

This benchmark exercises the renderer-neutral core writers with deterministic
prepared sample layers. It is a diagnostic tool, not a CI timing threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

import numpy as np

from flowdesk_core.batch_plot_export import run_batch_plot_export
from flowdesk_core.execution_control import (
  ExecutionBackend,
  ExecutionControl,
  ExecutionOptions,
)
from flowdesk_core.models import BatchPlotExportSpec
from flowdesk_core.plot_export import (
  prepare_plot_export,
  write_plot_pdf,
  write_plot_png,
  write_plot_svg,
)
from flowdesk_core.plot_presentation import OverlaySourceResolution


class _RunResult(TypedDict):
  backend: str
  elapsed_seconds: float
  output_bytes: int
  status: str
  execution: Mapping[str, Any] | None
  peak_rss_bytes: int | None
  open_file_count_after: int | None


class _ProjectRunResult(TypedDict):
  backend: str
  elapsed_seconds: float
  status: str
  return_code: int
  output_hashes: Mapping[str, str]
  output_bytes: int
  execution: Mapping[str, Any] | None
  peak_rss_bytes: int | None
  open_file_count_after: int | None
  stderr_tail: str


def _peak_rss_bytes() -> int | None:
  """Return process peak RSS using the platform's standard-library API."""
  try:
    import resource
  except ImportError:
    return None
  value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
  # Linux and other Unix systems report KiB; macOS reports bytes.
  return value * 1024 if sys.platform != "darwin" else value


def _open_file_count() -> int | None:
  """Return the current open-descriptor count where the OS exposes it."""
  proc_fd = "/proc/self/fd"
  if not os.path.isdir(proc_fd):
    return None
  try:
    return len(os.listdir(proc_fd))
  except OSError:
    return None


def _output_hashes(output_dir: Path) -> tuple[dict[str, str], int]:
  """Hash only published plot files, excluding sidecars and the manifest."""
  hashes: dict[str, str] = {}
  output_bytes = 0
  if not output_dir.is_dir():
    return hashes, output_bytes
  for path in sorted(output_dir.iterdir()):
    if not path.is_file() or path.suffix.lower() not in {
      ".png", ".jpg", ".jpeg", ".svg", ".pdf",
    }:
      continue
    data = path.read_bytes()
    hashes[path.name] = hashlib.sha256(data).hexdigest()
    output_bytes += len(data)
  return hashes, output_bytes


def _prepare_representative_project(project: Path, destination_root: Path) -> Path:
  """Copy a project and add deterministic scientific stages for benchmarking."""
  if not project.is_dir():
    raise NotADirectoryError(project)
  destination = destination_root / project.name
  shutil.copytree(project, destination)
  manifest_path = destination / "manifest.json"
  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  samples = manifest.get("samples", [])
  if not samples:
    raise ValueError("representative project must contain samples")
  for sample in samples:
    sample_path = Path(str(sample.get("path", "")))
    if not sample_path.is_absolute():
      sample_path = (project / sample_path).resolve()
    sample["path"] = str(sample_path)
  channels = {
    str(channel.get("name")): str(channel.get("id"))
    for channel in samples[0].get("channels", [])
    if channel.get("name") and channel.get("id")
  }
  x_id = channels.get("FSC-A")
  y_id = channels.get("SSC-A")
  if not x_id or not y_id:
    raise ValueError("representative project requires FSC-A and SSC-A channels")
  matrix_id = "benchmark_identity_compensation"
  manifest["compensation_matrices"] = [{
    "id": matrix_id,
    "name": "Benchmark identity compensation",
    "source": "user_defined",
    "channels": [x_id, y_id],
    "matrix": [[1.0, 0.0], [0.0, 1.0]],
  }]
  manifest["default_compensation_matrix_id"] = matrix_id
  manifest["derived_parameters"] = [{
    "id": "benchmark_ratio",
    "output_channel_id": "benchmark_ratio",
    "name": "FSC-A / SSC-A ratio",
    "expression": f"{x_id} / {y_id}",
    "input_parameters": [x_id, y_id],
    "invalid_value_policy": "fail_run",
    "non_finite_policy": "strict",
    "source_stage": "compensated",
  }]
  strategies = manifest.get("gating_strategies_data", {})
  gate_ids = [
    str(gate.get("id"))
    for strategy in strategies.values()
    if isinstance(strategy, dict)
    for gate in strategy.get("gates", [])
    if isinstance(gate, dict) and gate.get("id")
  ]
  if not gate_ids:
    raise ValueError("representative project requires a gate")
  manifest["statistics"] = [{
    "id": "benchmark_gate_count",
    "name": "Benchmark gate count",
    "population_id": gate_ids[0],
    "metric": "count",
    "source_stage": "compensated",
  }]
  manifest_path.write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
  )
  return destination


def _run_project_backend(
  project: Path,
  export_id: str,
  output_dir: Path,
  backend: ExecutionBackend,
  max_workers: int,
  memory_budget_mib: int | None,
  timeout_seconds: float = 300.0,
) -> _ProjectRunResult:
  """Run one project export with bounded lifetime and isolated RSS accounting."""
  child_code = """
import json
import os
import sys
from flowdesk_cli.main import main

status = main()
try:
  import resource
except ImportError:
  resource = None
usage = None if resource is None else resource.getrusage(resource.RUSAGE_SELF)
rss = None if usage is None else int(
  usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
)
fd_count = None
if os.path.isdir("/proc/self/fd"):
  try:
    fd_count = len(os.listdir("/proc/self/fd"))
  except OSError:
    pass
print("__FLOWDESK_BENCHMARK_CHILD__" + json.dumps({
  "status": status, "peak_rss_bytes": rss, "open_file_count_after": fd_count,
}))
raise SystemExit(status)
"""
  command = [
    sys.executable, "-c", child_code, "batch-plot", str(project),
    "--export-id", export_id, "--output-dir", str(output_dir),
    "--execution-backend", backend, "--max-workers", str(max_workers),
  ]
  if memory_budget_mib is not None:
    command.extend(["--memory-budget-mib", str(memory_budget_mib)])
  output_dir.mkdir(parents=True, exist_ok=True)
  started = time.perf_counter()
  timed_out = False
  timeout_stderr = ""
  try:
    completed = subprocess.run(
      command, capture_output=True, text=True, check=False,
      timeout=timeout_seconds,
    )
  except subprocess.TimeoutExpired as exc:
    timed_out = True
    timeout_stderr = str(exc.stderr or exc.stdout or "")
    completed = None
  elapsed = time.perf_counter() - started
  child_result: dict[str, Any] = {}
  marker = "__FLOWDESK_BENCHMARK_CHILD__"
  stdout = "" if completed is None else completed.stdout
  for line in reversed(stdout.splitlines()):
    if line.startswith(marker):
      child_result = json.loads(line[len(marker):])
      break
  manifest_paths = sorted(output_dir.glob("*.batch.json"))
  execution: Mapping[str, Any] | None = None
  status = "timeout" if timed_out else "failed"
  if manifest_paths:
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    status = str(manifest.get("status", status))
    value = manifest.get("execution")
    if isinstance(value, Mapping):
      execution = dict(value)
  hashes, output_bytes = _output_hashes(output_dir)
  stderr = timeout_stderr if timed_out else (completed.stderr if completed else "")
  return {
    "backend": backend,
    "elapsed_seconds": elapsed,
    "status": status,
    "return_code": 124 if timed_out else (completed.returncode if completed else 1),
    "output_hashes": hashes,
    "output_bytes": output_bytes,
    "execution": execution,
    "peak_rss_bytes": child_result.get("peak_rss_bytes"),
    "open_file_count_after": child_result.get("open_file_count_after"),
    "stderr_tail": stderr[-2000:],
  }


def run_project_batch_plot_benchmark(
  *, project: Path | str, export_id: str, max_workers: int = 2,
  memory_budget_mib: int | None = None, scientific_stages: bool = False,
  timeout_seconds: float = 300.0,
) -> dict[str, object]:
  """Compare sequential/thread rendering for a real saved project.

  Each backend runs in a fresh child process so peak RSS is not contaminated by
  the preceding run.  Output hashes are retained for an explicit parity check.
  """
  if max_workers < 1:
    raise ValueError("max_workers must be positive")
  if memory_budget_mib is not None and memory_budget_mib < 1:
    raise ValueError("memory_budget_mib must be positive when set")
  if timeout_seconds <= 0:
    raise ValueError("timeout_seconds must be positive")
  project_path = Path(project)
  if not project_path.exists():
    raise FileNotFoundError(project_path)
  runs: dict[str, _ProjectRunResult] = {}
  with tempfile.TemporaryDirectory(prefix="flowdesk-project-benchmark-") as root:
    root_path = Path(root)
    benchmark_project = (
      _prepare_representative_project(project_path, root_path)
      if scientific_stages else project_path
    )
    for backend in ("sequential", "thread"):
      runs[backend] = _run_project_backend(
        benchmark_project, export_id, root_path / backend, backend, max_workers,
        memory_budget_mib, timeout_seconds,
      )
  sequential = runs["sequential"]
  threaded = runs["thread"]
  sequential_hashes = dict(sequential["output_hashes"])
  threaded_hashes = dict(threaded["output_hashes"])
  return {
    "project": str(project_path),
    "export_id": export_id,
    "scientific_stages": scientific_stages,
    "timeout_seconds": timeout_seconds,
    "max_workers": max_workers,
    "memory_budget_mib": memory_budget_mib,
    "sequential": sequential,
    "thread": threaded,
    "output_names_match": set(sequential_hashes) == set(threaded_hashes),
    "output_hashes_match": sequential_hashes == threaded_hashes,
    "thread_speedup": (
      sequential["elapsed_seconds"] / threaded["elapsed_seconds"]
      if threaded["elapsed_seconds"] else None
    ),
  }


def run_batch_plot_benchmark(
  *,
  sample_count: int = 8,
  event_count: int = 5_000,
  max_workers: int = 2,
  seed: int = 1729,
  memory_budget_mib: int | None = None,
) -> dict[str, object]:
  """Return timing and output-size diagnostics for serial and thread backends."""
  if sample_count < 1 or event_count < 1 or max_workers < 1:
    raise ValueError("sample_count, event_count, and max_workers must be positive")
  if memory_budget_mib is not None and memory_budget_mib < 1:
    raise ValueError("memory_budget_mib must be positive when set")
  rng = np.random.default_rng(seed)
  samples = [
    {"id": f"s{index + 1}", "name": f"Sample {index + 1}", "path": f"s{index + 1}.fcs"}
    for index in range(sample_count)
  ]
  prepared = {
    sample["id"]: prepare_plot_export(
      "benchmark-view",
      "scatter",
      ({
        "source_id": sample["id"],
        "sample_id": sample["id"],
        "population_id": "all_events",
        "display_name": sample["name"],
        "visible": True,
      },),
      (OverlaySourceResolution(sample["id"], "compatible"),),
    )
    for sample in samples
  }
  layers = {
    sample["id"]: {
      sample["id"]: (
        tuple(np.clip(rng.normal(0.5, 0.18, event_count), 0.0, 1.0)),
        tuple(np.clip(rng.normal(0.5, 0.18, event_count), 0.0, 1.0)),
      ),
    }
    for sample in samples
  }
  spec = BatchPlotExportSpec(
    id="batch-benchmark",
    name="Batch benchmark",
    formats=("png", "svg", "pdf"),
    width=640,
    height=480,
    vector_scatter_mode="compact_vector",
  )

  def render(
    sample: Mapping[str, str], path: Path, options: BatchPlotExportSpec
  ) -> None:
    sample_id = sample["id"]
    prepared_plot = prepared[sample_id]
    prepared_layers = layers[sample_id]
    if path.suffix == ".png":
      write_plot_png(
        path, prepared_plot, layers=prepared_layers,
        width=options.width, height=options.height, options=options,
      )
    elif path.suffix == ".svg":
      write_plot_svg(path, prepared_plot, layers=prepared_layers, options=options)
    elif path.suffix == ".pdf":
      write_plot_pdf(
        path, prepared_plot, layers=prepared_layers,
        width=options.width, height=options.height, options=options,
      )
    else:
      raise ValueError(path.suffix)

  def run(backend: ExecutionBackend) -> _RunResult:
    with tempfile.TemporaryDirectory(prefix=f"flowdesk-batch-{backend}-") as directory:
      output_dir = Path(directory)
      control = ExecutionControl(options=ExecutionOptions(
        backend=backend, max_workers=max_workers,
        memory_budget_bytes=(
          None if memory_budget_mib is None else memory_budget_mib * 1024 * 1024
        ),
      ))
      started = time.perf_counter()
      report = run_batch_plot_export(
        spec,
        samples,
        output_dir,
        render,
        estimate_render_bytes=lambda: max(
          (len(x) + len(y)) * 8
          for sample_layers in layers.values()
          for x, y in sample_layers.values()
        ) * 4,
        execution_control=control,
      )
      elapsed = time.perf_counter() - started
      output_bytes = sum(
        path.stat().st_size
        for path in output_dir.iterdir()
        if path.is_file() and not path.name.endswith(".json")
      )
      return {
        "backend": backend,
        "elapsed_seconds": elapsed,
        "output_bytes": output_bytes,
        "status": report.status,
        "execution": report.execution_provenance,
        "peak_rss_bytes": _peak_rss_bytes(),
        "open_file_count_after": _open_file_count(),
      }

  serial = run("sequential")
  threaded = run("thread")
  return {
    "sample_count": sample_count,
    "event_count": event_count,
    "max_workers": max_workers,
    "memory_budget_mib": memory_budget_mib,
    "seed": seed,
    "sequential": serial,
    "thread": threaded,
    "thread_speedup": (
      serial["elapsed_seconds"] / threaded["elapsed_seconds"]
      if threaded["elapsed_seconds"] else None
    ),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--samples", type=int, default=8)
  parser.add_argument("--events", type=int, default=5_000)
  parser.add_argument("--max-workers", type=int, default=2)
  parser.add_argument(
    "--memory-budget-mib", type=int,
    help="Limit estimated in-flight batch render memory in project mode.",
  )
  parser.add_argument("--seed", type=int, default=1729)
  parser.add_argument(
    "--project", type=Path,
    help="Benchmark a saved project instead of generating synthetic layers.",
  )
  parser.add_argument(
    "--scientific-stages", action="store_true",
    help="Copy --project and add compensation, derived data, and statistics.",
  )
  parser.add_argument(
    "--timeout-seconds", type=float, default=300.0,
    help="Fail each project child process after this many seconds.",
  )
  parser.add_argument(
    "--export-id",
    help="Batch export definition ID required with --project.",
  )
  parser.add_argument("--output", type=Path)
  args = parser.parse_args()
  if args.project is not None:
    if not args.export_id:
      parser.error("--export-id is required with --project")
    result = run_project_batch_plot_benchmark(
      project=args.project, export_id=args.export_id, max_workers=args.max_workers,
      memory_budget_mib=args.memory_budget_mib,
      scientific_stages=args.scientific_stages,
      timeout_seconds=args.timeout_seconds,
    )
  else:
    result = run_batch_plot_benchmark(
      sample_count=args.samples,
      event_count=args.events,
      max_workers=args.max_workers,
      seed=args.seed,
      memory_budget_mib=args.memory_budget_mib,
    )
  rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
  if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
  print(rendered, end="")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
