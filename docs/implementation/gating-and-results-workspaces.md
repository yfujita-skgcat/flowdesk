# Gating and Executed Results Workspaces

Spec: `S07`, `S14`
ToDo: `Phase B3.1`

## Goal

Replace the current vertically stacked Gate hierarchy, WorkspaceTree, Population Results,
and Custom Statistics presentation with two explicit concepts:

1. **Gating** edits gate definitions and the gating strategy.
2. **Results** navigates samples and displays populations, counts, frequencies, and
   statistic results produced by the last valid pipeline run.

Gate definitions and executed results have different lifecycles. A valid gate definition
may exist before execution, after execution failure, or while prior results are stale.
The GUI must preserve that distinction.

## Non-goals

- Do not combine gate definitions and executed values into one table.
- Do not move membership evaluation, counts, frequencies, or statistics into Qt.
- Do not replace `SampleBrowser` in this phase. A future project navigator may absorb it.
- Do not change the project schema merely to persist transient selection state.
- Do not weaken headless/GUI result agreement or stale-result handling.

## Required state model

Keep these states independent:

- `active_sample_id`: sample whose events and results are being viewed.
- `display_population_id`: population membership used to filter the plot.
- `selected_gate_id`: gate definition selected for editing and outline highlighting.

These values may be synchronized by an explicit user action, but they must not alias the
same field or be updated as an undocumented side effect.

Selection is display state and does not create an undo command. Gate geometry, parent,
name, type, expression, axes, and scale remain analysis definition state and use the
existing command/undo path.

## Right-pane layout

Use tabs or an equivalent exclusive mode switch:

```text
[ Gating ] [ Results ]
```

Only the selected workspace occupies the main right-pane area. Do not keep Gate hierarchy,
WorkspaceTree, Population Results, and Custom Statistics vertically stacked at the same
time.

### Gating tab

The Gating tab owns definition editing:

- gate type and creation controls
- gate definition hierarchy rooted at `All Events`
- gate type, axes/scale, and Boolean expression
- rename, delete, reparent, duplicate/copy, geometry edit, and Boolean edit
- parent context for explicit child-gate creation
- `Show Gate` and `Show Population` as separate actions

Rename the first hierarchy column from `Population` to `Gate` or `Gate definition`.

Selecting a gate:

- updates `selected_gate_id`
- highlights its plot outline
- changes the definition-editing target
- does not implicitly set `display_population_id` to that gate
- does not silently change axes or scales

`Show Gate` navigates to the gate's axes/scales, displays the gate's **parent** population,
and highlights the gate outline. This keeps outside events visible for geometry editing.

`Show Population` sets `display_population_id` to the population produced by the selected
gate. It requires a current, non-stale membership result; otherwise it explains that the
pipeline must be run.

Selecting the Gating `All Events` root clears `selected_gate_id`. It does not need to alter
`display_population_id` unless the user invokes an explicit display action.

### Results tab

Replace the current WorkspaceTree population/statistic duplication and Population Results
table with one results workspace backed only by `ExecutionReport` data.

Default hierarchy:

```text
Sample / Population       Events   % Parent   % Total   Status
1_A1
  All Events               31552      -        100%     current
    rect_1                   7812     24.76%     24.76%  current
      singlets               7000     89.60%     22.19%  current
```

Requirements:

- Every sample has an explicit `All Events` row.
- Selecting a sample row changes only `active_sample_id`.
- Selecting `All Events` sets `display_population_id = "all_events"`.
- Selecting a population changes `active_sample_id` and `display_population_id`.
- Result selection does not change `selected_gate_id` merely to force synchronization.
- Counts and frequencies come from the full-resolution `ExecutionReport`.
- Stale results are visibly stale and must not filter the plot.
- Missing population, zero events, stale results, and execution errors remain distinct.

Statistic results may be shown as expandable children or in a detail pane. Prefer a detail
pane when many statistics would make population navigation difficult. Do not display the
same statistic simultaneously in two adjacent trees.

### Flat table mode

