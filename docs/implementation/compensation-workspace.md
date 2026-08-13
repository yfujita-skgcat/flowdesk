# Compensation Workspace

> **Visual review follow-on:** A4/A5のbinding、calculation、provenance基盤はこの文書に
> 従う。係数とplotを連動させるinteractive review/fine-tuningは
> [`visual-compensation-workspace.md`](visual-compensation-workspace.md)を唯一の
> 実装指示書とする。現在の先頭event数値tableは互換用の基盤であり、S03が要求する
> 補償前後plotまたはresidual plotの完成を意味しない。

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

The Matrix Preview and Controls & Calculate lists start empty.  `New` explicitly
creates a draft definition; the UI must not insert a blank `New matrix` or `New
calculation` row merely because the project has no saved definitions.  This keeps
the compensation editors consistent with Edit Statistics and prevents an empty
draft from being mistaken for a usable definition.

Application / Bindings follows the same draft rule.  `New` uses the currently
selected Matrix ID and proposes a stable Binding ID, with `sample` as the default
scope.  It must never guess a Target ID, because applying compensation to the
wrong sample is a scientific error.  An untouched empty draft is ignored on save;
once a matrix, target, or note is edited, validation requires a non-empty Binding
ID, Matrix ID, and Target ID.  When the user supplies a target but leaves the ID
blank, the ID is generated from matrix, scope, and target.

Target ID is a scope-dependent combo box, not a free-text field for normal
creation.  The candidate namespace must be rebuilt whenever Scope changes:

- `sample`: every loaded sample ID, displayed with its sample title;
- `group`: every project sample-group ID, displayed with its group name;
- `execution_profile`: every available execution-profile ID, displayed with its
  profile name.

The combo stores the stable ID as `currentData()` while showing the human label.
An existing manifest binding whose target is no longer available must remain
loadable and visible as an explicit `(saved; unavailable)` option; it must not be
silently rewritten.  A new binding must choose one of the current candidates,
and changing Scope clears the previous target rather than carrying an ID across
namespaces.  Headless resolution continues to consume only the persisted stable
`target_id`.

Each binding also has an `enabled` boolean, defaulting to `true` for legacy
manifests that omit it.  Disabled bindings remain visible and are persisted, but
the core resolver must exclude them before duplicate detection and scope-priority
resolution.  Toggling this flag is therefore a reversible way to stop applying a
matrix without deleting its provenance or target assignment.

When the workspace changes tabs, the currently visible matrix/calculation fields
are committed to the in-memory draft before the destination tab is shown.  The
Application / Bindings matrix combo is then rebuilt from matrices with a non-empty
Matrix ID.  A blank draft is never a binding candidate; if no saved/draft matrix
has an ID, the combo displays a disabled `(no saved matrix)` item.  Save and Apply
is still the only operation that commits the workspace to the project, and Cancel
discards these in-memory edits.

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

## Confirmed contract after A4 increment 3

- `resolve_compensation_binding()` implements sample, execution-profile,
  group, project-default, then no-compensation priority. Duplicate
  `(scope, target_id)` definitions, different-matrix group conflicts, and an
  applicable unknown matrix ID raise stable compensation errors; they never
  fall through to uncompensated data.
- Multiple applicable groups may resolve only when every binding names the same
  matrix. The resolution retains all binding and group IDs for audit. A
  higher-priority sample or execution-profile binding resolves before group
  conflicts are evaluated.
- `PipelineRunner` resolves compensation independently for each sample before
  derived parameters. It accepts current singular `group_id` metadata and a
  future-compatible explicit `group_ids` array without inferring group
  membership from names or paths.
- Every applied matrix emits `compensation_matrix_applied` with matrix ID,
  source, persisted channel order, aligned column indices, condition number,
  binding IDs/targets, and resolution priority. Inspection warnings are copied
  into `ExecutionReport` with the same context and full event count.
- Invalid binding or matrix definitions stop the run with their diagnostic code.
  A selected matrix is never silently skipped. Existing global-default projects
  retain their numerical execution behavior while gaining report metadata.
- Two-sample synthetic runner tests prove different sample bindings produce
  different downstream gate membership while both raw arrays remain unchanged.
  Project schema declaration and forward migration remain increment 4 work.

## Increments A4

1. **Done:** Add typed provenance, manual edit record, and binding specs.
2. **Done:** Validate finite square matrices, unique channels, alignment, and condition number.
3. **Done:** Resolve bindings per sample in the runner and record the choice in reports.
4. Migrate the old global default without changing results.
5. Add matrix list/editor, heat map, duplicate-before-edit, apply action, and badges.
6. Add compensated/uncompensated preview using core outputs, not Qt calculations.

## Increments A5

1. **Done:** Add a calculation spec referencing explicit control samples and positive/negative populations.
2. **Done:** Define linear or median background-subtracted methods, minimum events, and outlier policy.
3. **Done:** Write known asymmetric synthetic single-stain fixtures and expected spill coefficients.
4. **Done:** Implement the traditional calculation in core with residual diagnostics.
5. Add detector × control assignment UI and stale invalidation after gate edits.
6. Save the calculated matrix as an immutable result with full provenance.

## Confirmed contract after A5 core calculation repair

- Each detector assignment names its control sample explicitly. The runner never
  infers a control sample from a filename or a profile-wide fallback.
- Calculated matrices use the same convention as `apply_compensation`: matrix
  rows are receiving detectors and columns are single-stain source detectors.
  A non-symmetric synthetic fixture verifies that compensation restores a
  single-stain event to its source detector.
- `linear` is a background-subtracted, through-origin least-squares slope;
  `median` is the background-subtracted median ratio. Unsupported methods are
  rejected rather than silently calculated as median.
- Minimum positive/negative event thresholds and a non-positive reference signal
  are fatal calculation errors. A requested calculation never becomes an
  identity matrix or an uncompensated successful run.
- Calculated matrix values, provenance, condition number, and residual-aware
  channel diagnostics are retained in execution diagnostics. Persisting an
  immutable calculated result in the project and its GUI workflow remain the
  next increments.

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
