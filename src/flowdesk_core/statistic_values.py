"""GUI-independent choices for selecting a statistic value representation.

The user-facing value choice is a view over the persisted statistic triple
``parameter_id + source_stage + transform_id``.  It never creates synthetic
scientific channel IDs and never evaluates event data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from flowdesk_core.parameter_catalog import ParameterCatalogEntry

StatisticValueStage = Literal["raw", "compensated", "transformed"]


@dataclass(frozen=True)
class StatisticValueChoice:
  """One selectable representation of a stable acquired/derived parameter."""

  parameter_id: str
  parameter_kind: Literal["acquired", "derived"]
  source_stage: StatisticValueStage
  transform_id: str | None
  display_label: str
  provenance_label: str
  available: bool = True
  diagnostic_code: str | None = None
  diagnostic_message: str | None = None

  @property
  def key(self) -> tuple[str, StatisticValueStage, str | None]:
    """Structured persisted identity; never parse display text for this."""
    return (self.parameter_id, self.source_stage, self.transform_id)


@dataclass(frozen=True)
class StatisticValueResolution:
  """Resolution result for one persisted statistic value triple."""

  choice: StatisticValueChoice | None
  code: str | None = None
  message: str | None = None

  @property
  def is_valid(self) -> bool:
    return self.choice is not None and self.choice.available and self.code is None


def _transform_fields(transform: object) -> tuple[str, str, str | None, str]:
  if isinstance(transform, Mapping):
    transform_id = str(transform.get("id") or "")
    name = str(transform.get("name") or transform_id)
    parameter_id = transform.get("parameter")
    role = str(transform.get("role") or "analysis")
    return transform_id, name, None if parameter_id is None else str(parameter_id), role
  transform_id = str(getattr(transform, "id", "") or "")
  name = str(getattr(transform, "name", "") or transform_id)
  parameter_id = getattr(transform, "parameter", None)
  role = str(getattr(transform, "role", "analysis") or "analysis")
  return transform_id, name, None if parameter_id is None else str(parameter_id), role


def _derived_provenance(entry: ParameterCatalogEntry) -> str:
  if entry.source_stage == "raw":
    return "Derived value (raw inputs)"
  if entry.source_stage == "compensated":
    return "Derived value (compensated inputs)"
  return f"Derived value ({entry.source_stage} inputs)"


def _entry_diagnostic(entry: ParameterCatalogEntry) -> tuple[str | None, str | None]:
  if entry.is_definition_valid:
    return None, None
  diagnostic = entry.diagnostics[0] if entry.diagnostics else None
  if diagnostic is None:
    return "invalid_parameter_definition", "The parameter definition is invalid."
  return diagnostic.code, diagnostic.message


def build_statistic_value_choices(
  entries: Sequence[ParameterCatalogEntry],
  transforms: Sequence[object] = (),
) -> tuple[StatisticValueChoice, ...]:
  """Build deterministic virtual value choices from the shared catalog.

  Derived outputs are materialized in the compensated/derived stage even when
  their expressions read raw inputs.  Therefore no ``raw`` statistic choice is
  created for a derived entry.
  """
  choices: list[StatisticValueChoice] = []
  transform_rows = tuple(
    _transform_fields(value)
    for value in transforms
  )
  for entry in entries:
    diagnostic_code, diagnostic_message = _entry_diagnostic(entry)
    if entry.kind == "acquired":
      choices.extend((
        StatisticValueChoice(
          parameter_id=entry.parameter_id,
          parameter_kind="acquired",
          source_stage="raw",
          transform_id=None,
          display_label=f"{entry.display_name} — Raw FCS value",
          provenance_label="Raw FCS value",
          available=entry.is_definition_valid,
          diagnostic_code=diagnostic_code,
          diagnostic_message=diagnostic_message,
        ),
        StatisticValueChoice(
          parameter_id=entry.parameter_id,
          parameter_kind="acquired",
          source_stage="compensated",
          transform_id=None,
          display_label=f"{entry.display_name} — Compensated analysis value",
          provenance_label="Compensated analysis value",
          available=entry.is_definition_valid,
          diagnostic_code=diagnostic_code,
          diagnostic_message=diagnostic_message,
        ),
      ))
    else:
      choices.append(StatisticValueChoice(
        parameter_id=entry.parameter_id,
        parameter_kind="derived",
        source_stage="compensated",
        transform_id=None,
        display_label=f"{entry.display_name} — {_derived_provenance(entry)}",
        provenance_label=_derived_provenance(entry),
        available=entry.is_definition_valid,
        diagnostic_code=diagnostic_code,
        diagnostic_message=diagnostic_message,
      ))

    if not entry.is_definition_valid:
      continue
    for transform_id, transform_name, parameter_id, role in transform_rows:
      if role != "analysis" or not transform_id or parameter_id != entry.parameter_id:
        continue
      choices.append(StatisticValueChoice(
        parameter_id=entry.parameter_id,
        parameter_kind=entry.kind,
        source_stage="transformed",
        transform_id=transform_id,
        display_label=f"{entry.display_name} — {transform_name}",
        provenance_label=f"Transform {transform_name}",
        available=True,
      ))
  return tuple(choices)


def resolve_statistic_value_choice(
  entries: Sequence[ParameterCatalogEntry],
  transforms: Sequence[object],
  parameter_id: str | None,
  source_stage: str | None,
  transform_id: str | None,
) -> StatisticValueResolution:
  """Resolve persisted statistic fields without display-name matching."""
  parameter = str(parameter_id or "")
  stage = str(source_stage or "")
  transform = None if transform_id is None else str(transform_id)
  entry = next((item for item in entries if item.parameter_id == parameter), None)
  if entry is None:
    return StatisticValueResolution(
      None, "unknown_parameter", f"Unknown statistic parameter {parameter!r}."
    )
  if not entry.is_definition_valid:
    code, message = _entry_diagnostic(entry)
    return StatisticValueResolution(
      None, code or "invalid_parameter_definition", message
    )
  if entry.kind == "derived" and stage == "raw":
    return StatisticValueResolution(
      None,
      "derived_output_not_available_in_raw_stage",
      "Derived outputs are materialized after compensation/derived processing; "
      "raw is an input stage, not a derived-output value domain.",
    )
  choices = build_statistic_value_choices(entries, transforms)
  matching = tuple(
    choice for choice in choices
    if choice.key == (parameter, stage, transform)
  )
  if not matching:
    if stage == "transformed" and not transform:
      code = "transformed_statistic_requires_transform"
      message = "A transformed statistic requires an explicit transform."
    elif transform:
      code = "unknown_or_mismatched_transform"
      message = f"Transform {transform!r} is unavailable for parameter {parameter!r}."
    else:
      code = "unsupported_statistic_value_domain"
      message = f"Value domain {stage!r} is unavailable for parameter {parameter!r}."
    return StatisticValueResolution(None, code, message)
  return StatisticValueResolution(matching[0])
