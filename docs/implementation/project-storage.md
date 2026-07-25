# Project Storage Implementation Guide

## Goal

Implement robust loading, validation, and saving for `.flowdesk` project bundles.

## Target Files

- `src/flowdesk_storage/project.py`
- `src/flowdesk_storage/manifest.py`
- `src/flowdesk_storage/serialization.py`
- `schemas/project.schema.json`
- `schemas/gating_strategy.schema.json`
- `tests/test_project_headless_execution.py`
- new tests such as `tests/test_project_storage.py`

## Implementation Rules

- Treat a project as a directory bundle, not one JSON file.
- Keep sample FCS files as path references.
- Support relative paths resolved from the project bundle directory.
- On save, convert local absolute sample paths to POSIX-separated paths relative to the target bundle; arbitrary sibling directories such as `../260724_apoptosis/sample.fcs` are valid.
- When copying a project to a new bundle, accept the source bundle path so existing relative references can be rebased before saving.
- Preserve unknown manifest fields unless a validation mode explicitly rejects them.
- Do not import PySide6 or `flowdesk_qt`.
- Use structured JSON parsing, not string manipulation.
- Return typed dataclasses or clearly documented dictionaries. Avoid mixing both styles without an adapter.
- The GUI Save Project action accepts a user-entered name with `QFileDialog.getSaveFileName()`;
  the selected name is normalized to one `.flowdesk` suffix and passed to the storage
  API as a directory path. Storage remains GUI-independent and creates the bundle
  structure through `save_project()`.

## Required Behavior

- Load `manifest.json` from a `.flowdesk` directory.
- Load `gates/gating_strategy.json` when referenced.
- Validate required fields: project id, project version, pipeline version, samples, execution profiles.
- Resolve sample paths according to `sample_path_resolution_policy`.
- Save a manifest without losing execution profile and pipeline metadata.

## Required Tests

- Loading `examples/example_project.flowdesk` succeeds.
- Missing `manifest.json` raises a Flowdesk-specific exception.
- Missing required manifest fields raise a validation error.
- Relative sample paths resolve against the project bundle path.
- A load-save-load round trip preserves execution profiles and derived parameter definitions.

## Acceptance Criteria

- `pytest tests/test_project_storage.py tests/test_project_headless_execution.py` passes.
- `pyenv exec ruff check src/flowdesk_storage tests` passes.
- `pyenv exec mypy src/flowdesk_storage tests` passes.
- No storage module imports Qt or GUI modules.
