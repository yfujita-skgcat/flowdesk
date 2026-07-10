"""Execution reports for reproducible headless analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flowdesk_core.models import PopulationMembership, PopulationResult


@dataclass(frozen=True)
class ExecutionReport:
  """Summary and reproducibility metadata from a pipeline run."""

  project_id: str
  execution_profile_id: str
  pipeline_version: str
  status: str
  population_results: tuple[PopulationResult, ...] = field(default_factory=tuple)
  population_membership: tuple[PopulationMembership, ...] = field(
    default_factory=tuple
  )
  input_files: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  messages: tuple[str, ...] = field(default_factory=tuple)

  @property
  def summary(self) -> str:
    """Return a compact run summary."""

    return (
      f"{self.status}: {self.project_id} profile={self.execution_profile_id} "
      f"populations={len(self.population_results)}"
    )
