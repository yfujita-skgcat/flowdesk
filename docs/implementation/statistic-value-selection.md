# Unified Statistic Value Selection

Spec: `S04`, `S05`, `S11`
ToDo: `Bug follow-up: session and statistics usability / Increment 5`

## Goal

Make Population Statistics ask one user-facing question: **which numeric value
should this metric summarize?**  Replace the current independent `Parameter`,
`Value domain`, and `Transform` choices with one `Statistic value` selector.

The selector presents raw acquired values, compensated acquired values,
explicit transformed values, and derived outputs as recognizable virtual
choices.  Internally, Flowdesk continues to persist the established stable
triple:

```text
parameter_id + source_stage + transform_id
```

This is a UI and validation unification, not a new scientific execution path.
Do not persist synthetic IDs such as `comp_FL1-A` or `log10_FL1-A`, and do not
materialize duplicate event columns in the project file.

Read `AGENTS.md`, `docs/implementation/llm-task-protocol.md`, this guide, and
the matching skills before production edits.  Implement exactly one numbered
increment per LLM run.

## Why the current UI is confusing

The three current fields expose pipeline implementation details independently:

```text
Parameter:     FL1-A or derived output ID
Value domain: raw | compensated | transformed
Transform:     explicit transform ID
```

This permits combinations that look plausible but cannot exist.  In the
reported failure, a derived definition reads raw inputs and produces a derived
output.  A mean statistic then selects that output with `Value domain=raw`.
The raw table contains only immutable FCS channels, so the derived output is
absent.  `PipelineRunner._step_statistics()` currently executes `continue`,
emits no `StatisticResult`, and Results displays `-` for every row.

Two concepts have been conflated:

- A derived definition's `source_stage` specifies where its **inputs** come
  from.  `raw` means `raw FL1-A / raw FL4-A`.
- A statistic's `source_stage` specifies which **value table** contains the
  selected parameter.  A derived output is appended only after the
  compensation/derived stage, even when its inputs were raw.

The internal distinction remains necessary, but users should select a complete
value representation instead of manually constructing the triple.

## Existing behavior that must remain correct

The following are established contracts.  Treat any change as a regression:

1. Raw FCS event arrays are immutable.
2. Canonical processing order remains:

   ```text
   raw -> compensation -> derived parameters -> transforms
       -> gate membership -> statistics -> export
   ```

3. A derived definition may read `raw` or `compensated` inputs.  Its safe
   expression, dependency order, failure policy, non-finite values, output
   channel ID, and numerical result must not change.
4. Downstream consumers bind a derived **output channel ID**, never its
   definition ID, display name, list position, or expression text.
5. Compensation remains a derived view.  With no applicable matrix, an
   acquired compensated value is numerically identical to its raw value.
6. A transformed statistic uses exactly one explicit persisted transform whose
   `parameter` matches the selected stable parameter ID.  It must not infer the
   current plot transform and must not transform twice.
7. Gate membership is calculated once from full events; the same full-length
   mask is applied to the selected statistic value.  Display downsampling and
   density rendering never affect Statistics.
8. Count and frequency metrics do not use a statistic value.  Their values,
   target populations, and parent/total denominators remain unchanged.
9. `strict` and `exclude_invalid` non-finite policies retain their current
   meanings.  Do not convert an unavailable value to zero, NaN, or an empty
   population result.
10. GUI, CLI, Python API, project save/load, and exports use the same persisted
    definition and `PipelineRunner` result.

## User-facing contract

For value metrics, show one control:

```text
Statistic value: [ one choice ]
```

Recommended display groups and examples:

```text
Acquired values
  FL1-A — Raw FCS value
  FL1-A — Compensated analysis value

Derived values
  GFPvsRFP — Derived value (raw inputs)
  Ratio2 — Derived value (compensated inputs)

Transformed values
  FL1-A — Log10 [transform_fl1_log]
  GFPvsRFP — Asinh [transform_ratio_asinh]
```

The text before the dash uses the project-wide parameter display resolver, so
an entry may appear as `GFP (FITC-A)`.  Stable IDs remain in item data and in a
tooltip/details string; display labels are never bindings.

When no compensation matrix applies, the tooltip for an acquired compensated
choice may explain that the analysis value currently equals raw.  Do not remove
the choice based only on the active sample because compensation bindings may be
sample/group/profile scoped.

For count/frequency metrics, disable or hide `Statistic value` and explain that
no event-value parameter is used.

## Mapping contract

Every selectable row resolves deterministically to the existing persisted
fields:

|Visible choice|parameter_id|source_stage|transform_id|
|---|---|---|---|
|Acquired raw|acquired stable ID|`raw`|`null`|
|Acquired compensated|acquired stable ID|`compensated`|`null`|
|Acquired transformed|acquired stable ID|`transformed`|matching transform ID|
|Derived native, raw inputs|derived output ID|`compensated`|`null`|
|Derived native, compensated inputs|derived output ID|`compensated`|`null`|
|Derived transformed|derived output ID|`transformed`|matching transform ID|

