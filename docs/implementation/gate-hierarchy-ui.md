# Gate Hierarchy UI Implementation Guide

## Goal

Provide a FlowJo-like hierarchy editor for geometric and Boolean gates while
keeping membership evaluation in the GUI-independent pipeline.

## Target Files

- `src/flowdesk_qt/gate_editor.py`: hierarchy tree, child creation, reparent,
  Boolean editing, and gate details
- `src/flowdesk_qt/population_tree.py`: explicit child-gate requests
- `src/flowdesk_qt/main_window.py`: display navigation and stale handling
- `src/flowdesk_core/gating_strategy.py`: graph validation and evaluation
- core models, project schemas, and GUI/headless/CLI tests

## State Boundaries

Scientific state consists of stable ids, names, gate types, parents, Boolean
source ids and operations, parameters, axis scales, and coordinates. Every
scientific edit invalidates membership and statistics and must be persisted.

Display state consists of selected/expanded rows, viewport, displayed sample
and population, and displayed channels/scales. Selection alone never changes a
gate parent.

## Required Workflows

1. A tree rooted at All Events stores population ids in `Qt.UserRole`.
2. Create Child Gate explicitly fixes the selected population as parent and
   shows parent id, sample, parameters, and scales before drawing.
3. Reparent validates the complete graph before committing and rolls back on
   self/descendant/missing-parent/cycle failures.
4. Boolean AND/OR require at least two sources; NOT requires exactly one.
   Existing Boolean gates can be edited using hierarchy ids.
5. Show Gate navigates to matching parameters/scales without changing analysis.
6. Deletion of a referenced gate is rejected.

## Required Tests

- Three-level hierarchy, duplicate names, rename, reload, and id safety
- Explicit child creation and cancellation
- Valid/invalid reparent with atomic rollback
- Boolean create/edit, arity, self/cycle/dangling-source validation
- GUI/headless/CLI agreement after project round-trip
- Mixed scales, multiple samples, stale invalidation, stable object names

## Acceptance Criteria

- GUI code never computes membership or population statistics.
- `PipelineRunner` full-resolution results are the sole source of masks/counts.
- Analysis edits reproduce through GUI, Python API, and CLI.
- GUI, core, storage, and CLI tests pass without weakened assertions.
