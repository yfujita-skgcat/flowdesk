# Implementation Guides

This directory contains task-level implementation instructions for Codex, opencode, or other local LLM agents.

Each guide defines:

- scope and non-scope
- target files
- implementation rules
- required tests
- acceptance criteria

Agents should read `AGENTS.md`, `llm-task-protocol.md`, the relevant guide in this
directory, and related docs before editing code. A Qwen3.6 27B-class agent should
implement only one numbered increment from one guide per run.

Use `source-map.md` to locate the owning production module and minimum test files.

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
12. `qt-gui-debugging.md`
13. `performance-and-review.md`
14. `population-filtering-and-histograms.md`
15. `gate-hierarchy-ui.md`

The list above documents the implemented MVP foundation. New work follows the
release order below.

## Release A: scientific foundation

| ToDo phase | Guide | Prerequisite |
|---|---|---|
| A1 | `sample-catalog-and-channel-identity.md` | FCS I/O, runner |
| A2 | `derived-parameter-editor.md` | A1 typed sample data |
| A3 | `scientific-transforms-v2.md` | A1 |
| A4-A5 | `compensation-workspace.md` | A1 |
| A6 | `statistics-definitions.md` | A1-A3 |
| A7, B8 | `project-migration-and-recovery.md` | project storage |

## Release B: experiment-scale gating

| ToDo phase | Guide | Prerequisite |
|---|---|---|
| B1 | `groups-and-annotations.md` | A1 |
| B2, B5 | `gate-engine-v2.md` | A3 |
| B3 | `workspace-tree-and-undo.md` | B2 |
| B3.1 | `gating-and-results-workspaces.md` | B3 |
| B3.2 | `interactive-current-sample-preview.md` | B3.1 |
| B3.3 | `results-integrated-current-sample-recalculation.md` | B3.2 |
| B4 | `group-gating-and-overrides.md` | B1-B3 |
| B6 | `graph-window-v2.md` | A3, A6 |
| B7 | `overlay-and-backgating.md` | B3, B6 |
| B7.1 | `multi-sample-overlay-and-plot-presentation.md` | B6-B7 |
| B7.2 | `integrated-overlay-controls-and-plot-appearance.md` | B7.1 |
| B7.3 | `sample-sheet-results-and-batch-plot-export.md` | B1, B3.3, B7.1, A6 |
| B7.4 | `analysis-workflow-integration.md` | A2-A3, A6, B1, B3.3, B7.2-B7.3 |
| B7.6 | `unified-results-export-and-population-paths.md` | B7.5, B1-B4, A7 |

## Release C: reports and interoperability

| ToDo phase | Guide | Prerequisite |
|---|---|---|
| C1 | `table-editor.md` | A6, B1 |
| C2 | `layout-editor.md` | B6-B7, C1 |
| C3 | `templates-and-mapping.md` | A1, B1-B4 |
| C4-C6, C8 | `interoperability.md` | A1-A7 |
| C7 | `plate-workspace.md` | B1, C1 |

## Release D: scientific platforms and extensions

| ToDo phase | Guide | Prerequisite |
|---|---|---|
| D1 | `kinetics-platform.md` | A6, B6 |
| D2 | `proliferation-platform.md` | A3, A6 |
| D3 | `cell-cycle-platform.md` | A3, A6 |
| D4 | `population-comparison.md` | A6, B7 |
| D5 | `spectral-compensation.md` | A4-A5 |
| D6 | `extension-api.md` | A7 |
| D7 | `preferences-and-accessibility.md` | B8 |
| all releases | `performance-and-review.md` | continuous |

## Choosing a guide

- If a task changes scientific output, start with the core/scientific guide, not a Qt guide.
- If a task changes only rendering or interaction, also read `qt-gui-debugging.md`.
- If a task changes project JSON, also read `project-migration-and-recovery.md`.
- If a task affects more than one row above, split it and complete prerequisites first.
