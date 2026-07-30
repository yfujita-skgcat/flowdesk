# Parallel Execution and Progress Reporting

Source issue: [`docs/bug.md`](../bug.md)
Spec: `S23`
ToDo: `Performance track / Parallel execution and progress`

## Goal

Reduce interactive sample-switch/render latency first, then reduce elapsed time for
multi-sample analysis and batch plot export while keeping the GUI responsive and
preserving exact scientific and export behavior. Provide observable, cancelable progress
for long-running `Run Pipeline` and Batch Plot Export operations.

This guide deliberately separates three different problems:

1. **Interactive current-sample display** needs low latency and latest-request-wins
   scheduling. The scheduler class exists, but the current cache-miss path bypasses it and
   performs display preparation synchronously. Density coloring also performs redundant
   scatter submission. These are the highest-priority optimizations.
2. **Run Pipeline** has a serial project-wide preparation phase followed by mostly
   independent per-sample work. This is the primary analysis parallelism boundary.
3. **Batch Plot Export** has deterministic planning and shared-source dependencies, then
   independent output items. It needs progress and cancellation before parallel rendering.

Implement only one numbered increment per LLM run. Complete the interactive hot-path
Increments 1–3 before the general progress/parallelism increments unless a new profile
demonstrates a different dominant cost. Do not combine the density hot path, progress
contract, pipeline refactor, Qt UI, and parallel execution in one change.

## Required reading

Read completely, in this order:

1. `AGENTS.md`
2. `docs/specs.md`, section `S23`
3. `ToDo.md`, `Performance track`
4. `docs/implementation/llm-task-protocol.md`
5. `docs/implementation/performance-and-review.md`
6. this guide
7. `docs/implementation/pipeline-runner.md`
8. `docs/implementation/interactive-current-sample-preview.md`
9. `docs/implementation/sample-sheet-results-and-batch-plot-export.md`, Increment 2
10. `.codex/skills/performance-benchmark/SKILL.md`
11. `.codex/skills/scientific-review/SKILL.md`
12. `.codex/skills/qt-plot-widget/SKILL.md` before a Qt increment

## Inspect first

Read every selected file completely before production edits.

Core and CLI:

- `src/flowdesk_core/execution_context.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/batch_plot_export.py`
- `src/flowdesk_core/processed_display.py`
- `src/flowdesk_cli/run_project.py`
- `src/flowdesk_cli/batch_plot.py`

Qt:

- `src/flowdesk_qt/preview_scheduler.py`
- `src/flowdesk_qt/processed_display_scheduler.py`
- `src/flowdesk_qt/main_window.py`, especially `_PipelineWorker`,
  `_on_run_pipeline()`, `_on_pipeline_finished()`, and `_on_batch_plot_export()`
- `src/flowdesk_qt/batch_plot_export_dialog.py`
- main-window status-bar and shutdown handling

Tests and benchmarks:

- `tests/test_pipeline_runner.py`
- `tests/test_project_headless_execution.py`
- `tests/test_interactive_preview.py`
- `tests/test_batch_plot_export.py`
- `tests/test_cli_batch_plot.py`
- `tests/gui/test_batch_plot_export_dialog.py`
- `tests/gui/test_gui_workflow.py`
- `tests/test_qt_plot_widget.py` only where worker shutdown is already tested
- existing files under `benchmarks/` and `src/flowdesk_core/vector_scatter_benchmark.py`

## Baseline implementation facts before Increments 1–3 (historical)

- Before Increment 2, `ProcessedDisplayScheduler` and `PreviewScheduler` defined a one-worker `QThreadPool`,
  immutable request snapshots, debounce/coalescing, and latest-wins result acceptance.
  However, `MainWindow._queue_processed_display()` currently calls
  `PipelineRunner.prepare_display_sample()` synchronously and then calls `_replot()`.
  No call to `ProcessedDisplayScheduler.schedule()` exists in the active main-window
  path. Do not describe current sample switching as already off the GUI thread.
- Before Increment 1, density mode in `PlotWidget.plot_events()` first submitted a uniform-color scatter item,
  then `_refresh_density_colors()` calculates density colors, builds per-event brushes,
  and calls `ScatterPlotItem.setData()` a second time. Density estimation, brush
  construction, and pyqtgraph item mutation all currently occur on the GUI thread.
- Before Increment 3, the density cache key used Python array identity. Main-window population/filter
  selection can create new arrays for semantically identical data, so repeated displays
  can miss the cache even when sample, population, axes, transforms, revision, and event
  selection are unchanged.
- `Display max points = 0` sends every selected display event to Qt. This is a supported
  explicit setting, but it disables the display sampling safety valve and can make
  density brush creation and pyqtgraph transfer dominate latency. It must never change
  authoritative counts, gates, statistics, or the full-data density field.
- `MainWindow._PipelineWorker` runs `PipelineRunner.run_samples()` in one background
  `QThread`. The GUI remains responsive, but samples are processed serially and there is
  no structured progress/cancellation contract.
- `PipelineRunner._run_full_pipeline()` performs project-wide compensation-calculation
  preparation before its per-sample loop. A calculated compensation matrix may depend on
  multiple control samples and must not be independently recomputed in concurrent workers.
- `run_batch_plot_export()` now accepts adapter-neutral progress/cancellation controls
  and an explicit preparation provenance record; the default remains sequential.
- `flowdesk_cli.batch_plot.batch_plot_command()` resolves source scope before reading
  FCS files and can prepare required source layers with bounded threads only when the
  CLI explicitly selects the thread backend. Completion results are merged in source
  order before shared-range reduction.
- `shared_ranges` requires a barrier after all required source ranges are known. Overlay
  outputs may share source samples, so output items are not independent during source
  preparation even when their final files are independent.

## Non-goals

- Do not change compensation, derived-parameter, transform, gate, statistic, density, or
  export formulas to obtain speed.
- Do not use display-downsampled events for gate membership, counts, frequencies,
  statistics, QC, or authoritative export.
- Do not split one event array into arbitrary Python thread chunks in the first
  implementation.
- Do not run Qt widgets, `QPainter`, pyqtgraph items, dialogs, or `QPixmap` in a worker
  process or non-GUI thread.
- Do not add concurrent mutation of a shared `ExecutionReport`, list accumulator, project
  dictionary, cache entry, manifest, or output file.
- Do not forcefully terminate `QThread`, Python threads, processes, NumPy calls, or file
  writes.
- Do not make a 10M-event generated dataset or large FCS file part of the repository.
- Do not add an absolute wall-clock assertion to normal CI.
- Do not change the default worker count to “all CPUs” without a measured memory budget.
- Do not silently replace a user's explicit `Display max points = 0` with a finite value.
- Do not mutate a pyqtgraph item, Qt widget, `QBrush`, or other Qt-owned presentation
  object from a worker thread.

## Measured interactive hot-path baseline (2026-07-29)

The following offscreen measurements used the repository's four example FCS files and
the current implementation. They are diagnostic baselines, not CI thresholds:

| File | Events | Density numeric kernel | Uniform plot | Density plot total |
|---|---:|---:|---:|---:|
| `data/1_A1.fcs` | 31,552 | 115.3 ms | 192.4 ms | 328.2 ms |
| `data/5_A2.fcs` | 23,570 | 77.5 ms | 189.2 ms | 325.3 ms |
| `data/9_A3.fcs` | 40,051 | 129.6 ms | 189.7 ms | 329.7 ms |
| `data/13_A4.fcs` | 23,583 | 77.2 ms | 190.5 ms | 327.8 ms |

A minimal project without the complete real project gate/statistic graph measured:

| File | FCS load | Minimal display preparation |
|---|---:|---:|
| `data/1_A1.fcs` | 7.5 ms | 3.8 ms |
| `data/5_A2.fcs` | 4.6 ms | 1.4 ms |
| `data/9_A3.fcs` | 3.9 ms | 2.7 ms |
| `data/13_A4.fcs` | 5.0 ms | 0.5 ms |

Interpretation:

- for these files, visible density latency is dominated by density estimation plus Qt
  scatter construction/transfer, not the minimal canonical display preparation;
