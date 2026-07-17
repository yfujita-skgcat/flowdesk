"""Qt-independent contracts for integrated overlay display state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from flowdesk_core.models import OverlaySourceSpec

OverlayRoute = Literal[
  "manual_source", "comparison_source", "comparison_role", "automatic_source"
]


@dataclass(frozen=True)
class OverlaySourceCandidate:
  """A source plus the display route that produced it."""

  source: OverlaySourceSpec
  route: OverlayRoute


@dataclass(frozen=True)
class ResolvedOverlayCandidate:
  """One source after active-sample filtering and deterministic deduplication."""

  source: OverlaySourceSpec
  route: OverlayRoute


@dataclass(frozen=True)
class OverlayStyleResolution:
  """Resolved color and its inspectable display provenance."""

  color: str
  provenance: str
  used_fallback: bool


@dataclass(frozen=True)
class PopulationColorResolution:
  """Resolved base-layer color for one event."""

  population_id: str | None
  color: str
  provenance: str


_ROUTE_PRIORITY: dict[OverlayRoute, int] = {
  "manual_source": 0,
  "comparison_source": 1,
  "comparison_role": 2,
  "automatic_source": 3,
}


def _source_identity(source: OverlaySourceSpec) -> tuple[object, ...]:
  """Return stable identity used to deduplicate display layers."""
  return (
    source.sample_id,
    source.template_source_role,
    source.population_id,
    source.template_population_path,
    source.x_parameter_id,
    source.y_parameter_id,
    source.x_transform_id,
    source.y_transform_id,
    source.x_unit,
    source.y_unit,
  )


def deduplicate_overlay_sources(
  candidates: Iterable[OverlaySourceCandidate],
  *,
  active_sample_id: str | None,
) -> tuple[ResolvedOverlayCandidate, ...]:
  """Remove active sample and duplicate source routes deterministically.

  Route priority is resolved before source order, so a manual override remains the
  winner even if an automatic source was listed first. Remaining ties use source order
  and source ID; no set/dict iteration order affects the result.
  """
  ordered = sorted(
    candidates,
    key=lambda candidate: (
      _ROUTE_PRIORITY[candidate.route],
      candidate.source.order,
      candidate.source.source_id,
    ),
  )
  by_identity: dict[tuple[object, ...], ResolvedOverlayCandidate] = {}
  for candidate in ordered:
    if candidate.source.sample_id == active_sample_id:
      continue
    identity = _source_identity(candidate.source)
    if identity not in by_identity:
      by_identity[identity] = ResolvedOverlayCandidate(
        source=candidate.source,
        route=candidate.route,
      )
  return tuple(sorted(
    by_identity.values(),
    key=lambda candidate: (candidate.source.order, candidate.source.source_id),
  ))


def resolve_overlay_style(
  *,
  explicit_overlay_color: str | None = None,
  comparison_role_color: str | None = None,
  automatic_overlay_color: str | None = None,
  population_display_color: str | None = None,
  default_event_color: str,
) -> OverlayStyleResolution:
  """Resolve the documented overlay color precedence."""
  choices = (
    ("explicit_overlay_source", explicit_overlay_color),
    ("comparison_role", comparison_role_color),
    ("sample_automatic_overlay", automatic_overlay_color),
    ("population_display_color", population_display_color),
    ("plot_default_event", default_event_color),
  )
  for index, (provenance, color) in enumerate(choices):
    if color:
      return OverlayStyleResolution(
        color=color,
        provenance=provenance,
        used_fallback=index > 0,
      )
  raise ValueError("default_event_color must be non-empty")


def resolve_population_display_color(
  containing_population_ids: Iterable[str],
  *,
  depth_by_population: Mapping[str, int],
  colors: Mapping[str, str],
  z_order_by_population: Mapping[str, int],
  hierarchy_order: Mapping[str, int],
  default_color: str,
) -> PopulationColorResolution:
  """Apply deepest-descendant and deterministic sibling overlap precedence."""
  candidates = [
    population_id
    for population_id in containing_population_ids
    if population_id in colors and colors[population_id]
  ]
  if not candidates:
    return PopulationColorResolution(None, default_color, "plot_default_event")
  winner = min(
    candidates,
    key=lambda population_id: (
      -depth_by_population.get(population_id, 0),
      z_order_by_population.get(population_id, 2**31 - 1),
      hierarchy_order.get(population_id, 2**31 - 1),
      population_id,
    ),
  )
  return PopulationColorResolution(
    population_id=winner,
    color=colors[winner],
    provenance="population_display_color",
  )
