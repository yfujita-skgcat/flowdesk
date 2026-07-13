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
  than an evaluator exception. Domain and evaluation failures follow the stored
  policy.

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

## Required tests

- Ratio and dependent-derived chain work after compensation.
- Cycle, unknown input, wrong-length result, and unsafe syntax fail clearly.
- `emit_nan_with_warning` records affected count and sample ID.
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
