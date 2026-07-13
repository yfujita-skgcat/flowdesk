# Project Migration, Diagnostics, Save, and Recovery

Spec: `S14`, `S23`
ToDo: `Phase A7`, `Phase B8`

## Goal

Make project upgrades and saves atomic, observable, and recoverable without changing
scientific meaning.

## Inspect first

- `src/flowdesk_storage/project.py`
- `src/flowdesk_storage/manifest.py`
- `src/flowdesk_storage/serialization.py`
- `src/flowdesk_storage/cache.py`
- `src/flowdesk_storage/manifest.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_qt/main_window.py`
- `schemas/project.schema.json`
- `tests/test_project_storage.py`

Read `project-storage.md`, `pipeline-runner.md`, and `qt-gui-debugging.md`.

## Contracts

- Every migration is `from_version -> to_version`, pure on parsed data, tested, and
  recorded in a `MigrationReport`.
- A newer unsupported project opens read-only or fails; it is never rewritten.
- Save writes a sibling temporary bundle/file, flushes required data, then atomically
  replaces the target where the platform permits.
- Diagnostics use stable code, severity, stage, message, and optional sample/population IDs.

## Increments A7

1. Add typed diagnostic and migration result models.
2. Add reference-integrity validation for IDs and file references.
3. Create a migration registry and fixtures for every historical version in examples/tests.
4. Implement atomic manifest/gate writes and failure cleanup.
5. Add CLI JSON diagnostics and GUI diagnostics panel.

## Increments B8

1. Add global autosave settings and project dirty-state tracking.
2. Save only dirty projects to a separate recovery location with retention limits.
3. On startup, compare project/recovery timestamps and project IDs.
4. Offer open recovery as a copy; never overwrite the original automatically.
5. Test active worker, interrupted write, disk error, and recovery cleanup.

## Required tests

- Each old fixture migrates to the expected exact JSON structure.
- Migration is idempotent at the target version.
- Unknown/newer version is not modified.
- Simulated write failure leaves the previous project readable.
- Dangling gate/matrix/channel references report stable diagnostic codes.
- Autosave does not run for clean/read-only projects.

## Do not do

- Do not migrate caches as authoritative scientific results.
- Do not remove unknown fields without an explicit migration rule.
- Do not use in-place partial writes to `manifest.json`.
- Do not claim recovery success until the recovered project validates and runs.

## Final verification

```bash
pytest -q tests/test_project_storage.py tests/test_project_headless_execution.py
./tools/run-gui-tests.sh -q
ruff check src tests
mypy src/flowdesk_storage src/flowdesk_core src/flowdesk_cli
```

