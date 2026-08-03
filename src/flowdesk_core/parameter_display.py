"""Project-scoped display labels for acquired and derived parameters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def mapping_by_parameter_id(
  mappings: Sequence[Mapping[str, object]] | None,
) -> dict[str, dict[str, str]]:
  """Normalize persisted display mappings without changing parameter identity."""
  result: dict[str, dict[str, str]] = {}
  for value in mappings or ():
    parameter_id = str(value.get("parameter_id", "")).strip()
    if not parameter_id:
      continue
    result[parameter_id] = {
      "plot_label": str(value.get("plot_label", "")).strip(),
      "annotation": str(value.get("annotation", "")).strip(),
    }
  return result


def parameter_display_label(
  parameter_id: str,
  fallback: str,
  mappings: Sequence[Mapping[str, object]] | None,
) -> str:
  """Resolve a display-only label, retaining the fallback when unset."""
  mapping = mapping_by_parameter_id(mappings).get(str(parameter_id), {})
  plot_label = mapping.get("plot_label") or fallback
  annotation = mapping.get("annotation")
  if annotation:
    return f"{annotation} ({plot_label})"
  return plot_label
