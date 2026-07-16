"""Safe, GUI-independent sample-group membership resolution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import AnnotationSpec, SampleGroupSpec, SampleSpec


class GroupResolutionError(FlowdeskError):
  """A stable error raised for malformed or ambiguous group definitions."""

  def __init__(self, code: str, message: str, **details: Any) -> None:
    self.code = code
    self.details = details
    super().__init__(message)


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
