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

