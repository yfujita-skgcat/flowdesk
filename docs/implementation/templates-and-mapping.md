# Templates and Channel Mapping

Spec: `S15`
ToDo: `Phase C3`, with archive details in `interoperability.md`

## Goal

Reuse analysis definitions on new samples through an explicit, reviewable channel-role
mapping instead of filename or column-position guesses.

## Inspect first

- project schema/storage/migration
- sample/channel identity and group models
- compensation, gate, statistic, table, and layout definitions
- GUI project open/save workflows

Prerequisite: Phase A1. Read `sample-catalog-and-channel-identity.md`.

## Template contract

A template excludes sample paths/events and caches. It includes channel roles, group
rules, compensation setup, strategies, statistics, tables, layouts, and source project
version. References point to abstract roles until an application plan binds them to
target channel IDs.

Mapping states are `exact`, `suggested`, `ambiguous`, `missing`, and `confirmed`.
Suggested/ambiguous mappings never execute without confirmation.

## Increments

1. Define template manifest and export validation.
2. Convert a project to a template while proving no sample/event/cache path remains.
3. Build a pure mapping-plan generator using ID/name/marker/detector evidence.
4. Apply only a fully confirmed plan to a copied project state atomically.
5. Build a wizard showing evidence and all affected definitions.
6. Add CLI `template inspect` and `template apply --mapping <json>`.

## Required tests

- Same panel/different channel order maps correctly.
- Detector rename, marker alias, missing marker, and duplicate marker are surfaced.
- Cancel leaves the project byte-equivalent.
- Applied template validates and produces the expected headless strategy.
- Template contains no FCS path, event data, or membership cache.

## Do not do

- Do not select the first fuzzy match.
- Do not modify the source template during application.
- Do not carry old execution results into a new experiment.

## Verification

```bash
pytest -q tests/test_project_storage.py tests/test_pipeline_runner.py
./tools/run-gui-tests.sh -q
```