The derived definition's input stage appears only as provenance in the label or
tooltip.  It must not be copied into the statistic `source_stage`.  In
particular, there is no selectable `Derived raw` statistic row.

Use a typed GUI-independent descriptor such as `StatisticValueChoice` with at
least:

```text
parameter_id
parameter_kind                 acquired | derived
source_stage                   raw | compensated | transformed
transform_id                   optional
display_label
provenance_label
availability
diagnostic_code/message
```

Choice identity must be a structured tuple or dataclass.  Do not create a
parseable concatenated scientific ID and later split it.

## Invalid and legacy definitions

Existing project definitions remain loadable.  Resolve their persisted triple
back to one choice without altering the definition merely by opening the
dialog.

- A valid triple selects its exact corresponding choice.
- An unknown parameter, missing/mismatched transform, or derived output with
  `source_stage=raw` appears as a synthetic read-only `Unavailable saved value`
  entry with the original IDs and a repair message.
- `OK` is blocked until that definition is repaired, but `Cancel` must preserve
  it byte-for-byte.
- Do not silently migrate a derived/raw statistic to compensated.  Although
  compensated is usually the user's intent, changing a stored value domain is
  a scientific definition change.
- Headless execution of an unrepaired definition must emit an explicit error
  result and structured diagnostic; it must not silently omit the result.

## Increment 1 — Typed value-choice resolver

### Scope

Add the GUI-independent choice and compatibility model.  Do not change the
Statistics editor or pipeline execution in this increment.

### Inspect first

- `src/flowdesk_core/models.py`
- `src/flowdesk_core/parameter_catalog.py`
- `src/flowdesk_core/parameter_display.py`
- `src/flowdesk_core/pipeline_runner.py` stage construction
- `tests/test_parameter_catalog.py` or the nearest catalog tests
- `tests/test_pipeline_runner.py` existing derived-statistic tests

### Required implementation

1. Add a core helper/module that constructs choices from the shared Parameter
   Catalog and persisted analysis transforms.
2. Include two native choices for each valid acquired parameter: raw and
   compensated.
3. Include one native compensated-stage choice for each valid derived output;
   carry its definition input stage only as provenance.
4. Include transformed choices only when a valid analysis transform explicitly
   targets the same stable parameter ID.
5. Add a reverse resolver from persisted
   `(parameter_id, source_stage, transform_id)` to exactly one choice or a typed
   incompatibility.  Ambiguous or unknown references must not use display-name
   matching.
6. Keep invalid/missing derived catalog entries visible but unavailable with
   their structured catalog diagnostics.

### Required tests

- Exact mapping table above for acquired and raw/compensated-input derived
  parameters.
- Multiple transforms on one parameter create distinct choices with stable IDs.
- Same display name with different stable IDs remains unambiguous.
- Derived output plus statistic raw resolves to an incompatibility.
- Missing/mismatched transform and unknown parameter return stable codes.
- Resolver construction does not import PySide6 or mutate project definitions.

## Increment 2 — Headless execution must never silently skip

### Scope

Enforce the resolver contract in core execution and Results data.  Do not
change the editor in this increment.

### Inspect first

