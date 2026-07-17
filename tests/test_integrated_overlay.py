from __future__ import annotations

from dataclasses import asdict

import pytest

from flowdesk_core.integrated_overlay import (
  OverlaySourceCandidate,
  deduplicate_overlay_sources,
  resolve_overlay_style,
  resolve_population_display_color,
)
from flowdesk_core.models import (
  ComparisonMemberSpec,
  ComparisonSetSpec,
  IntegratedOverlayState,
  OverlaySourceSpec,
  PopulationDisplaySpec,
)


def _source(source_id: str, sample_id: str, order: int = 0) -> OverlaySourceSpec:
  return OverlaySourceSpec(
    source_id=source_id,
    sample_id=sample_id,
    population_id="viable",
    display_name=sample_id,
    x_parameter_id="x",
    y_parameter_id="y",
    x_transform_id="tx",
    y_transform_id="ty",
    order=order,
  )


def test_comparison_set_supports_pair_and_one_to_many_without_scientific_group() -> None:
  comparison = ComparisonSetSpec(
    id="dose-1",
    name="Dose",
    members=(
      ComparisonMemberSpec("vehicle", "reference"),
      ComparisonMemberSpec("low", "target"),
      ComparisonMemberSpec("high", "target"),
    ),
  )
  assert comparison.member("vehicle").role == "reference"
  assert [member.sample_id for member in comparison.members] == [
    "vehicle", "low", "high"
  ]

  state = IntegratedOverlayState(
    active_sample_id="vehicle",
    manual_overlay_sample_ids=("high",),
    comparison_set_definitions=(comparison,),
  )
  assert state.active_sample_id != state.manual_overlay_sample_ids[0]
  assert asdict(state)["comparison_set_definitions"][0]["id"] == "dose-1"


def test_population_display_color_prefers_depth_then_deterministic_sibling_order() -> None:
  result = resolve_population_display_color(
    ("viable", "gfp", "sibling"),
    depth_by_population={"viable": 1, "gfp": 2, "sibling": 2},
    colors={"viable": "#00ff00", "gfp": "#0000ff", "sibling": "#ff0000"},
    z_order_by_population={"sibling": 0, "gfp": 1},
    hierarchy_order={"gfp": 10, "sibling": 20},
    default_color="#ffffff",
  )
  assert result.population_id == "sibling"
  assert result.color == "#ff0000"
  assert result.provenance == "population_display_color"


def test_population_display_color_uses_stable_hierarchy_order_when_z_order_ties() -> None:
  result = resolve_population_display_color(
    ("a", "b"),
    depth_by_population={"a": 2, "b": 2},
    colors={"a": "#111111", "b": "#222222"},
    z_order_by_population={},
    hierarchy_order={"a": 4, "b": 2},
    default_color="#ffffff",
  )
  assert result.population_id == "b"
  assert result.color == "#222222"


def test_deduplication_excludes_active_sample_and_prefers_manual_route() -> None:
  candidates = (
    OverlaySourceCandidate(_source("automatic", "s2", 5), route="automatic_source"),
    OverlaySourceCandidate(_source("manual", "s2", 1), route="manual_source"),
    OverlaySourceCandidate(_source("active", "s1", 0), route="manual_source"),
    OverlaySourceCandidate(_source("duplicate", "s2", 2), route="comparison_source"),
  )
  resolved = deduplicate_overlay_sources(candidates, active_sample_id="s1")
  assert len(resolved) == 1
  assert resolved[0].source.sample_id == "s2"
  assert resolved[0].route == "manual_source"


def test_style_precedence_reports_explicit_source_and_fallback_provenance() -> None:
  explicit = resolve_overlay_style(
    explicit_overlay_color="#010203",
    comparison_role_color="#040506",
    automatic_overlay_color="#070809",
    population_display_color="#0a0b0c",
    default_event_color="#0d0e0f",
  )
  assert explicit.color == "#010203"
  assert explicit.provenance == "explicit_overlay_source"

  fallback = resolve_overlay_style(
    comparison_role_color="#040506",
    automatic_overlay_color="#070809",
    population_display_color="#0a0b0c",
    default_event_color="#0d0e0f",
  )
  assert fallback.color == "#040506"
  assert fallback.provenance == "comparison_role"


def test_old_plot_view_state_round_trips_with_independent_overlay_defaults() -> None:
  state = IntegratedOverlayState.from_mapping({
    "active_sample_id": "s1",
    "display_population_id": "all_events",
    "selected_gate_id": "gate-1",
  })
  assert state.manual_overlay_sample_ids == ()
  assert state.overlay_mode == "manual_only"
  assert state.population_display_colors == ()
  encoded = state.to_mapping()
  assert encoded["active_sample_id"] == "s1"
  assert encoded["manual_overlay_sample_ids"] == []


def test_display_specs_reject_duplicate_population_or_comparison_members() -> None:
  with pytest.raises(ValueError, match="unique"):
    ComparisonSetSpec(
      id="bad",
      name="bad",
      members=(ComparisonMemberSpec("s1", "reference"), ComparisonMemberSpec("s1", "target")),
    )
  with pytest.raises(ValueError, match="color"):
    PopulationDisplaySpec(population_id="p", color="blue")
