# Results Statistics Matrix and Computation Scope

Spec: `S07`, `S11`, `S14`  
ToDo: `Phase B7.5`

## Goal

Replace statistic child rows in Results with scientifically labelled dynamic columns and
allow one persisted statistic definition to target an explicit set of populations.
Users must be able to control analytical computation separately from column visibility,
while GUI, headless execution, preview, export, and project reload continue to resolve the
same stable definitions and full-resolution event values.

Implement exactly one numbered increment per LLM/Codex run. Do not mark the phase complete
because a column is visible: model migration, execution, state handling, export, and
GUI/headless agreement are required.

## Audited current boundary

- Results uses `Sample -> Population -> Statistic` child rows.
- A statistic child is forced into the population table's fixed columns. Its numeric value
  currently occupies the `% Total` column position even when the metric is mean, median,
  CV, or percentile. This is semantically incorrect and must not remain as the final UI.
- `StatisticSpec` targets one `population_id`. Applying the same measurement to several
  populations requires repeated definitions and has no shared column identity.
- `RuntimeResultState` identifies a statistic row by sample ID and statistic ID. A
  multi-population statistic therefore requires population ID to become part of the
  runtime result key.
- Column visibility is a display concern. It must not silently enable, disable, or lazily
  change authoritative analysis computation.

## Required Results layout

Population remains the row dimension. Built-in population values remain fixed columns;
each named statistic becomes one dynamic column to the right of them.

```text
Sample / Population | Events | % Parent | % Total | Population Status | FL1-A Mean | FL1-A Median
1_A1
  All Events          31552       -        1.0000   current                   -              -
  rect_1               7324    0.2321       0.2321   current              594405.6       512340.2
```

Rules:

- Statistic results are cells, never children occupying unrelated population columns.
- The existing `Status` column becomes `Population Status`; each statistic cell carries
  its own result/freshness status through text/icon plus an accessible tooltip.
- `-` means the statistic is not assigned to that population. `Disabled`, `Not run`,
  `Stale`, `Undefined`, `Error`, and a valid numeric zero are distinct states.
- A sample container row never displays an aggregate statistic unless a separate explicit
  sample-level statistic model is introduced.
- A default header is concise, for example `FL1-A Mean`. Header tooltip/accessibility data
  must expose statistic ID, parameter ID, metric, value domain/source stage, transform ID,
  unit, non-finite policy, and target count. Ambiguous domains should be visible in the
  label, for example `FL1-A Mean [raw]` versus `FL1-A Mean [compensated]`.
- Standard columns remain pinned where supported. Dynamic columns permit horizontal
  scrolling, deterministic ordering, width persistence, and a column chooser.
- A long-form Statistics Detail surface remains available for QC-heavy inspection:

```text
Sample | Population | Statistic | Value | Unit | Status | n valid | n total | Reason | Revision
```

  It is another presentation of the same `StatisticResult` objects, not a second
  calculation or definition model.

## Persisted analysis model

Evolve `StatisticSpec` so one stable statistic/column ID can target multiple populations:

```text
id
name
population_ids             ordered, explicit, non-empty stable population IDs
parameter_id
metric
source_stage
transform_id
value_policy
non_finite_policy
settings
format
notes
compute_enabled            persisted analysis state; default true
```

Compatibility and identity rules:

- Load legacy `population_id` as `population_ids = [population_id]` without changing the
  metric, value domain, non-finite policy, or numeric result.
- Do not automatically merge separate legacy statistics merely because their labels or
  fields look equal. Their stable IDs may carry distinct scientific/export meaning.
- A `StatisticResult` is uniquely identified by `(sample_id, statistic_id,
  population_id)`. Update runtime state, preview merging, selection, and caches so results
  for different populations cannot overwrite each other.
- Population target order is deterministic and persisted. Duplicate or unknown IDs are
  rejected by the project validator before execution.
- `All populations` and `Current population and descendants` in the GUI resolve to an
  explicit snapshot of stable population IDs when the user accepts the edit. Adding a new
  gate later does not silently expand an existing statistic. An explicit `Update targets`
  action may refresh the snapshot.
- Sample/Group applicability remains separate from population applicability. Existing
  Group statistic bindings continue to reference the statistic ID; they must not be
  inferred from Results column visibility.

## Computation versus presentation state

Two controls have different scientific effects and must use different state paths:

```text
Compute / Enabled for analysis
  persisted in StatisticSpec
  changes authoritative and preview results
  increments the analysis revision and invalidates only affected statistic results
  is honored identically by GUI, CLI, and Python PipelineRunner

Show / Visible in Results
  persisted in Results view/display state
  changes only column visibility/order/width
  does not run the pipeline, change analysis revision, membership, values, or export
```

The runner skips disabled statistics. Disabled definitions remain in the project and are
shown as `Disabled` when their column is visible. The authoritative report/provenance must
record which definitions were disabled or otherwise make the omission unambiguous.
Default CSV/TSV statistic export includes computed results only; an explicit metadata
option may include disabled definitions, but it must never fabricate values.

Never make authoritative computation depend on viewport visibility or whether the user
has scrolled to a cell. Current-sample preview may request a subset for responsiveness,
but it remains labelled preview and cannot replace missing authoritative batch results.

## Add and Manage Statistics UX

`Add Statistic...` opens the existing side-effect-free editor. A definition is created
only after explicit `New`. The form includes:

New definitions receive a readable initial name such as `rect_1_mean` from the target
population name and metric. A suggested Statistic ID is generated for editing (for example
`stat_rect_1_mean`). The ID becomes stable and read-only when the dialog is accepted;
changing the display name or target in a later edit does not rewrite the ID.

```text
Parameter / Metric / Source stage / Transform / Non-finite policy / Format

Apply to:
  Current population
  Current population and descendants
  Selected populations...
  All current populations
```

`Selected populations...` uses a stable-ID population hierarchy with checkboxes. It must
show missing/incompatible populations and reject an empty target selection. The default
is the Results population from which the command was invoked; a graph shortcut may also
prefill the active parameter ID.

`Manage Statistics...` presents:

```text
Compute | Show | Statistic | Parameter | Metric | Value domain | Applies to
```

- `Compute` changes persisted analytical state and requires canonical recalculation.
- `Show` changes Results view state only.
- `Applies to` is editable from Manage Statistics through the shared stable-ID
  population chooser; changing targets invalidates the affected statistic cells
  and requires canonical recalculation.
- `Parameter` shows the user-facing parameter name (for example `FSC-A`), not only
  the stable internal parameter ID.
- `Applies to` shows the user-facing names of the explicit target populations. A
  statistic may target multiple populations through `Selected populations...`,
  descendant scope, or all-current-populations scope; it is not limited to one.
- Result-level status is shown in the Results table, not duplicated in this
  Compute/Show management table.
- Edit of a shared definition changes all its assigned population cells atomically.
- Duplicate creates a new stable statistic ID and copies targets only after explicit user
  confirmation/default selection.
- Remove lists downstream Group/export/table references and uses the existing dependency
  command path; no silent cascade deletion.

## Execution and performance contract

Scientific correctness comes before speculative optimization. First measure the cost by
sample count, event count, target population count, parameter, metric family, and source
stage. Then implement optimizations that preserve exact results:

- execute only `compute_enabled` definitions and their explicit population targets;
- reuse full-resolution population membership masks;
- resolve/extract a parameter and value-space column once per sample/stage/transform;
- share finite-value masks and sufficient statistics where metric definitions permit it;
- cache by analysis revision, sample ID, statistic ID, population ID, upstream dependency
  revision, and non-finite policy;
- invalidate only changed statistics and populations affected by upstream membership;
- never substitute display-downsampled points, histogram bins, rounded GUI values, or a
  viewport-only lazy result.

Mean/count optimizations must not be assumed to make median/percentile cheap. Benchmarks
must include quantile-like metrics and overlapping parent/child populations before any
automatic warning threshold is chosen.

## Numbered implementation increments

### Increment 1: Model, schema, migration, and runtime identity

- Add explicit `population_ids` and `compute_enabled` to the typed statistic model,
  schema, validator, commands, and project migration.
- Extend runtime/result keys with population ID and prove two populations with the same
  statistic ID cannot collide.
- Preserve legacy one-population results and project round trips exactly.

### Increment 2: Canonical multi-population execution and invalidation

- Execute one enabled definition over each explicit population target in
  `PipelineRunner`; keep GUI free of scientific computation.
- Connect group binding, preview requests, disabled provenance, dependency invalidation,
  and revision-safe cache keys.
- Add known-value and performance-characterization fixtures for mean, median, percentile,
  empty, undefined, and non-finite cases.

### Increment 3: Results wide matrix and detail presentation