- the density path currently pays for an unnecessary uniform scatter submission before
  the final density submission;
- the minimal preparation measurement does not prove that a real project with
  compensation, derived parameters, gates, and statistics is equally cheap, so retain
  stage timing around the canonical request;
- record commands, environment, event counts, warm/cold-cache state, and medians in any
  follow-up benchmark artifact. Do not treat the values above as portable performance
  promises.

## Interactive optimization order

Use this order unless new profiling evidence contradicts it:

1. remove the redundant uniform `setData()` in density mode and establish a focused
   render-call/per-stage benchmark;
2. route processed-display cache misses through the existing scheduler with latest-wins,
   revision validation, error handling, and clean shutdown;
3. calculate renderer-neutral density arrays outside the GUI thread, use a semantic
   density cache, and minimize the final GUI-thread Qt payload;
4. profile per-event brush construction/transfer and optimize its representation only
   after result/color parity is locked down;
5. retain a finite default display maximum for new/default configurations and clearly
   report the performance implication when a user explicitly selects all events;
6. consider event-chunk parallelism only if a remaining pure kernel dominates after the
   preceding changes.

Density computation may use fixed-bin chunk accumulation only after its mathematical
contract is defined. Chunks may accumulate integer histograms independently, but the
histograms must be summed before one global smoothing and one global normalization step.
Query-point color lookup can then be partitioned because each lookup is independent.
Chunk-local normalization, smoothing, or colormap scaling is prohibited because it
changes colors at chunk boundaries and breaks whole-population comparability.

## Why event-chunk parallelism is not the first step

The proposal in `docs/bug.md` to divide one dot population into `n` groups is suitable
only for a pure, independently mergeable kernel. The current display request may include:

- compensation matrix application;
- derived-parameter dependency order and failure policy;
- transforms;
- hierarchical/Boolean/automatic gate evaluation;
- full-population statistics;
- display sampling;
- density normalization based on the complete selected population.

Several of these operations require global reductions, parent membership, fitted
parameters, or deterministic selection across the complete population. NumPy already
executes many pointwise kernels in compiled code and may release the GIL. Python chunking
can therefore increase copies, temporary arrays, scheduler overhead, and BLAS
oversubscription without reducing latency.

Keep one interactive sample as one scheduler job. First measure stage timings and remove
redundant recomputation through the existing processed-display cache. Only propose a
chunked kernel later when all of the following are demonstrated:

1. profiling identifies one pure pointwise kernel as the dominant cost;
2. chunk boundaries cannot change invalid-value policy, gate boundary inclusion,
   density normalization, display sampling, or result order;
3. merging is mathematically specified and tested against the unchunked result;
4. peak memory, not only elapsed time, improves or remains within budget;
5. the same optimization is in core and is usable headlessly.

Interactive improvement may later include bounded, low-priority prefetch of the next
sample only after the active request finishes. Prefetch must be cancelable, must not delay
the active request, and must obey the same cache and memory budget.

## Decision record: why active-sample display is not sample-parallel (2026-07-30)

The main-window plot request processes the selected sample only.  It does **not** run,
wait for, or merge the other project samples before displaying that plot.  Sample-level
threads therefore reduce elapsed time for authoritative multi-sample `Run Pipeline`, but
do not directly reduce the latency of selecting one sample in the main window.

For a selected sample, the likely visible-cost stages are processed-display preparation,
density histogram/smoothing/global normalization, per-event colour/brush creation,
payload transfer to pyqtgraph, and GUI-thread drawing.  The fact that a colour is finally
assigned to each point does not make the density algorithm an arbitrary independent
event operation: its result depends on a density field computed from the complete selected
display population.  Qt and pyqtgraph presentation objects also have GUI-thread affinity.

Apply the following decision table before proposing concurrency:

| Candidate | Initial decision | Required proof before implementation |
|---|---|---|
| Reuse an unchanged semantic display/density result | Implement first | Cold and warm paths have identical events, colours, point order, labels, gates, and interaction state. |
| Remove repeated Qt payload transfer or reduce its representation | Implement after profiling | Rare colours, alpha, draw order, selection, and hit testing remain equivalent. |
| Renderer-neutral density calculation in one owned worker | Deferred until lifecycle coverage exists | Worker owns only NumPy arrays; GUI thread creates `QBrush`/pyqtgraph objects; stale generation is discarded; close/shutdown is safe. |
| Fixed-bin density histogram chunks | Deferred | Sum integer chunk histograms first, then perform exactly one global smoothing, normalization, and colour mapping; result equals unchunked across chunk sizes/workers and stays within the memory budget. |
| Arbitrary Python-thread event chunks for display or analysis | Do not implement initially | A profile identifies a dominant pure kernel and mathematical merge, invalid-value, sampling, parent/Boolean/automatic-gate, ordering, raw-immutability, memory, and headless parity tests all pass. |

NumPy may already release the GIL for suitable kernels, but extra Python scheduling,
temporary arrays, memory bandwidth pressure, and native-library inner threads can still
make a threaded version slower.  Measure numerical computation, Qt payload transfer, and
paint time separately.  Never claim a GUI rendering improvement from an authoritative
pipeline benchmark, or vice versa.

## Decision record: active-sample display and optimization order (2026-07-29)

Selecting a sample in the main window is an interactive request for that active sample;
it is not a request to first process the other samples in the project.  The selected
sample's display may use already-derived project definitions and caches, but it must not
wait for a project-wide `Run Pipeline` merely to populate the plot.  Its latency is
therefore governed by the active request's display preparation, density calculation,
per-event presentation payload, and Qt/pyqtgraph drawing.

The canonical processed-display cache is a bounded GUI presentation cache: it keeps
the four most-recent entries subject to an estimated 256 MiB NumPy payload budget,
promotes entries on a hit, and removes entries for deleted/reconnected samples or
project replacement. Eviction only causes a later cache miss and re-execution of the
same immutable `ProcessedDisplayRequest`; it never changes authoritative counts,
membership, statistics, or raw events.

Raw FCS acquisition is also separated from the GUI event loop for files at least 4 MiB:
`SampleLoadScheduler` owns one `QThreadPool` worker, keeps only the newest pending sample,
and emits immutable `SampleData`/error results back to the GUI thread. A result is adopted
only if its sample still exists; a stale selection is cached but never replotted. Shutdown
waits for the worker. Small files retain the synchronous path to avoid scheduler overhead
for trivial fixtures. This is input acquisition only; compensation, derived parameters,
transforms, gates, and statistics still run through the canonical Qt-independent runner.

This distinction determines the execution boundaries:

| Operation | First optimization boundary | Not an initial optimization |
|---|---|---|
| Main-window sample switch | One active sample, latest-wins scheduler, semantic cache, renderer-neutral density data, reduced Qt payload | Running unrelated samples; arbitrary event chunks |
| Authoritative Run Pipeline | Independent complete sample results after shared planning, then deterministic coordinator merge | Parallel mutation of the report/project/cache |
| Batch Plot Export | Explicit source-dependency preparation, then independent prepared output items | Concurrent access to shared source/range state or final paths |

Accordingly, the implementation priority is:

1. Finish the remaining interactive hot-path work in Increment 3: reuse a
   whole-population, viewport-independent density field; complete semantic-cache
   invalidation coverage; measure and reduce per-event Qt payload; and test rapid
   pan/zoom/sample switch and shutdown.  If an owned worker array cannot be transferred
   safely with a reproducible lifecycle test, retain the safe scheduler/cache path and
   do not introduce an unsafe background NumPy implementation.
2. Complete Increment 6 sequential Batch Plot Export phase separation, progress,
   cooperative cancellation, and atomic staging.  This creates measurable source/render
   stages and a deterministic baseline before export workers exist.
3. Complete Increment 7's immutable `SampleExecutionResult` and coordinator merge, then
   Increment 8's bounded sample-level pipeline workers with memory budgeting and exact
   sequential-parallel parity tests.
