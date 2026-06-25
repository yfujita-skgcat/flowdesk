# Gate Engine Implementation Guide

## Goal

Implement reproducible gate membership for rectangle, range, polygon, and boolean gates.

## Target Files

- `src/flowdesk_core/gates.py`
- `src/flowdesk_core/gating_strategy.py`
- `src/flowdesk_core/models.py`
- `tests/test_gates.py`

## Implementation Rules

- Store gates in data coordinates or transformed data coordinates, never screen pixels.
- Gate membership must run on full event data, not display-downsampled data.
- Keep gate evaluation GUI-independent.
- Use explicit boundary semantics. For example, rectangle min/max boundaries are inclusive unless documented otherwise.
- Boolean gates must reference named populations or gate ids, not GUI objects.
- Polygon implementation must handle points on edges consistently.

## Required Behavior

- Rectangle membership for arrays of x/y values.
- Range membership for one parameter.
- Polygon membership for simple convex and concave polygons.
- Boolean AND, OR, NOT over existing membership masks.
- Parent population masks restrict child gates.

## Required Tests

- Current scalar rectangle test remains or is replaced by vectorized tests.
- Rectangle membership includes boundary points.
- Range gate membership works on one parameter.
- Polygon membership has inside, outside, edge, and vertex cases.
- Boolean gate combines masks correctly.
- Parent-child masking produces expected child counts.

## Acceptance Criteria

- `pytest tests/test_gates.py` passes without xfail once polygon is implemented.
- No gate module imports Qt or `flowdesk_qt`.
- `pyenv exec ruff check src/flowdesk_core/gates.py src/flowdesk_core/gating_strategy.py tests/test_gates.py` passes.
- `pyenv exec mypy src/flowdesk_core tests` passes.
