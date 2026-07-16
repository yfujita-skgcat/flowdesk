"""Nested Boolean gate validation, evaluation, and legacy migration tests."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.boolean_expression import (
  BooleanExpressionError,
  evaluate_expression,
  migrate_boolean_thresholds,
  validate_expression,
)
from flowdesk_core.gating_strategy import GatingStrategyError, ordered_gates
from flowdesk_core.models import GateSpec, GatingStrategySpec
from flowdesk_storage.migrations import migrate_manifest


def test_nested_boolean_precedence_and_not_use_full_masks() -> None:
  masks = {
    "a": np.array([True, True, False, False]),
    "b": np.array([True, False, True, False]),
    "c": np.array([False, True, True, False]),
  }
  expression = {
    "op": "or",
    "children": [
      {"op": "and", "children": [{"op": "ref", "id": "a"}, {"op": "ref", "id": "b"}]},
      {"op": "not", "child": {"op": "ref", "id": "c"}},
    ],
  }
  result = evaluate_expression(expression, masks)
  assert result.tolist() == [True, False, False, True]
  assert not result.flags.writeable
  assert validate_expression(expression, set(masks)) == {"a", "b", "c"}


def test_nested_boolean_missing_scope_and_cycle_are_rejected_before_run() -> None:
  missing = {"op": "and", "children": [{"op": "ref", "id": "a"}, {"op": "ref", "id": "outside"}]}
  with pytest.raises(BooleanExpressionError, match="unknown id"):
    validate_expression(missing, {"a"})
  cyclic: dict = {"op": "not"}
  cyclic["child"] = cyclic
  with pytest.raises(BooleanExpressionError, match="cycle"):
    validate_expression(cyclic, {"a"})

  gates = (
    GateSpec(id="a", name="A", gate_type="range", x_parameter="X", thresholds={"min": 0}),
    GateSpec(
      id="b",
      name="B",
      gate_type="boolean",
      thresholds={"expression": {"op": "ref", "id": "outside"}},
    ),
  )
  with pytest.raises(GatingStrategyError, match="unknown source"):
    ordered_gates(GatingStrategySpec(id="s", name="S", gates=gates))


def test_legacy_boolean_thresholds_migrate_to_expression_tree() -> None:
  migrated = migrate_boolean_thresholds({"operation": "and", "source_ids": ["a", "b"]})
  assert migrated["expression"] == {
    "op": "and",
    "children": [{"op": "ref", "id": "a"}, {"op": "ref", "id": "b"}],
  }


def test_legacy_manifest_migration_persists_nested_boolean_expression() -> None:
  manifest = {
    "project_id": "legacy",
    "project_version": "1.5.0",
    "pipeline_version": "test",
    "samples": [],
    "gating_strategies_data": {
      "strategy": {
        "id": "strategy",
        "name": "Strategy",
        "gates": [{
          "id": "combined",
          "name": "Combined",
          "gate_type": "boolean",
          "thresholds": {"operation": "and", "source_ids": ["a", "b"]},
        }],
      }
    },
  }
  migrated = migrate_manifest(manifest)
  thresholds = migrated["gating_strategies_data"]["strategy"]["gates"][0]["thresholds"]
  assert thresholds["expression"]["op"] == "and"