4. Consider Increment 9 batch-render workers, Increment 10 prefetch, and Increment 11
   fixed-bin density histogram chunks only after the preceding measurements demonstrate
   material benefit.

"More CPU cores" is not sufficient evidence to reorder these steps.  Every optimization
must retain raw-event immutability and must prove that counts, frequencies, memberships,
statistics, display sampling behavior, scene/source order, and cancellation semantics are
unchanged at its stated boundary.

## Common runtime control contract

Add Qt-independent runtime types in a focused core module such as
`flowdesk_core.execution_control`. Names may be adjusted to existing conventions, but
the following concepts are required.

```text
ExecutionOptions
  backend: sequential | thread
  max_workers: positive integer
  memory_budget_bytes: positive integer or None

CancellationToken
  is_cancelled() -> bool
  raise_if_cancelled() -> None

ProgressEvent
  operation_id
  operation: pipeline | batch_plot_export | display_prefetch
  phase
  completed_units
  total_units
  sample_id (optional)
  output_path (optional)
  message

ExecutionControl
  options
  cancellation token
  progress sink/callback
```

These are runtime controls, not scientific project definitions. Do not serialize a
callback, thread event, process handle, or Qt object into `.flowdesk`. Record only the
resolved backend, effective worker count, memory budget, software version, and relevant
benchmark/provenance fields in the final report/manifest.

Contract details:

- `completed_units` is monotonic and never exceeds `total_units`.
- The planner determines `total_units` before execution whenever possible.
- A progress sink receives immutable events on the coordinator/runner thread. Worker
  threads return structured results to the coordinator; they do not call Qt.
- Progress callback failures are adapter/programming errors and must not be converted
  into successful scientific execution.
- Cancellation is cooperative. Check before starting a sample/item and between canonical
  stages or output formats. Do not interrupt a numeric kernel or file replacement halfway.
- Existing calls without `ExecutionControl` retain sequential behavior and API
  compatibility.
- A cancelled authoritative pipeline does not return an adoptable partial
  `ExecutionReport`. Raise a typed cancellation outcome or return a report contract that
  contains no authoritative partial results. The GUI keeps the previous authoritative
  report and marks it stale.
- A cancelled batch export may retain already completed output files. Its manifest must
  list `success`, `failed`, `cancelled`, and `not_started` items explicitly and use overall
  status `cancelled` or `partial_cancelled`; it must never report success.

Recommended pipeline phases:

```text
planning
compensation_controls
sample_compensation
sample_derived
sample_transform
sample_gating
sample_statistics
qc
finalizing
```

Recommended batch phases:

```text
planning
loading_sources
preparing_sources
resolving_shared_ranges
rendering
writing_sidecars
finalizing_manifest
```

Do not promise a percentage for work that has not been assigned measurable units. The GUI
may show an indeterminate progress bar during project-wide planning and switch to a
determinate sample/item count afterward.

## Pipeline sample-level parallelism design

### Required refactor

Refactor the body of the current per-sample loop into a GUI-independent function/method
that accepts only immutable/read-only inputs and returns one complete result object, for
example:

```text
SampleExecutionResult
  sample_id
  project_order
  input_file
  population_results
  population_membership
  statistic_results
  diagnostics
  messages
  auto/magnetic/tethered fit records
  status
```

The worker must not append to the runner's shared lists. The coordinator alone merges
completed results.

Run these operations serially before worker submission:

- execution-profile and selected-sample resolution;
- Group/strategy/statistic assignment;
- derived-parameter planning;
- compensation-control calculation and creation of shared calculated matrices;
- validation of stable IDs and immutable execution snapshot;
- conservative per-sample memory estimate.

Submit only the independent per-sample canonical stage sequence after shared calculated
matrices are complete. After workers finish, merge every tuple, diagnostic, message, and
fit record in deterministic project sample order, not future-completion order. Run
cross-sample/group QC after the merge.

### Thread backend first

Implement `sequential` and bounded `thread` backends first:

- threads can share immutable NumPy input arrays without pickling/copying them;
- many NumPy kernels release the GIL;
- the existing GUI already executes the coordinator outside the GUI thread;
- the same backend remains available to CLI and Python API without Qt.

Do not assume threads are faster. Benchmark representative pipelines. Record outer worker
count and relevant BLAS/OpenMP thread settings to detect oversubscription.

### Process backend decision gate

Do not add `ProcessPoolExecutor` in the same increment as thread parallelism. Add it only
if profiling shows material GIL-bound work and the following design is completed:

- use a top-level picklable worker entry point compatible with Windows `spawn`;
- do not pickle multi-million-event arrays per task as the normal path;
- prefer file-backed/path-based worker input or documented shared-memory ownership;
- reconstruct a read-only project snapshot inside each process;
- bound aggregate resident memory and temporary arrays;
- propagate structured exceptions/diagnostics without traceback-only UI;
- shut down cleanly in PyInstaller packages on Linux, macOS, and Windows;
- prove output identity with sequential/thread execution.

If these criteria are not met, document the benchmark and retain the thread backend.

### Memory budget and worker count

The effective worker count is not simply `os.cpu_count()`. Resolve it conservatively from:

```text
requested max_workers
selected sample count
available logical CPUs
memory budget
estimated in-flight bytes per sample
numeric-library inner thread count
```

Add a tested estimator based on source event bytes plus documented stage multipliers for
compensated, derived, transformed, membership, and temporary arrays. Calibrate the
multiplier with benchmark measurements. If a single sample exceeds the budget, either run
one sample with an explicit warning or fail according to a documented runtime policy.
Never start extra workers and rely on swapping.

## Batch export dependency and parallelism design

### Why the worker unit is not simply one FCS file

An FCS file is a source/dependency unit, not necessarily an executable render job. A
naive “one FCS per thread” implementation is correct only for the narrow case where an
output has one prepared sample source, no overlay dependency, no unresolved shared range,
and no mutable renderer state. Batch definitions can violate that assumption:

- one overlay output depends on multiple FCS sources in a fixed source order;
- `shared_ranges` requires a deterministic reduction across all participating sources;
- one FCS source can produce several views and PNG/JPEG/SVG/PDF outputs;
- several outputs may reuse the same transformed/downsampled/density arrays;
- manifest order, collision policy, cancellation, and partial failure are properties of
  the planned output set rather than of an individual FCS file.

Therefore use two distinct boundaries:

1. **Source preparation boundary**: load each required FCS source once per compatible
   cache key, calculate immutable renderer-neutral prepared data, and resolve every
   cross-source dependency and shared range.
2. **Render execution boundary**: submit only a dependency-complete immutable prepared
   output item to the bounded executor. A worker must not discover or mutate another
   sample's source, range, cache entry, output path, or manifest state.

For the simple non-overlay case, preparation of one sample followed by rendering is
independent from other samples and is the first required parallel test case. The CLI
may now run this source-preparation phase with the same explicitly requested bounded
thread backend; preparation results are merged in source order before any shared-range
reduction. Do not let this fast path bypass the same planning, ordering, memory-bound,
and cancellation contracts used by the general path.

The implementation may benchmark grouping all formats for one sample/view into one job
against submitting each format separately. Grouping can reuse prepared arrays and reduce
peak concurrent memory, while per-format jobs provide finer cancellation and load
balancing. Select the unit from measured wall time and peak RSS; do not duplicate prepared
event arrays merely to increase the number of jobs.

### Make preparation explicit

Remove the hidden “prepare every sample on first render callback” behavior from
`flowdesk_cli.batch_plot.batch_plot_command()`. Split execution into explicit phases:

1. build deterministic `BatchPlotExportItem` plans;
2. build a dependency map from each output item to base and overlay source sample IDs;
3. load/prepare each unique source at most once per compatible cache key;
4. resolve `shared_ranges` only after all required ranges are available;
5. build one immutable renderer-neutral scene/input per output item;
6. render each output path;
7. write sidecars and one final manifest.

The source cache key includes sample fingerprint/path identity, population, axes,
transforms, analysis revision, display sampling, density mode/version, and every source
style/range input that changes prepared data. Do not share mutable renderer objects.

Overlay correctness:

- an overlay output depends on all of its source samples;
- source preparation may be shared, but each output keeps its own ordered source list,
  colors, clipping, title, and gate geometry;
- failure of a required overlay source produces the existing structured item failure;
- parallel completion order must not change source order, filenames, title order, colors,
  sidecar data, or manifest order.

`shared_ranges` is a barrier: prepare all required sources, reduce ranges in deterministic
sample order, then render. `current_view` may render once its complete dependency set is
ready.

### Progress before parallel rendering

First add sequential progress/cancellation to the explicit phases. Only then allow bounded
parallel output rendering.

- Plan all unique paths and collisions before starting workers.
- Each worker owns distinct temporary output and sidecar paths.
- Publish a completed file with an atomic same-filesystem replace.
- Only the coordinator writes the batch manifest.
- `collision_policy=replace` applies to planned target paths only and must not delete
  unrelated files.
- On cancellation, finish or safely discard the currently staged file, cancel pending
  futures, wait for active tasks, write the cancellation manifest, and return.

The core/headless renderer may run in workers only after a concurrency test proves it has
no shared mutable global state. Qt/pyqtgraph screenshot or painter backends remain on the
GUI thread and are not candidates for parallel workers. Prefer the existing
renderer-neutral core scene and PNG/JPEG/SVG/PDF writers.

Bound render workers by logical CPUs, measured renderer scaling, estimated immutable
prepared-scene bytes, per-format temporary bytes, and the configured memory budget. Do
not assume that source independence implies renderer thread safety. Profile whether the
writer releases the GIL; if thread workers do not provide a repeatable speedup, keep
sequential rendering as the default. A process backend requires the separate Increment 11
decision because copying/pickling prepared arrays, Windows spawn behavior, cancellation,
and aggregate memory can outweigh its GIL benefit.

## Qt progress and cancellation UI

The GUI adapter runs the synchronous core pipeline or batch runner in an owned worker and
converts core progress events to queued Qt signals. It must never calculate scientific
values or render worker output itself.

For Batch Plot Export, add a modeless or modal progress surface after the definition
dialog is accepted. Minimum controls:

- progress bar;
- `completed / total` text;
- current phase and sample title/ID;
- current output format/path in elided text or details;
- Cancel button;
- expandable failure/diagnostic details;
- final success/partial/cancelled/failed state.

Use stable object names:

```text
batchPlotProgressDialog
batchPlotProgressBar
batchPlotProgressSummary
batchPlotProgressCurrentItem
batchPlotProgressCancelButton
batchPlotProgressDetails
```

Also update the main status surface with short messages such as
`Batch export: 3/12 (A3, PNG)`. Do not show a completion message until the manifest has
been finalized.

For `Run Pipeline`, expose at least phase, sample count, and cancel. A cancelled run keeps
the previous Results report, marks it stale, resumes the preview scheduler, and never
labels partial values current.

Worker lifecycle:

- disable duplicate Run/Export actions while the same operation is active;
- clicking Cancel requests cooperative cancellation and changes text to `Cancelling…`;
- project/window close requests cancellation and waits for owned workers without
  force-termination;
- late signals after project replacement/window close are ignored;
- no `QThread: Destroyed while thread is still running` warning is acceptable;
- tests wait on signals/event-loop state, not fixed sleep.

## Benchmark and decision protocol

Add an opt-in benchmark harness using deterministic synthetic profiles:

| Profile | Events per sample | Suggested samples | Purpose |
|---|---:|---:|---|
| small | 100,000 | 8 | scheduler overhead and GUI responsiveness |
| medium | 1,000,000 | 8 | realistic sample-level speedup/memory |
| large | 10,000,000 | 2–4 | memory-budget and cancellation behavior |

Record:

- random seed, sample/channel count, population proportions and expected counts;
- OS, Python, NumPy, Qt, CPU model/logical CPUs;
- worker backend/count and BLAS/OpenMP thread settings;
- per-stage and total wall time;
- peak RSS and estimated in-flight memory;
- serial and parallel result hashes/counts;
- code revision.

Benchmark display preparation, authoritative analysis, source preparation, and rendering
separately. Do not claim analysis speedup from a rendering benchmark.

Do not enable parallelism by default until repeated same-machine measurements show a
useful median speedup on the target workload and no unacceptable memory increase. A
suggested review gate is at least 1.25× median multi-sample speedup with peak RSS within
the configured budget, but this is a release decision, not a normal CI assertion. If the
gate is not met, keep sequential as the default and retain progress/cancellation.

## Target files

The exact split may follow existing module conventions, but ownership must remain:

Core:

- new `src/flowdesk_core/execution_control.py` (or equivalently focused module) for
  Qt-independent runtime options, progress, cancellation, and effective-worker policy;
- `src/flowdesk_core/execution_context.py` for compatible runtime-control attachment only;
- `src/flowdesk_core/execution_report.py` for resolved execution provenance, without
  serializing callbacks/tokens;
- `src/flowdesk_core/pipeline_runner.py` for project-wide planning, pure per-sample
  execution, deterministic coordination, and cross-sample finalization;
- `src/flowdesk_core/batch_plot_export.py` for explicit batch plans, progress/cancel,
  atomic output publication, item statuses, and final manifest coordination.

CLI:

- `src/flowdesk_cli/run_project.py` for runtime options, progress text, cancellation exit
  semantics, and no second runner;
- `src/flowdesk_cli/batch_plot.py` for explicit source preparation/scene tasks and the
  common batch runner adapter;
- `src/flowdesk_cli/main.py` only when public CLI flags are introduced.

Qt:

- `src/flowdesk_qt/main_window.py` for action lifecycle and applying completed reports;
- `src/flowdesk_qt/plot_widget.py` for the single-submit density path and GUI-thread-only
  pyqtgraph mutation;
- `src/flowdesk_qt/processed_display_scheduler.py` in the interactive scheduling
  increment, preserving latest-wins/revision/shutdown behavior;
- a focused new worker/controller module rather than expanding scientific logic in
  `main_window.py`;
- a focused progress widget/dialog module for stable object names and terminal states;
- `src/flowdesk_qt/preview_scheduler.py` only if shared lifecycle code is extracted
  without changing latest-wins behavior.

Tests and benchmark artifacts:

- `tests/test_execution_control.py` (new);
- `tests/test_pipeline_runner.py`;
- `tests/test_project_headless_execution.py`;
- `tests/test_batch_plot_export.py`;
- `tests/test_cli.py` and `tests/test_cli_batch_plot.py`;
- focused GUI tests under `tests/gui/`, preferably a new progress/lifecycle file;
- deterministic generator and opt-in runner under `benchmarks/` or `tests/support/`;
- benchmark JSON output under ignored `artifacts/`, never committed generated event data.

Documentation:

- this guide and `ToDo.md` as increments are completed;
- `docs/user-manual/user_manual.md` in the same increment as any user-visible control;
- CLI help/README only when public runtime flags become available.

## Numbered implementation increments

### Increment 1: Remove redundant density submission and measure the hot path — complete

- `PlotWidget.plot_events()` now skips `_plot_uniform_scatter()` when density is active.
  `_refresh_density_colors()` creates the final scatter and submits display data once.
- Uniform single-color and population-color paths remain unchanged. Density mode still
  ignores supplied population/gate colors, as defined by the single-sample contract.
- `test_density_coloring_submits_final_scatter_once` verifies one data-bearing
  `ScatterPlotItem.setData()` call and exact estimator-color/event-array parity. The
  pyqtgraph constructor's empty initialization `setData()` call is deliberately excluded.
- The opt-in command `make benchmark-density` writes a reproducible JSON report with
  density-numeric and total cold-widget timings. On 2026-07-29,
  `tools/benchmark_density_plot.py --points 2200 --repeats 5` measured a 53.9 ms total
  median and 11.1 ms density-numeric median. This is diagnostic evidence only; it is not
  a portable target or CI threshold.

Acceptance: density mode performs one main scatter `setData()` submission per plot,
visible points/order/colors and density normalization are unchanged, and the benchmark
separates numeric from Qt-transfer cost.

