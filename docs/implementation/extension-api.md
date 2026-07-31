# Extension API and Batch Queue

Spec: `S22`
ToDo: `Phase D6`

## Goal

Define a versioned Python/CLI surface and isolate plugins so malformed or untrusted
extensions cannot corrupt project state.

## Inspect first

- public imports in `flowdesk_core/__init__.py`
- CLI commands and pipeline runner/context/report
- project storage/artifact handling
- Qt worker lifecycle and diagnostics

## API contract

Publish typed request/result objects and semantic API version. Plugin manifests declare
ID/version, compatible API range, input population/data stage, outputs, resources, and
permissions. Default execution is a child process with bounded paths/resources; outputs
are validated before an atomic project import.

## Increments

1. Inventory and freeze the supported Python/CLI API; add contract tests.
2. Add batch-job model: project/profile/sample selector/output/failure policy.
3. Add progress/cancel result protocol and sample-level queue without GUI.
4. Add plugin manifest/schema and dry-run validation.
5. Add subprocess request/result serialization with timeout and captured diagnostics.
6. Validate/import derived parameters, populations, tables, and artifacts separately.
7. Add GUI queue/status after CLI behavior is stable.

## Implemented CLI batch-plot queue slice

The first queue slice is intentionally limited to saved `Batch Plot Export` definitions;
it does not execute plugins or project-embedded code. `flowdesk batch-plot` accepts repeated
`--queue-export-id` values and runs them in declaration order. Each definition receives a
safe numbered subdirectory under the requested output directory, the same runtime worker and
memory policy, and one shared cooperative cancellation token. `fail-fast` is the default;
`continue` records failures and proceeds to later definitions. A queue cannot combine
`--export-id` with `--queue-export-id`, and queue items are sequential at the definition level
even when each definition opts into bounded sample-level rendering threads.

The GUI now exposes the same saved-definition queue through `Run Saved Queue`; it uses the
headless queue adapter in a Qt worker and keeps cancellation/progress updates on the GUI side.
The queue emits `batch_plot_queue` progress events for `definition_started` and
`definition_completed`, with deterministic `completed_units`/`total_units` and the definition ID
in `sample_id`. Nested `batch_plot_export` events remain available for source/render detail.
The queue loads the project bundle once and passes the immutable mapping snapshot to each
definition invocation. It does not share raw FCS arrays, transformed layers, density fields, or
mutable renderer caches across definitions; those remain definition-scoped to preserve output
isolation and bounded memory behavior.
The queue also atomically updates `batch-queue-manifest.json` after each definition boundary.
The manifest is an audit index only: it records ordered definition IDs, output directories,
failure/cancellation status, and result codes without replacing per-definition manifests.
The queue still deliberately leaves plugin subprocess isolation, queue-level parallelism, and
cross-definition cache sharing for later increments. The existing per-definition manifest and
atomic output rules remain authoritative.

## Required tests

- API compatibility version rejection is explicit.
- Batch fail-run/fail-sample/continue policies produce exact statuses.
- Timeout/crash/malformed/oversized output cannot alter the project.
- Plugin cannot reference files outside allowed paths.
- Imported output has provenance and invalidates dependent caches.

## Do not do

- Do not auto-run scripts embedded in projects.
- Do not pass mutable project objects into plugins.
- Do not deserialize arbitrary Python objects/pickle from plugins.

## Verification

```bash
pytest -q tests/test_cli.py tests/test_pipeline_runner.py tests/test_project_storage.py
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
