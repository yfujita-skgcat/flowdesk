# Interactive Current-Sample Preview

> **Presentation superseded by Phase B3.3**
>
> The core preview contract, revision checking, debounce, latest-wins scheduling, and
> worker lifecycle in this guide remain valid. The separate Current Sample Preview panel
> and the default All Events fallback are transitional B3.2 behavior and are replaced by
> `results-integrated-current-sample-recalculation.md`.

Spec: `S07`, `S14`
ToDo: `Phase B3.2`

## Goal

Provide responsive, scientifically consistent feedback after a gate definition changes
without running the full multi-sample batch pipeline after every drag.

The feature has two deliberately separate result lifecycles:

1. **Current-sample preview** recalculates the active sample after a short debounce and is
   clearly labelled as non-authoritative preview data.
2. **Run Pipeline** remains the authoritative execution boundary for all samples, Groups,
   overrides, statistics, QC, diagnostics, export, CLI, and Python API results.

The preview must call GUI-independent core execution APIs. Qt may schedule work, display
status, and atomically adopt completed results, but it must not calculate compensation,
derived parameters, transforms, membership, counts, frequencies, or statistics.

## Why Run Pipeline currently owns result updates

Population and statistic results depend on the complete processing order:

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
```

Using `PipelineRunner` as the formal boundary guarantees full-event calculations,
GUI/headless/CLI agreement, and one invalidation policy when any upstream definition
changes. It also avoids recomputing every loaded sample after each mouse movement.

This architecture remains correct. B3.2 adds a responsive current-sample view without
weakening the authoritative batch boundary.

## Non-goals

- Do not automatically run the full multi-sample pipeline after every gate change.
- Do not compute statistics from display-downsampled events.
- Do not add a second gate evaluator or statistic implementation in Qt.
- Do not expose preview values through authoritative export, QC, or saved batch reports.
- Do not use a permanent `while True` worker loop with an unbounded FIFO queue.
- Do not apply partial worker output to shared caches while a job is still running.
- Do not forcefully terminate a Python/Qt worker thread to cancel obsolete work.

## Required state model

Keep the existing display states independent and add explicit result revisions:

- `active_sample_id`
- `selected_gate_id`
- `display_population_id`
- `analysis_revision`: monotonically increasing revision of analysis definitions.
- `authoritative_result_revision`: revision represented by the last accepted batch report.
- `preview_result_revision`: revision represented by the accepted current-sample preview.
- `preview_status`: `idle`, `pending`, `running`, `current`, `stale`, or `error`.

Revision values are transient runtime state unless a later persistence requirement proves
otherwise. Persisted analysis definitions remain the reproducible source of truth.

The GUI must never infer that a result is current merely because its population ID and
sample ID match. A result is usable only when its revision also matches the current
analysis revision.

## Invalidation and dependency rules

When a gate, compensation binding/matrix, derived parameter, transform, override, or
statistic definition changes:

1. Increment `analysis_revision` immediately.
2. Mark the authoritative batch result stale.
3. Mark affected preview memberships and statistics stale before scheduling work.
4. Prevent stale memberships from filtering the plot.
5. Preserve gate definitions and editable gate outlines.

For a gate change, invalidate the changed gate and all descendant populations. If gate
`A` is changed in `A -> B -> C`, memberships and statistics for `A`, `B`, and `C` are
invalid for the new revision. Unrelated branches may remain reusable only after a core
dependency API and tests prove that reuse is scientifically equivalent. The first
implementation should prefer correctness over fine-grained cache reuse.

## Immutable preview job and result

The scheduler submits an immutable definition snapshot. A worker must never read mutable
Qt widgets or the live project dictionary.

Minimum request fields:

```text
revision
sample_id
strategy_id
changed_gate_id or invalidation reason
required_population_id
immutable project-definition snapshot
immutable typed sample input
```

Minimum result fields:

```text
revision
sample_id
population memberships/counts/frequencies
requested statistics
diagnostics
```

Revision is scheduler metadata; scientific values still come from the canonical core
pipeline stages. Prefer a typed core `PreviewRequest`/`PreviewReport` and a synchronous,
GUI-independent `PipelineRunner.preview_sample()` API before adding asynchronous Qt code.

## Scheduling rules

### Drag and text editing

- During mouse drag, update only the gate outline and mark preview as pending/stale.
- Commit the gate definition on release.
- Start or restart a 200–400 ms debounce timer.
- Submit one preview after the user stops editing.

Numeric editors use the same debounce after a valid committed definition. Invalid or
incomplete editor text never starts scientific execution.

### Coalescing and latest-wins behavior

Do not process revisions as an unbounded FIFO sequence. If revisions 41, 42, and 43 are
created quickly:

- replace pending 41 with 42, then replace pending 42 with 43;
- allow an already-running 41 to finish if safe cancellation is unavailable;
- discard result 41 when it returns;
- execute or accept only the newest still-required revision.

At most one preview job should run initially. A maximum worker count of one avoids
concurrent writes and makes memory use predictable. `QThreadPool` with one worker, or one
owned `QThread` worker object, is preferable to a manually looping permanent thread.

## Result acceptance and atomicity

The worker builds a complete local result. It must not progressively mutate a shared
membership dictionary.

On completion, the GUI thread accepts a preview only when all are true:

- `result.revision == analysis_revision`
- `result.sample_id == active_sample_id` or the result is intentionally cached without
  changing the active display
- the requested population/strategy identity still matches
- the project/window is not closing

Otherwise discard the result without changing the plot or visible statistics.

Accepted memberships, counts, frequencies, and statistics are exchanged atomically in the
GUI thread, followed by one redraw. Worker threads must never touch widgets or pyqtgraph
items.

## Navigation while preview is pending

The B3.2 fallback below is retained only as implementation history. Under B3.3, preserve
the selected descendant, its old membership, and its old values when they exist. Mark the
affected rows `recalculating` and show the explicit plot banner
`Recalculating — displayed events are from the previous revision`.

Fallback to a parent population or All Events only when the displayed population was
deleted, is no longer resolvable, has no prior membership for that sample, or the sample
became unavailable. Gate outlines remain visible and editable.

Selecting a new descendant while a job is pending updates the required population. The
scheduler prioritizes the ancestor path to that target and its requested statistics. Other
affected branches and other samples remain deferred to Run Pipeline.

## User-interface presentation

Do not present preview values as authoritative `ResultsWorkspace` rows without provenance.
Use the ResultsWorkspace as the sole visible result surface. The former compact
`Current Sample Preview` area is transitional B3.2 presentation and is replaced by the
ResultsWorkspace overlay defined in `results-integrated-current-sample-recalculation.md`.

The ResultsWorkspace must show:

- sample and population identity
- Events, `% Parent`, `% Total`, and requested statistics
- preview source, revision, and row freshness status
- a global `Batch results stale` indicator when Run Pipeline has not accepted the current definitions

Recommended combined status examples:

```text
Current-sample preview: current (revision 43)
Batch results: stale (revision 42)
```

ResultsWorkspace may overlay an accepted current-sample `PreviewReport` on the batch
baseline, but authoritative export, QC, and diagnostics continue to use only an accepted
batch `ExecutionReport`. Preview values may never silently replace that authoritative
baseline.

## Run Pipeline interaction

`Run Pipeline` snapshots the current definitions and revision after all pending gate edits
are committed. It has priority over new preview submission.

- Do not start redundant preview work while the authoritative run is active.
- A preview already running may finish, but obsolete output is discarded.
- Accept the batch report only for the revision it executed.
- If definitions change during the batch run, mark that report stale or discard it rather
  than labelling it current.
- A successful current-revision batch run atomically updates authoritative Results and may
  seed the current-sample preview cache from identical core outputs.

## Thread lifecycle and errors

- Own workers from one scheduler/controller with explicit shutdown.
- Do not leave a `QThread` running when the window or test exits.
- Convert worker exceptions to typed preview diagnostics and `preview_status = error`.
- Keep the previous authoritative report unchanged on preview failure.
- Clear pending timers and ignore late signals during shutdown/project replacement.

## Target files

Core:

- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/execution_report.py` or a focused preview result module
- pure dependency traversal in `src/flowdesk_core/populations.py` if needed