### Increment 2: Activate asynchronous processed-display scheduling — complete

- `_queue_processed_display()` now submits the immutable manifest/request snapshot to
  `ProcessedDisplayScheduler`; it no longer invokes `PipelineRunner` on the GUI thread.
  The manual-overlay cache-miss path uses the same submission route.
- Existing one-worker debounce/coalescing, snapshot copying, revision/current-request
  checks, and `closeEvent()` shutdown remain in force. A closed scheduler never falls
  back to synchronous core execution.
- Main-window failure handling now verifies the current sample and complete display key,
  so a late failure from a prior selected sample cannot clear the current plot.
- GUI tests cover scheduler coalescing/snapshot isolation and an intentionally delayed
  A→B→C selection. Only C is adopted, a stale B failure leaves C visible, and teardown
  waits for the worker.

Acceptance: an intentionally delayed display preparation does not block event-loop
interaction; only C is displayed; scientific preview/count state equals the synchronous
core result; no worker remains at shutdown.

### Increment 3: Off-thread density arrays and semantic cache

Status (2026-07-30): the semantic cache key, viewport-invariant logical density
grid, explicit all-event warning, safe GUI-thread reuse path, and an opt-in
latest-wins numeric worker are implemented.
For the same semantic processed-display identity, a gate/label-only replot retains
the resolved density colors and existing `ScatterPlotItem`; it does not send a new
per-event Qt payload.  Repeating an unchanged `PlotItem.setLogMode()` is also
avoided because pyqtgraph otherwise rebuilds existing scatter data.  A dot-size or
opacity change refreshes Qt presentation only and reuses the normalized density
field.  As of 2026-07-30, a size-only change calls `ScatterPlotItem.setSize()` and
an opacity change calls `setBrush()` over the resolved colours; neither path resubmits
the large X/Y payload through `setData()`. In the opt-in 20,000-event/5-repeat offscreen benchmark, cold
`plot_events` median was 216.0 ms and the semantic cached replot median was
1.75 ms; these environment-specific display measurements are not CI thresholds
or analysis speedup claims. A 20,000-event/three-repeat measurement on 2026-07-30
recorded 73.2 ms for the no-coordinate-resubmission size update and 148.6 ms for
the opacity update, compared with 234.8 ms cold `plot_events`. Opacity still requires
one brush per event, so this is presentation-payload evidence, not density-kernel
speedup evidence.

The opacity path now retains the last per-event `QBrush` list keyed by the exact
resolved colour array identity and opacity. Repeated style/label updates therefore
reuse the existing Qt payload; changing opacity creates a fresh list, while changing
only dot size reuses it. Palette grouping is intentionally not used because it could
change draw order and overlap semantics. A 20,000-event/three-repeat diagnostic after
this change measured 134.2 ms median for opacity update on Linux/NumPy 2.5.1; this is
an environment-specific presentation measurement, not a CI threshold.

Main-window density requests now use an owned one-worker `DensityColorScheduler`.
The worker receives read-only NumPy views (copying only writable inputs) and returns only the
renderer-neutral colour result.  `PlotWidget` applies brushes and creates or
mutates `ScatterPlotItem` exclusively on the GUI thread.  A semantic key is used
as the stale-result guard, so a rapid sample/axis/population change cannot apply
an older result.  The scheduler is explicitly shut down by `MainWindow` and
`PlotWidget`; synchronous export calls resolve any pending density result before
painting.  While a cold worker is running, the new density scatter remains blank
until its complete field is ready; this avoids concurrently painting a large
placeholder array and keeps the event loop responsive.  The core estimator
serializes overlapping density kernels because NumPy histogram/convolution
re-entrancy varies across supported native-library builds.

Focused Qt tests cover off-thread colour parity, semantic cache reuse/invalidation,
stale-result discard, rapid replot, and clean completion.  A full Qt-file run still encounters an existing environment-specific
segmentation fault in the unrelated sample-browser test; this is tracked as a
distribution/CI issue and is not used as evidence of density correctness.
The renderer-neutral result, GUI-only brush/item mutation, viewport-independent
semantic reuse, and generation checks therefore satisfy the Increment 3 acceptance
contract. Arbitrary event-chunk workers and process backends remain explicitly out of
scope until the Increment 11 mathematical-merge, memory, cancellation, and packaging
gates are met.
An offscreen diagnostic run with 5,000 events measured about 12.6 ms for the GUI
submission path and about 103 ms until the worker result was painted (Linux,
NumPy 2.5.1); these values are workload/environment evidence, not CI thresholds.

The bounded-grid Gaussian smoothing pass was also optimized without changing the
estimator contract: the previous Python callback per row/column was replaced with a
`sliding_window_view`/`tensordot` contraction.  Edge padding, kernel construction,
axis order, normalization, and returned event order remain unchanged; comparison with
the former convolution loop differed by at most approximately `4e-16` in the smoothed
field.  A 20,000-event, five-repeat diagnostic on Linux/NumPy 2.5.1 measured a
71.9 ms median for the numeric density phase.  This is a local diagnostic, not a CI
performance threshold or an analytical speedup claim.

- Split density work into a renderer-neutral numeric result and GUI presentation.
  Numeric histogram/smoothing/normalization/color-index arrays may run in an owned worker;
  `QBrush`, pyqtgraph items, and widget mutation remain on the GUI thread.
- Replace object-identity cache keys with a semantic immutable key including analysis and
  display revision, sample/population identity, axes, transforms/ranges as required by
  the algorithm, selected-event/display-sample identity, density algorithm/version and
  parameters.
- Use latest-wins generation checks so stale pan/zoom/sample results are discarded. Reuse
  a whole-population density field across pan/zoom when the scientific display contract
  says density is viewport invariant.
- Minimize per-event GUI payload after profiling. Any palette-index/grouped-layer
  optimization must preserve draw order, rare colors, alpha, selection, and interaction.
  The currently implemented semantic scatter reuse is the safe first reduction; do not
  claim that it makes a cold all-event scatter inexpensive.
- Keep a finite default display limit for new/default configurations. If the user chooses
  all events, preserve that choice and expose a non-blocking performance status/warning
  rather than silently sampling.

Acceptance: pan/zoom and repeated semantic requests reuse valid work; density colors do
not change merely because the viewport changes; cache invalidates for every relevant
upstream/display change; GUI remains responsive; cached/uncached colors are identical;
stale worker results are discarded; export and shutdown never leave a density worker
or apply Qt objects from a worker thread.

### Increment 4: Benchmark baseline and progress/cancel core types

Status (2026-07-29): `flowdesk_core.pipeline_benchmark` now provides deterministic
small (100k × 8), medium (1M × 8), and large (10M × 2) immutable sample profiles;
`make benchmark-pipeline` writes the opt-in JSON baseline.  The report records its
fixture fingerprint, expected all-events counts, OS/Python/NumPy/PySide6/CPU,
requested/effective workers, peak RSS, and separate fixture/pipeline timing.  It
does not measure display or rendering and must not be cited as a rendering speedup.
`ExecutionOptions`, `ExecutionControl`, `ProgressEvent`, `CancellationToken`, and
`ExecutionCancelled` are Qt-independent runtime-only types.  They are accepted
optionally by `ExecutionContext`, but checkpoints and parallel execution are not
implemented until Increment 5 and Increment 8.  Batch-source timing is still
required before this increment can be marked complete.

- Add deterministic multi-sample generator and opt-in benchmark report.
- Add Qt-independent `ExecutionOptions`, `ExecutionControl`, `ProgressEvent`,
  `CancellationToken`, and typed cancellation outcome.
- Preserve existing sequential calls when no control is supplied.
- Add contract tests for monotonic progress, callback failure, cancellation, and no Qt
  imports.

Acceptance: no pipeline/export algorithm changes; baseline focused tests pass; benchmark
JSON records environment and stage boundaries.

### Increment 5: Sequential pipeline progress and cooperative cancellation

