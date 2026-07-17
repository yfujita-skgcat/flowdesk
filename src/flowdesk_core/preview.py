"""Immutable contracts for non-authoritative current-sample previews."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from flowdesk_core.execution_report import ExecutionDiagnostic
from flowdesk_core.models import (
  PopulationMembership,
  PopulationResult,
  StatisticResult,
)
from flowdesk_core.sample import SampleData

PreviewStatus = Literal["idle", "pending", "running", "current", "stale", "error"]


@dataclass
class PreviewRevisionState:
  """Runtime revision and invalidation state shared by GUI schedulers.

  This class contains no scientific execution and deliberately does not persist
  revision values in the project definition.  It is the guard that prevents a
  result from an older definition from being treated as current.
  """

  analysis_revision: int = 0
  authoritative_result_revision: int | None = None
  preview_result_revision: int | None = None
  preview_status: PreviewStatus = "idle"
  stale_population_ids: set[str] = field(default_factory=set)

  def invalidate(self, population_ids: set[str] | frozenset[str]) -> int:
    """Advance the definition revision and invalidate affected populations."""
    self.analysis_revision += 1
    self.stale_population_ids.update(population_ids)
    self.preview_status = "stale"
    return self.analysis_revision

  def mark_pending(self) -> None:
    """Mark a current revision as awaiting preview scheduling."""
    self.preview_status = "pending"

  def mark_running(self) -> None:
    """Mark a current revision as being calculated."""
    self.preview_status = "running"

  def mark_error(self) -> None:
    """Record a preview failure without changing accepted result revisions."""
    self.preview_status = "error"

  def accept_preview(self, revision: int, population_ids: set[str]) -> bool:
    """Accept only a preview produced for the current definition revision."""
    if revision != self.analysis_revision:
      return False
    self.preview_result_revision = revision
    self.stale_population_ids.difference_update(population_ids)
    self.preview_status = "current"
    return True

  def accept_authoritative(self, revision: int) -> bool:
    """Accept only a batch report produced for the current revision."""
    if revision != self.analysis_revision:
      return False
    self.authoritative_result_revision = revision
    self.stale_population_ids.clear()
    if self.preview_result_revision != revision:
      self.preview_status = "idle"
    return True

  def result_is_current(self, population_id: str, revision: int | None) -> bool:
    """Return whether one result can safely be used for display filtering."""
    if revision != self.analysis_revision:
      return False
    if population_id in self.stale_population_ids:
      return False
    return (
      self.preview_result_revision == revision
      or self.authoritative_result_revision == revision
    )

  def nearest_valid_population(
    self,
    target_population_id: str,
    parents: dict[str, str | None],
    available_population_ids: set[str],
    result_revision: int | None,
  ) -> str | None:
    """Find the closest current ancestor for safe navigation fallback."""
    current: str | None = target_population_id
    seen: set[str] = set()
    while current and current not in seen:
      seen.add(current)
      if (
        current in available_population_ids
        and self.result_is_current(current, result_revision)
      ):
        return current
      current = parents.get(current)
    return None


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
