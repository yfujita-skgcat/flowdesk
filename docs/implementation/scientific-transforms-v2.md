# Scientific Transforms v2

Spec: `S05`
ToDo: `Phase A3`

## Goal

Replace the approximate transform ambiguity with explicit, invertible transform
definitions used consistently by the runner, gates, axes, and serialization.

## Inspect first

- `src/flowdesk_core/transforms.py`
- `src/flowdesk_core/gating_strategy.py`
- `src/flowdesk_core/models.py`
- `src/flowdesk_qt/channel_selector.py`
- `src/flowdesk_qt/plot_widget.py`
- `schemas/project.schema.json`
- `tests/test_transforms.py`
- transform-related tests in `tests/test_gates.py` and `tests/test_qt_plot_widget.py`

Read `transforms.md`, `qt-interactive-plot-controls.md`, `gate-engine.md`, and
`.codex/skills/scientific-review/SKILL.md`.

## Scientific contract

Each transform definition has a stable ID, type, parameter ID, complete numeric
settings, forward function, inverse function, domain policy, and implementation
version. The same definition converts events, gate coordinates, and axis ticks.

Rename existing `logicle_like` through migration to an honest legacy type. Do not
claim FlowJo Biex compatibility without versioned reference fixtures.

## Increments

1. **Transform protocol**
   - Introduce typed forward/inverse dispatch and settings validation.
   - Keep linear/log/asinh results backward compatible.
2. **Legacy migration**
   - Map `logicle_like` to `legacy_logicle_approximation` without changing values.
   - Display a warning but preserve old project membership.
3. **Published Logicle**
   - Select and document a primary equation/reference implementation.
   - Implement `T`, `W`, `M`, `A`, convergence limits, and inverse.
   - Add reference vectors before connecting gates or GUI.
4. **Single-application model**
   - Gate axes reference transform IDs rather than applying an independent second scale.
   - Separate analysis transforms from display-only view settings.
   - Detect and reject accidental double application.
5. **GUI and migration UX**
   - Add parameter editor and preview.
   - Keep mismatched gate overlays hidden; offer explicit duplicate/migrate with preview.

## Required tests

- Published/reference forward values and inverse round trips.
- Negative, zero, near-linear, transition, and high-positive regions.
- Invalid parameters and non-convergence return typed errors.
- Legacy projects retain previous gate membership.
- Logicle-drawn rectangle/polygon has identical GUI/headless membership.
- Project transform plus gate reference is applied exactly once.

## Stop condition

If no licensed/reference implementation or equation can be verified, stop after the
legacy rename and leave a failing/xfail reference test with an explanation. Do not
invent a Logicle formula.

## Final verification

```bash
pytest -q tests/test_transforms.py tests/test_gates.py tests/test_qt_plot_widget.py
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```

