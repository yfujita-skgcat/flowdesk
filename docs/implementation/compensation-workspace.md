# Compensation Workspace

Spec: `S03`
ToDo: `Phase A4`, then `Phase A5`

## Goal

Add sample/group-specific compensation bindings, provenance, diagnostics, and a
GUI matrix workspace; then calculate traditional compensation from controls.

## Inspect first

- `src/flowdesk_core/compensation.py`
- `src/flowdesk_core/models.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/fcs_io.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/sample_browser.py`
- `schemas/project.schema.json`
- `tests/test_compensation.py`

Read `compensation-engine.md`, `fcs-io.md`, and
`.codex/skills/compensation/SKILL.md`.

## Binding contract

Persist matrix provenance separately from the binding that applies it. Resolve
bindings in the documented order: explicit sample binding, execution-profile
binding, group binding, project default, then no compensation. Conflicting group
bindings are an error unless profile configuration resolves them.

Never edit a matrix already referenced by an execution report. Duplicate it and
record `derived_from_matrix_id` plus manual edit history.

## Increments A4

1. Add typed provenance, manual edit record, and binding specs.
2. Validate finite square matrices, unique channels, alignment, and condition number.
3. Resolve bindings per sample in the runner and record the choice in reports.
4. Migrate the old global default without changing results.
5. Add matrix list/editor, heat map, duplicate-before-edit, apply action, and badges.
6. Add compensated/uncompensated preview using core outputs, not Qt calculations.

## Increments A5

1. Add a calculation spec referencing control samples and positive/negative populations.
2. Define regression/background method, minimum events, and outlier policy.
3. Write known synthetic single-stain fixtures and expected spill coefficients.
4. Implement the traditional calculation in core with residual diagnostics.
5. Add detector × control assignment UI and stale invalidation after gate edits.
6. Save the calculated matrix as an immutable result with full provenance.

## Required tests

- Channel permutation aligns by ID and produces identical compensated values.
- Missing, duplicate, NaN, singular, and ill-conditioned matrices are diagnosed.
- Two samples can use different matrices in one run.
- Matrix edit does not mutate the original or raw events.
- Synthetic controls recover the known matrix within a documented tolerance.
- GUI preview equals core output and survives project round trip.

## Do not do

- Do not infer a control solely from filename.
- Do not add AutoSpill/spectral unmixing in A4/A5.
- Do not invert/apply a matrix in Qt.
- Do not make condition warnings fatal without a documented threshold policy.

## Final verification

```bash
pytest -q tests/test_compensation.py tests/test_pipeline_runner.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
ruff check src tests
```

