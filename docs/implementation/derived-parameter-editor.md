# Derived Parameter Pipeline and Editor

Spec: `S04`
ToDo: `Phase A2`

## Goal

Make derived parameters safe, dependency-ordered, visible to downstream stages,
and editable in the GUI without hiding evaluation failures.

## Inspect first

- `src/flowdesk_core/derived_parameters.py`
- `src/flowdesk_core/models.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_qt/main_window.py`
- `schemas/project.schema.json`
- `tests/test_derived_parameters.py`
- `tests/test_pipeline_runner.py`

Read `safe-derived-parameters.md` and `.codex/skills/derived-parameters/SKILL.md`.

## Core contract

Define an enum-like failure policy: `fail_run`, `fail_sample`, and
`emit_nan_with_warning`. The result of the derived stage must carry both the new
event table and the updated ordered channel specs. Downstream transforms, gates,
statistics, and exports reference the new stable channel ID.

The stage runs after compensation and before transforms. Existing
`source_stage="transformed"` is legacy-invalid: migration must report it and must
not silently reinterpret it.

## Increments

1. **Typed policies and diagnostics**
   - Add policy validation and a structured diagnostic code.
   - Replace broad exception-to-NaN handling in the runner.
   - Test all three policies before adding GUI.
2. **Dependency planner**
   - Parse parameter references using the existing safe parser.
   - Topologically order derived definitions; reject cycles and unknown IDs.
   - Keep user display order separate from execution order.
3. **Stage result**
   - Return events plus updated channel specs.
   - Validate result shape, dtype, and row count.
   - Do not mutate input arrays.
4. **Schema/migration**
   - Persist output ID, unit, inputs, policy, and source semantics.
   - Add a diagnostic for legacy transformed-source definitions.
5. **Qt editor**
   - Add a dialog for name, expression, inputs, unit, source, and policy.
   - Preview through the core evaluator on a bounded copy of events.
   - Show syntax location and diagnostic code; never calculate expressions in Qt.

## Decisions fixed before implementation

- Derived execution remains after compensation and before transforms. A
  `source_stage="raw"` definition will read immutable `SampleData.events`;
  `source_stage="compensated"` will read the compensated stage view. Supporting
  both requires explicit stage views and must not reorder the canonical pipeline.
- `source_stage="transformed"` is invalid for new definitions because it would
  introduce a backward edge. Legacy transformed-source definitions require a
  later migration diagnostic and explicit compatibility action; they are never
  silently reinterpreted as compensated input.
- Dependency edges are stable derived output IDs referenced by
  `input_parameters` or by the safe parsed expression. Execution order will be a
  deterministic topological order; project/display order remains unchanged.
- Unknown input IDs and cycles are definition errors detected before any sample
  events are processed. They do not use a per-event invalid-value policy.
- The only new failure policies are `fail_run`, `fail_sample`, and
  `emit_nan_with_warning`. Division by zero remains a numeric NaN result rather
  than an evaluator exception. Event-local invalid numeric domains such as
  `sqrt(-1)` likewise produce NaN only for affected events. Structural
  expression and evaluation failures follow the stored policy.

## Confirmed contract after increment 1

- `DerivedFailurePolicy` is a typed string enum. New definitions default to
  `emit_nan_with_warning`; invalid values are rejected when constructing the
  model and are wrapped as `invalid_derived_parameter_definition` by the runner.
- The historical `division_by_zero_to_nan` value is read as an explicit
  compatibility alias for `emit_nan_with_warning`. The canonical example now
  stores the new value. Migration diagnostics and normalization of legacy saved
  values remain increment 4 work.
- Derived evaluation no longer has a broad `except Exception`. Only expected
  expression, arithmetic, type, and result-shape failures enter policy handling;
  unexpected programming/system exceptions propagate.
- `fail_run` stops the complete run with `PipelineError`. `fail_sample` records
  an error diagnostic, skips all downstream stages for that sample, and
  continues other samples. Reports use `partial_success` when another sample
  succeeds and `failed_samples` when every processed sample fails.
- `emit_nan_with_warning` appends an event-count-aligned NaN column and continues
  downstream execution. `ExecutionReport.diagnostics` records stable code
  `derived_parameter_evaluation_failed`, stage, severity, expression, policy,
  sample ID, parameter ID, exception type, and affected event count.
- The existing safe evaluator is scalar-first. Full vector evaluation,
  dependency planning, stage-aware input views, result contracts, and GUI preview
  remain increments 2–5; this increment does not pretend the current array
  adapter is scientifically complete.

## Confirmed contract after increment 2

- `extract_parameter_references()` parses the same restricted Python AST used
  by the safe evaluator. It recognizes exact stable IDs including hyphens and
  dots, distinguishes subtraction between identifier-like IDs, ignores only
  explicitly whitelisted function names, and rejects attributes, unsafe calls,
  syntax errors, and unknown identifiers.
- Planning uses the union of explicit `input_parameters` and references found in
  the expression. Explicit declarations cannot hide an actual expression
  dependency, and an unused declared dependency is still validated and ordered.
- `plan_derived_parameters()` preserves the project tuple as `display_order` and
  returns a separate `execution_order`. Kahn ordering uses original display
  indexes as its deterministic tie-break, so independent definitions do not
  reorder unpredictably between runs.
- Duplicate derived IDs, output/input ID collisions, unknown inputs, invalid
  expressions, and dependency cycles raise `DerivedParameterPlanningError`
  with a stable code and structured IDs. Cycle diagnostics contain an actual
  cycle and exclude definitions that are merely blocked downstream.