Status (2026-07-29): complete. The core runner emits deterministic checkpoints for
planning, compensation controls, each sample stage, QC, and finalization when
an `ExecutionControl` is supplied.  It checks cancellation before and after
each callback/stage boundary and raises `ExecutionCancelled` without returning
the locally accumulated report.  The CLI adapter maps this outcome to exit code
130.  The Qt worker owns the same control, transfers progress through a
thread-safe queue polled on the GUI thread, displays phase/sample count in the
status bar and `pipelineProgressBar`, and exposes `actionCancelPipeline`.
Cancellation retains the previous Results report and marks it stale. Contract
tests prove unchanged uncancelled results, raw input arrays, CLI cancellation,
and the Qt cancellation lifecycle.

- Add progress checkpoints around project-wide preparation and every sample stage.
- Keep the existing scientific loop sequential.
- Ensure cancellation produces no adoptable partial authoritative report/cache.
- Update CLI exit/status behavior and tests.

Acceptance: uncancelled report equals the previous report; cancelling at controlled
checkpoints leaves raw input and previous authoritative result unchanged.

### Increment 6: Batch export phase refactor and GUI progress

Status (2026-07-30): complete.  The core and CLI execution boundary is implemented.  The CLI's
former first-render side effect is now explicit `prepare_sources()` work: source loading,
canonical display preparation, shared-range resolution, and vector preflight run once
before an output is rendered.  The Qt-independent runner reports planning/preparation,
per-format rendering/sidecar, and final-manifest phases; checks cancellation between
outputs; writes a `cancelled`/`not_started` manifest; and publishes output/sidecar/manifest
through same-directory staged atomic replacement.  The GUI starts the same headless adapter
in an owned `_BatchPlotExportWorker`, transfers core progress through a queue polled on the
GUI thread, and exposes `batchPlotProgressDialog`, `batchPlotProgressBar`,
`batchPlotProgressSummary`, `batchPlotProgressCurrentItem`, `batchPlotProgressCancelButton`,
and `batchPlotProgressDetails`.  Cancel and window close request cooperative cancellation
and wait for the worker; focused GUI tests cover completion, Cancel, and window close.

- Make source preparation and dependency planning explicit.
- Add sequential batch progress, cancellation, cancellation manifest, and atomic staged
  outputs.
- Move GUI invocation off the GUI thread and add the progress surface/object names.
- Keep renderer results identical before introducing parallel rendering.

Acceptance: every completed sample advances progress; Cancel is responsive between
items/formats; GUI remains responsive; sequential output hashes/scene metadata remain
equal; worker teardown is clean.

### Increment 7: Pure per-sample pipeline result and deterministic merge

Status (2026-07-30): complete.  `SampleExecutionResult` now contains all report-ready
values for one sample—input-file provenance, population results/masks, statistics,
diagnostics/messages, automatic/magnetic/tethered fits, and status.  Shared group,
statistic, derived-plan, and calculated-compensation preparation remain before this
boundary.  The sequential coordinator is the only code that merges results, always sorted
by project order, before cross-sample QC.  An adversarial reverse-order merge test proves
that input provenance, messages, fits, and failed-sample status do not follow completion
order.  This increment intentionally does not create any parallel worker.

- Extract one immutable per-sample execution function/result.
- Keep the coordinator sequential initially.
- Move cross-sample calculations before/after the worker boundary as specified.
- Add adversarial completion-order tests using a fake executor.

Acceptance: merged report tuple ordering, messages, diagnostics, fits, counts, masks, and
statistics equal the original serial implementation.

### Increment 8: Bounded thread sample-level pipeline parallelism

Status (2026-07-30): complete. `ExecutionOptions` remains runtime-only and defaults to
the compatible sequential backend.  An explicit `thread` backend runs only complete,
immutable `SampleExecutionResult` jobs after the serial shared preparation barrier.
`ExecutionResolution` bounds requested workers by selected samples, logical CPUs, an
optional memory budget, conservative worst-sample in-flight bytes, and declared
OpenMP/BLAS/NumExpr inner-thread environment settings; it never enables all CPUs by
default.  The full resolution is recorded in `ExecutionReport.execution_provenance`.

### Decision record: why independent FCS files do not imply one-thread-per-file

Batch export has a useful independence boundary, but it is narrower than the input-file
boundary. After target/group selection, overlay-source resolution, shared-range reduction,
compensation/derived/transform preparation, density normalization, and vector preflight
have completed, an immutable prepared `(sample, view, format bundle)` can be rendered
independently. This is the boundary used by the opt-in bounded thread backend.

Do not submit one unrestricted task per FCS file. Doing so would duplicate shared
preparation, increase peak event-array and temporary-array memory, and may concurrently
touch non-reentrant renderer state, Qt/pyqtgraph objects, shared caches, or final output
paths. The coordinator therefore owns dependency planning, shared reductions, cache
lifetime, deterministic manifest order, staged/atomic replacement, cancellation, and
failure aggregation. Workers receive only immutable prepared data and return isolated
format bytes/metadata. A format bundle reuses its prepared scene and colour mapping so
PNG, SVG, and PDF do not reload or transform the same FCS independently.

This backend remains CLI opt-in and GUI export remains sequential until representative
compensation/derived/gating FCS measurements demonstrate acceptable wall time, peak RSS,
open-file count, writer reentrancy, and Windows/PyInstaller shutdown behavior. The
backend must never be reused for active-sample GUI switching: that request concerns one
selected sample and has separate latest-wins, Qt-thread-affinity, and density-cache
constraints.

Workers keep the shared cancellation token but suppress progress callbacks.  The
coordinator submits at most the resolved worker count, publishes monotonic queued/completed
events, cancels unstarted futures on an error/cancellation path, and waits for active
workers before returning or raising.  Shared report mutation, deterministic project-order
merge, cross-sample QC, and final report construction remain coordinator work.  Existing
sample failure policy is unchanged: a non-recoverable sample exception aborts the
authoritative report, while the existing recoverable derived-parameter policy returns a
`failed_sample` result for deterministic merge.

The opt-in small benchmark on 2026-07-30 (100,000 events × 8, fallback-root
population, one repeat) measured 3.37 ms sequential and 4.65 ms with two thread
workers; the scientific report hashes matched.  This deliberately lightweight
workload does not demonstrate a speedup, so the default remains sequential.
Repeat the benchmark with representative compensation, derived-parameter, and
gating workloads before exposing or recommending a thread setting to users.

The headless CLI exposes the runtime-only opt-in as `flowdesk run
--execution-backend thread --max-workers N [--memory-budget-mib M]`.  These flags create
an `ExecutionOptions` value for that invocation; they do not alter or serialize the
project.  The CLI prints the report's resolved backend and effective/requested worker
count after a full pipeline run.  No GUI preference is added in this increment: interactive
sample display remains a separate one-sample scheduler/cache problem, and GUI `Run
Pipeline` remains conservative until representative benchmark evidence justifies exposing
the option there.

- Add explicit sequential/thread executor selection without project serialization.
- Estimate canonical per-sample array and membership memory before submission.
- Bound and record effective workers; retain coordinator-owned cancellation/progress.
- Test resolution limits, workers 1/2/N parity for gating/statistics/masks/order/raw input,
  and cancellation while an active worker is waiting at a safe checkpoint.

Acceptance: worker counts 1, 2, and N return identical ordered reports; failures and
cancellation are deterministic; measured benchmark and peak memory are reported.

### Increment 9: Bounded batch rendering parallelism

Status (2026-07-30): bounded executors are implemented. The runtime resolves target
and overlay dependencies in the coordinator, optionally prepares independent required
sources with bounded threads, merges them in source order, then resolves shared ranges
and optionally renders one sample/view format bundle per thread after an immutable
prepared-data barrier. Both thread phases require `--execution-backend thread`; the
default and GUI execution remain sequential. Preparation and render worker resolutions
are written to the batch manifest, and staged output,
sidecar, plan-order manifest, cooperative cancellation, and memory-bound resolution
are retained. The real core PNG/SVG/PDF writer parity test and a CLI overlay plus
`shared_ranges` thread test now cover concurrent writer use. The diagnostic benchmark
`python tools/benchmark_batch_plot.py --samples 8 --events 5000 --max-workers 2`
measured 1.833 s sequential versus 1.580 s thread/2 (1.16x) with identical
18,317,448 output bytes on 2026-07-30. This uses prepared synthetic layers, not a
full compensation/derived/gating FCS workload; repeat representative measurements
before recommending this backend or enabling it by default.

