"""Cleanup of live project references when catalog samples are removed."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


def prune_removed_sample_references(
  state: Mapping[str, Any], removed_sample_ids: Iterable[str]
) -> dict[str, Any]:
  """Return a copy without live references to removed stable sample IDs.

  Shared analysis definitions are deliberately preserved. Matrix provenance is
  historical audit metadata and is also left intact; only selectors that would
  try to execute or display a removed sample are pruned.
  """
  removed = {str(value) for value in removed_sample_ids if str(value)}
  candidate = deepcopy(dict(state))
  if not removed:
    return candidate

  candidate["annotations"] = _without_sample_id(
    candidate.get("annotations", []), removed
  )
  candidate["gate_overrides"] = _without_sample_id(
    candidate.get("gate_overrides", []), removed
  )
  for key in ("auto_gate_fits", "magnetic_gate_fits", "tethered_gate_fits"):
    candidate[key] = _without_sample_id(candidate.get(key, []), removed)

  groups: list[dict[str, Any]] = []
  for value in candidate.get("sample_groups", []):
    group = deepcopy(dict(value))
    group["sample_ids"] = [
      sample_id for sample_id in group.get("sample_ids", [])
      if str(sample_id) not in removed
    ]
    groups.append(group)
  candidate["sample_groups"] = groups

  candidate["compensation_bindings"] = [
    deepcopy(dict(value))
    for value in candidate.get("compensation_bindings", [])
    if not (
      value.get("scope") == "sample"
      and str(value.get("target_id", "")) in removed
    )
  ]

  calculations: list[dict[str, Any]] = []
  for value in candidate.get("compensation_calculations", []):
    calculation = deepcopy(dict(value))
    controls = [
      deepcopy(dict(control))
      for control in calculation.get("controls", [])
      if str(control.get("sample_id", "")) not in removed
    ]
    if controls:
      calculation["controls"] = controls
      calculations.append(calculation)
  candidate["compensation_calculations"] = calculations

  exports: list[dict[str, Any]] = []
  for value in candidate.get("batch_plot_exports", []):
    definition = deepcopy(dict(value))
    if definition.get("target") == "explicit":
      definition["sample_ids"] = [
        sample_id for sample_id in definition.get("sample_ids", [])
        if str(sample_id) not in removed
      ]
      if not definition["sample_ids"]:
        continue
    exports.append(definition)
  candidate["batch_plot_exports"] = exports

  candidate["plot_views"] = [
    _prune_plot_view(value, removed)
    for value in candidate.get("plot_views", [])
  ]
  candidate["overlays"] = [
    _prune_overlay(value, removed)
    for value in candidate.get("overlays", [])
  ]
  return candidate


def _without_sample_id(
  values: Iterable[Mapping[str, Any]], removed: set[str]
) -> list[dict[str, Any]]:
  return [
    deepcopy(dict(value)) for value in values
    if str(value.get("sample_id", "")) not in removed
  ]


def _prune_sources(
  values: Iterable[Mapping[str, Any]], removed: set[str]
) -> list[dict[str, Any]]:
  return [
    deepcopy(dict(value)) for value in values
    if str(value.get("sample_id", "")) not in removed
  ]


def _prune_plot_view(
  value: Mapping[str, Any], removed: set[str]
) -> dict[str, Any]:
  view = deepcopy(dict(value))
  manual_ids = [
    sample_id for sample_id in view.get("manual_overlay_sample_ids", [])
    if str(sample_id) not in removed
  ]
  view["manual_overlay_sample_ids"] = manual_ids
  allowed = {str(value) for value in manual_ids}
  view["manual_overlay_colors"] = {
    str(sample_id): color
    for sample_id, color in view.get("manual_overlay_colors", {}).items()
    if str(sample_id) in allowed
  }
  view["overlay_sources"] = _prune_sources(
    view.get("overlay_sources", []), removed
  )
  return view


def _prune_overlay(
  value: Mapping[str, Any], removed: set[str]
) -> dict[str, Any]:
  overlay = deepcopy(dict(value))
  overlay["sources"] = _prune_sources(overlay.get("sources", []), removed)
  return overlay
