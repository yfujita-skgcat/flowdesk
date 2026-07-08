"""Run a saved Flowdesk project without the GUI."""

from __future__ import annotations

import sys

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.export import (
  ExportError,
  write_population_results_wide,
)
from flowdesk_core.pipeline_runner import PipelineError, run_project_pipeline
from flowdesk_storage.manifest import ManifestValidationError
from flowdesk_storage.project import load_project


def run_project_command(
  project_path: str,
  output: str | None = None,
  execution_profile_id: str = "default",
) -> int:
  """CLI adapter for headless project execution.

  Args:
    project_path: Path to the ``.flowdesk`` project bundle directory.
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
      results = list(report.population_results)
      write_population_results_wide(results, output)
      print(f"Exported {len(results)} population rows to {output}")
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
  # Any status containing 'failed' is an error.
  if "failed" in status:
    print(f"Error: pipeline status: {status}", file=sys.stderr)
    return 1

  return 0