The CLI preparation path now resolves the batch target and overlay dependency map
before reading FCS files. An explicit or group target prepares only its target samples
and required overlay sources; unrelated samples are not loaded or transformed. A
`shared_ranges` reduction still includes every required source, while vector preflight
uses the maximum event count of one planned output item rather than summing unrelated
batch items. This source-scope optimization is covered by a group/overlay test and
must preserve the existing unknown-source validation.

The real `data/analysis.flowdesk` workload was rerun after enabling source-preparation
threads: sequential took 22.03 s / 289,888 KB peak RSS, while thread/2 took 24.90 s /
489,036 KB. Preparation itself took about 0.04 s and rendering 24.56 s in the threaded
run; all eight PNG/PDF SHA-256 values matched. This validates parity and bounded
execution provenance, but does not support enabling threads by default.

The `shared_ranges` reduction now computes global extrema from each prepared source's
min/max values instead of concatenating all event arrays into another temporary array.
This preserves the exact range contract while lowering peak preparation memory for
large overlays. It does not change density input, event order, or rendered coordinates.

The CLI now builds an explicit base-sample to overlay-source dependency graph once
before source preparation. Visible advanced and manual overlay sources are ordered,
deduplicated, and reused by every target render; render callbacks no longer rebuild
that dependency list. Unknown source validation remains in the planning layer, and
the graph is display-only state: it does not alter population membership or source
colors. A regression test covers order, duplicate removal, and hidden-source exclusion.

Prepared render bundles are item-scoped. Successful PNG/JPEG/SVG/PDF formats reuse the
same scene, normalized layers, event colors, and vector cache until the final format;
any writer failure releases that bundle immediately. If cooperative cancellation stops
before a later format callback, the coordinator clears all remaining bundles after its
workers have joined. This bounds transient cache retention without changing output order
or format parity.

The normalized coordinate and event-color caches store read-only NumPy arrays rather
than expanding values into Python tuples. This reduces object overhead while retaining
the same sequence contract for every writer; vector adapters still build their own
immutable point plan when required. The retained-byte estimator uses NumPy `nbytes` and
continues to include visibility masks and event colors. A real four-sample PNG/PDF run
produced the same eight SHA-256 values; 21.82 s / 286,008 KB peak RSS was comparable to
the prior 21.96 s / 284,388 KB baseline, so the change is a memory-pressure reduction,
not evidence for enabling more workers.

Source preparation no longer creates unused `raw_x`/`raw_y` copies or stores them in
layer metadata. All downstream scene, gate, tick, and writer paths consume the prepared
transformed layer directly. The real four-sample run remained byte-identical and measured
21.97 s / 286,408 KB peak RSS; this is a working-set reduction, not a reason to change
the sequential default.

When the same source appears in multiple target scenes, the CLI reuses its normalized
coordinates, visibility mask, and event-color order keyed by `(source_id, actual_bounds)`.
This applies to both `shared_ranges` and `current_view`: targets with different persisted
view ranges receive separate entries, while identical ranges reuse the immutable layer.
The cache is renderer-neutral and is released with the batch operation; it does not share
mutable Qt objects or alter source order.

Gate geometry is cached in the same coordinator-owned lifetime using
`(x_parameter, y_parameter, actual_bounds, x_transform, y_transform, outline_color)`.
Targets with identical geometry reuse the immutable overlay tuple; different ranges or
styles produce separate entries. This removes repeated polygon clipping and transform
work without sharing mutable Qt objects or changing gate order.

The same coordinator lifetime now caches normalized axis ticks by axis, bounds, transform,
and tick policy. `current_view` targets with different ranges receive independent tick
tuples, while identical ranges avoid repeated transform tick generation. The cached scene
values are renderer-neutral and are released with the export operation.

The export coordinator also precomputes immutable sample lookup, manual overlay-color,
and overlay-style maps. Render callbacks reuse these maps instead of rebuilding a sample
dictionary or linearly scanning persisted overlay definitions for every source layer.
This is a planning/render overhead optimization only; source order and style precedence
remain the persisted first-match order.

Persisted presentation source styles are also indexed once by source ID. Each render
copies only the styles for its ordered source list before applying manual-color and
overlay-style overrides, preserving the existing precedence while avoiding a full style
list scan for every target.

The normalized-layer cache is an LRU bounded to `min(256, 4 * required_source_count)`
entries (with a minimum of one) and an estimated 128 MiB payload budget. A single
payload above the byte budget is not cached. This prevents many distinct `current_view`
bounds or one huge source from retaining unbounded tuple copies of event coordinates.
Eviction affects only renderer cache data; a later miss recomputes the same normalized
coordinates from immutable prepared layers and cannot affect scientific results or output
ordering. The byte estimate is a conservative diagnostic guard, not an OS RSS guarantee.

The Batch Export adapter now estimates memory per prepared output item rather
than using only the largest single source array. The estimate includes unique
overlay source arrays, normalized coordinate/mask copies, per-event colors,
vector representation overhead, and the hybrid scatter RGBA/provenance working
set. It is used only to reduce the resolved worker count under an explicit
memory budget; it does not reject a scientific export or alter display-event
selection. The estimate remains conservative and must be rechecked against
peak RSS for large compensation/derived/gating workloads.

Within one sample/view format bundle, the CLI now caches the immutable prepared scene,
normalized layers, and event-color mapping between formats. The cache is protected for
thread callbacks and is released after the bundle's last format, so it does not become
a batch-wide event-array cache. A regression test verifies that a two-format item calls
scene preparation once and that the real writers remain byte-identical.

For SVG/PDF vector modes, the same bundle additionally reuses an immutable
VectorRenderCache. It contains the normalized vector layer plan, compact compound
paths when applicable, and the hybrid scatter PNG bytes when hybrid_raster is selected.
The cache is built lazily only for compact/hybrid output, so the full-vector path does
not pay a new preparation cost. Writers still receive the same ordered layer input and
produce the same bytes; this optimization only removes repeated format-adapter work.
The cache is sample-scoped and is released with the existing format-bundle cache.

An actual local FCS comparison on 2026-07-30 used `data/analysis.flowdesk` (4 samples,
`max_points=0`, PNG/PDF, DPI 300, hybrid raster): sequential took 22.63 s with a
270,084 KB maximum RSS, while thread/2 took 21.43 s with a 483,888 KB maximum RSS.
All eight PNG/PDF output hashes and sizes matched exactly. The measured speedup was
only 1.06x while peak RSS was about 1.8x, and this project does not exercise a full
compensation/derived-parameter workload. Keep thread rendering opt-in and repeat the
measurement after any renderer or source-preparation change.

After the format-bundle payload cache was added, the same comparison measured 22.24 s
sequential and 21.21 s thread/2, with maximum RSS 269,668 KB and 483,876 KB respectively.
The eight output hashes still matched. The small timing difference is not a stable
speedup claim, while the memory multiplier remains material.

The subsequent VectorRenderCache change was checked again on the same project:
sequential 21.96 s / 284,388 KB and thread/2 23.09 s / 497,968 KB. The eight PNG/PDF
hashes remained identical. This confirms correctness and removes repeated vector
preparation, but does not justify enabling thread rendering by default.

The bounded executor now also has regression coverage for threaded cancellation: each
worker owns a unique staged output/sidecar, successful staged files are atomically
published, pending work is marked `not_started`, and the final manifest remains in
plan order.  The real PNG/SVG/PDF writer parity test exercises concurrent calls into
the headless renderer without Qt objects; matching bytes and sidecars are the
reentrancy evidence currently available.  A full representative compensation/
derived/gating profile and Windows/PyInstaller run remain deployment gates.

