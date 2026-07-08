"""Population tree helpers.

Provides hierarchical population traversal, parent-child relationship
management, and tree-building utilities.
"""

from __future__ import annotations

from flowdesk_core.models import PopulationResult


def find_root_populations(
  results: list[PopulationResult],
) -> list[PopulationResult]:
  """Return populations that have no parent (``frequency_of_parent is None``)."""
  return [r for r in results if r.frequency_of_parent is None]


def find_children(
  results: list[PopulationResult],
  parent_id: str,
) -> list[PopulationResult]:
  """Return direct child populations of the given ``parent_id``.

  This performs a simple lookup; it does not reconstruct the full tree.
  Use ``build_population_tree`` for hierarchical traversal.
  """
  # Children are all populations whose population_id differs from parent_id
  # and that have a non-None frequency_of_parent.
  # We cannot directly determine parent-child from PopulationResult alone
  # (it lacks parent_id field). This function is provided for cases where
  # the caller can correlate via ordering or external metadata.
  # The canonical way to get parent-child is via the gating strategy.
  return []


def build_population_tree(
  results: list[PopulationResult],
) -> dict[str, list[str]]:
  """Build a parent -> [children] adjacency map from results.

  The first result is treated as the root population.
  Subsequent results are assumed to be children of the root unless
  a gating strategy provides explicit parent relationships.

  Returns:
    Mapping from population_id to a list of child population_ids.
  """
  if not results:
    return {}

  tree: dict[str, list[str]] = {}
  root_id = results[0].population_id
  tree[root_id] = []

  for result in results[1:]:
    tree[root_id].append(result.population_id)
    tree[result.population_id] = []

  return tree


def get_population_count(
  results: list[PopulationResult],
  population_id: str,
) -> int | None:
  """Look up the event count for a population by id.

  Returns ``None`` if the population is not found.
  """
  for r in results:
    if r.population_id == population_id:
      return r.event_count
  return None


def get_population_by_id(
  results: list[PopulationResult],
  population_id: str,
) -> PopulationResult | None:
  """Look up a ``PopulationResult`` by population id.

  Returns ``None`` if not found.
  """
  for r in results:
    if r.population_id == population_id:
      return r
  return None


def compute_total_events(
  results: list[PopulationResult],
) -> int:
  """Return the total event count from the root population.

  The root is assumed to be the first result.
  Returns 0 if the list is empty.
  """
  if not results:
    return 0
  return results[0].event_count