- The runner builds the plan once, before compensation or any other per-sample
  processing. Project sample channel metadata and typed input samples contribute
  the known base-ID union. An ID known in another selected sample is a valid
  project input; if absent from a particular sample, that sample's stored
  failure policy applies during evaluation.
- Definition errors are never converted into NaN, even when a definition stores
  `emit_nan_with_warning`. They stop the run with a `PipelineError` prefixed by
  the structured planning code.
- Evaluation appends derived channels in dependency execution order while the
  project definition order remains unchanged. Full vectorized evaluator and
  typed stage-result validation remain increment 3 work.

## Confirmed contract after increment 3

- `evaluate_array_expression()` uses the same restricted AST and exact stable-ID
  normalization as scalar evaluation, but operates on complete event-aligned
  `float64` columns. Numeric constants are expanded to the sample row count.
- Vector division by zero and invalid whitelisted-function domains produce NaN
  at only the affected events. Expression inputs are validated as one-dimensional
  `float64` arrays with the declared row count and are never mutated.
- `DerivedParameterStageResult` is the public typed result for the derived stage.
  It owns an immutable copy of a two-dimensional `float64` event table and the
  ordered `ChannelSpec` tuple aligned to its columns.
- Appending a result validates NumPy type, `float64` dtype, one-dimensional
  shape, row count, and stable channel-ID uniqueness. Failures carry a stable
  `DerivedParameterStageError.code` and parameter ID and follow the persisted
  evaluation failure policy in the runner.
- The runner passes the typed result directly into transforms and gating. A
  synthetic ratio test proves that the same derived stable ID is transformed,
  gated, and counted without position-based lookup, while raw input events stay
  unchanged.
- Unit/output-ID persistence and raw/compensated source-view semantics remain
  increment 4 work; this increment does not reinterpret `source_stage`.

## Confirmed contract after increment 4

- Project version `1.2.0` persists definition `id` separately from stable
  `output_channel_id`, plus nullable `unit`, explicit `source_stage`, inputs,
  and failure policy. Legacy definitions migrate with `output_channel_id=id`
  and retain unknown extension fields.
- Dependency planning and all downstream transforms, gates, and statistics use
  `output_channel_id`. Definition IDs remain provenance identifiers and are
  stored in derived `ChannelSpec.metadata`.
- The runner carries immutable raw and compensated stage views into the derived
  stage. A raw-source definition resolves measured inputs from the raw view; a
  compensated-source definition resolves them from the compensated view.
  Already-computed derived dependencies remain available to either source.
- Derived columns are still appended only after compensation and before
  transforms. A hand-computable fixture verifies raw 15, compensated 10, then a
  downstream linear transform of the raw-derived channel to 30 before gating.
- Legacy `source_stage="transformed"` is never rewritten as compensated.
  Migration preserves it, adds `legacy_source_stage_policy="reject"`, and
  records `legacy_transformed_derived_source` in persisted migration diagnostics.
  The runner rejects it before compensation or other sample processing.
- New/current transformed-source data without the explicit legacy reject policy
  fails manifest/model validation. The later Qt editor must offer only raw and
  compensated for new definitions.
- The legacy `division_by_zero_to_nan` storage alias is normalized during
  migration; current schema stores only the three explicit failure policies.

## Confirmed contract after increment 5

- **Analysis → Derived Parameters** opens a project-state editor with stable Qt
  object names. Definitions can be added, selected, edited, and deleted; closing
  with Cancel leaves project state unchanged.
- The dialog edits definition ID, name, stable output channel ID, expression,
  explicit inputs, raw/compensated source, unit, and failure policy. Unknown
  definition fields, output label, and notes survive editing.
- Measured and derived output IDs are available for insertion at the expression
  cursor and for explicit input selection. Validation calls the core model and
  dependency planner, showing the stable diagnostic code and core-provided line
  and column for syntax errors.
- Preview calls `PipelineRunner.preview_derived_parameter()` on a deterministic
  copy of at most 200 events. It reuses compensation, source views, dependency
  order, vector evaluation, and failure policy from the headless pipeline. Qt
  only displays event count, NaN count, range, and the first five returned values.
- MainWindow preserves derived definitions, compensation matrices, transforms,
  default compensation binding, and migration diagnostics across project
  save/load. New definitions offer only raw and compensated sources; an existing
  transformed legacy definition remains visibly rejected until the user makes
  an explicit source change.
- A GUI E2E fixture stores a ratio definition and gate, then proves GUI and
  headless population counts are identical on full event data.

## Required tests

- Ratio and dependent-derived chain work after compensation.
- Cycle, unknown input, wrong-length result, and unsafe syntax fail clearly.
- `emit_nan_with_warning` records affected count and sample ID.
- Division by zero and invalid function domains produce event-aligned NaN values
  without changing valid rows or mutating source events. An all-NaN input keeps
  its event count, and downstream numeric gates exclude those NaN events.
- Unknown parameters are planning errors before compensation or other sample
  processing and are never converted into NaN by a stored failure policy.
- A derived channel can be transformed, gated, reported, and exported by stable ID.
- Save/reload/CLI produces the same values and diagnostics.

## Do not do

- Do not use `eval`, `exec`, or unrestricted AST execution.
- Do not swallow `Exception` in the pipeline.
- Do not append a numeric column without appending its channel spec.
- Do not allow GUI preview to define different semantics from headless execution.

## Focused verification

```bash
pytest -q tests/test_derived_parameters.py tests/test_pipeline_runner.py
rg -n "eval|exec|compile" src/flowdesk_core/derived_parameters.py
ruff check src tests
```