The worker-count profile was repeated with tools/benchmark_batch_plot.py at
8 samples × 5,000 events, compact-vector output, and worker counts 1/2/4.
Thread/2 reached 0.965× sequential speed with peak RSS about 1.38×; thread/4
reached 0.686× with peak RSS about 1.95×. Open-file count remained 4 after each
run. These measurements reinforce the sequential default and CLI opt-in policy;
they are diagnostic rather than CI timing thresholds.

`tools/benchmark_batch_plot.py` now records standard-library peak RSS and, on Linux,
the open-file count after each run.  These are diagnostic fields (the RSS value is
process-lifetime `ru_maxrss` and therefore should be compared using separate benchmark
processes; unsupported platforms report `null`), not CI thresholds.  They make memory
and descriptor leaks visible while the renderer backend remains opt-in.

The batch manifest now records the actual execution unit (`prepared_output_item`),
planned/submitted/completed item counts, and `peak_in_flight_items`.  These values are
runtime telemetry, not scientific settings; they make the bounded-worker and cancellation
behavior auditable without inferring concurrency from wall time alone.  Regression tests
assert that the observed peak never exceeds the resolved worker limit.

It also records `execution.phase_wall_seconds` for `planning`, `preparation`, `render`,
and `total`. These are coordinator wall-clock measurements: `render` is the elapsed
interval containing all bounded workers, not the sum of worker CPU times. They are
diagnostic provenance only and must not be used to claim analytical pipeline speedup.

- Treat the FCS file as a dependency source, not automatically as one executor job.
- Submit only dependency-complete immutable prepared output items; begin parity testing
  with non-overlay, one-source outputs.
- Benchmark per-format jobs against one sample/view format bundle for reuse, cancellation
  granularity, wall time, and peak RSS.
- Verify core renderer reentrancy before enabling workers.
- Parallelize independent prepared output items with unique staged paths.
- Preserve dependency barriers, item/manifest order, strictness and collision policies.
- Add shared-overlay-source and `shared_ranges` tests.

Acceptance: sequential and parallel PNG/SVG/PDF scene/sidecar content is equivalent;
failures/cancellation cannot corrupt successful or unrelated outputs; worker bounds include
prepared-scene and format-temporary memory; the selected thread job unit demonstrates
repeatable benefit on a documented representative batch workload. The current synthetic
writer benchmark is diagnostic only and does not satisfy the representative FCS speedup
gate.

### Increment 10: Optional adjacent-sample prefetch

- Status (2026-07-30): a bounded implementation is present. After the active display
  is ready, a 500 ms single-shot timer requests at most one adjacent unread large FCS
  (>=4 MiB) through `SampleLoadScheduler`. A new active selection cancels pending
  prefetch and the loaded prefetch is retained as exactly one non-active raw sample;
  it is reused immediately if selected later. Prefetch completion never calls `replot`
  for the active sample, and scheduler/window shutdown waits for the worker. Requests
  are identified by `(sample_id, path)`, not only by sample ID: reconnecting a sample
  while its previous path is still being read queues the new path, suppresses the
  obsolete completion/failure signal, and adopts only the current file. This prevents
  stale raw events from crossing a reconnect boundary.
- The implementation deliberately does not claim a speedup yet. Representative real-FCS
  latency, peak-memory, cancel, and close measurements remain required; if they show no
  material benefit or unacceptable memory growth, automatic prefetch must be disabled.

Acceptance: current sample is never delayed by prefetch; cached/uncached display arrays
and scientific preview results are identical.

### Increment 11: Event-chunk/process backend decision

- Status (2026-07-30): decision complete; no production event-chunk or process backend
  was added. Density remains a one-worker renderer-neutral estimator because its global
  histogram/smoothing/normalization contract has not demonstrated a chunk speedup or
  memory advantage. Arbitrary Python event chunks remain prohibited.
- The bounded Batch Export diagnostic was repeated at 8 samples × 5,000 events and
  16 samples × 10,000 events with PNG/SVG/PDF compact-vector output. Thread/2 measured
  speed ratios of 0.976 and 0.866 (values below 1 are slower than sequential); thread
  peak RSS was about 1.42× the sequential run in the larger profile. Output bytes and
  manifest status remained identical. This is evidence against enabling more workers
  by default, not a claim about every renderer or workload.
- A real-FCS check was also run against data/analysis.flowdesk (4 samples, PNG/PDF,
  DPI 300). Sequential completed in 22.10 s with 284,840 KB peak RSS; thread/2 took
  23.06 s with 476,864 KB peak RSS (0.96× speed and 1.67× RSS relative to sequential).
  All eight output files had identical bytes and SHA-256 hashes. The check covered
  writer parity and the current project’s overlay/gate path, but not a large
  compensation/derived-parameter workload, renderer reentrancy on every platform,
  or Windows/PyInstaller shutdown.
- A process backend is deferred: Windows `spawn`, event-array transfer/shared-memory,
  memory budgeting, structured cancellation, and PyInstaller cleanup would add a large
  lifecycle surface without measured benefit. The existing CLI opt-in bounded thread
  backend and sequential default remain the supported choices.

Acceptance: no chunk/process backend is merged merely because CPU cores exist. Any
implemented path passes scientific/color parity, memory, cancellation, cleanup, and
Linux/macOS/Windows package tests.

## Required tests

Core:

- sequential execution without controls retains current API behavior;
- progress phases and completed/total values are monotonic and deterministic;
- serial and parallel reports have identical project/profile/status, ordered population
  results, membership masks, statistics, diagnostics, input files, messages, and fit
  records;
- raw `SampleData.events` remains byte-for-byte unchanged;
- display sampling never changes authoritative output;
- compensation-control calculations run once before sample workers;
- cancellation cannot publish partial authoritative results or cache entries;
- memory budget limits active workers.

Batch:

- explicit source preparation occurs once per unique cache key;
- overlay source dependencies and source order are preserved;
- `shared_ranges` waits for all required sources;
- progress accounts for planned failures, formats, completed items, and final manifest;
- serial/parallel filenames, item order, statuses, scene data, sidecars, and manifest are
  deterministic;
- cancellation and renderer failure leave no truncated final file;
- pre-existing unrelated files are unchanged.

GUI:

- density mode submits the main scatter data once and preserves point/color parity;
- processed-display cache misses do not block event-loop interaction;
- rapid sample selection is latest-wins and stale density/display results are discarded;
- semantic density-cache hits preserve colors across viewport-only changes, while every
  relevant analysis/display input invalidates the cache;
- Qt/pyqtgraph objects are created and mutated only on the GUI thread;
- Run Pipeline and Batch Export do not block event-loop interaction;
- progress labels/bar update via queued signals;
- Cancel requests cancellation once and reaches a terminal state;
- previous authoritative Results remain visible/stale after pipeline cancellation;
- close/project replacement leaves no running thread or late widget call;
- stable object names are present and state is not color-only.

## Verification

Run after each increment's focused tests:

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q \
  tests/test_pipeline_runner.py tests/test_project_headless_execution.py \
  tests/test_interactive_preview.py tests/test_batch_plot_export.py \
  tests/test_cli_batch_plot.py
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy \
  src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

Run 1M/10M benchmarks separately and record the command/result artifact. Do not make the
10M profile part of the default test suite.

## Final acceptance criteria

- GUI sample switching remains latest-wins and responsive, with measured cache/latency
  evidence, one main density scatter submission, viewport-stable density colors, and no
  unsafe event-chunk implementation.
- Run Pipeline reports observable progress, can be cooperatively cancelled, and can use
  bounded sample-level parallelism without changing any scientific result or ordering.
- Batch Plot Export reports per-item progress, can be cancelled, and can use bounded
  parallel rendering without changing plots, overlays, gates, labels, filenames,
  sidecars, or manifest order.
- GUI, CLI, and Python API use the same Qt-independent execution controls and runner.
- Memory use is bounded and reported; no unbounded queue, worker, cache, or event-array
  copy is introduced.
- All worker/thread/process lifecycles shut down cleanly on success, failure,
  cancellation, project replacement, and application exit.
- User manual is updated in the increment that exposes progress, cancellation, or
  performance settings to users.
