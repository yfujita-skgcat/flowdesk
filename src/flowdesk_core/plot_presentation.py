"""GUI-independent overlay compatibility and presentation validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from flowdesk_core.channels import AmbiguousChannelReferenceError, resolve_channel_index
from flowdesk_core.models import (
  ChannelSpec,
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
  for style in presentation.source_styles:
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
    **kwargs,
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
    diagnostics = [x_diagnostic] if x_diagnostic is not None else []
    if x_diagnostic is None:
      diagnostics.append(_resolve_transform(
        source, context, source.x_transform_id, source.x_parameter_id
      ))
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
    diagnostics = [item for item in diagnostics if item is not None]
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
