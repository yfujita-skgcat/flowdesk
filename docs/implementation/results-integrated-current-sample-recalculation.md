# Results-Integrated Current-Sample Recalculation

Spec: `S07`, `S11`, `S14`  
ToDo: `Phase B3.3`

## Goal

Use `ResultsWorkspace` as the only visible result presentation surface.

After an analysis definition changes:

1. preserve the active sample, displayed population, axes, scale, and view range;
2. retain previous values and memberships as explicitly stale context;
3. mark the affected active-sample subtree as `recalculating`;
4. recalculate the active sample through the GUI-independent canonical pipeline;
5. atomically replace the affected Results rows and plot membership;
6. mark the accepted active-sample rows `current`;
7. leave affected rows for other samples `stale` until `Run Pipeline`.

`Run Pipeline` remains the authoritative boundary for multi-sample Results, Group QC,
diagnostics, export, CLI, and Python API.

## Superseded B3.2 presentation policy

Retain these B3.2 components:

- `PreviewRequest`
- `PreviewReport`
- `PipelineRunner.preview_sample()`
- revision checking
- debounce and latest-wins scheduling
- immutable project/sample snapshots
- obsolete completion discard
- clean worker shutdown

Replace these B3.2 presentation choices:

- the separate `Current Sample Preview` panel;
- unconditional fallback to `All Events` after an ancestor edit;
- clearing current-sample scientific values while preview is pending;
- treating ResultsWorkspace as batch-only presentation.

The separate panel was a safe transitional implementation, not the final UX.

## Result lifecycles

The application still has two execution lifecycles.

### Active-sample interactive result

- produced by `PipelineRunner.preview_sample()`;
- full-resolution and scientifically identical to the same sample in a batch run;
- usable for the active sample's plot and Results rows;
- not usable for authoritative export, Group QC, or saved batch diagnostics.

### Authoritative batch result

- produced by `Run Pipeline`;
- covers all selected samples and resolved Group/strategy bindings;
- owns export, QC, diagnostics, CLI-equivalent result state, and persisted execution provenance.

ResultsWorkspace may display both lifecycles, but must keep their source and revision
internally explicit.

## Runtime result-state model

Add a Qt-independent runtime presentation model. It must not calculate scientific values.

Minimum concepts:

```text
analysis_revision
authoritative_report and authoritative_revision
accepted preview reports keyed by sample
row freshness keyed by sample/population/statistic
row source: authoritative_batch | active_sample_preview
affected population IDs
batch_stale
```

Minimum row freshness values:

```text
current
recalculating
stale
error
missing
```

Zero events and undefined statistic state must remain distinguishable without losing
freshness provenance, for example by a secondary outcome field or `current` (zero events).

The model may merge report objects for presentation, but it must not convert preview output
into an authoritative batch report.

## Gate-change behavior

For a gate geometry or definition change:

- affected populations are the changed gate and all descendants;
- ancestors and independent sibling branches remain valid;
- active sample affected rows become `recalculating`;
- other sample affected rows become `stale`;
- old values remain visible;
- the active sample is scheduled through the existing preview scheduler;
- do not change `display_population_id`.

The first implementation may continue to execute the complete active sample through
`preview_sample()`. Do not add a second partial gate/statistic executor merely to optimize
the affected subtree. The affected subtree controls invalidation and presentation scope,
not necessarily the initial numeric execution scope.

## Atomic application

A worker must return one complete immutable `PreviewReport`.

Do not update rows one by one as individual populations finish.

On the GUI thread, accept the result only when:

- its revision equals the current analysis revision;
- its sample is still the intended sample;
- the project/window is not closing.

Then, in one transaction:

- update the accepted preview overlay;
- update affected population and statistic rows;
- update membership used by the plot;
- clear the recalculating banner;
- redraw once.

This prevents new-parent/old-child frequency combinations from appearing.

## Plot behavior while recalculating

Use the previous membership as context when available.

Do not change:

- active sample;
- displayed population;
- axes;
- scale;
- zoom/pan range;
- selected gate.

Show an unmistakable plot banner:

`Recalculating — displayed events are from the previous revision`

The old membership must not be presented as current or exported.

Fallback to the parent population or `All Events` only when:

- the displayed population was deleted;
- the population is no longer resolvable;
- no prior membership exists for that sample/population;
- the sample itself changed or became unavailable.