The Results workspace may switch between `Hierarchy` and `Flat table` using the same
underlying report model. The flat form is intended for cross-sample comparison and export:

```text
Sample | Population | Parent | Events | % Parent | % Total | Status
```

Do not encode tree indentation into the population name in flat mode.

## Stale and pre-execution behavior

- Gating remains usable before pipeline execution and while results are stale.
- Results shows samples before execution but no fabricated population values.
- A gate edit invalidates executed membership, counts, frequencies, and statistics without
  invalidating the gate definition itself.
- Stale result rows may remain visible for context only if clearly marked and disabled for
  plot filtering; otherwise clear them consistently.
- Re-running the canonical headless `PipelineRunner` replaces stale result data atomically.

## Target files

Primary:

- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/gate_editor.py`
- proposed `src/flowdesk_qt/results_workspace.py`
- transitional `src/flowdesk_qt/workspace_tree.py`
- transitional `src/flowdesk_qt/population_tree.py`

Tests:

- `tests/gui/test_gate_hierarchy_ui.py`
- `tests/gui/test_population_filtering.py`
- `tests/gui/test_gui_workflow.py`
- `tests/test_qt_plot_widget.py`

Core changes are not expected. If report queries need reusable hierarchy preparation, add
pure helpers to `flowdesk_core.populations`; do not calculate results in Qt.

## Implementation increments

Implement only one numbered increment per agent run.

1. **State separation**
   - Introduce independently observable active sample, display population, and selected
     gate state in `MainWindow`.
   - Preserve current layout temporarily.
   - Add tests proving Gate hierarchy selection does not filter the plot and Results
     selection does not change the editing target.
2. **Gating semantics**
   - Update Gate hierarchy labels and root behavior.
   - Separate `Show Gate` from `Show Population`.
   - Make `Show Gate` display the parent population with the gate outline highlighted.
3. **Results hierarchy model/widget**
   - Add the unified Sample -> All Events -> Population results tree-table.
   - Integrate counts, frequencies, status, and one non-duplicated statistic presentation.
   - Add explicit sample-root versus All Events selection tests.
4. **Right-pane tabs and duplicate removal**
   - Add `Gating` and `Results` tabs.
   - Stop simultaneously displaying the old WorkspaceTree, Population Results, and Custom
     Statistics widgets after equivalent Results behavior is tested.
5. **Flat table mode**
   - Add a hierarchy/flat switch over the same report data.
   - Verify multi-sample ordering, stable IDs, and export-oriented columns.
6. **Transitional cleanup and documentation**
   - Remove or reduce obsolete `WorkspaceTree`/`PopulationTree` adapters only after all
     callers and tests use Results workspace APIs.
   - Update user documentation and screenshots to the final layout.

## Required tests

- Gate selection changes `selected_gate_id` and outline highlight, not displayed membership.
- `Show Gate` displays the parent population and matching axes/scales.
- `Show Population` displays child membership only with current results.
- Sample row changes sample only; explicit All Events restores the full event display.
- Results population selection filters the plot and leaves gate editing selection unchanged.
- Gate edits keep definitions available while making old Results stale/non-filterable.
- Hierarchy and flat modes show identical counts and frequencies.
- Statistics are not duplicated in adjacent views.
- Multi-sample navigation keeps sample/population IDs correctly scoped.
- GUI displayed counts match `PipelineRunner` and CLI/headless results exactly.
- Existing rectangle/polygon/range/Boolean editing and Undo/Redo remain correct.

## Acceptance criteria

- The right pane presents two clear modes: Gating definitions and executed Results.
- Gate definitions are never presented as if they were current sample results.
- WorkspaceTree and Population Results are no longer simultaneously visible duplicates.
- `active_sample_id`, `display_population_id`, and `selected_gate_id` are independently
  testable.
- All Events is explicit in Results and restores full-event display.
- No Qt code computes scientific membership, counts, frequencies, or statistics.
- GUI/headless/CLI numerical agreement and strict GUI teardown tests pass.
