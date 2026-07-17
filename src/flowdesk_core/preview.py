"""Immutable contracts for non-authoritative current-sample previews."""

from __future__ import annotations

from dataclasses import dataclass, field

from flowdesk_core.execution_report import ExecutionDiagnostic
from flowdesk_core.models import (
  PopulationMembership,
  PopulationResult,
  StatisticResult,
)
from flowdesk_core.sample import SampleData


@dataclass(frozen=True)
class PreviewRequest:
  """One full-resolution sample preview against a runner definition snapshot."""

  revision: int
  sample: SampleData
  execution_profile_id: str = "default"
  strategy_id: str | None = None
  required_population_id: str = "all_events"
  changed_gate_id: str | None = None
  invalidation_reason: str | None = None

  def __post_init__(self) -> None:
    if self.revision < 0:
      raise ValueError("preview revision must be non-negative")
    if not self.execution_profile_id:
      raise ValueError("preview execution_profile_id must be non-empty")
    if not self.required_population_id:
      raise ValueError("preview required_population_id must be non-empty")

  @property
  def sample_id(self) -> str:
    """Stable sample identity carried by the immutable typed input."""
    return self.sample.sample_id


@dataclass(frozen=True)
class PreviewReport:
  """Complete scientific output for one non-authoritative sample preview."""

  revision: int
  project_id: str
  execution_profile_id: str
  sample_id: str
  strategy_id: str | None
  required_population_id: str
  source_event_count: int
  status: str
  population_results: tuple[PopulationResult, ...] = field(default_factory=tuple)
  population_membership: tuple[PopulationMembership, ...] = field(
    default_factory=tuple
  )
  statistic_results: tuple[StatisticResult, ...] = field(default_factory=tuple)
  diagnostics: tuple[ExecutionDiagnostic, ...] = field(default_factory=tuple)
  messages: tuple[str, ...] = field(default_factory=tuple)

  def __post_init__(self) -> None:
    if self.revision < 0:
      raise ValueError("preview revision must be non-negative")
    if self.source_event_count < 0:
      raise ValueError("preview source_event_count must be non-negative")
    if not self.sample_id or not self.required_population_id:
      raise ValueError("preview sample and population IDs must be non-empty")
    for result in self.population_results:
      if result.sample_id != self.sample_id:
        raise ValueError("preview population results must belong to one sample")
    for membership in self.population_membership:
      if membership.sample_id != self.sample_id:
        raise ValueError("preview memberships must belong to one sample")
    for statistic_result in self.statistic_results:
      if statistic_result.sample_id != self.sample_id:
        raise ValueError("preview statistic results must belong to one sample")
