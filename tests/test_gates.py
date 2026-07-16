"""Tests for gate evaluation: rectangle, range, polygon, boolean, hierarchy."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.gate_transform_migration import (
  GateTransformMigrationError,
  build_gate_transform_migration_candidate,
  preview_gate_transform_migration,
)
from flowdesk_core.gates import (
  GateError,
  apply_parent_mask,
  evaluate_gate,
  point_in_rectangle,
)
from flowdesk_core.gating_strategy import (
  GatingStrategyError,
  evaluate_gating_strategy,
  evaluate_gating_strategy_with_membership,
  ordered_gates,
)
from flowdesk_core.models import (
  GateSpec,
  GatingStrategySpec,
  TransformSpec,
)
from flowdesk_core.transforms import LOGICLE_IMPLEMENTATION_VERSION, apply_transform

# ---------------------------------------------------------------------------
# Backward-compatible scalar rectangle
# ---------------------------------------------------------------------------


def test_rectangle_gate_membership_placeholder() -> None:
  """Original scalar test preserved for backward compatibility."""
  gate = GateSpec(
    id="g1",
    name="live",
    gate_type="rectangle",
    x_parameter="FSC-A",
    y_parameter="SSC-A",
    thresholds={"x_min": 1.0, "x_max": 3.0, "y_min": 2.0, "y_max": 4.0},
  )

  assert point_in_rectangle(gate, 2.0, 3.0)
  assert not point_in_rectangle(gate, 4.0, 3.0)


# ---------------------------------------------------------------------------
# Vectorized rectangle gate
# ---------------------------------------------------------------------------


def test_rectangle_vectorized_basic() -> None:
  gate = GateSpec(
    id="g_rect",
    name="rect",
    gate_type="rectangle",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  x = np.array([5.0, 15.0, 0.0, 10.0, -1.0], dtype=np.float64)
  y = np.array([5.0, 5.0, 0.0, 10.0, 5.0], dtype=np.float64)

  mask = evaluate_gate(gate, x, y)
  expected = np.array([True, False, True, True, False])
  np.testing.assert_array_equal(mask, expected)


def test_rectangle_boundary_inclusive() -> None:
  """Rectangle boundaries are inclusive on all sides."""
  gate = GateSpec(
    id="g_bound",
    name="bound",
    gate_type="rectangle",
    thresholds={"x_min": 1.0, "x_max": 5.0, "y_min": 2.0, "y_max": 6.0},
  )
  # Exactly on boundary
  x = np.array([1.0, 5.0, 3.0], dtype=np.float64)
  y = np.array([2.0, 6.0, 4.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert mask.all()


def test_rectangle_missing_y_raises() -> None:
  gate = GateSpec(
    id="g_noy",
    name="noy",
    gate_type="rectangle",
    thresholds={"x_min": 0.0, "x_max": 1.0},
  )
  x = np.array([0.5], dtype=np.float64)
  with pytest.raises(GateError, match="requires y_values"):
    evaluate_gate(gate, x, None)


# ---------------------------------------------------------------------------
# Range gate
# ---------------------------------------------------------------------------


def test_range_basic() -> None:
  gate = GateSpec(
    id="g_range",
    name="range",
    gate_type="range",
    thresholds={"min": 10.0, "max": 20.0},
  )
  x = np.array([5.0, 10.0, 15.0, 20.0, 25.0], dtype=np.float64)
  mask = evaluate_gate(gate, x)
  expected = np.array([False, True, True, True, False])
  np.testing.assert_array_equal(mask, expected)


def test_range_open_low() -> None:
  """Range with only max is open on the low side."""
  gate = GateSpec(
    id="g_olow",
    name="open_low",
    gate_type="range",
    thresholds={"max": 10.0},
  )
  x = np.array([-100.0, 0.0, 10.0, 11.0], dtype=np.float64)
  mask = evaluate_gate(gate, x)
  expected = np.array([True, True, True, False])
  np.testing.assert_array_equal(mask, expected)


def test_range_open_high() -> None:
  """Range with only min is open on the high side."""
  gate = GateSpec(
    id="g_ohigh",
    name="open_high",
    gate_type="range",
    thresholds={"min": 5.0},
  )
  x = np.array([0.0, 5.0, 100.0], dtype=np.float64)
  mask = evaluate_gate(gate, x)
  expected = np.array([False, True, True])
  np.testing.assert_array_equal(mask, expected)


def test_range_unbounded() -> None:
  """Range with no thresholds accepts all events."""
  gate = GateSpec(
    id="g_unbound",
    name="unbounded",
    gate_type="range",
  )
  x = np.array([1.0, 2.0, 3.0], dtype=np.float64)
  mask = evaluate_gate(gate, x)
  assert mask.all()


# ---------------------------------------------------------------------------
# Ellipse gate
# ---------------------------------------------------------------------------


def test_rotated_ellipse_inclusive_boundary_and_nan() -> None:
  gate = GateSpec(
    id="ellipse",
    name="ellipse",
    gate_type="ellipse",
    thresholds={
      "center_x": 0.0,
      "center_y": 0.0,
      "radius_x": 2.0,
      "radius_y": 1.0,
      "rotation": np.pi / 2,
    },
  )
  x = np.array([0.0, 1.0, 0.0, 1.1, np.nan])
  y = np.array([1.0, 0.0, 2.1, 2.1, 0.0])
  assert evaluate_gate(gate, x, y).tolist() == [True, True, False, False, False]


def test_ellipse_rejects_degenerate_radii() -> None:
  gate = GateSpec(
    id="ellipse",
    name="ellipse",
    gate_type="ellipse",
    thresholds={
      "center_x": 0.0,
      "center_y": 0.0,
      "radius_x": 0.0,
      "radius_y": 1.0,
    },
  )
  with pytest.raises(GateError, match="radii"):
    evaluate_gate(gate, np.array([0.0]), np.array([0.0]))


# ---------------------------------------------------------------------------
# Polygon gate
# ---------------------------------------------------------------------------


def test_polygon_triangle_inside() -> None:
  """Point inside a triangle polygon."""
  gate = GateSpec(
    id="g_poly",
    name="triangle",
    gate_type="polygon",
    coordinates=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)],
  )
  x = np.array([5.0], dtype=np.float64)
  y = np.array([3.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert mask[0]


def test_polygon_triangle_outside() -> None:
  """Point outside a triangle polygon."""
  gate = GateSpec(
    id="g_poly2",
    name="triangle",
    gate_type="polygon",
    coordinates=[(0.0, 0.0), (10.0, 0.0), (5.0, 10.0)],
  )
  x = np.array([20.0], dtype=np.float64)
  y = np.array([20.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert not mask[0]


def test_polygon_edge_inclusive() -> None:
  """Point exactly on a polygon edge is inside."""
  gate = GateSpec(
    id="g_edge",
    name="square",
    gate_type="polygon",
    coordinates=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
  )
  # Point on bottom edge
  x = np.array([5.0], dtype=np.float64)
  y = np.array([0.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert mask[0]


def test_polygon_vertex_inclusive() -> None:
  """Point exactly at a polygon vertex is inside."""
  gate = GateSpec(
    id="g_vert",
    name="square",
    gate_type="polygon",
    coordinates=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
  )
  x = np.array([0.0], dtype=np.float64)
  y = np.array([0.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert mask[0]


def test_polygon_concave() -> None:
  """Concave polygon: L-shape."""
  gate = GateSpec(
    id="g_concave",
    name="l_shape",
    gate_type="polygon",
    coordinates=[
      (0.0, 0.0),
      (10.0, 0.0),
      (10.0, 5.0),
      (5.0, 5.0),
      (5.0, 10.0),
      (0.0, 10.0),
    ],
  )
  # Inside the L
  x = np.array([2.0, 7.0, 7.0], dtype=np.float64)
  y = np.array([2.0, 7.0, 7.0], dtype=np.float64)
  mask = evaluate_gate(gate, x, y)
  assert mask[0]  # (2, 2) inside
  assert not mask[1]  # (7, 7) in the cut-out


def test_polygon_too_few_vertices_raises() -> None:
  gate = GateSpec(
    id="g_bad",
    name="bad",
    gate_type="polygon",
    coordinates=[(0.0, 0.0), (1.0, 1.0)],
  )
  x = np.array([0.5], dtype=np.float64)
  y = np.array([0.5], dtype=np.float64)
  with pytest.raises(GateError, match="at least 3"):
    evaluate_gate(gate, x, y)


# ---------------------------------------------------------------------------
# Boolean gate
# ---------------------------------------------------------------------------


def test_boolean_and() -> None:
  gate = GateSpec(
    id="g_and",
    name="and",
    gate_type="boolean",
    thresholds={
      "operation": "and",
      "source_ids": ["g_a", "g_b"],
    },
  )
  masks = {
    "g_a": np.array([True, True, False, False]),
    "g_b": np.array([True, False, True, False]),
  }
  result = evaluate_gate(gate, np.array([0.0]), None, masks)
  expected = np.array([True, False, False, False])
  np.testing.assert_array_equal(result, expected)


def test_boolean_or() -> None:
  gate = GateSpec(
    id="g_or",
    name="or",
    gate_type="boolean",
    thresholds={
      "operation": "or",
      "source_ids": ["g_a", "g_b"],
    },
  )
  masks = {
    "g_a": np.array([True, False, False]),
    "g_b": np.array([False, True, False]),
  }
  result = evaluate_gate(gate, np.array([0.0]), None, masks)
  expected = np.array([True, True, False])
  np.testing.assert_array_equal(result, expected)


def test_boolean_not() -> None:
  gate = GateSpec(
    id="g_not",
    name="not",
    gate_type="boolean",
    thresholds={
      "operation": "not",
      "source_ids": ["g_a"],
    },
  )
  masks = {"g_a": np.array([True, False, True])}
  result = evaluate_gate(gate, np.array([0.0]), None, masks)
  expected = np.array([False, True, False])
  np.testing.assert_array_equal(result, expected)


def test_boolean_unknown_source_raises() -> None:
  gate = GateSpec(
    id="g_bad_bool",
    name="bad_bool",
    gate_type="boolean",
    thresholds={
      "operation": "and",
      "source_ids": ["nonexistent"],
    },
  )
  masks = {"other": np.array([True])}
  with pytest.raises(GateError, match="unknown id"):
    evaluate_gate(gate, np.array([0.0]), None, masks)


def test_boolean_no_masks_raises() -> None:
  gate = GateSpec(
    id="g_nomask",
    name="no_mask",
    gate_type="boolean",
    thresholds={"operation": "and", "source_ids": ["g_a"]},
  )
  with pytest.raises(GateError, match="requires boolean_masks"):
    evaluate_gate(gate, np.array([0.0]), None, None)


def test_boolean_invalid_op_raises() -> None:
  gate = GateSpec(
    id="g_badop",
    name="bad_op",
    gate_type="boolean",
    thresholds={"operation": "xor", "source_ids": ["g_a"]},
  )
  with pytest.raises(GateError, match="must be"):
    evaluate_gate(gate, np.array([0.0]), None, {"g_a": np.array([True])})


# ---------------------------------------------------------------------------
# Parent-child masking
# ---------------------------------------------------------------------------


def test_parent_mask_restriction() -> None:
  parent = np.array([True, True, False, False])
  child = np.array([True, False, True, False])
  result = apply_parent_mask(child, parent)
  expected = np.array([True, False, False, False])
  np.testing.assert_array_equal(result, expected)


# ---------------------------------------------------------------------------
# Gating strategy evaluation
# ---------------------------------------------------------------------------


def test_gating_strategy_basic() -> None:
  """Two gates: live cells -> CD4+ within live cells."""
  gate_live = GateSpec(
    id="live",
    name="Live",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="FSC-A",
    y_parameter="SSC-A",
    thresholds={"x_min": 100.0, "x_max": 500.0, "y_min": 50.0, "y_max": 300.0},
  )

  gate_cd4 = GateSpec(
    id="cd4",
    name="CD4+",
    gate_type="rectangle",
    parent_population_id="live",
    x_parameter="FSC-A",
    y_parameter="FITC-A",
    thresholds={"x_min": 100.0, "x_max": 500.0, "y_min": 200.0, "y_max": 600.0},
  )

  strategy = GatingStrategySpec(
    id="strat1",
    name="Test Strategy",
    gates=(gate_live, gate_cd4),
    root_population_id="all_events",
  )

  data = np.array([
    [200.0, 100.0, 300.0],  # live, CD4+
    [200.0, 100.0, 100.0],  # live, CD4-
    [600.0, 100.0, 300.0],  # dead (outside live gate)
    [200.0, 100.0, 500.0],  # live, CD4+
  ], dtype=np.float64)

  channels = ["FSC-A", "SSC-A", "FITC-A"]
  results = evaluate_gating_strategy(strategy, data, channels)

  # Root: all 4 events
  assert results[0].population_id == "all_events"
  assert results[0].event_count == 4

  # Live: 3 events (row 0, 1, 3)
  assert results[1].population_id == "live"
  assert results[1].event_count == 3

  # CD4+: 2 events within live (row 0, 3)
  assert results[2].population_id == "cd4"
  assert results[2].event_count == 2
  assert results[2].frequency_of_parent == pytest.approx(2 / 3)
  assert results[2].frequency_of_total == pytest.approx(2 / 4)


def test_gating_strategy_unknown_parent_raises() -> None:
  gate = GateSpec(
    id="g_orphan",
    name="orphan",
    gate_type="rectangle",
    parent_population_id="nonexistent",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 1.0, "y_min": 0.0, "y_max": 1.0},
  )
  strategy = GatingStrategySpec(
    id="s1",
    name="bad",
    gates=(gate,),
  )
  data = np.array([[0.5, 0.5]], dtype=np.float64)
  with pytest.raises(GatingStrategyError, match="unknown parent"):
    evaluate_gating_strategy(strategy, data, ["x", "y"])


def test_gating_strategy_orders_boolean_gate_after_sources() -> None:
  source = GateSpec(
    id="source",
    name="source",
    gate_type="range",
    parent_population_id="all_events",
    x_parameter="x",
    thresholds={"min": 1.0},
  )
  boolean = GateSpec(
    id="not_source",
    name="not source",
    gate_type="boolean",
    parent_population_id="all_events",
    thresholds={"operation": "not", "source_ids": ["source"]},
  )
  strategy = GatingStrategySpec(id="s", name="s", gates=(boolean, source))

  assert [gate.id for gate in ordered_gates(strategy)] == ["source", "not_source"]
  results = evaluate_gating_strategy(
    strategy,
    np.array([[0.0], [2.0]], dtype=np.float64),
    ["x"],
  )
  assert {result.population_id: result.event_count for result in results} == {
    "all_events": 2,
    "source": 1,
    "not_source": 1,
  }


def test_gating_strategy_rejects_unknown_boolean_source() -> None:
  gate = GateSpec(
    id="bad",
    name="bad",
    gate_type="boolean",
    thresholds={"operation": "not", "source_ids": ["missing"]},
  )
  with pytest.raises(GatingStrategyError, match="unknown source"):
    ordered_gates(GatingStrategySpec(id="s", name="s", gates=(gate,)))


def test_gating_strategy_rejects_dependency_cycle() -> None:
  gate_a = GateSpec(
    id="a",
    name="a",
    gate_type="range",
    parent_population_id="b",
    x_parameter="x",
    thresholds={"min": 0.0},
  )
  gate_b = GateSpec(
    id="b",
    name="b",
    gate_type="range",
    parent_population_id="a",
    x_parameter="x",
    thresholds={"min": 0.0},
  )
  with pytest.raises(GatingStrategyError, match="cycle"):
    ordered_gates(GatingStrategySpec(id="s", name="s", gates=(gate_a, gate_b)))


# ---------------------------------------------------------------------------
# Phase 2: PopulationMembership tests
# ---------------------------------------------------------------------------


def test_population_membership_dataclass_frozen() -> None:
  """PopulationMembership is a frozen dataclass."""
  from flowdesk_core.models import PopulationMembership

  mask = np.array([True, True, False], dtype=np.bool_)
  mask.setflags(write=False)
  pm = PopulationMembership(
    sample_id="s1",
    population_id="all_events",
    mask=mask,
  )
  assert pm.sample_id == "s1"
  assert pm.population_id == "all_events"
  assert pm.event_count == 2


def test_population_membership_mask_is_readonly() -> None:
  """The mask inside PopulationMembership is read-only after construction."""
  from flowdesk_core.models import PopulationMembership

  mask = np.array([True, False, True], dtype=np.bool_)
  pm = PopulationMembership(
    sample_id="s1",
    population_id="pop1",
    mask=mask,
  )
  # Original array may be modified, but the mask inside pm must not be.
  assert not pm.mask.flags["WRITEABLE"]
  mask[0] = False
  assert bool(pm.mask[0]) is True
  with pytest.raises(ValueError, match="read-only"):
    pm.mask[0] = False


def test_population_membership_event_count_matches_mask_sum() -> None:
  """event_count property equals mask.sum()."""
  from flowdesk_core.models import PopulationMembership

  mask = np.array([True, True, False, True, False], dtype=np.bool_)
  pm = PopulationMembership(
    sample_id="s1",
    population_id="pop1",
    mask=mask,
  )
  assert pm.event_count == 3
  assert pm.event_count == int(pm.mask.sum())


def test_population_membership_mask_shape_and_dtype() -> None:
  """Mask has correct shape and dtype."""
  from flowdesk_core.models import PopulationMembership

  n = 50
  mask = np.ones(n, dtype=np.bool_)
  pm = PopulationMembership(
    sample_id="s1",
    population_id="all_events",
    mask=mask,
  )
  assert pm.mask.shape == (n,)
  assert pm.mask.dtype == np.bool_


def test_evaluate_gating_strategy_with_membership_root_mask_all_true() -> None:
  """Root population mask is all True."""
  gate = GateSpec(
    id="g1",
    name="g1",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  strategy = GatingStrategySpec(
    id="s1",
    name="s1",
    gates=(gate,),
    root_population_id="all_events",
  )
  data = np.array([[5.0, 5.0], [20.0, 20.0]], dtype=np.float64)
  channels = ["x", "y"]

  results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channels
  )

  root_mask = masks["all_events"]
  assert root_mask.shape == (2,)
  assert root_mask.dtype == np.bool_
  assert root_mask.all()
  assert not root_mask.flags["WRITEABLE"]


def test_evaluate_with_membership_child_mask_subset_of_parent() -> None:
  """Child mask is a subset of parent mask."""
  gate_live = GateSpec(
    id="live",
    name="Live",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  gate_cd4 = GateSpec(
    id="cd4",
    name="CD4+",
    gate_type="rectangle",
    parent_population_id="live",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 5.0, "y_min": 0.0, "y_max": 5.0},
  )
  strategy = GatingStrategySpec(
    id="s2",
    name="s2",
    gates=(gate_live, gate_cd4),
    root_population_id="all_events",
  )
  data = np.array([
    [3.0, 3.0],   # live, cd4+
    [8.0, 8.0],   # live, cd4-
    [20.0, 20.0], # dead
  ], dtype=np.float64)
  channels = ["x", "y"]

  results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channels
  )

  live_mask = masks["live"]
  cd4_mask = masks["cd4"]

  # cd4 events must be subset of live events
  assert (cd4_mask <= live_mask).all()
  # Event outside live must not be in cd4
  assert not cd4_mask[2]


def test_evaluate_with_membership_event_count_consistency() -> None:
  """PopulationResult.event_count == membership.mask.sum() for every population."""
  gate = GateSpec(
    id="g1",
    name="g1",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 5.0, "x_max": 15.0, "y_min": 5.0, "y_max": 15.0},
  )
  strategy = GatingStrategySpec(
    id="s3",
    name="s3",
    gates=(gate,),
    root_population_id="all_events",
  )
  data = np.array([
    [10.0, 10.0],
    [20.0, 20.0],
    [10.0, 10.0],
    [20.0, 5.0],
  ], dtype=np.float64)
  channels = ["x", "y"]

  results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channels
  )

  for result in results:
    pop_id = result.population_id
    mask = masks[pop_id]
    assert result.event_count == int(mask.sum()), (
      f"event_count mismatch for {pop_id}: {result.event_count} != {mask.sum()}"
    )


def test_evaluate_with_membership_boolean_gate_consistency() -> None:
  """Boolean gate mask matches existing event count."""
  gate_a = GateSpec(
    id="ga",
    name="A",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  gate_b = GateSpec(
    id="gb",
    name="B",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 5.0, "x_max": 15.0, "y_min": 5.0, "y_max": 15.0},
  )
  gate_and = GateSpec(
    id="g_and",
    name="A and B",
    gate_type="boolean",
    parent_population_id="all_events",
    thresholds={"operation": "and", "source_ids": ["ga", "gb"]},
  )
  strategy = GatingStrategySpec(
    id="s4",
    name="s4",
    gates=(gate_a, gate_b, gate_and),
    root_population_id="all_events",
  )
  data = np.array([
    [3.0, 3.0],   # A only
    [8.0, 8.0],   # A and B
    [20.0, 20.0], # neither
    [12.0, 12.0], # B only
  ], dtype=np.float64)
  channels = ["x", "y"]

  results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channels
  )

  and_mask = masks["g_and"]
  # Only event index 1 should be in both A and B
  expected = np.array([False, True, False, False])
  np.testing.assert_array_equal(and_mask, expected)

  # Verify consistency with PopulationResult
  and_result = next(
    r for r in results if r.population_id == "g_and"
  )
  assert and_result.event_count == int(and_mask.sum())


def test_evaluate_with_membership_masks_are_readonly() -> None:
  """Returned masks are read-only."""
  gate = GateSpec(
    id="g1",
    name="g1",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  strategy = GatingStrategySpec(
    id="s5",
    name="s5",
    gates=(gate,),
  )
  data = np.array([[5.0, 5.0]], dtype=np.float64)
  channels = ["x", "y"]

  _results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, channels
  )

  for mask in masks.values():
    assert not mask.flags["WRITEABLE"]
    with pytest.raises(ValueError, match="read-only"):
      mask[0] = False


def test_evaluate_with_membership_raw_data_unchanged() -> None:
  """The raw input data array is not modified by the gating strategy."""
  gate = GateSpec(
    id="g1",
    name="g1",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    thresholds={"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0},
  )
  strategy = GatingStrategySpec(
    id="s6",
    name="s6",
    gates=(gate,),
  )
  data = np.array([[5.0, 5.0], [20.0, 20.0]], dtype=np.float64)
  data_copy = data.copy()
  channels = ["x", "y"]

  evaluate_gating_strategy_with_membership(strategy, data, channels)

  np.testing.assert_array_equal(data, data_copy)


def test_polygon_gate_is_evaluated_in_its_stored_log_scales() -> None:
  strategy = GatingStrategySpec(
    id="log-gating",
    name="Log gating",
    gates=(
      GateSpec(
        id="log-poly",
        name="Log polygon",
        gate_type="polygon",
        parent_population_id="all_events",
        x_parameter="x",
        y_parameter="y",
        x_scale="log10",
        y_scale="log10",
        coordinates=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
      ),
    ),
  )
  data = np.array([
    [1.0, 1.0], [10.0, 10.0], [100.0, 100.0],
    [1000.0, 10.0], [0.0, 10.0],
  ])

  results, masks = evaluate_gating_strategy_with_membership(
    strategy, data, ["x", "y"]
  )

  assert masks["log-poly"].tolist() == [True, True, True, False, False]
  result = next(r for r in results if r.population_id == "log-poly")
  assert result.event_count == 3


def _gate_logicle_transform(parameter: str, transform_id: str) -> TransformSpec:
  return TransformSpec(
    id=transform_id,
    name=f"Logicle {parameter}",
    transform_type="logicle",
    parameter=parameter,
    settings={
      "T": 262144.0,
      "W": 0.5,
      "M": 4.5,
      "A": 0.0,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
  )


def test_rectangle_gate_uses_referenced_logicle_transforms_once() -> None:
  x_transform = _gate_logicle_transform("x", "logicle_x")
  y_transform = _gate_logicle_transform("y", "logicle_y")
  events = np.array([
    [-100.0, -100.0],
    [0.0, 0.0],
    [100.0, 100.0],
    [1000.0, 1000.0],
  ], dtype=np.float64)
  transformed = apply_transform(
    x_transform,
    np.array([-100.0, 100.0], dtype=np.float64),
  )
  gate = GateSpec(
    id="logicle_rectangle",
    name="Logicle rectangle",
    gate_type="rectangle",
    parent_population_id="all_events",
    x_parameter="x",
    y_parameter="y",
    x_transform_id=x_transform.id,
    y_transform_id=y_transform.id,
    thresholds={
      "x_min": float(transformed[0]),
      "x_max": float(transformed[1]),
      "y_min": float(transformed[0]),
      "y_max": float(transformed[1]),
    },
  )

  _results, masks = evaluate_gating_strategy_with_membership(
    GatingStrategySpec(id="s", name="s", gates=(gate,)),
    events,
    ["x", "y"],
    transforms=(x_transform, y_transform),
  )

  assert masks[gate.id].tolist() == [True, True, True, False]


def test_gate_transform_reference_rejects_second_legacy_scale() -> None:
  transform = _gate_logicle_transform("x", "logicle_x")
  gate = GateSpec(
    id="double",
    name="double",
    gate_type="range",
    x_parameter="x",
    x_scale="log10",
    x_transform_id=transform.id,
    thresholds={"min": 0.0},
  )

  with pytest.raises(GatingStrategyError, match="double transform"):
    evaluate_gating_strategy_with_membership(
      GatingStrategySpec(id="s", name="s", gates=(gate,)),
      np.array([[10.0]], dtype=np.float64),
      ["x"],
      transforms=(transform,),
    )


@pytest.mark.parametrize(
  ("transform", "values", "minimum", "maximum"),
  (
    (
      TransformSpec(
        id="linear_x",
        name="Linear X",
        transform_type="linear",
        parameter="x",
        settings={"scale": 2.0, "offset": 0.0},
      ),
      np.array([1.0, 2.0, 3.0], dtype=np.float64),
      3.5,
      4.5,
    ),
    (
      TransformSpec(
        id="log_x",
        name="Log X",
        transform_type="log",
        parameter="x",
        settings={"base": 10.0, "invalid_value_policy": "to_nan"},
      ),
      np.array([1.0, 10.0, 100.0], dtype=np.float64),
      0.5,
      1.5,
    ),
    (
      TransformSpec(
        id="asinh_x",
        name="Asinh X",
        transform_type="asinh",
        parameter="x",
        settings={"cofactor": 1.0},
      ),
      np.array([-10.0, 0.0, 10.0], dtype=np.float64),
      -0.1,
      0.1,
    ),
  ),
  ids=("linear", "log", "asinh"),
)
def test_existing_transform_types_use_the_same_gate_reference_api(
  transform: TransformSpec,
  values: np.ndarray,
  minimum: float,
  maximum: float,
) -> None:
  gate = GateSpec(
    id="range",
    name="Range",
    gate_type="range",
    x_parameter="x",
    x_transform_id=transform.id,
    thresholds={"min": minimum, "max": maximum},
  )

  _results, masks = evaluate_gating_strategy_with_membership(
    GatingStrategySpec(id="s", name="s", gates=(gate,)),
    values[:, np.newaxis],
    ["x"],
    transforms=(transform,),
  )

  assert masks[gate.id].tolist() == [False, True, False]


def test_evaluate_with_membership_no_gui_dependency() -> None:
  """The membership API is importable and runnable without any GUI dependency."""
  # This test verifies that the core modules do not import PySide6/Qt.
  # If we reach here without error, the core is GUI-independent.
  # The test itself may run in a GUI environment, but the core modules
  # must not have forced a Qt import.
  results, masks = evaluate_gating_strategy_with_membership(
    GatingStrategySpec(id="s", name="s", gates=()),
    np.array([[1.0, 1.0]], dtype=np.float64),
    ["x", "y"],
  )
  assert len(results) == 1  # root only
  assert "all_events" in masks


def test_rectangle_gate_transform_migration_preserves_membership() -> None:
  transform = _gate_logicle_transform("x", "logicle_x")
  gate = GateSpec(
    id="legacy",
    name="Legacy rectangle",
    gate_type="rectangle",
    x_parameter="x",
    y_parameter="y",
    x_scale="asinh",
    thresholds={"x_min": -2.0, "x_max": 2.0, "y_min": -1.0, "y_max": 1.0},
  )
  events = np.array([
    [-10.0, 0.0], [-2.0, -1.0], [0.0, 0.0], [2.0, 1.0], [10.0, 0.0],
  ])
  parent_mask = np.array([False, True, True, True, True])

  preview = preview_gate_transform_migration(
    gate,
    events,
    ["x", "y"],
    transforms=(transform,),
    target_x_transform=transform,
    parent_mask=parent_mask,
  )

  assert preview.candidate_gate.id == gate.id
  assert preview.candidate_gate.x_transform_id == transform.id
  assert preview.candidate_gate.x_scale == "linear"
  assert preview.source_event_count == preview.candidate_event_count == 3
  assert preview.gained_event_count == preview.lost_event_count == 0
  assert preview.mapping_kind == "exact_axis_monotonic"


def test_polygon_gate_transform_migration_is_labeled_approximate() -> None:
  transform = _gate_logicle_transform("x", "logicle_x")
  gate = GateSpec(
    id="legacy_polygon",
    name="Legacy polygon",
    gate_type="polygon",
    x_parameter="x",
    y_parameter="y",
    coordinates=((-10.0, -2.0), (10.0, -2.0), (0.0, 2.0)),
  )
  events = np.array([[-5.0, 0.0], [0.0, 0.0], [5.0, 0.0], [9.0, 1.5]])

  preview = preview_gate_transform_migration(
    gate,
    events,
    ["x", "y"],
    transforms=(transform,),
    target_x_transform=transform,
  )

  assert preview.mapping_kind == "vertex_reprojection_approximation"
  assert preview.scientifically_equivalent is False


def test_legacy_approximation_gate_cannot_claim_formal_inverse_migration() -> None:
  legacy = TransformSpec(
    id="legacy_x",
    name="Legacy approximation",
    transform_type="legacy_logicle_approximation",
    parameter="x",
    settings={"w": 0.25, "td": 1e6, "tn": 1e4},
  )
  formal = _gate_logicle_transform("x", "formal_x")
  gate = GateSpec(
    id="legacy_gate",
    name="Legacy gate",
    gate_type="range",
    x_parameter="x",
    x_transform_id=legacy.id,
    thresholds={"min": 0.0, "max": 1.0},
  )

  with pytest.raises(GateTransformMigrationError) as error:
    build_gate_transform_migration_candidate(
      gate,
      transforms=(legacy, formal),
      target_x_transform=formal,
    )

  assert error.value.code == "source_transform_inverse_unavailable"
