"""GUI-independent pipeline runner skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult


def run_project_pipeline(
  project: Mapping[str, Any],
  output_dir: str | None = None,
  execution_profile_id: str = "default",
) -> ExecutionReport:
  """Run a project pipeline and return an execution report.

  This MVP skeleton validates that the project object can be executed without GUI
  imports. Scientific execution steps are intentionally placeholders.
  """

  context = ExecutionContext(
    output_dir=None if output_dir is None else Path(output_dir),
    execution_profile_id=execution_profile_id,
  )
  return PipelineRunner(project).run(context)


class PipelineRunner:
  """Headless runner used by GUI, CLI, and Python API."""

  def __init__(self, project: Mapping[str, Any]) -> None:
    self._project = project

  def run(self, context: ExecutionContext) -> ExecutionReport:
    """Run the configured profile.

    The initial implementation returns existing synthetic population results from
    the project object when present. Full FCS execution is a future task.
    """

    profiles = self._project.get("execution_profiles", [])
    if profiles and not any(p.get("id") == context.execution_profile_id for p in profiles):
      raise ValueError(f"unknown execution profile: {context.execution_profile_id}")

    results = tuple(
      PopulationResult(**result)
      for result in self._project.get("population_results", [])
    )
    return ExecutionReport(
      project_id=str(self._project.get("project_id", "unknown")),
      execution_profile_id=context.execution_profile_id,
      pipeline_version=str(self._project.get("pipeline_version", "0.1")),
      status="placeholder_complete",
      population_results=results,
      messages=("Pipeline execution skeleton ran without GUI dependencies.",),
    )
