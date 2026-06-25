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

## Implementation Guides

Before implementing a feature, read the matching guide under `docs/implementation/`. Each guide defines target files, implementation rules, required tests, and acceptance criteria. If no guide exists for the task, add or update one before writing production code.

