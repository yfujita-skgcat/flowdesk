"""Display-definition reuse contracts for Layout and Template workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LayoutMode = Literal["reference", "copy"]
TemplateMappingStatus = Literal["exact", "ambiguous", "missing", "incompatible"]


@dataclass(frozen=True)
class LayoutPlotReference:
  id: str
  plot_view_id: str
  mode: LayoutMode
  scene_bounds: tuple[float, float, float, float] | None = None
  caption: str | None = None
  presentation_overrides: dict[str, Any] | None = None

  def __post_init__(self) -> None:
    if not self.id or not self.plot_view_id:
      raise ValueError("layout plot identity must be non-empty")
    if self.mode not in {"reference", "copy"}:
      raise ValueError(f"invalid layout plot mode: {self.mode!r}")
    if self.mode == "reference" and self.presentation_overrides:
      raise ValueError("live references cannot contain copied presentation overrides")

  def to_mapping(self) -> dict[str, Any]:
    result: dict[str, Any] = {
      "id": self.id,
      "plot_view_id": self.plot_view_id,
      "mode": self.mode,
      "scene_bounds": None if self.scene_bounds is None else list(self.scene_bounds),
      "caption": self.caption,
    }
    if self.mode == "copy":
      result["copied_from"] = self.plot_view_id
      result["presentation_overrides"] = dict(self.presentation_overrides or {})
    return result


@dataclass(frozen=True)
class TemplateSourceRole:
  source_role: str
  population_path: str
  parameter_role: str
  transform_role: str | None = None

  def __post_init__(self) -> None:
    if not self.source_role or not self.population_path or not self.parameter_role:
      raise ValueError("template source role, population path, and parameter role are required")


@dataclass(frozen=True)
class TemplateSourceMapping:
  source_role: str
  status: TemplateMappingStatus
  sample_id: str | None = None
  population_id: str | None = None
  parameter_id: str | None = None
  diagnostics: tuple[str, ...] = ()


def map_template_sources(
  roles: tuple[TemplateSourceRole, ...],
  candidates: tuple[dict[str, Any], ...],
) -> tuple[TemplateSourceMapping, ...]:
  """Build an explicit mapping plan; never auto-select among multiple matches."""
  results: list[TemplateSourceMapping] = []
  for role in roles:
    matches = [
      candidate for candidate in candidates
      if candidate.get("source_role") == role.source_role
      and candidate.get("population_path") == role.population_path
      and candidate.get("parameter_id") == role.parameter_role
      and (
        role.transform_role is None
        or candidate.get("transform_role") == role.transform_role
      )
    ]
    if not matches:
      results.append(TemplateSourceMapping(
        role.source_role, "missing",
        diagnostics=("no candidate matches the required source role/path/parameter",),
      ))
      continue
    if len(matches) > 1:
      results.append(TemplateSourceMapping(
        role.source_role, "ambiguous",
        diagnostics=(f"{len(matches)} candidates require confirmation",),
      ))
      continue
    candidate = matches[0]
    results.append(TemplateSourceMapping(
      role.source_role, "exact", candidate.get("sample_id"),
      candidate.get("population_id"), candidate.get("parameter_id"),
    ))
  return tuple(results)
