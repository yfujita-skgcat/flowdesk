"""GUI-independent overlay compatibility and presentation validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

from flowdesk_core.channels import AmbiguousChannelReferenceError, resolve_channel_index
from flowdesk_core.models import (
  ChannelSpec,
  FontSpec,
  OverlaySourceSpec,
  PlotPresentationSpec,
  PlotType,
  SourceStyleSpec,
  TransformSpec,
)

CompatibilityStatus = Literal[
  "compatible", "incompatible", "ambiguous", "missing", "stale", "error"
]


@dataclass(frozen=True)
class PresentationDiagnostic:
  code: str
  message: str
  source_id: str | None = None
  sample_id: str | None = None
  population_id: str | None = None
  parameter_id: str | None = None
  transform_id: str | None = None
  details: dict[str, object] | None = None


@dataclass(frozen=True)
class SamplePresentationContext:
  """Immutable analysis metadata needed to resolve one display source."""

  sample_id: str
  channels: tuple[ChannelSpec, ...]
  population_ids: tuple[str, ...]
  transform_ids: tuple[str, ...] = ()
  transforms: tuple[TransformSpec, ...] = ()
  analysis_revision: str | None = None


@dataclass(frozen=True)
class OverlaySourceResolution:
  source_id: str
  status: CompatibilityStatus
  x_index: int | None = None
  y_index: int | None = None
  diagnostics: tuple[PresentationDiagnostic, ...] = ()


@dataclass(frozen=True)
class ResolvedPresentation:
  """One immutable presentation consumed by preview, export, and reuse."""

  presentation: PlotPresentationSpec
  provenance: dict[str, str]
  diagnostics: tuple[PresentationDiagnostic, ...] = ()


SUPPORTED_STYLE_FIELDS: dict[PlotType, frozenset[str]] = {
  "dot": frozenset({"marker_shape", "marker_size", "color", "alpha"}),
  "scatter": frozenset({"marker_shape", "marker_size", "color", "alpha"}),
  "pseudocolor": frozenset({"colormap"}),
  "density": frozenset({"colormap"}),
  "contour": frozenset({"colormap", "line_color", "line_width", "line_style"}),
  "histogram": frozenset({
    "line_color", "line_width", "line_style", "histogram_fill_color",
    "histogram_outline_color", "histogram_alpha",
  }),
  "cdf": frozenset({"line_color", "line_width", "line_style"}),
}


class PresentationValidationError(ValueError):
  """Raised when a style field is not supported by a plot type."""


_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_color(value: str | None, field_name: str) -> None:
  if value is not None and not _COLOR_RE.fullmatch(value):
    raise PresentationValidationError(
      f"{field_name} must be a #RRGGBB color, got {value!r}"
    )


def _style_fields(style: SourceStyleSpec) -> set[str]:
  values = {
    "marker_shape": style.marker_shape,
    "marker_size": style.marker_size,
    "color": style.color,
    "alpha": style.alpha,
    "line_color": style.line_color,
    "line_width": style.line_width,
    "line_style": style.line_style,
    "histogram_fill_color": style.histogram_fill_color,
    "histogram_outline_color": style.histogram_outline_color,
    "histogram_alpha": style.histogram_alpha,
  }
  return {name for name in style.manual_fields if name in values} | {
    name for name, value in values.items() if value is not None and name not in {
      "marker_size", "alpha", "line_width", "line_style", "histogram_alpha"
    }
  }


def validate_presentation(
  plot_type: PlotType,
  presentation: PlotPresentationSpec,
) -> None:
  """Validate source styles against the one shared plot support matrix."""
  supported = SUPPORTED_STYLE_FIELDS[plot_type]
  _validate_color(presentation.background_color, "background_color")
  _validate_color(presentation.gate_outline_color, "gate_outline_color")
  for style in presentation.source_styles:
    for field_name in (
      "color", "line_color", "histogram_fill_color", "histogram_outline_color"
    ):
      _validate_color(getattr(style, field_name), field_name)
    unsupported = _style_fields(style) - supported
    if unsupported:
      fields = ", ".join(sorted(unsupported))
      raise PresentationValidationError(
        f"style fields {fields} are unsupported for plot type {plot_type!r}"
      )
  if presentation.colormap is not None and "colormap" not in supported:
      raise PresentationValidationError(
        f"style field colormap is unsupported for plot type {plot_type!r}"
      )


def _presentation_fields() -> tuple[str, ...]:
  return (
    "title", "title_mode", "subtitle", "x_axis_display_label", "y_axis_display_label",
    "background_color", "legend_visible", "legend_position", "legend_source_ids",
    "title_font", "axis_label_font", "tick_font", "legend_font",
    "gate_outline_color", "gate_outline_width", "gate_outline_style", "axis_line_width",
    "show_grid",
    "colormap",
    "automatic_style_policy",
  )


def _typed_presentation(value: Mapping[str, object]) -> PlotPresentationSpec:
  """Convert JSON presentation data to the validated core type."""
  fonts: dict[str, Any] = {}
  for key in ("title_font", "axis_label_font", "tick_font", "legend_font"):
    raw_font = value.get(key, {})
    if not isinstance(raw_font, Mapping):
      raise PresentationValidationError(f"{key} must be an object")
    fonts[key] = FontSpec(**dict(raw_font))
  source_styles: list[SourceStyleSpec] = []
  raw_source_styles = value.get("source_styles", [])
  if not isinstance(raw_source_styles, (list, tuple)):
    raise PresentationValidationError("source_styles must be an array")
  for raw in raw_source_styles:
    if not isinstance(raw, Mapping):
      raise PresentationValidationError("source_styles entries must be objects")
    source_styles.append(SourceStyleSpec(
      **{
        **dict(raw),
        "manual_fields": tuple(raw.get("manual_fields", ())),
        "provenance": dict(raw.get("provenance", {})),
      }
    ))
  presentation_values: dict[str, Any] = {
      **{field: value[field] for field in _presentation_fields() if field in value},
      **fonts,
      "legend_source_ids": tuple(cast(Any, value.get("legend_source_ids", ()))),
      "source_styles": tuple(source_styles),
  }
  return PlotPresentationSpec(**presentation_values)


def resolve_presentation_title(
  presentation: Mapping[str, object] | PlotPresentationSpec,
  sample_titles: tuple[str, ...] | list[str] = (),
) -> str:
  """Resolve the display title from persisted mode and visible sample titles.

  Sample titles are runtime display metadata and are therefore not copied into
  the persisted presentation.  The first title is the active sample title;
  subsequent titles are overlay sources in their display order.
  """
  if isinstance(presentation, PlotPresentationSpec):
    title_mode: str = presentation.title_mode
    fallback = presentation.title
  else:
    title_mode = str(presentation.get("title_mode", "overlay_sample_titles"))
    fallback = str(presentation.get("title", ""))
  titles = tuple(str(title).strip() for title in sample_titles if str(title).strip())
  if title_mode == "overlay_sample_titles" and titles:
    return "\n".join(titles)
  if title_mode == "current_sample" and titles:
    return titles[0]
  return fallback


def resolve_presentation_layers(
  view_override: Mapping[str, object] | None = None,
  project_default: Mapping[str, object] | None = None,
  global_preference: Mapping[str, object] | None = None,
  *,
  source_ids: tuple[str, ...] = (),
  builtin_default: Mapping[str, object] | None = None,
) -> ResolvedPresentation:
  """Resolve presentation precedence and retain field-level provenance.

  The four layers are applied in increasing priority: built-in, global,
  project, and view.  Source styles are merged field-by-field so resetting a
  higher layer reveals the lower value instead of copying it into the view.
  """
  builtin = deepcopy(dict(builtin_default or asdict(PlotPresentationSpec())))
  layers = (
    ("builtin_default", builtin),
    ("global_preference", dict(global_preference or {})),
    ("project_display_default", dict(project_default or {})),
    ("view_override", dict(view_override or {})),
  )
  merged: dict[str, object] = builtin
  provenance: dict[str, str] = {
    field: "builtin_default" for field in _presentation_fields()
  }
  source_values: dict[str, dict[str, object]] = {}
  source_provenance: dict[str, dict[str, str]] = {}
  for source in builtin.get("source_styles", []):
    if isinstance(source, Mapping) and source.get("source_id"):
      source_values[str(source["source_id"])] = dict(source)
  for layer_name, layer in layers[1:]:
    for field in _presentation_fields():
      if field in layer:
        merged[field] = deepcopy(layer[field])
        provenance[field] = layer_name
    raw_styles = layer.get("source_styles", [])
    if isinstance(raw_styles, (list, tuple)):
      for raw in raw_styles:
        if not isinstance(raw, Mapping) or not raw.get("source_id"):
          continue
        source_id = str(raw["source_id"])
        target = source_values.setdefault(source_id, {"source_id": source_id})
        target_provenance = source_provenance.setdefault(source_id, {})
        for field, field_value in raw.items():
          if field in {"source_id", "manual_fields", "provenance"}:
            continue
          target[field] = deepcopy(field_value)
          target_provenance[field] = layer_name
        if raw.get("manual_fields"):
          target["manual_fields"] = list(raw["manual_fields"])
          for field in raw["manual_fields"]:
            target_provenance[str(field)] = layer_name
  if source_ids:
    current_source_ids = tuple(
      str(source_id)
      for source_id in cast(Any, merged.get("legend_source_ids", source_ids))
    )
    merged["legend_source_ids"] = tuple(
      source_id for source_id in current_source_ids
      if source_id in source_ids
    )
    existing_source_ids = cast(tuple[str, ...], merged["legend_source_ids"])
    merged["legend_source_ids"] = existing_source_ids + tuple(
      source_id for source_id in source_ids
      if source_id not in existing_source_ids
    )
  merged["source_styles"] = [
    {
      **source_values[source_id],
      "provenance": source_provenance.get(source_id, {}),
    }
    for source_id in source_ids
    if source_id in source_values
  ]
  for source_id, fields in source_provenance.items():
    for field, layer_name in fields.items():
      provenance[f"source:{source_id}:{field}"] = layer_name
  presentation = _typed_presentation(merged)
  return ResolvedPresentation(presentation, provenance)


def _diagnostic(
  code: str,
  message: str,
  source: OverlaySourceSpec,
  **kwargs: object,
) -> PresentationDiagnostic:
  return PresentationDiagnostic(
    code=code,
    message=message,
    source_id=source.source_id,
    sample_id=source.sample_id,
    population_id=source.population_id,
    **cast(Any, kwargs),
  )


def _resolve_parameter(
  source: OverlaySourceSpec,
  context: SamplePresentationContext,
  parameter_id: str,
) -> tuple[int | None, PresentationDiagnostic | None]:
  try:
    return resolve_channel_index(context.channels, parameter_id, sample_id=context.sample_id), None
  except AmbiguousChannelReferenceError as exc:
    return None, _diagnostic(
      "overlay_ambiguous_channel",
      str(exc),
      source,
      parameter_id=parameter_id,
      details={"candidate_ids": list(exc.candidate_ids)},
    )
  except Exception as exc:
    return None, _diagnostic(
      "overlay_missing_channel",
      str(exc),
      source,
      parameter_id=parameter_id,
    )


def _resolve_transform(
  source: OverlaySourceSpec,
  context: SamplePresentationContext,
  transform_id: str | None,
  parameter_id: str,
) -> PresentationDiagnostic | None:
  if transform_id is None:
    return None
  transform = next((item for item in context.transforms if item.id == transform_id), None)
  if transform_id not in context.transform_ids and transform is None:
    return _diagnostic(
      "overlay_missing_transform",
      f"transform {transform_id!r} is not available for sample {context.sample_id!r}",
      source,
      parameter_id=parameter_id,
      transform_id=transform_id,
    )
  if transform is not None and transform.parameter != parameter_id:
    return _diagnostic(
      "overlay_incompatible_transform",
      f"transform {transform_id!r} is bound to {transform.parameter!r}, not {parameter_id!r}",
      source,
      parameter_id=parameter_id,
      transform_id=transform_id,
    )
  return None


def resolve_overlay_sources(
  sources: tuple[OverlaySourceSpec, ...],
  contexts: dict[str, SamplePresentationContext],
) -> tuple[OverlaySourceResolution, ...]:
  """Resolve sources by stable identity without selecting an active sample fallback."""
  ordered = sorted(sources, key=lambda source: (source.order, source.source_id))
  resolved: list[OverlaySourceResolution] = []
  for source in ordered:
    if source.sample_id is None or source.sample_id not in contexts:
      diagnostic = _diagnostic(
        "overlay_missing_sample",
        f"sample {source.sample_id!r} is not available",
        source,
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, "missing", diagnostics=(diagnostic,)
      ))
      continue
    context = contexts[source.sample_id]
    if source.population_id is None or source.population_id not in context.population_ids:
      diagnostic = _diagnostic(
        "overlay_missing_population",
        f"population {source.population_id!r} is not available",
        source,
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, "missing", diagnostics=(diagnostic,)
      ))
      continue
    if (
      source.analysis_revision is not None
      and source.analysis_revision != context.analysis_revision
    ):
      diagnostic = _diagnostic(
        "overlay_stale_membership",
        "source membership belongs to a different analysis revision",
        source,
        details={
          "source_revision": source.analysis_revision,
          "current_revision": context.analysis_revision,
        },
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, "stale", diagnostics=(diagnostic,)
      ))
      continue
    x_index, x_diagnostic = _resolve_parameter(source, context, source.x_parameter_id)
    diagnostics: list[PresentationDiagnostic] = (
      [x_diagnostic] if x_diagnostic is not None else []
    )
    if x_diagnostic is None:
      transform_diagnostic = _resolve_transform(
        source, context, source.x_transform_id, source.x_parameter_id
      )
      if transform_diagnostic is not None:
        diagnostics.append(transform_diagnostic)
    y_index: int | None = None
    if source.y_parameter_id is not None and not diagnostics:
      y_index, y_diagnostic = _resolve_parameter(source, context, source.y_parameter_id)
      if y_diagnostic is not None:
        diagnostics.append(y_diagnostic)
      else:
        transform_diagnostic = _resolve_transform(
          source, context, source.y_transform_id, source.y_parameter_id
        )
        if transform_diagnostic is not None:
          diagnostics.append(transform_diagnostic)
    if diagnostics:
      status: CompatibilityStatus = (
        "ambiguous" if diagnostics[0].code.startswith("overlay_ambiguous")
        else "incompatible" if "incompatible" in diagnostics[0].code else "missing"
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, status, diagnostics=tuple(diagnostics)
      ))
      continue
    x_channel = context.channels[x_index] if x_index is not None else None
    y_channel = context.channels[y_index] if y_index is not None else None
    x_unit = source.x_unit if source.x_unit is not None else source.unit
    y_unit = source.y_unit if source.y_unit is not None else source.unit
    if x_channel is None or (x_unit is not None and x_unit != x_channel.unit):
      diagnostic = _diagnostic(
        "overlay_incompatible_unit",
        f"source unit {x_unit!r} does not match channel unit "
        f"{x_channel.unit if x_channel else None!r}",
        source,
        parameter_id=source.x_parameter_id,
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, "incompatible", diagnostics=(diagnostic,)
      ))
      continue
    if y_channel is not None and y_unit is not None and y_unit != y_channel.unit:
      diagnostic = _diagnostic(
        "overlay_incompatible_unit",
        f"source unit {y_unit!r} does not match channel unit {y_channel.unit!r}",
        source,
        parameter_id=source.y_parameter_id,
      )
      resolved.append(OverlaySourceResolution(
        source.source_id, "incompatible", diagnostics=(diagnostic,)
      ))
      continue
    resolved.append(OverlaySourceResolution(source.source_id, "compatible", x_index, y_index))
  return tuple(resolved)
