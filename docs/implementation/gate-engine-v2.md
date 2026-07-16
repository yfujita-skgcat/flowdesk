# Gate Engine v2

Spec: `S06`
ToDo: `Phase B2`, later `Phase B5`

## Goal

Add ellipse/quadrant gates and nested Boolean expressions while preserving full-data,
transform-aware, parent-restricted membership.

## Inspect first

- `src/flowdesk_core/gates.py`, `gating_strategy.py`, `models.py`
- `src/flowdesk_qt/gate_editor.py`, `plot_widget.py`
- `schemas/gating_strategy.schema.json`
- `tests/test_gates.py`, `tests/test_qt_plot_widget.py`

Read `gate-engine.md`, `gate-hierarchy-ui.md`, `scientific-transforms-v2.md`, and
`.codex/skills/gate-engine/SKILL.md`.

## Geometry contracts

- Ellipse stores center, radii, and rotation in its transform coordinate system.
- Quadrant stores shared X/Y thresholds and four stable child population IDs.
- Offset quadrant stores explicit arm thresholds; shared-boundary ownership must be
  documented so one event is not counted twice unless intentionally allowed.
- All definitions include parameter and transform IDs; no screen coordinates.

Ellipse v2 stores `center_x`, `center_y`, `radius_x`, `radius_y`, and optional
`rotation` (radians, counter-clockwise) in `GateSpec.thresholds`. Membership is
inclusive (`normalized_distance <= 1`); NaN/Inf event values are excluded.
Centers, radii, and rotation must be finite, and both radii must be strictly
positive. A zero or negative radius is a degenerate-geometry error rather than
an empty gate.

Rectangle, range, polygon, and ellipse thresholds/coordinates must be finite;
event NaN/Inf values are excluded. Rectangle/range bounds are inclusive and
must be ordered. Polygon area must be non-zero. Overlapping geometric gates
may intentionally count an event in both populations; quadrant gates will
define deterministic ownership of exact shared thresholds when implemented.

## Boolean contract

Use an expression tree with leaf population references and `and`, `or`, `not` nodes.
Validate arity, references, scope, and cycles before evaluation. Persist tree order for
readability, but evaluation must not depend on GUI list order.

The persisted tree uses `{ "op": "ref", "id": "population-id" }` leaves,
`{ "op": "not", "child": node }`, and `{ "op": "and"|"or",
"children": [node, ...] }` branches. Legacy `operation`/`source_ids` thresholds
are accepted by the evaluator and migrated to `thresholds.expression` when a
legacy project is loaded. References are restricted to the same strategy (or
its root population); nested cycles and missing references fail before a run.

## Increments B2

1. Add schema/model variants and validation only.
2. Implement ellipse vectorized membership and boundary tests.
3. Implement quadrant membership/results atomically.
4. Implement nested Boolean parser/model/evaluator and legacy migration.
5. Add numeric editors and Qt drawing/overlays one gate type at a time. The
   current editor exposes rectangle/range thresholds at creation, ellipse
   center/radii/rotation at creation and edit, and polygon vertices as an
   editable data-coordinate table. Editing always writes a `GateSpec` and
   reuses the core validation path; it never evaluates membership in Qt.

## Increments B5

Implement auto, magnetic, tethered, and clone gates as separate subprojects. Each needs
an algorithm spec, deterministic full-data fit, diagnostics, template definition, and
sample-specific fitted geometry. Do not add a GUI placeholder before the core result exists.

## Required tests

- Rotated ellipse inside/outside/on-boundary cases.
- Quadrant exact-threshold ownership and total count conservation.
- Nested Boolean precedence, NOT scope, missing source, and cycle.
- Parent restriction for every new gate.
- NaN/Inf and degenerate geometry errors.
- GUI-created definitions equal headless membership after save/reload.

## Do not do

- Do not approximate an ellipse with a display polygon for analysis.
- Do not calculate automatic gates from display-downsampled data.
- Do not permit Boolean references outside the valid sample/group population graph.

## Verification

```bash
pytest -q tests/test_gates.py tests/test_pipeline_runner.py tests/test_qt_plot_widget.py
ruff check src tests
```
