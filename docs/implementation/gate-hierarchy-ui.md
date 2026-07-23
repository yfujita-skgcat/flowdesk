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
and population, and displayed channels/scales. Selection alone never changes an
existing gate parent; it only determines the parent for a newly requested gate.

Keep `selected_gate_id` separate from `display_population_id`. Selecting a gate definition
changes the editing target and outline highlight only; it must not implicitly filter the
plot to that gate's child population.

## Required Workflows

1. A definition tree rooted at All Events stores gate ids in `Qt.UserRole`; label the
   first column `Gate` or `Gate definition`, not `Population`.
2. Create Gate uses the selected hierarchy population as parent. Selecting a gate
   creates a child under it; selecting All Events or leaving the hierarchy without
   a selection creates a root gate. The creation context shows parent details,
   with sample, parameters, and scales available in its tooltip before drawing.
3. Reparent validates the complete graph before committing and rolls back on
   self/descendant/missing-parent/cycle failures.
4. Boolean AND/OR require at least two sources; NOT requires exactly one.
   Existing Boolean gates can be edited using hierarchy ids.
5. Show Gate navigates to matching parameters/scales, displays the parent population, and
   highlights the outline without changing analysis.
6. Deletion of a referenced gate is rejected.
7. Show Population is a separate action that displays child membership only when current,
   non-stale pipeline results exist.
8. The Gating All Events root clears gate editing selection; Results owns explicit
   `all_events` population display selection.

## Required Tests

- Three-level hierarchy, duplicate names, rename, reload, and id safety
- Explicit child creation and cancellation
- Valid/invalid reparent with atomic rollback
- Boolean create/edit, arity, self/cycle/dangling-source validation
- GUI/headless/CLI agreement after project round-trip
- Mixed scales, multiple samples, stale invalidation, stable object names
- Gate selection versus displayed population independence, Show Gate parent display, and
  explicit Show Population behavior

## Acceptance Criteria

- GUI code never computes membership or population statistics.
- `PipelineRunner` full-resolution results are the sole source of masks/counts.
- Analysis edits reproduce through GUI, Python API, and CLI.
- GUI, core, storage, and CLI tests pass without weakened assertions.
