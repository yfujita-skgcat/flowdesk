# Groups and Workspace Annotations

Spec: `S02`
ToDo: `Phase B1`

## Goal

Organize samples into explicit and rule-based groups and store editable annotations
without modifying FCS files.

## Inspect first

- `src/flowdesk_core/models.py`, `sample.py`, `pipeline_runner.py`
- `src/flowdesk_storage/project.py`, `schemas/project.schema.json`
- `src/flowdesk_qt/sample_browser.py`, `main_window.py`
- `tests/test_models.py`, `test_pipeline_runner.py`, GUI sample tests

Read `sample-catalog-and-channel-identity.md` first. Phase A1 is a prerequisite.

## Model contract

`SampleGroupSpec` contains ID, name, role, color, explicit sample IDs, optional safe
membership rule, and analysis bindings. A sample may belong to multiple groups.
`AnnotationSpec` records sample ID, keyword, typed value, and source (`fcs`,
`workspace`, `imported`). Workspace values shadow FCS display values but never mutate raw metadata.

## Increments

1. Add typed models/schema and explicit-membership resolver.
2. Add a restricted rule grammar for equality, membership, numeric comparison, and
   boolean composition; reject arbitrary Python.
3. Resolve groups headlessly and include resolved IDs in execution provenance.
4. Add All Samples, Compensation Controls, and user group UI.
5. Add annotation columns, edit, find/replace, fill series, and CSV import preview.
6. Bind strategies/statistics to groups and validate new members before application.

## Current implementation scope

The first increment persists `SampleGroupSpec`, `AnnotationSpec`, and a
`GroupStrategyBindingSpec`. Every newly created manifest contains the internal
`all-samples` Group, whose `{ "all": [] }` rule deterministically selects every
sample, and binds it to `default-strategy`. Normal GUI operation continues to
edit that one strategy; no Group pane is exposed yet.

The current GUI exposes an explicit `Use Multiple Analysis Groups` toggle. It
is unchecked by default, persists as `advanced_groups_enabled`, and reveals the
Group overview with explicit create/rename/delete controls. Disabling it hides
the view without deleting, merging, or changing any persisted Group, binding,
or annotation. Drag/drop membership editing remains a later increment.

Advanced mode now provides a sample-ID drag source and Group drop target. A
drop adds the sample to the Group's explicit `sample_ids` (duplicates are
ignored), emits a project-state change, and marks existing results stale.
`all-samples` remains protected from deletion but accepts membership drops.

Membership rules are JSON ASTs, never Python expressions:

- `{ "all": [rule, ...] }`, `{ "any": [rule, ...] }`, and `{ "not": rule }`
- `{ "keyword": "Panel", "comparison": "equals", "value": "A" }`
- `comparison` may be `equals`, `in`, `gt`, `gte`, `lt`, or `lte`.

Rule evaluation is headless and metadata-only. Missing keywords and nonnumeric
values for numeric comparisons do not match. Workspace/imported annotations
shadow FCS annotations and sample metadata for display and membership; raw FCS
bytes are never changed.

Headless execution resolves these persisted Groups before processing any
sample. A sample matching multiple Groups is accepted when all bindings select
the same strategy. If bindings select different strategies, the runner raises
`PipelineError` with code `conflicting_group_strategy_binding`, including the
sample, matching Group IDs, and candidate strategy IDs; no partial analysis is
started.

## Required tests

- Multiple group membership and deterministic rule resolution.
- Missing keyword, type mismatch, invalid rule, duplicate group ID.
- GUI and CLI resolve identical members.
- New matching sample receives bound analysis.
- Annotation round trip preserves source and raw FCS bytes.

## Do not do

- Do not use `eval` for membership rules.
- Do not make group color or tree position scientific state.
- Do not silently resolve conflicting group analysis bindings.

## Verification

```bash
pytest -q tests/test_models.py tests/test_pipeline_runner.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
```