- Replace statistic child nodes with dynamic columns after `Population Status`.
- Implement cell states, QC/accessibility tooltips, column chooser/order/width persistence,
  pinned standard columns where supported, and the long-form detail view.
- Keep hierarchy and flat modes backed by the same result-state snapshot.

### Increment 4: Population target selection and Compute/Show management

- Implemented current/subtree/selected/all-current population targeting in the shared
  statistic editor. Targets are materialized as an explicit ordered `population_ids`
  list at commit time; a later gate is not implicitly added.
- `Compute enabled` is persisted in the statistic definition and is honored by the
  headless runner. Results `Columns...` controls `Show` as display-only state, while
  `Manage Statistics...` presents a table with `Compute`, `Show`, `Statistic`,
  `Parameter`, `Metric`, `Value domain`, `Applies to`, and `Status` columns. Detailed
  target/expression editing remains in the shared Add/definition editor.
- Cancel, duplicate, save/reload, stable object-name coverage, statistics editor
  Undo/Redo, and missing-target/empty-selection validation are implemented. Removing a
  gate leaves its statistic definition intact but surfaces a blocking dependency
  diagnostic instead of silently retargeting it. Selected targets are rendered in a
  checkable hierarchy and an empty selection is rejected by model validation. Deleting
  a statistic with downstream Group strategy bindings is blocked and the references are
  listed so the dependency command path can be handled explicitly.

### Increment 5: Export, preview, cleanup, and end-to-end acceptance

The existing matrix export contract is the foundation for the implemented
`unified-results-export-and-population-paths.md` increment. The unified Results
export adds population full paths and combines population metrics with custom
statistics without changing the authoritative report or recalculating values
in Qt.

- GUI wide/detail cells, authoritative report, preview, Python API, and long/wide
  CSV/TSV export now use the same `(sample, statistic, population)` identity. Long
  export retains status and non-finite QC fields; the new wide helper emits one row per
  sample/population and one stable statistic-ID metadata block per definition
  (value, unit, status, undefined reason, QC counts, non-finite policy, and optional
  runtime revision). Missing metadata remains blank; no disabled value is fabricated.
- The legacy statistic-child rendering path is removed; saved Results display state
  migrates through mode/visibility/order/width settings, with hidden columns kept
  distinct from disabled definitions.
- Full core and GUI suites pass with strict callback handling and thread-shutdown
  coverage already in the repository. Display column operations and downsampling stay
  outside the scientific execution path.

## Required acceptance tests

- Mean/median values appear only in their named Statistic columns, never `% Parent` or
  `% Total`.
- One definition assigned to All Events and two gates produces three independently keyed
  results per applicable sample and one shared column.
- Unassigned, disabled, not-run, stale, undefined/error, zero, and valid cells are
  distinguishable without color alone.
- Toggling `Show` changes no project analysis revision or headless/exported value.
- Toggling `Compute` persists, skips/runs the same definitions in GUI/CLI/Python, and does
  not change gates, memberships, or unrelated statistic results.
- Current/subtree/selected/all-current targeting saves explicit stable IDs and does not
  silently include a gate created later.
- Native/transformed domain, unit, non-finite QC counts, reason, and revision match the
  authoritative `StatisticResult` and exports after save/reload.
- Display downsampling, column hiding/reordering, horizontal scrolling, and detail-view
  selection never alter scientific values.

## Target files

- Core/storage: `models.py`, `statistics.py`, `pipeline_runner.py`, `execution_report.py`,
  `preview.py`, project schema/validator/migrations, commands, export, and caches.
- Qt: `statistics_editor.py`, `results_state.py`, `results_workspace.py`, `main_window.py`,
  and Results view-state persistence.
- Tests: population statistics, pipeline runner, preview/result state, project migration,
  export, Results workspace, Statistics Editor entry points, and GUI/headless E2E.

## Do not do

- Do not calculate, filter, aggregate, or repair statistic values in Qt.
- Do not use one global `Status` cell to hide per-statistic failure/QC state.
- Do not infer target populations from visible rows at run time.
- Do not treat hidden as disabled or disabled as deleted.
- Do not merge legacy definitions by display name or formatted header.
- Do not use dynamic column position as statistic identity.

## Verification

Run focused tests for each increment. Before completing Phase B7.5 run:

```bash
pytest -q tests/test_population_statistics.py tests/test_pipeline_runner.py \
  tests/test_results_state.py tests/test_project_storage.py tests/test_export.py
./tools/run-gui-tests.sh -q
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
