"""Run smoke checks against already-built native package executables.

This script deliberately runs outside the application package. It is suitable
for a clean virtual machine where Python is not installed, provided the test
runner itself is available through the CI image or copied beside the artifact.
The GUI and CLI executables are passed separately because the GUI must not own
headless scientific execution logic.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], *, timeout: int, env: dict[str, str]) -> None:
  completed = subprocess.run(
    command,
    check=False,
    capture_output=True,
    text=True,
    timeout=timeout,
    env=env,
  )
  if completed.returncode != 0:
    details = (completed.stdout + completed.stderr).strip()
    raise RuntimeError(
      f"package command failed ({completed.returncode}): {' '.join(command)}\n{details}"
    )


def run_smoke(
  gui_executable: Path | None,
  cli_executable: Path | None,
  project: Path | None,
  fcs_file: Path | None,
  output_dir: Path,
  timeout: int = 60,
  qt_platform: str | None = None,
  batch_export_id: str | None = None,
) -> None:
  """Validate GUI startup and optional headless package operations."""
  output_dir.mkdir(parents=True, exist_ok=True)
  env = os.environ.copy()
  if qt_platform is not None:
    env["QT_QPA_PLATFORM"] = qt_platform

  if gui_executable is not None:
    report_path = output_dir / "gui-smoke-report.json"
    _run(
      [
        str(gui_executable),
        "--test-mode",
        "--debug-artifacts-dir",
        str(output_dir / "gui-artifacts"),
        "--smoke-report",
        str(report_path),
      ],
      timeout=timeout,
      env=env,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "ok" or report.get("main_window_created") is not True:
      raise RuntimeError(f"invalid GUI smoke report: {report}")
    if report.get("platform") != platform.system().lower():
      raise RuntimeError(f"unexpected smoke platform: {report}")

  if cli_executable is None:
    return
  if project is None:
    raise ValueError("--project is required when --cli is provided")

  if fcs_file is not None:
    _run([str(cli_executable), "inspect", str(fcs_file)], timeout=timeout, env=env)

  result_path = output_dir / "results.tsv"
  _run(
    [
      str(cli_executable),
      "run",
      str(project),
      "--output",
      str(result_path),
      "--include-qc",
    ],
    timeout=timeout,
    env=env,
  )
  if not result_path.is_file() or result_path.stat().st_size == 0:
    raise RuntimeError(f"package pipeline did not create a non-empty result: {result_path}")

  if batch_export_id is None:
    return
  batch_output = output_dir / "batch-export"
  _run(
    [
      str(cli_executable),
      "batch-plot",
      str(project),
      "--export-id",
      batch_export_id,
      "--output-dir",
      str(batch_output),
    ],
    timeout=timeout,
    env=env,
  )
  manifest = batch_output / f"{batch_export_id}.batch.json"
  if not manifest.is_file() or manifest.stat().st_size == 0:
    raise RuntimeError(f"package batch export did not create a non-empty manifest: {manifest}")
  output_files = [
    path for path in batch_output.iterdir()
    if path.is_file() and path.name != manifest.name and path.stat().st_size > 0
  ]
  if not output_files:
    raise RuntimeError(f"package batch export did not create non-empty outputs: {batch_output}")


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--gui", type=Path)
  parser.add_argument("--cli", type=Path)
  parser.add_argument("--project", type=Path)
  parser.add_argument("--fcs", type=Path)
  parser.add_argument("--output-dir", type=Path, required=True)
  parser.add_argument("--timeout", type=int, default=60)
  parser.add_argument("--qt-platform", default=None)
  parser.add_argument("--batch-export-id")
  args = parser.parse_args()

  try:
    run_smoke(
      args.gui,
      args.cli,
      args.project,
      args.fcs,
      args.output_dir,
      args.timeout,
      args.qt_platform,
      args.batch_export_id,
    )
  except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
    print(f"package smoke test failed: {exc}", file=sys.stderr)
    return 1
  print(f"package smoke test passed: {args.output_dir}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
