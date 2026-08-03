"""Qt-independent runtime state for authoritative and preview result rows.

This module only merges already-computed core report objects.  It deliberately
does not evaluate gates, memberships, frequencies, or statistics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult, StatisticResult
from flowdesk_core.preview import PreviewReport

ResultFreshness = Literal[
  "current",
  "recalculating",
  "stale",
  "error",
  "missing",
]
ResultSource = Literal["authoritative_batch", "active_sample_preview"]
ResultKind = Literal["population", "statistic"]
ResultValue = PopulationResult | StatisticResult


@dataclass(frozen=True)
class ResultRowKey:
  """Stable identity for one sample/population or sample/statistic row."""

  sample_id: str
  kind: ResultKind
  result_id: str
  population_id: str = ""

  @classmethod
  def population(cls, sample_id: str, population_id: str) -> ResultRowKey:
    return cls(sample_id, "population", population_id, population_id)

  @classmethod
  def statistic(
    cls, sample_id: str, statistic_id: str, population_id: str = ""
  ) -> ResultRowKey:
    return cls(sample_id, "statistic", statistic_id, population_id)


@dataclass(frozen=True)
class ResultRowState:
  """Presentation metadata plus the most recent available core result.

  During invalidation, ``result`` intentionally remains the previous value.
  ``revision`` and ``freshness`` make that value explicit context rather than
  allowing it to be mistaken for a current result.
  """

  key: ResultRowKey
  result: ResultValue | None
  revision: int | None
  source: ResultSource
  freshness: ResultFreshness
  outcome_status: str | None = None


class RuntimeResultState:
  """Merge baseline batch results with accepted active-sample preview output."""

  def __init__(
    self,
    authoritative_report: ExecutionReport | None = None,
    *,
    authoritative_revision: int | None = None,
    sample_ids: Sequence[str] = (),
    population_ids: Sequence[str] = (),
    statistic_definitions: Sequence[tuple[str, str]] = (),
  ) -> None:
    self._authoritative_report = authoritative_report
    self._authoritative_revision = authoritative_revision
    self._analysis_revision = authoritative_revision
    self._active_sample_id: str | None = None
    self._batch_stale = False
    self._defined_sample_ids = set(sample_ids)
    self._defined_population_ids = set(population_ids)
    self._statistic_population_ids: dict[str, tuple[str, ...]] = {}
    self._register_statistic_definitions(statistic_definitions)
    self._rows: dict[ResultRowKey, ResultRowState] = {}
    self._rebuild_from_authoritative()

  @property
  def authoritative_report(self) -> ExecutionReport | None:
    """Return the unchanged authoritative baseline report."""
    return self._authoritative_report

  @property
  def authoritative_revision(self) -> int | None:
    return self._authoritative_revision

  @property
  def analysis_revision(self) -> int | None:
    return self._analysis_revision

  @property
  def active_sample_id(self) -> str | None:
    return self._active_sample_id

  @property
  def batch_stale(self) -> bool:
    return self._batch_stale

  @property
  def statistic_definitions(self) -> Mapping[str, tuple[str, ...]]:
    """Return statistic-to-population identities for missing overlay rows."""
    return dict(self._statistic_population_ids)

  @property
  def defined_population_ids(self) -> frozenset[str]:
    """Return the population IDs currently represented by the result state."""
    return frozenset(self._defined_population_ids)

  def remove_populations(self, population_ids: Sequence[str]) -> None:
    """Discard deleted populations from rows, definitions, and cached reports."""
    removed = {str(population_id) for population_id in population_ids}
    if not removed:
      return

    self._defined_population_ids.difference_update(removed)
    self._statistic_population_ids = {
      statistic_id: tuple(
        population_id
        for population_id in population_ids_for_statistic
        if population_id not in removed
      )
      for statistic_id, population_ids_for_statistic
      in self._statistic_population_ids.items()
    }
    self._statistic_population_ids = {
      statistic_id: population_ids_for_statistic
      for statistic_id, population_ids_for_statistic
      in self._statistic_population_ids.items()
      if population_ids_for_statistic
    }
    self._rows = {
      key: row
      for key, row in self._rows.items()
      if (key.population_id or key.result_id) not in removed
    }

    if self._authoritative_report is not None:
      self._authoritative_report = replace(
        self._authoritative_report,
        population_results=tuple(
          result
          for result in self._authoritative_report.population_results
          if result.population_id not in removed
        ),
        population_membership=tuple(
          membership
          for membership in self._authoritative_report.population_membership
          if membership.population_id not in removed
        ),
        statistic_results=tuple(
          result
          for result in self._authoritative_report.statistic_results
          if result.population_id not in removed
        ),
      )

  def _register_statistic_definitions(
    self,
    statistic_definitions: Sequence[tuple[str, str]],
  ) -> None:
    grouped: dict[str, list[str]] = {}
    for definition in statistic_definitions:
      statistic_id, population_id = definition[:2]
      if population_id not in self._defined_population_ids:
        continue
      grouped.setdefault(statistic_id, []).append(population_id)
    for statistic_id, population_ids in grouped.items():
      merged = list(self._statistic_population_ids.get(statistic_id, ()))
      for population_id in population_ids:
        if population_id not in merged:
          merged.append(population_id)
      self._statistic_population_ids[statistic_id] = tuple(merged)

  def set_authoritative_report(
    self,
    report: ExecutionReport | None,
    revision: int,
    *,
    sample_ids: Sequence[str] = (),
    population_ids: Sequence[str] = (),
    statistic_definitions: Sequence[tuple[str, str]] = (),
  ) -> None:
    """Replace the baseline after a successful authoritative pipeline run."""
    self._authoritative_report = report
    self._authoritative_revision = revision
    self._analysis_revision = revision
    self._batch_stale = False
    self._defined_sample_ids.update(sample_ids)
    self._defined_population_ids.update(population_ids)
    self._register_statistic_definitions(statistic_definitions)
    self._rows = {}
    self._rebuild_from_authoritative()

  def update_definitions(
    self,
    *,
    sample_ids: Sequence[str] = (),
    population_ids: Sequence[str] = (),
    statistic_definitions: Sequence[tuple[str, str]] = (),
  ) -> None:
    """Register newly defined rows without inventing scientific values."""
    self._defined_sample_ids.update(sample_ids)
    self._defined_population_ids.update(population_ids)
    self._register_statistic_definitions(statistic_definitions)
    self._ensure_defined_rows()

  def invalidate(
    self,
    *,
    revision: int,
    active_sample_id: str,
    affected_population_ids: Sequence[str],
  ) -> None:
    """Mark affected rows stale while retaining their previous core values."""
    if revision < 0:
      raise ValueError("analysis revision must be non-negative")
    affected = set(affected_population_ids)
    self._analysis_revision = revision
    self._active_sample_id = active_sample_id
    self._defined_sample_ids.add(active_sample_id)
    self._batch_stale = True
    self._ensure_defined_rows()
    updated = dict(self._rows)
    for key, row in self._rows.items():
      if key.kind == "population":
        population_id = key.population_id or key.result_id
      else:
        population_id = key.population_id
        if not population_id:
          targets = self._statistic_population_ids.get(key.result_id, ())
          population_id = targets[0] if len(targets) == 1 else ""
      if population_id not in affected:
        continue
      freshness: ResultFreshness = (
        "recalculating" if key.sample_id == active_sample_id else "stale"
      )
      updated[key] = ResultRowState(
        key=key,
        result=row.result,
        revision=row.revision,
        source=row.source,
        freshness=freshness,
        outcome_status=row.outcome_status,
      )
    self._rows = updated

  def accept_preview(self, report: PreviewReport) -> bool:
    """Atomically overlay one current-revision active-sample preview report."""
    if report.revision != self._analysis_revision:
      return False
    if self._active_sample_id != report.sample_id:
      return False

    population_by_id = {
      result.population_id: result for result in report.population_results
    }
    statistic_by_id = {
      (result.statistic_id, result.population_id): result
      for result in report.statistic_results
    }
    self._defined_sample_ids.add(report.sample_id)
    candidate = dict(self._rows)
    for key, _row in self._rows.items():
      if key.sample_id != report.sample_id:
        continue
      if key.kind == "population":
        result = population_by_id.get(key.result_id)
      else:
        result = statistic_by_id.get((key.result_id, key.population_id))
      candidate[key] = self._preview_row(key, result)
    for result in report.population_results:
      key = ResultRowKey.population(report.sample_id, result.population_id)
      candidate[key] = self._preview_row(key, result)
    for result in report.statistic_results:
      key = ResultRowKey.statistic(
        report.sample_id, result.statistic_id, result.population_id
      )
      candidate[key] = self._preview_row(key, result)

    # One assignment is the commit point.  No parent/child row is observable
    # between the construction of the candidate and this replacement.
    self._rows = candidate
    self._batch_stale = True
    return True

  def mark_error(self, affected_population_ids: Sequence[str]) -> None:
    """Mark affected rows as errored without discarding their previous values."""
    affected = set(affected_population_ids)
    updated = dict(self._rows)
    for key, row in self._rows.items():
      population_id = (
        key.population_id or key.result_id
        if key.kind == "population"
        else key.population_id
      )
      if population_id in affected:
        updated[key] = ResultRowState(
          key, row.result, row.revision, row.source, "error", row.outcome_status
        )
    self._rows = updated

  def row(self, key: ResultRowKey) -> ResultRowState:
    """Return one row, including an explicit missing row when it is defined."""
    self._ensure_defined_rows()
    try:
      return self._rows[key]
    except KeyError:
      # Legacy callers omitted population_id because statistic IDs used to be
      # one-to-one with populations. Keep that lookup unambiguous while the
      # canonical key remains (sample, statistic, population).
      if key.kind == "statistic" and not key.population_id:
        matches = [
          row for row_key, row in self._rows.items()
          if row_key.sample_id == key.sample_id
          and row_key.kind == "statistic"
          and row_key.result_id == key.result_id
        ]
        if len(matches) == 1:
          return matches[0]
      raise KeyError(f"result row not found: {key!r}") from None

  def rows(self) -> tuple[ResultRowState, ...]:
    """Return a stable snapshot of all currently known result rows."""
    self._ensure_defined_rows()
    return tuple(self._rows.values())

  def _preview_row(
    self, key: ResultRowKey, result: ResultValue | None
  ) -> ResultRowState:
    outcome_status = self._outcome_status(result)
    freshness: ResultFreshness = "current" if result is not None else "missing"
    return ResultRowState(
      key=key,
      result=result,
      revision=self._analysis_revision,
      source="active_sample_preview",
      freshness=freshness,
      outcome_status=outcome_status,
    )

  def _rebuild_from_authoritative(self) -> None:
    self._ensure_defined_rows()
    if self._authoritative_report is None:
      return
    population_by_key = {
      ResultRowKey.population(result.sample_id, result.population_id): result
      for result in self._authoritative_report.population_results
    }
    statistic_by_key = {
      ResultRowKey.statistic(
        result.sample_id, result.statistic_id, result.population_id
      ): result
      for result in self._authoritative_report.statistic_results
    }
    for key in set(population_by_key) | set(statistic_by_key) | set(self._rows):
      result = population_by_key.get(key) or statistic_by_key.get(key)
      self._rows[key] = ResultRowState(
        key=key,
        result=result,
        revision=self._authoritative_revision,
        source="authoritative_batch",
        freshness="current" if result is not None else "missing",
        outcome_status=self._outcome_status(result),
      )

  def _ensure_defined_rows(self) -> None:
    if self._authoritative_report is not None:
      self._defined_sample_ids.update(
        result.sample_id for result in self._authoritative_report.population_results
      )
      self._defined_sample_ids.update(
        result.sample_id for result in self._authoritative_report.statistic_results
      )
    for sample_id in self._defined_sample_ids:
      for population_id in self._defined_population_ids:
        key = ResultRowKey.population(sample_id, population_id)
        if key not in self._rows:
          self._rows[key] = ResultRowState(
            key, None, self._authoritative_revision,
            "authoritative_batch", "missing", None,
          )
      for statistic_id in self._statistic_population_ids:
        for population_id in self._statistic_population_ids[statistic_id]:
          key = ResultRowKey.statistic(sample_id, statistic_id, population_id)
          if key not in self._rows:
            self._rows[key] = ResultRowState(
              key, None, self._authoritative_revision,
              "authoritative_batch", "missing", None,
            )

  @staticmethod
  def _outcome_status(result: ResultValue | None) -> str | None:
    if result is None:
      return None
    if isinstance(result, StatisticResult):
      return result.status
    return "ok"
