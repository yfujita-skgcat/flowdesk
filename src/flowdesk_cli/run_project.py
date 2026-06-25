"""Run a saved Flowdesk project without the GUI."""

from __future__ import annotations

from flowdesk_core.pipeline_runner import run_project_pipeline
from flowdesk_storage.project import load_project


def run_project_command(
  project_path: str,
  output: str | None = None,
  execution_profile_id: str = "default",
) -> int:
  """CLI adapter for headless project execution."""

  project = load_project(project_path)
  report = run_project_pipeline(
    project,
    output_dir=output,
    execution_profile_id=execution_profile_id,
  )
  print(report.summary)
  return 0
