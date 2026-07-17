# Workspace Tree and Undo/Redo

Spec: `S07`, `S14`
ToDo: `Phase B3`

## Goal

Unify sample/population/statistic navigation and make project mutations reversible
without embedding cached scientific results in undo history.

This guide records the completed B3 baseline. Do not extend the current vertically
stacked `WorkspaceTree` and `PopulationTree` design. The required follow-up architecture is
defined by `gating-and-results-workspaces.md` (Phase B3.1): keep Gate definition editing
separate and merge executed sample/population/statistic results into one Results workspace.

## Inspect first

- `src/flowdesk_qt/gate_editor.py`, `population_tree.py`, `main_window.py`
- `src/flowdesk_core/models.py`, `gating_strategy.py`
- `src/flowdesk_storage/project.py`
- GUI hierarchy and workflow tests

Read `gate-hierarchy-ui.md` and `qt-gui-debugging.md`.

## Command contract

Each command has stable type, validated input, `apply(project_state)`, and an inverse or
captured prior definition. Commands operate on definitions only. Membership/results are
invalidated by dependency hash and never stored in command payloads.

Initial commands: create/edit/rename/delete/reparent/duplicate gate, copy subtree, edit
annotation, and bind analysis. A failed validation must leave state and undo index unchanged.

Flowdesk's first command implementation uses a JSON-compatible project-state mapping
(`dict[str, Any]`) as its boundary. Commands copy only definition data with
`deepcopy`; raw event arrays, execution reports, and membership masks are never part
of a command. Every command exposes a stable `type`, validates its input before
mutation, and records the prior definition needed for an exact inverse. The stack
keeps a clean marker separately from the command history so saving a project does not
discard undo entries. Applying a command or undoing/redoing one emits a dependency
invalidation reason; the GUI may use that reason to mark cached results stale.

## Increments

1. Add immutable project-state mutation helpers and focused core tests.
2. Add command objects and undo stack independent of Qt.
3. Route existing gate mutations through commands without changing UI. GateEditor
   now routes create/edit/rename/delete/reparent plus duplicate and subtree copy
   through the core stack; loading a saved gate list resets the clean marker.
4. Build a unified tree with stable IDs in `Qt.UserRole`. `WorkspaceTree` displays
   sample roots, report populations, and statistic children, and bridges only
   display selection back to the existing sample/population navigation callbacks.
5. Add breadcrumb and parent/previous/next sample navigation. MainWindow's
   navigation bar derives the breadcrumb from stable population parents and
   disables parent/next/previous actions at the corresponding boundaries.
6. Add subtree copy and preflight conflict dialog. GateEditor exposes preflight
   warnings for sibling-name conflicts and validates reparent cycles/missing
   parents before the confirmation dialog; referenced deletes remain blocked
   with dependent IDs shown.
   `CopySubtreeAnalysisCommand` applies one source subtree to multiple resolved
   target strategies for population/sample/group scopes atomically.
7. Add Undo/Redo actions, shortcuts, labels, dirty/stale updates. MainWindow
   exposes Undo/Redo actions with standard shortcuts, updates enabled state from
   GateEditor, marks the project clean after save/load, and routes undo mutations
   through the existing results-stale invalidation path.

The original B3 implementation synchronizes GateEditor, WorkspaceTree, and PopulationTree
selection as display-only state. This is transitional behavior, not the final selection
contract. Phase B3.1 must separate `active_sample_id`, `display_population_id`, and
`selected_gate_id`; selecting a gate definition must not implicitly filter the plot to the
gate's child population. No selection callback creates a project command.

## Required tests

- Apply/undo/redo restores exact serialized definitions and stable IDs.
- Invalid reparent/delete/copy is atomic and not added to history.
- Undo after pipeline run marks old results stale.
- Selection/breadcrumb changes do not create commands.
- Project save establishes a clean undo marker.
- GUI and headless counts agree after redo and reload.

## Do not do

- Do not use screen/widget snapshots as undo state.
- Do not put NumPy event arrays or membership masks in commands.
- Do not merge unrelated commands merely to shorten history.

## Verification

```bash
pytest -q tests/test_gates.py tests/test_project_storage.py tests/gui/test_gate_hierarchy_ui.py
./tools/run-gui-tests.sh -q
```
