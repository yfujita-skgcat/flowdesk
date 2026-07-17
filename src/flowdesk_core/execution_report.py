"""Execution reports for reproducible headless analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flowdesk_core.models import (
  PopulationMembership,
  PopulationResult,
  StatisticResult,
)


@dataclass(frozen=True)
class ExecutionDiagnostic:
  """Structured, reproducible diagnostic emitted by a pipeline stage."""

  code: str
  message: str
  severity: str
  stage: str
  sample_id: str | None = None
  parameter_id: str | None = None
  exception_type: str | None = None
  affected_event_count: int | None = None
  details: dict[str, Any] = field(default_factory=dict)

  def to_mapping(self) -> dict[str, Any]:
    """Return the complete stable diagnostic representation for adapters."""
    return {
      "code": self.code,
      "message": self.message,
      "severity": self.severity,
      "stage": self.stage,
      "sample_id": self.sample_id,
      "parameter_id": self.parameter_id,
      "exception_type": self.exception_type,
      "affected_event_count": self.affected_event_count,
      "details": dict(self.details),
    }


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
  statistic_results: tuple[StatisticResult, ...] = field(default_factory=tuple)
  input_files: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  messages: tuple[str, ...] = field(default_factory=tuple)
  diagnostics: tuple[ExecutionDiagnostic, ...] = field(default_factory=tuple)
  auto_gate_fits: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  magnetic_gate_fits: tuple[dict[str, Any], ...] = field(default_factory=tuple)
  tethered_gate_fits: tuple[dict[str, Any], ...] = field(default_factory=tuple)

  @property
  def summary(self) -> str:
    """Return a compact run summary."""

    return (
      f"{self.status}: {self.project_id} profile={self.execution_profile_id} "
      f"populations={len(self.population_results)}"
    )
