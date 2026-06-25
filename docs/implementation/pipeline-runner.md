# Pipeline Runner Implementation Guide

## Goal

Implement the GUI-independent project execution engine used by GUI, CLI, and Python API.

## Target Files

- `src/flowdesk_core/pipeline.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/execution_context.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_storage/project.py`
- `tests/test_pipeline_runner.py`
- `tests/test_project_headless_execution.py`

## Implementation Rules

- Do not import PySide6, Qt, or `flowdesk_qt`.
- Execute the canonical order: raw events, compensation, derived parameters, transforms, gates, population statistics, export.
- Select execution profile by id.
- Record project version, pipeline version, software version, sample path, size, mtime, and hash when available.
- GUI display downsampling must not affect execution.
- Cache usage must be explicit and invalidated when upstream definitions change.

## Required Behavior

- Run a project object from Python API.
- Run a project loaded from `.flowdesk` storage.
- Select execution profiles.
- Include population statistics in `ExecutionReport`.
- Produce clear failure reports or exceptions for missing samples, missing strategies, and invalid profiles.

## Required Tests

- Existing import-without-GUI test remains.
- Unknown execution profile raises a clear error.
- Synthetic project with one sample and precomputed event table can produce expected population result.
- Execution report includes pipeline version and selected profile id.
- No import path from `flowdesk_core` to `flowdesk_qt` exists.

## Acceptance Criteria

- `pytest tests/test_pipeline_runner.py tests/test_project_headless_execution.py` passes.
- `pyenv exec flowdesk run examples/example_project.flowdesk` exits 0.
- `pyenv exec ruff check src/flowdesk_core src/flowdesk_cli tests` passes.
- `pyenv exec mypy src/flowdesk_core src/flowdesk_cli tests` passes.
- `rg -n "flowdesk_qt|PySide6|Qt" src/flowdesk_core src/flowdesk_cli` has no forbidden core execution imports.
