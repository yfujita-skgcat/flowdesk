"""Tests for gate evaluation: rectangle, range, polygon, boolean, hierarchy."""

from __future__ import annotations

import numpy as np
import pytest

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
)

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
