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

## Boolean contract

Use an expression tree with leaf population references and `and`, `or`, `not` nodes.
Validate arity, references, scope, and cycles before evaluation. Persist tree order for
readability, but evaluation must not depend on GUI list order.

## Increments B2

1. Add schema/model variants and validation only.
2. Implement ellipse vectorized membership and boundary tests.
3. Implement quadrant membership/results atomically.
4. Implement nested Boolean parser/model/evaluator and legacy migration.
5. Add numeric editors and Qt drawing/overlays one gate type at a time.

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

