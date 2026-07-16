"""Validated nested Boolean expressions for gating strategies."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import numpy as np
from numpy.typing import NDArray


class BooleanExpressionError(ValueError):
  """Raised when a nested Boolean expression is invalid."""


Expression = dict[str, Any]


def legacy_expression(operation: str, source_ids: list[str] | tuple[str, ...]) -> Expression:
  """Convert the legacy flat Boolean representation to a nested tree."""
  refs = [{"op": "ref", "id": source_id} for source_id in source_ids]
  if operation not in {"and", "or", "not"}:
    raise BooleanExpressionError(
      "Boolean operation must be 'and', 'or', or 'not'"
    )
  if operation == "not":
    if len(refs) != 1:
      raise BooleanExpressionError("Boolean NOT requires exactly one source")
    return {"op": "not", "child": refs[0]}
  if len(refs) < 1:
    raise BooleanExpressionError(
      f"Boolean {operation!r} requires at least two sources"
    )
  return {"op": operation, "children": refs}


def expression_for_gate(thresholds: Mapping[str, Any]) -> Expression:
  """Return a nested expression, migrating legacy ``operation/source_ids``."""
  expression = thresholds.get("expression")
  if expression is not None:
    return deepcopy(dict(expression))
  operation = thresholds.get("operation")
  source_ids = thresholds.get("source_ids", [])
  if not isinstance(source_ids, (list, tuple)):
    raise BooleanExpressionError("Boolean source_ids must be an array")
  return legacy_expression(str(operation), list(source_ids))


def validate_expression(
  expression: Mapping[str, Any],
  available_ids: set[str],
  *,
  root_id: str = "all_events",
  owner_id: str | None = None,
) -> set[str]:
  """Validate expression shape and return referenced population IDs."""
  references: set[str] = set()
  active: set[int] = set()

  def visit(node: Mapping[str, Any], depth: int) -> None:
    if depth > 100:
      raise BooleanExpressionError("Boolean expression is too deeply nested")
    marker = id(node)
    if marker in active:
      raise BooleanExpressionError("Boolean expression cycle detected")
    active.add(marker)
    op = node.get("op")
    if op == "ref":
      ref_id = node.get("id")
      if not isinstance(ref_id, str) or not ref_id:
        raise BooleanExpressionError("Boolean ref id must be a non-empty string")
      if ref_id != root_id and ref_id not in available_ids:
        raise BooleanExpressionError(f"Boolean expression references unknown id: {ref_id!r}")
      if owner_id is not None and ref_id == owner_id:
        raise BooleanExpressionError(
          f"Boolean expression cycle/self-reference: {owner_id!r}"
        )
      references.add(ref_id)
    elif op == "not":
      child = node.get("child")
      if not isinstance(child, Mapping):
        raise BooleanExpressionError("Boolean NOT requires one child")
      visit(child, depth + 1)
    elif op in {"and", "or"}:
      children = node.get("children")
      if not isinstance(children, list) or len(children) < 1:
        raise BooleanExpressionError(f"Boolean {op!r} requires at least two children")
      for child in children:
        if not isinstance(child, Mapping):
          raise BooleanExpressionError("Boolean children must be objects")
        visit(child, depth + 1)
      if len(children) < 2:
        raise BooleanExpressionError(f"Boolean {op!r} requires at least two children")
    else:
      raise BooleanExpressionError(f"invalid Boolean expression op: {op!r}")
    active.remove(marker)

  if not isinstance(expression, Mapping):
    raise BooleanExpressionError("Boolean expression must be an object")
  visit(expression, 0)
  return references


def evaluate_expression(
  expression: Mapping[str, Any],
  masks: Mapping[str, NDArray[np.bool_]],
  *,
  root_mask: NDArray[np.bool_] | None = None,
) -> NDArray[np.bool_]:
  """Evaluate a validated expression against full-length Boolean masks."""
  root = root_mask
  if root is None:
    if not masks:
      raise BooleanExpressionError("cannot infer event count without masks")
    root = np.ones(len(next(iter(masks.values()))), dtype=np.bool_)

  def visit(node: Mapping[str, Any]) -> NDArray[np.bool_]:
    op = node.get("op")
    if op == "ref":
      ref_id = node.get("id")
      if ref_id == "all_events":
        return root
      if ref_id not in masks:
        raise BooleanExpressionError(f"Boolean expression references unknown id: {ref_id!r}")
      return masks[ref_id]
    if op == "not":
      return np.logical_not(visit(node["child"]))
    children = [visit(child) for child in node["children"]]
    result = children[0]
    for child in children[1:]:
      result = np.logical_and(result, child) if op == "and" else np.logical_or(result, child)
    return result

  result = np.asarray(visit(expression), dtype=np.bool_)
  result.setflags(write=False)
  return result


def migrate_boolean_thresholds(thresholds: Mapping[str, Any]) -> dict[str, Any]:
  """Persist a nested expression while retaining legacy fields for readers."""
  migrated = deepcopy(dict(thresholds))
  migrated["expression"] = expression_for_gate(thresholds)
  return migrated