Qt:

- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/preview_scheduler.py`
- `src/flowdesk_qt/current_sample_preview.py`
- `src/flowdesk_qt/plot_widget.py` for status consumption only
- `src/flowdesk_qt/results_workspace.py` only if preview provenance is explicit

Tests:

- `tests/test_interactive_preview.py`
- `tests/gui/test_interactive_preview.py`
- existing pipeline, population filtering, gate hierarchy, and strict Qt teardown suites

## Implementation increments

Implement one increment at a time.

Current status: increments 1–6 are implemented and retained as the B3.2 execution
foundation. `PreviewRequest`, `PreviewReport`,
and the synchronous GUI-independent `PipelineRunner.preview_sample()` contract execute
one full-resolution sample through the canonical runner. `PreviewRevisionState` now
tracks analysis, authoritative, and preview revisions, invalidates changed gate
descendants, and provides transitional stale-navigation fallback. `PreviewScheduler` now adds a
single-worker debounce/latest-wins queue with immutable project snapshots and obsolete
completion discard. `CurrentSamplePreview` now presents only accepted current-revision
preview values with explicit batch-stale provenance, and stale navigation uses a current
ancestor fallback. Preview requests now carry target statistic IDs, while Run Pipeline
suspends new preview work and accepts only matching batch revisions. Scheduler shutdown,
late-signal handling, queue coalescing, and full-resolution representative-event tests
complete the B3.2 implementation.

1. **Synchronous core preview contract**
   - Add immutable request/result types and `PipelineRunner.preview_sample()`.
   - Execute the canonical stage order on one full-resolution sample.
   - Prove numerical identity with the same sample in a full batch run.
2. **Revision and invalidation model**
   - Add analysis/authoritative/preview revision state.
   - Invalidate changed gates and descendants before any asynchronous scheduling.
   - Add navigation fallback tests without starting threads.
3. **Debounced latest-wins scheduler**
   - Add one-worker scheduling, coalescing, immutable snapshots, and stale-result discard.
   - Add deterministic tests using controlled fake completion order.
4. **Atomic GUI preview presentation**
   - Add the transitional `Current Sample Preview` status/values and nearest-valid-ancestor fallback.
   - Never update Qt widgets from the worker thread.
5. **Preview statistics and batch interaction**
   - Recompute only requested current-sample statistics through core APIs.
   - Give Run Pipeline priority and revision-check both preview and batch completion.
6. **Performance and shutdown verification**
   - Benchmark debounce/coalescing on representative event counts.
   - Verify no unbounded queue, no stale flash, bounded memory, and clean Qt teardown.

## Required tests

- Preview and full batch return identical membership/count/frequency/statistic values for
  the same sample, definition snapshot, and revision.
- Display downsampling does not affect preview values.
- Parent gate change invalidates every descendant before navigation can display it.
- Results arriving out of order accept only the current revision.
- Repeated edits coalesce to the newest pending revision.
- Descendant selection during recalculation preserves the old result with explicit
  `recalculating` provenance, and falls back only when no prior membership is available.
- Worker output is applied atomically in the GUI thread.
- Run Pipeline commits pending edits and remains authoritative for all samples/export/QC.
- Definition changes during preview or batch execution prevent obsolete results from being
  labelled current.
- Worker exception/project close/window close leaves no running thread or late widget call.

## Acceptance criteria

- Gate editing receives responsive current-sample feedback without full batch execution.
- Preview provenance and batch stale state are simultaneously visible.
- No stale descendant membership is silently displayed after an ancestor change.
- No obsolete or partial result can overwrite a newer revision.
- GUI, preview, batch, CLI, and Python API use the same scientific core definitions and
  full-resolution event data.
- Run Pipeline remains the sole authoritative multi-sample result and export boundary.
