# Implementation Guides

This directory contains task-level implementation instructions for Codex, opencode, or other local LLM agents.

Each guide defines:

- scope and non-scope
- target files
- implementation rules
- required tests
- acceptance criteria

Agents should read `AGENTS.md`, the relevant guide in this directory, and related docs before editing code.

Recommended implementation order:

1. `project-storage.md`
2. `safe-derived-parameters.md`
3. `compensation-engine.md`
4. `transforms.md`
5. `gate-engine.md`
6. `population-statistics.md`
7. `pipeline-runner.md`
8. `fcs-io.md`
9. `export-and-cli.md`
10. `qt-integration.md`
11. `qt-interactive-plot-controls.md`
12. `performance-and-review.md`
