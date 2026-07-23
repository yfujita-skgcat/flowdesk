"""Batch gate command: apply gates to FCS files and export results."""

from __future__ import annotations

import sys
from pathlib import Path

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.export import (
  ExportError,
  write_results_wide,
)
from flowdesk_core.pipeline_runner import PipelineError, run_project_pipeline
from flowdesk_storage.manifest import ManifestValidationError
from flowdesk_storage.project import load_project


def batch_gate_command(
  project_path: str,
  fcs_files: list[str],
  output: str | None = None,
  execution_profile_id: str = "default",
) -> int:
  """CLI adapter for batch gating multiple FCS files.

  Loads a project, overrides sample paths with provided FCS files,
  runs the pipeline, and exports population statistics.

  Args:
    project_path: Path to the ``.flowdesk`` project bundle directory.
    fcs_files: List of FCS file paths to process.
    output: Path for the TSV export file. If omitted, results are not
        written to disk.
    execution_profile_id: Id of the execution profile to run.

  Returns:
    Exit code: 0 on success, 1 on error.
  """

  # ------------------------------------------------------------------
  # Load project
  # ------------------------------------------------------------------
  try:
    project = load_project(project_path)
  except FileNotFoundError as exc:
    print(f"Error: project not found: {project_path}", file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    return 1
  except ManifestValidationError as exc:
    print("Error: project manifest validation failed:", file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    return 1
  except Exception as exc:
    print(f"Error: failed to load project: {project_path}", file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    return 1

  # ------------------------------------------------------------------
  # Override sample paths with provided FCS files
  # ------------------------------------------------------------------
  samples = []
  for fcs_path in fcs_files:
    p = Path(fcs_path)
    if not p.exists():
      print(f"Error: FCS file not found: {fcs_path}", file=sys.stderr)
      return 1
    samples.append({
      "id": p.stem,
      "fcs_file": str(p.resolve()),
    })

  project["samples"] = samples

  # ------------------------------------------------------------------
  # Run pipeline
  # ------------------------------------------------------------------
  try:
    report = run_project_pipeline(
      project,
      output_dir=None,
      execution_profile_id=execution_profile_id,
    )
  except PipelineError as exc:
    print("Error: pipeline execution failed:", file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    return 1
  except FlowdeskError as exc:
    print(f"Error: {exc}", file=sys.stderr)
    return 1

  # ------------------------------------------------------------------
  # Print summary
  # ------------------------------------------------------------------
  print(report.summary)

  if report.messages:
    for msg in report.messages:
      print(f"  {msg}")

  # ------------------------------------------------------------------
  # Export results
  # ------------------------------------------------------------------
  if output is not None:
    try:
      delimiter = "," if output.lower().endswith(".csv") else "\t"
      write_results_wide(report, project, output, delimiter=delimiter)
      print(f"Exported unified Results to {output}")
    except ExportError as exc:
      print("Error: export failed:", file=sys.stderr)
      print(f"  {exc}", file=sys.stderr)
      return 1

  # ------------------------------------------------------------------
  # Determine exit code from status
  # ------------------------------------------------------------------
  status = report.status
  if status == "success":
    return 0
  if status == "placeholder_complete":
    return 0
  if status == "no_data_processed":
    print("Warning: no data was processed.", file=sys.stderr)
    return 0
  if "failed" in status:
    print(f"Error: pipeline status: {status}", file=sys.stderr)
    return 1

  return 0
