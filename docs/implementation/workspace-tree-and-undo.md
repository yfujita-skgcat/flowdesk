# Workspace Tree and Undo/Redo

Spec: `S07`, `S14`
ToDo: `Phase B3`

## Goal

Unify sample/population/statistic navigation and make project mutations reversible
without embedding cached scientific results in undo history.

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

## Increments

1. Add immutable project-state mutation helpers and focused core tests.
2. Add command objects and undo stack independent of Qt.
3. Route existing gate mutations through commands without changing UI.
4. Build a unified tree with stable IDs in `Qt.UserRole`.
5. Add breadcrumb and parent/previous/next sample navigation.
6. Add subtree copy and preflight conflict dialog.
7. Add Undo/Redo actions, shortcuts, labels, dirty/stale updates.

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

