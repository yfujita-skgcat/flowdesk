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

### Confirmed binding resolution contract

Bindings are immutable records with a stable binding ID, matrix ID, one scope
(`sample`, `group`, or `execution_profile`), and one target ID. Matrix
provenance is stored on the immutable matrix and never inferred from binding
location.

For a `(sample, execution profile)` run, resolve in this order:

1. the unique binding targeting the sample;
2. the unique binding targeting the selected execution profile;
3. all bindings targeting groups containing the sample;
4. `default_compensation_matrix_id`;
5. no compensation.

Duplicate bindings for the same `(scope, target_id)` are invalid even if they
name the same matrix. If multiple applicable group bindings name different
matrices, resolution fails with a conflict. Multiple groups naming the same
matrix are scientifically unambiguous and may resolve to that matrix. A higher
priority sample or execution-profile binding resolves the run before group
conflicts are considered. An explicit binding with an unknown matrix ID is an
error and never falls through to a lower-priority choice.

### Confirmed provenance contract

`CompensationProvenanceSpec` records the source sample and FCS metadata keyword,
explicit control sample/population IDs, algorithm and algorithm version,
Flowdesk/software version, duplicate lineage, and an ordered manual edit
history. Existing `created_by`, `created_at`, source enum, and notes remain on
`CompensationMatrixSpec` for compatibility.

Each `CompensationManualEditSpec` identifies the row and column by stable
channel ID and records old/new values, editor, timestamp, and reason. A matrix
with manual edits must name `derived_from_matrix_id`; editing an original matrix
in place is structurally invalid. Numeric finiteness and matrix/channel
validation remain increment 2 work.

### Confirmed diagnostic contract

Compensation diagnostics use `ExecutionDiagnostic(stage="compensation")`. An
applied-matrix diagnostic will include `matrix_id`, `matrix_source`, resolved
`channel_order`, `binding_id`, `binding_scope`, `binding_target_id`, resolution
priority, and condition number in `details`. Stable planned codes are:

- `compensation_matrix_applied` (`info`);
- `compensation_condition_warning` (`warning`);
- `compensation_binding_conflict`, `unknown_compensation_matrix`,
  `missing_compensation_channel`, and `invalid_compensation_matrix` (`error`).

Errors stop the affected analysis according to the runner contract; they are
never converted to uncompensated results. Threshold selection and report
emission are increments 2 and 3.

## Confirmed contract after A4 increment 1

- Core models now represent provenance, duplicate-only manual edit history, and
  explicit sample/group/execution-profile bindings without importing Qt.
- The original matrix constructor and global default remain API-compatible.
- No project schema/version or runner behavior changes in this increment;
  persistence and legacy migration are intentionally deferred to increment 4.

## Confirmed contract after A4 increment 2

- `inspect_compensation_matrix()` is the non-throwing core inspection API. It
  returns matrix ID, persisted channel order, aligned event-column indices,
  condition number, and stable warning/error diagnostics.
- `validate_compensation_matrix()` remains the compatibility API. It delegates
  to inspection, raises `CompensationError` for the first error diagnostic, and
  returns the inspection result when valid. `apply_compensation()` reuses this
  exact alignment result instead of maintaining a second resolver.
- Empty/shape-mismatched, duplicate-channel, nonfinite, missing-channel,
  ambiguous event-channel, and numerically singular definitions are errors.
  Extra event channels remain allowed and are copied unchanged.
- Condition number uses the NumPy 2-norm/SVD definition. For float64,
  `condition_number >= 1e8` emits `compensation_condition_warning` because at
  least about eight decimal digits may be lost. It is not fatal.
  `condition_number >= 1 / numpy.finfo(float64).eps` (or nonfinite) is fatal as
  `reason=numerically_singular`, because `kappa * eps >= 1` cannot guarantee a
  relative significant digit.
- Inspection does not apply compensation and raw event arrays remain untouched.
  Conversion of these diagnostics into `ExecutionReport` entries remains
  increment 3 work.

## Increments A4

1. **Done:** Add typed provenance, manual edit record, and binding specs.
2. **Done:** Validate finite square matrices, unique channels, alignment, and condition number.
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
