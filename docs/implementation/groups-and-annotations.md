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

