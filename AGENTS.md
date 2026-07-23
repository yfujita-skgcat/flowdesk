# Flowdesk Agent Guide

Flowdesk is a Linux-first, cross-platform-capable FlowJo-like flow cytometry analysis application.

## Project Rules

- Prioritize scientific correctness and reproducibility over GUI polish.
- Keep `flowdesk_core` independent from PySide6, Qt, and `flowdesk_qt`.
- Treat raw FCS event data as immutable. Compensation, derived parameters, transforms, gates, and statistics are derived views or caches.
- Preserve the processing order:

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

- Do not use arbitrary Python `eval` for derived parameter expressions.
- Prefer core tests before GUI changes.
- Use 2 spaces for Python indentation.
- Do not commit large FCS files. Use small synthetic fixtures or documented external data references.

## Commit Message Rule

- Write commit messages in the exact format below, returning only the message lines without labels, headings, backticks, or code fences.
- The Japanese and English titles must each be 50 characters or fewer.
- Keep exactly one blank line between the title, body, separator, and English section as shown.
- Every body line must start with `- ` and describe a concrete change.
- Use Japanese for the first title and body, then a line containing exactly `----`, followed by the English title and body.
- When the current model name is available, include it as a standalone line immediately below each corresponding title, as in the project’s commit examples; otherwise omit it.

Japanese title (≤ 50 chars)

[current model name, when available]

- Japanese body line

----

English title (≤ 50 chars)

[current model name, when available]

- English body line

## User Manual Rule

- When adding or changing a user-visible feature, update `docs/user-manual/user_manual.md` in the same change.
- Document the user-facing behavior, relevant settings or workflow, and any limitations needed to reproduce the feature.
- Keep the manual consistent with the current implementation; do not defer the documentation update to a separate change.

## Before Changes

Before making a substantial change, summarize the purpose, files expected to change, and acceptance criteria.

## After Changes

After making a substantial change, summarize tests run, remaining limitations, and next small task.

## Headless Execution Rule

The analysis pipeline created or edited in the GUI must be executable outside the GUI.

All analysis execution must go through a GUI-independent pipeline runner.

The GUI must not contain scientific execution logic. It may only edit project state, call the pipeline runner, and display results.

Any feature that affects analysis results must be represented in the project file format so that CLI and Python API execution can reproduce the same result.

Before adding GUI behavior, ensure the same behavior can be represented in the core project model and executed by the headless pipeline runner.

## GUI Debugging

Flowdesk GUI uses PySide6 and pyqtgraph.

```bash
./tools/run-gui-tests.sh
./tools/run-single-gui-test.sh <pytest-node-id>
make test-all
```

- Use stable Qt object names instead of screen coordinates.
- GUI tests run with strict callback exception handling.
- Do not leave a QThread running at test shutdown.
- Inspect screenshots, application logs, and UI state under `artifacts/gui/`.
- GUI population counts must match headless `PipelineRunner` results.
- Never use display-downsampled data for scientific results or weaken assertions.

## Implementation Guides

Before implementing a feature, read the matching guide under `docs/implementation/`. Each guide defines target files, implementation rules, required tests, and acceptance criteria. If no guide exists for the task, add or update one before writing production code.
docs/user-manual/user_manual.md