- `src/flowdesk_core/models.py` (`StatisticResult` and reason types)
- `src/flowdesk_core/pipeline_runner.py` (`_step_statistics`)
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_core/statistics.py`
- `src/flowdesk_core/tables.py` and result-state conversion
- `tests/test_population_statistics.py`
- `tests/test_pipeline_runner.py`

### Required implementation

1. Replace every missing statistic parameter/column `continue` with one explicit
   result for each requested sample/population target.
2. Use `status="error"`, `value=None`, and a typed reason such as
   `parameter_unavailable_at_source_stage`; do not reuse `empty_population`,
   `all_nan`, or `calculation_error`.
3. Emit `statistic_parameter_unavailable_at_source_stage` (and typed transform
   incompatibility codes where appropriate) with sample ID, statistic ID,
   parameter ID, requested stage, available channel IDs, transform ID, and
   derived output/definition provenance.
4. Continue unrelated statistics and samples.  Preserve deterministic result
   ordering and parallel/sequential parity.
5. Make Results state retain the explicit error result and tooltip fields.  A
   cell may show `-`, but it must be visually/error-state distinguishable from
   absent historic data and numerical undefined values.

### Required tests

- Raw-input ratio + compensated statistic gives a hand-computed mean.
- The same ratio + invalid raw statistic gives one error result per target and
  the stable diagnostic instead of disappearing.
- Acquired raw and compensated hand-computed means retain existing values.
- Empty, all-NaN, Inf, and invalid percentile statuses remain unchanged.
- Sequential and threaded execution have identical result/error ordering.

## Increment 3 — Replace three editor controls with one selector

### Scope

Implement the user-facing `Statistic value` selector using the core resolver.
Do not calculate values in Qt.

### Inspect first

- `src/flowdesk_qt/statistics_editor.py`
- `src/flowdesk_qt/main_window.py` (`_open_statistics_editor`)
- `src/flowdesk_core/parameter_catalog.py`
- `src/flowdesk_core/parameter_display.py`
- `tests/gui/test_statistics_entrypoints.py`
- `tests/gui/test_parameter_catalog_gui.py`
- `tests/gui/test_results_workspace.py`

### Required implementation

1. Replace the visible Parameter, Value domain, and Transform rows with one
   combo/tree-combo whose stable object name is `statisticValueCombo`.
2. Commit the selected descriptor into the existing `parameter_id`,
   `source_stage`, and `transform_id` fields.  Do not add a second persisted
   statistic model or hidden independently editable controls.
3. Restore existing definitions through the reverse resolver.  Preserve all
   other unknown mapping fields when editing.
4. Show category headings or equivalent readable grouping, a concise visible
   label, and a tooltip containing stable ID, stage, transform, and derived
   input provenance.
5. Count/frequency disables the selector without erasing an unrelated draft
   until the definition is committed according to current metric behavior.
6. Update generated Name/Statistic ID suggestions from the selected value's
   readable label while preserving the existing rule that accepted stable
   Statistic IDs do not change on later edits.
7. For an unavailable saved triple, show it explicitly and block `OK` until
   repaired.  Opening and cancelling must not mutate it.
8. Refresh choices after derived/transform edits through the existing shared
   Parameter Catalog; no widget-owned scientific registry.

### Required tests

- Each visible choice saves exactly the mapping-table triple.
- Reopening selects the same choice and leaves the stable Statistic ID fixed.
- Derived raw-input choice saves statistic source stage `compensated`.
- Multiple transforms are distinguishable and save the exact transform ID.
- Invalid saved triples are visible, cancel-safe, and blocked on accept.
- Count/frequency, New/Delete/Duplicate/Clear/Undo/Redo, population targets,
  non-finite policy, format, and notes retain their working behavior.
- Stable Qt object names are used; tests do not click screen coordinates.

## Increment 4 — End-to-end parity, documentation, and cleanup

### Scope

Prove the new selection surface preserves existing scientific behavior, then
remove obsolete GUI-only code.  Do not change numerical algorithms.

### Required implementation

1. Add one synthetic GUI/headless/CLI fixture containing acquired raw and
   compensated statistics, a raw-input derived ratio, a compensated-input
   derived parameter, one transformed statistic, multiple populations, and a
   non-finite derived event.
2. Compare exact stable IDs, result counts/status/reasons, and hand-computed
   numeric values across GUI `Run Pipeline`, direct `PipelineRunner`, saved
   project reload, and CLI export.
3. Confirm raw event arrays and hashes are unchanged and display downsampling
   does not affect results.
4. Remove obsolete `statisticSourceCombo`/`statisticTransformCombo` GUI state,
   callbacks, and tests only after the unified selector has equivalent
   coverage.  Keep the persisted model fields and headless API.
5. Update `docs/user-manual/user_manual.md` with the visible choices, provenance
   wording, invalid saved-definition repair, and the fact that compensated
   equals raw when no matrix applies.
6. Mark the ToDo item complete only when all four increments and required tests
   pass.  Record remaining platform validation separately rather than claiming
   it from Linux-only evidence.

### Required tests

- Existing derived evaluator/planner/editor suites remain green.
- Existing population statistics, Results matrix, transform, gate, project
  storage, CLI, and export suites remain green.
- GUI and headless reports match for every fixture result and diagnostic.
- Save-load-save preserves valid triples and unknown extension fields.
- No test or production code selects a statistic by display text or channel
  position.

## Non-goals

- Do not rename acquired or derived stable IDs.
- Do not persist `comp_`/`log10_` pseudo-channel IDs.
- Do not copy full compensated/transformed arrays into the project bundle.
- Do not change compensation equations, derived expressions, transforms,
  gates, statistic formulas, or non-finite policies.
- Do not infer a compensation matrix from a label.
- Do not infer a transform from the currently displayed plot.
- Do not add arbitrary Python evaluation.
- Do not use GUI-downsampled events for statistics.
- Do not silently reinterpret invalid saved scientific definitions.

## Final verification

Run focused tests after each increment.  After Increment 4 run at least:

```bash
python -m pytest -q \
  tests/test_parameter_catalog.py \
  tests/test_pipeline_runner.py \
  tests/test_population_statistics.py \
  tests/test_project_storage.py \
  tests/test_cli.py
./tools/run-gui-tests.sh -q
ruff check src tests
git diff --check
```

If a listed test file does not exist, use the nearest existing catalog test and
record the substitution.  Do not create an empty file merely to satisfy the
command.

## Completion report template

- Increment implemented and explicit non-goals
- Production/test/documentation files changed
- Baseline and final test commands with exit codes
- Hand-computed expected values and observed values
- GUI/headless/CLI equality evidence
- Raw-event immutability evidence
- Remaining invalid legacy definitions or platform limitations
- Next single increment
