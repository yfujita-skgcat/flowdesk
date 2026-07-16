"""Safe, GUI-independent sample-group membership resolution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import (
  AnnotationSpec,
  GroupStrategyBindingSpec,
  SampleGroupSpec,
  SampleSpec,
)


class GroupResolutionError(FlowdeskError):
  """A stable error raised for malformed or ambiguous group definitions."""

  def __init__(self, code: str, message: str, **details: Any) -> None:
    self.code = code
    self.details = details
    super().__init__(message)


def resolve_group_strategy_bindings(
  groups: Sequence[SampleGroupSpec],
  bindings: Sequence[GroupStrategyBindingSpec],
  samples: Sequence[SampleSpec],
  annotations: Sequence[AnnotationSpec] = (),
) -> dict[str, tuple[str, tuple[str, ...]]]:
  """Resolve each sample to one unambiguous strategy and matching Groups.

  A sample may match multiple Groups when all matching bindings select the same
  strategy. Different strategies are rejected instead of being resolved by
  list order, preserving reproducibility.
  """
  group_members = resolve_group_member_ids(groups, samples, annotations)
  groups_by_sample: dict[str, list[str]] = {sample.id: [] for sample in samples}
  bindings_by_group: dict[str, list[GroupStrategyBindingSpec]] = {}
  for binding in bindings:
    bindings_by_group.setdefault(binding.group_id, []).append(binding)
  for group_id, member_ids in group_members.items():
    for sample_id in member_ids:
      groups_by_sample[sample_id].append(group_id)

  resolved: dict[str, tuple[str, tuple[str, ...]]] = {}
  for sample_id, group_ids in groups_by_sample.items():
    matched = [
      binding
      for group_id in group_ids
      for binding in bindings_by_group.get(group_id, [])
    ]
    strategy_ids = sorted({binding.gating_strategy_id for binding in matched})
    if len(strategy_ids) > 1:
      raise GroupResolutionError(
        "conflicting_group_strategy_binding",
        f"sample {sample_id!r} matches conflicting gating strategies",
        sample_id=sample_id,
        group_ids=tuple(sorted(group_ids)),
        strategy_ids=tuple(strategy_ids),
      )
    if strategy_ids:
      resolved[sample_id] = (strategy_ids[0], tuple(sorted(group_ids)))
  return resolved


def sample_group_specs_from_mapping(
  values: Sequence[Mapping[str, Any]],
) -> tuple[SampleGroupSpec, ...]:
  """Parse persisted Group mappings through the typed model contract."""
  try:
    return tuple(
      SampleGroupSpec(
        id=str(value["id"]),
        name=str(value.get("name", value["id"])),
        role=value.get("role", "user"),
        color=value.get("color"),
        sample_ids=tuple(value.get("sample_ids", ())),
        membership_rule=value.get("membership_rule"),
      )
      for value in values
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise GroupResolutionError("invalid_sample_group", str(exc)) from exc


def group_strategy_binding_specs_from_mapping(
  values: Sequence[Mapping[str, Any]],
) -> tuple[GroupStrategyBindingSpec, ...]:
  """Parse persisted Group/Strategy binding mappings."""
  try:
    return tuple(
      GroupStrategyBindingSpec(
        id=str(value["id"]),
        group_id=str(value["group_id"]),
        gating_strategy_id=str(value["gating_strategy_id"]),
        statistic_ids=tuple(value.get("statistic_ids", ())),
      )
      for value in values
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise GroupResolutionError("invalid_group_strategy_binding", str(exc)) from exc


def resolve_group_assignments_from_mappings(
  groups: Sequence[Mapping[str, Any]],
  bindings: Sequence[Mapping[str, Any]],
  samples: Sequence[Mapping[str, Any]],
  annotations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
  """Resolve persisted mappings to a stable API result for GUI and CLI."""
  typed_samples = tuple(
    SampleSpec(
      id=str(sample.get("id", "")),
      name=str(sample.get("name", sample.get("id", ""))),
      path=str(sample.get("path", "")),
      metadata=dict(sample.get("metadata", {})),
    )
    for sample in samples
  )
  resolved = resolve_group_strategy_bindings(
    sample_group_specs_from_mapping(groups),
    group_strategy_binding_specs_from_mapping(bindings),
    typed_samples,
    annotation_specs_from_mapping(annotations),
  )
  return {
    sample_id: {
      "group_ids": list(group_ids),
      "strategy_id": strategy_id,
    }
    for sample_id, (strategy_id, group_ids) in resolved.items()
  }


def annotation_specs_from_mapping(
  values: Sequence[Mapping[str, Any]],
) -> tuple[AnnotationSpec, ...]:
  """Parse persisted typed annotations."""
  try:
    return tuple(
      AnnotationSpec(
        sample_id=str(value["sample_id"]),
        keyword=str(value["keyword"]),
        value=value.get("value"),
        source=value["source"],
      )
      for value in values
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise GroupResolutionError("invalid_annotation", str(exc)) from exc


def resolve_group_member_ids(
  groups: Sequence[SampleGroupSpec],
  samples: Sequence[SampleSpec],
  annotations: Sequence[AnnotationSpec] = (),
) -> dict[str, tuple[str, ...]]:
  """Resolve explicit and restricted-rule membership in sample input order.

  Workspace and imported annotations shadow FCS annotations and sample metadata
  for rule evaluation only; neither path mutates raw FCS metadata.
  """

  sample_by_id = {sample.id: sample for sample in samples}
  if len(sample_by_id) != len(samples):
    raise GroupResolutionError("duplicate_sample_id", "sample IDs must be unique")
  if len({group.id for group in groups}) != len(groups):
    raise GroupResolutionError("duplicate_group_id", "sample group IDs must be unique")
  metadata = _resolved_metadata(samples, annotations)
  resolved: dict[str, tuple[str, ...]] = {}
  for group in groups:
    unknown_ids = set(group.sample_ids) - sample_by_id.keys()
    if unknown_ids:
      raise GroupResolutionError(
        "unknown_group_sample",
        f"group {group.id!r} references unknown sample IDs",
        group_id=group.id,
        sample_ids=tuple(sorted(unknown_ids)),
      )
    members = [sample_id for sample_id in group.sample_ids]
    for sample in samples:
      if group.membership_rule is not None and _matches_rule(
        group.membership_rule, metadata[sample.id]
      ) and sample.id not in members:
        members.append(sample.id)
    resolved[group.id] = tuple(members)
  return resolved


def _resolved_metadata(
  samples: Sequence[SampleSpec],
  annotations: Sequence[AnnotationSpec],
) -> dict[str, dict[str, Any]]:
  result = {sample.id: dict(sample.metadata) for sample in samples}
  sample_ids = set(result)
  source_rank = {"fcs": 0, "imported": 1, "workspace": 2}
  seen: dict[tuple[str, str], int] = {}
  for annotation in annotations:
    if annotation.sample_id not in sample_ids:
      raise GroupResolutionError(
        "unknown_annotation_sample",
        f"annotation references unknown sample {annotation.sample_id!r}",
        sample_id=annotation.sample_id,
      )
    key = (annotation.sample_id, annotation.keyword)
    rank = source_rank[annotation.source]
    if rank >= seen.get(key, -1):
      result[annotation.sample_id][annotation.keyword] = annotation.value
      seen[key] = rank
  return result


def _matches_rule(rule: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
  """Evaluate the documented JSON rule AST without arbitrary expression code."""

  operators = [key for key in ("all", "any", "not", "keyword") if key in rule]
  if len(operators) != 1:
    raise GroupResolutionError("invalid_group_rule", "rule must contain one operator")
  operator = operators[0]
  if operator in {"all", "any"}:
    children = rule[operator]
    if not isinstance(children, list):
      raise GroupResolutionError("invalid_group_rule", f"{operator} must be an array")
    values = [
      _matches_rule(child, metadata)
      if isinstance(child, Mapping) else _invalid_rule()
      for child in children
    ]
    return all(values) if operator == "all" else any(values)
  if operator == "not":
    child = rule["not"]
    if not isinstance(child, Mapping):
      raise GroupResolutionError("invalid_group_rule", "not must contain a rule object")
    return not _matches_rule(child, metadata)

  keyword = rule["keyword"]
  comparison = rule.get("comparison", "equals")
  value = rule.get("value")
  if not isinstance(keyword, str) or not keyword:
    raise GroupResolutionError("invalid_group_rule", "keyword must be a non-empty string")
  if comparison not in {"equals", "in", "gt", "gte", "lt", "lte"}:
    raise GroupResolutionError("invalid_group_rule", "unsupported keyword comparison")
  actual = metadata.get(keyword)
  if actual is None:
    return False
  if comparison == "equals":
    return actual == value
  if comparison == "in":
    if not isinstance(value, list):
      raise GroupResolutionError("invalid_group_rule", "in comparison value must be an array")
    return actual in value
  if not _is_finite_number(actual) or not _is_finite_number(value):
    return False
  if comparison == "gt":
    return actual > value
  if comparison == "gte":
    return actual >= value
  if comparison == "lt":
    return actual < value
  return actual <= value


def _is_finite_number(value: Any) -> bool:
  return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _invalid_rule() -> bool:
  raise GroupResolutionError("invalid_group_rule", "boolean child must be a rule object")
