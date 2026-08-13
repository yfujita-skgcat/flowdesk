"""Tests for removing live sample-scoped project references."""

from __future__ import annotations

from copy import deepcopy

from flowdesk_core.groups import resolve_group_assignments_from_mappings
from flowdesk_core.sample_references import prune_removed_sample_references


def test_prune_removed_sample_references_cleans_live_selectors() -> None:
  state = {
    "annotations": [
      {"sample_id": "old", "keyword": "Condition", "value": "A", "source": "workspace"},
      {"sample_id": "keep", "keyword": "Condition", "value": "B", "source": "workspace"},
    ],
    "sample_groups": [{"id": "g", "sample_ids": ["old", "keep"]}],
    "gate_overrides": [{"id": "override-old", "sample_id": "old"}],
    "auto_gate_fits": [{"sample_id": "old"}, {"sample_id": "keep"}],
    "magnetic_gate_fits": [{"sample_id": "old"}],
    "tethered_gate_fits": [{"sample_id": "old"}],
    "compensation_bindings": [
      {"id": "old-binding", "scope": "sample", "target_id": "old"},
      {"id": "group-binding", "scope": "group", "target_id": "g"},
    ],
    "compensation_calculations": [
      {"id": "mixed", "controls": [{"sample_id": "old"}, {"sample_id": "keep"}]},
      {"id": "old-only", "controls": [{"sample_id": "old"}]},
    ],
    "batch_plot_exports": [
      {"id": "mixed", "target": "explicit", "sample_ids": ["old", "keep"]},
      {"id": "old-only", "target": "explicit", "sample_ids": ["old"]},
      {"id": "all", "target": "all", "sample_ids": []},
    ],
    "plot_views": [{
      "id": "main-view",
      "manual_overlay_sample_ids": ["old", "keep"],
      "manual_overlay_colors": {"old": "#ff0000", "keep": "#00ff00"},
      "overlay_sources": [
        {"source_id": "old-source", "sample_id": "old"},
        {"source_id": "keep-source", "sample_id": "keep"},
      ],
    }],
    "overlays": [{"id": "overlay", "sources": [
      {"source_id": "old-source", "sample_id": "old"},
      {"source_id": "keep-source", "sample_id": "keep"},
    ]}],
    "gating_strategies_data": {"shared": {"gates": [{"id": "gate"}]}},
    "compensation_matrices": [{
      "id": "matrix", "provenance": {"source_sample_id": "old"}
    }],
  }
  before = deepcopy(state)

  result = prune_removed_sample_references(state, {"old"})

  assert state == before
  assert [item["sample_id"] for item in result["annotations"]] == ["keep"]
  assert result["sample_groups"][0]["sample_ids"] == ["keep"]
  assert result["gate_overrides"] == []
  assert result["auto_gate_fits"] == [{"sample_id": "keep"}]
  assert result["magnetic_gate_fits"] == []
  assert result["tethered_gate_fits"] == []
  assert [item["id"] for item in result["compensation_bindings"]] == ["group-binding"]
  assert result["compensation_calculations"] == [
    {"id": "mixed", "controls": [{"sample_id": "keep"}]}
  ]
  assert [item["id"] for item in result["batch_plot_exports"]] == ["mixed", "all"]
  assert result["batch_plot_exports"][0]["sample_ids"] == ["keep"]
  view = result["plot_views"][0]
  assert view["manual_overlay_sample_ids"] == ["keep"]
  assert view["manual_overlay_colors"] == {"keep": "#00ff00"}
  assert [source["sample_id"] for source in view["overlay_sources"]] == ["keep"]
  assert result["overlays"][0]["sources"][0]["sample_id"] == "keep"
  assert result["gating_strategies_data"] == state["gating_strategies_data"]
  assert result["compensation_matrices"] == state["compensation_matrices"]


def test_annotation_cleanup_prevents_unknown_sample_group_error() -> None:
  state = prune_removed_sample_references({
    "annotations": [{
      "sample_id": "old", "keyword": "Condition", "value": "A",
      "source": "workspace",
    }],
  }, {"old"})
  assignments = resolve_group_assignments_from_mappings(
    [{"id": "all", "name": "All", "sample_ids": [], "membership_rule": {"all": []}}],
    [],
    [{"id": "new", "name": "new.fcs", "path": "new.fcs"}],
    state["annotations"],
  )
  assert assignments == {}
