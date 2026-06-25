"""Population statistics helpers."""

from __future__ import annotations

from flowdesk_core.models import PopulationResult


def make_population_result(
  sample_id: str,
  population_id: str,
  event_count: int,
  parent_count: int | None,
  total_count: int | None,
) -> PopulationResult:
  """Create population frequency statistics from counts."""

  frequency_of_parent = None
  if parent_count is not None and parent_count != 0:
    frequency_of_parent = event_count / parent_count

  frequency_of_total = None
  if total_count is not None and total_count != 0:
    frequency_of_total = event_count / total_count

  return PopulationResult(
    sample_id=sample_id,
    population_id=population_id,
    event_count=event_count,
    frequency_of_parent=frequency_of_parent,
    frequency_of_total=frequency_of_total,
  )
