# Export and CLI Implementation Guide

## Goal

Implement population statistics export and CLI commands for running saved projects.

The unified export and population full-path implementation is specified in
[`unified-results-export-and-population-paths.md`](unified-results-export-and-population-paths.md).
The existing population-only and statistic-only writers remain compatibility
APIs; standard GUI/CLI Results export uses the unified writer.

## Target Files

- `src/flowdesk_core/export.py`
- `src/flowdesk_cli/main.py`
- `src/flowdesk_cli/run_project.py`
- `src/flowdesk_cli/inspect_fcs.py`
- `src/flowdesk_cli/batch_gate.py`
- `tests/test_export.py`
- `tests/test_pipeline_runner.py`

## Implementation Rules

- Export must consume core `PopulationResult` or `ExportRecord` values.
- CLI must call storage and pipeline runner APIs, not reimplement analysis logic.
- Support TSV first; CSV can share the same writer with delimiter selection.
- Handle `NaN` explicitly according to export settings.
- Do not import Qt or GUI modules.
- Build a unified row model before writing wide or long output; do not join
  separate files or recalculate values in Qt.

## Required Behavior

- Write TSV with sample id, population id, event count, frequency of parent, and frequency of total.
- Support `flowdesk run path/to/project.flowdesk --output exports/results.tsv`.
- Return non-zero CLI exit status on validation or execution errors.
- Print concise report summaries.

## Required Tests

- Export writes expected headers and rows.
- `NaN` policy is tested.
- CLI run command calls pipeline runner and writes output for a synthetic project.
- Invalid project path returns a non-zero result or raises a tested exception at adapter level.

## Acceptance Criteria

- `pytest tests/test_export.py tests/test_pipeline_runner.py` passes.
- `pyenv exec flowdesk run examples/example_project.flowdesk` exits 0.
- `pyenv exec ruff check src/flowdesk_core/export.py src/flowdesk_cli tests` passes.
- `pyenv exec mypy src/flowdesk_core src/flowdesk_cli tests` passes.
