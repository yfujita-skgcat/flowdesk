# Overlay and Backgating

Spec: `S10`
ToDo: `Phase B7`

## Goal

Compare populations and project a target population through ancestor views using only
membership produced by the headless pipeline.

## Inspect first

- `src/flowdesk_core/execution_report.py`, `gating_strategy.py`
- `src/flowdesk_qt/plot_widget.py`, `main_window.py`, `population_tree.py`
- population filtering and hierarchy tests

Read `population-filtering-and-histograms.md`, `gate-hierarchy-ui.md`, and
`.codex/skills/qt-plot-widget/SKILL.md`.

## Model contract

`OverlaySpec` stores population refs, parameter/transform IDs, normalization
(`count`, `mode`, `unit_area`), and styles. `BackgatingSpec` stores target population,
ancestor views, and styles. Neither stores copied event values or masks.

`prepare_overlay_1d` reads only full-length `ExecutionReport.population_membership`
and applies count, max-normalized mode, or unit-area normalization after finite-value
filtering. `prepare_backgating` reuses target and ancestor masks and verifies subset
relationships; it never re-evaluates gate geometry. Empty populations remain explicit
diagnostic layers.

## Increments

1. Add models/schema and reference validation.
2. Add core display-preparation helpers using report memberships.
3. Implement 1D count/mode/unit-area overlays and zero/empty policies.
4. Add 2D layers with deterministic style ordering.
5. Build ancestor path resolution and backgating projection.
6. Add GUI editor/navigation and project restore.
7. Expose both definitions to the layout renderer interface.

## Required tests

- Normalization values are hand-computable and do not alter membership.
- Empty/zero-mode population is diagnosed.
- Backgated target is a subset of every displayed ancestor mask.
- Gate/transform edit invalidates stale memberships before display.
- GUI and headless display preparation use identical population IDs/counts.

## Do not do

- Do not rerun polygon/rectangle membership in Qt.
- Do not normalize using scatter-downsampled points.
- Do not serialize masks in project files.

## Verification

```bash
pytest -q tests/test_gates.py tests/gui/test_population_filtering.py tests/test_qt_plot_widget.py
./tools/run-gui-tests.sh -q
```
