"""Typed, GUI-independent catalog of acquired and derived parameters.

The catalog is reconstructed from one sample's channel metadata plus persisted derived
definitions.  It never evaluates expressions or stores a second project definition.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from flowdesk_core.derived_parameters import (
  DerivedParameterPlanningError,
  extract_parameter_references,
  plan_derived_parameters,
)
from flowdesk_core.models import ChannelSpec, DerivedParameterSpec

ParameterKind = Literal["acquired", "derived"]
ParameterAvailability = Literal[
  "available", "missing_input", "stale", "error", "not_run"
]


@dataclass(frozen=True)
class ParameterCatalogDiagnostic:
  """Structured catalog diagnostic without a GUI-specific representation."""

  code: str
  message: str
  parameter_id: str | None = None
  references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParameterCatalogEntry:
  """One acquired channel or persisted derived output.

  ``availability`` describes whether the definition can be resolved for this sample;
  it does not claim that a pipeline result is current.  Consumers that can schedule a
  later pipeline run may accept ``not_run`` entries, while a current raw-only plot must
  keep derived entries disabled until the canonical processed display path is available.
  """

  parameter_id: str
  display_name: str
  kind: ParameterKind
  unit: str | None
  source_stage: str
  definition_id: str | None = None
  expression: str | None = None
  input_parameter_ids: tuple[str, ...] = ()
  availability: ParameterAvailability = "available"
  diagnostics: tuple[ParameterCatalogDiagnostic, ...] = ()
  sample_id: str | None = None

  @property
  def is_definition_valid(self) -> bool:
    """Whether a later canonical pipeline request may resolve this parameter."""
    return self.availability not in {"missing_input", "error"}

  @property
  def selector_label(self) -> str:
    """Return a deterministic label that never substitutes for stable identity."""
    if self.kind == "acquired":
      return self.display_name
    return f"{self.display_name} [{self.parameter_id}] (Derived)"


def build_parameter_catalog(
  channels: Sequence[ChannelSpec],
  derived_parameters: Sequence[Mapping[str, Any] | DerivedParameterSpec],
  *,
  sample_id: str | None = None,
) -> tuple[ParameterCatalogEntry, ...]:
  """Build deterministic acquired-then-derived entries for one sample.

  Invalid derived definitions remain visible with diagnostics.  This lets every consumer
  explain why an output cannot be selected instead of silently dropping it or selecting a
  same-named acquired channel.
  """
  acquired = tuple(
    ParameterCatalogEntry(
      parameter_id=channel.id,
      display_name=channel.short_name or channel.name,
      kind="acquired",
      unit=channel.unit,
      source_stage="raw",
      availability="available",
      sample_id=sample_id,
    )
    for channel in channels
  )
  available_ids = tuple(channel.id for channel in channels)
  derived_specs: list[DerivedParameterSpec] = []
  derived_entries: list[ParameterCatalogEntry] = []
  entry_by_definition_id: dict[str, int] = {}

  for value in derived_parameters:
    raw = value if isinstance(value, DerivedParameterSpec) else dict(value)
    try:
      spec = raw if isinstance(raw, DerivedParameterSpec) else DerivedParameterSpec(**raw)
    except (TypeError, ValueError) as exc:
      raw_id = str(raw.get("output_channel_id") or raw.get("id") or "invalid-derived")
      raw_name = str(raw.get("output_label") or raw.get("name") or raw_id)
      derived_entries.append(
        ParameterCatalogEntry(
          parameter_id=raw_id,
          display_name=raw_name,
          kind="derived",
          unit=raw.get("unit"),
          source_stage=str(raw.get("source_stage", "compensated")),
          definition_id=str(raw.get("id") or raw_id),
          expression=str(raw.get("expression") or ""),
          availability="error",
          diagnostics=(ParameterCatalogDiagnostic(
            code="invalid_derived_parameter_definition",
            message=str(exc),
            parameter_id=str(raw.get("id") or raw_id),
          ),),
          sample_id=sample_id,
        )
      )
      continue
    entry_by_definition_id[spec.id] = len(derived_entries)
    derived_specs.append(spec)
    derived_entries.append(
      ParameterCatalogEntry(
        parameter_id=spec.output_id,
        display_name=spec.output_label or spec.name or spec.output_id,
        kind="derived",
        unit=spec.unit,
        source_stage=spec.source_stage,
        definition_id=spec.id,
        expression=spec.expression,
        input_parameter_ids=spec.input_parameters,
        availability="not_run",
        sample_id=sample_id,
      )
    )

  try:
    plan = plan_derived_parameters(derived_specs, available_ids)
  except DerivedParameterPlanningError as exc:
    affected_definition_ids = set(exc.cycle_ids)
    affected_output_ids = set(exc.cycle_ids)
    if exc.parameter_id:
      affected_definition_ids.add(exc.parameter_id)
    # Duplicate output diagnostics may name an output rather than a definition ID.
    affected_output_ids.update(exc.references)
    for index, entry in enumerate(derived_entries):
      if (
        entry.definition_id not in affected_definition_ids
        and entry.parameter_id not in affected_output_ids
      ):
        continue
      availability: ParameterAvailability = (
        "missing_input" if exc.code == "unknown_derived_input" else "error"
      )
      derived_entries[index] = ParameterCatalogEntry(
        **{
          **entry.__dict__,
          "availability": availability,
          "diagnostics": (ParameterCatalogDiagnostic(
            code=exc.code,
            message=str(exc),
            parameter_id=entry.definition_id,
            references=exc.references,
          ),),
        }
      )
  else:
    known_ids = set(available_ids)
    known_ids.update(spec.output_id for spec in derived_specs)
    inputs_by_output: dict[str, tuple[str, ...]] = {}
    for spec in plan.display_order:
      try:
        expression_inputs = extract_parameter_references(spec.expression, known_ids)
      except DerivedParameterPlanningError:
        # Planning already succeeded; retain explicit inputs if an unexpected parser
        # incompatibility is introduced later.
        expression_inputs = ()
      inputs_by_output[spec.output_id] = tuple(dict.fromkeys(
        (*spec.input_parameters, *expression_inputs)
      ))
    for index, entry in enumerate(derived_entries):
      if entry.definition_id is None:
        continue
      derived_entries[index] = ParameterCatalogEntry(
        **{
          **entry.__dict__,
          "input_parameter_ids": inputs_by_output.get(
            entry.parameter_id, entry.input_parameter_ids
          ),
        }
      )

  return (*acquired, *derived_entries)