## ResultsWorkspace behavior

ResultsWorkspace is the only visible location for Events, `% Parent`, `% Total`, statistic
values, and result freshness.

While pending, retain the old values and show `recalculating`.

After acceptance, replace the active-sample values and show `current`.

For other samples affected by a shared gate definition, retain old values and show `stale`.

A current row means that row matches the current analysis definition for that sample. It
does not mean the multi-sample batch is current. Keep batch provenance visible through a
global indicator or tooltip, for example `Current sample updated; batch results stale`.

## Export and QC

Authoritative export, QC, and diagnostics continue to read only the accepted batch
`ExecutionReport`.

Do not allow a current active-sample overlay to make export available while batch results
are stale.

`Run Pipeline` success replaces the authoritative baseline, clears matching
stale/recalculating states, and marks the batch current only when the run revision equals
`analysis_revision`.

## Current Sample Preview removal

After ResultsWorkspace has equivalent tested behavior:

- remove `CurrentSamplePreview` from the center layout;
- remove MainWindow calls to `set_pending`, `set_report`, `set_stale`, and `set_error`;
- remove or retire `src/flowdesk_qt/current_sample_preview.py`;
- migrate tests to ResultsWorkspace row state and the global batch-stale indicator.

Do not remove the scheduler or core preview contract.

## Target files

Primary:

- `src/flowdesk_qt/results_workspace.py`
- proposed `src/flowdesk_qt/results_state.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/preview_scheduler.py`
- `src/flowdesk_core/preview.py` only if typed runtime metadata genuinely belongs there
- `src/flowdesk_qt/current_sample_preview.py` for final removal
- plot status/banner code

Tests:

- `tests/test_interactive_preview.py`
- `tests/gui/test_interactive_preview.py`
- `tests/gui/test_results_workspace.py`
- `tests/gui/test_population_filtering.py`
- `tests/gui/test_gate_hierarchy_ui.py`
- `tests/gui/test_gui_workflow.py`

## Implementation increments

Implement only one numbered increment per agent run.

1. **Runtime result overlay and row freshness**
   - Add the Qt-independent merge/state model.
   - Preserve authoritative values as the baseline.
   - Mark active affected rows `recalculating` and other affected rows `stale`.
   - Accept one current-revision `PreviewReport` atomically.
   - Add unit tests before widget changes.
2. **ResultsWorkspace integration**
   - Render the merged row state in hierarchy and flat modes.
   - Keep old values while recalculating.
   - Replace affected active-sample rows after acceptance.
   - Preserve row revision/source in data roles and tooltip/accessibility text.
3. **Display-population and plot preservation**
   - Remove unconditional All Events reset.
   - Keep old membership with a recalculating banner.
   - Atomically adopt preview membership and Results state.
   - Fallback only for deleted/unresolvable/no-prior-membership cases.
4. **Remove duplicate preview panel and finalize batch semantics**
   - Remove the visible Current Sample Preview panel and callers.
   - Move batch-stale status to Results/global status.
   - Verify Run Pipeline replacement, export/QC blocking, errors, and teardown.
   - Update documentation and screenshots.

## Required tests

- Gate edit does not change `display_population_id`.
- Ancestor edit while a descendant is displayed retains that descendant identity.
- Old descendant values and membership remain visible with `recalculating`.
- Other samples' affected rows become `stale`.
- An accepted same-revision preview atomically changes affected active-sample rows to `current`.
- An obsolete preview changes no row and no plot.
- Parent/child counts and frequencies never mix revisions.
- Hierarchy and flat modes show identical merged values and status.
- A deleted displayed population falls back safely.
- A new gate with no prior membership does not fabricate old values.
- Active-sample current rows do not enable stale batch export or QC.
- Run Pipeline makes matching rows authoritative and current.
- Current Sample Preview is no longer visible after increment 4.
- No worker remains at window shutdown.

## Acceptance criteria

- ResultsWorkspace is the sole visible result surface.
- Current-sample feedback is responsive and scientifically consistent.
- Gate editing does not unexpectedly navigate to All Events.
- Old results are visible only with explicit stale/recalculating provenance.
- Accepted results are applied atomically.
- GUI code performs no scientific calculations.
- Preview, batch, CLI, and Python API remain numerically consistent.
- Run Pipeline remains the authoritative multi-sample/export/QC boundary.
