# Sample Sheet, Results Statistics, and Batch Plot Export

Spec: `S02`, `S09`, `S11`, `S14`  
ToDo: `Phase B7.3`

## Goal

Provide three connected user workflows without creating a second analysis pipeline:

1. edit a user-facing title for every sample in an Excel-like Sample Sheet;
2. export plots for every selected FCS sample from one persisted plot/export definition;
3. add and inspect persisted numeric statistics, including mean and median, in Results.

The project file and the GUI-independent runner are authoritative. The Qt UI edits
persisted definitions, requests the runner, and renders returned values only.

> **Phase B7.4 follow-up:** Increment 1 completed the title-only Sample Sheet, while the
> older Sample Annotations dialog exposes arbitrary `AnnotationSpec` values separately.
> The normal GUI must combine them into one Sample Sheet with read-only FCS columns,
> editable Title, and typed workspace/imported annotation columns. The underlying model
> remains `AnnotationSpec`; this is a UI and dependency-invalidation integration, not a
> second metadata format. See
> [`analysis-workflow-integration.md`](analysis-workflow-integration.md).

## Inspect first

- `AGENTS.md`, `specs.md` sections `S02`, `S09`, `S11`, and `S14`
- `docs/implementation/groups-and-annotations.md`
- `docs/implementation/statistics-definitions.md`
- `docs/implementation/gating-and-results-workspaces.md`
- `docs/implementation/multi-sample-overlay-and-plot-presentation.md`
- `docs/implementation/integrated-overlay-controls-and-plot-appearance.md`
- `docs/implementation/export-and-cli.md`, `source-map.md`, and `llm-task-protocol.md`
- `src/flowdesk_core/annotations.py`, `statistics.py`, `plot_export.py`,
  `plot_presentation.py`, `pipeline_runner.py`, and `project_commands.py`
- `src/flowdesk_storage/project.py`, `schemas/project.schema.json`
- `src/flowdesk_qt/annotation_editor.py`, `sample_browser.py`,
  `results_workspace.py`, `statistics_editor.py`, `plot_widget.py`, and `main_window.py`
- `src/flowdesk_cli/run_project.py`
- `tests/test_annotations.py`, `test_population_statistics.py`, `test_export.py`,
  `test_plot_export_reuse.py`, `test_project_storage.py`, and the corresponding GUI tests

Read the `qt-plot-widget` and `scientific-review` skills before the relevant increments.

## Non-goals

- Do not edit FCS bytes, FCS keyword metadata, sample IDs, paths, fingerprints, or raw
  event arrays from the Sample Sheet.
- Do not calculate mean, median, membership, or plot coordinates in Qt.
- Do not use a Qt screen capture as batch-export output or as evidence of scientific
  results.
- Do not add a second statistics or plot-definition format for batch export.
- Do not silently substitute a missing sample, parameter, population, transform, font,
  overlay source, or renderer output.
- Do not make XLSX a required dependency. A Qt table with clipboard TSV support is enough
  for the initial Excel-like workflow; optional XLSX import/export belongs in a later,
  separately tested increment.

## Shared invariants

The canonical processing order remains:

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

Sample titles and plot presentation are display/export metadata. `StatisticSpec` is an
analysis definition, but its calculation remains after full-resolution membership.
Changing either workflow must never mutate raw events. Display downsampling is allowed
only for interactive rendering and must never feed gate membership, statistics, density
aggregation, or exported scientific values.

All saved references use stable IDs. Ambiguous parameter/population/sample mapping is a
validation error with a structured diagnostic, never a name-based fallback.

## Increment 1: Sample Sheet titles

### Model contract

Use the existing `AnnotationSpec`/annotation-resolution path rather than adding a second
per-sample metadata store. Reserve the workspace annotation keyword `sample_title` for
the editable title. It has source `workspace`, is a string, and shadows only the display
title; it never shadows arbitrary FCS keywords used by group rules.

The resolved display title is:

```text
non-empty workspace sample_title
  -> persisted sample name
  -> FCS filename stem
  -> stable sample ID
```

Persist both the title value and source/provenance through the existing annotation
serialization. An empty title means "use the fallback"; do not persist a generated
fallback as a workspace annotation. Duplicate display titles are allowed, but the GUI
must visibly retain the stable sample ID and batch export filenames must remain unique.

### GUI contract

Add or extend a `QAbstractTableModel`/`QTableView` Sample Sheet; do not use a grid of
independent widgets. At minimum it has the read-only columns `Sample ID`, `File`, and
`Sample name`, and the editable `Title` column. It may expose other resolved annotation
columns through the existing annotation editor, but must not present raw FCS metadata as
editable workspace data.

Support multi-cell TSV clipboard paste, deterministic fill series, undo/redo, filter,
sort, and CSV-import preview through the existing annotation operations where possible.
Before accepting paste/import, validate target sample IDs, column identity, value type,
and duplicate rows. Reject the invalid cells with row/column diagnostics; do not shift
subsequent input cells. Cancel must leave project state unchanged.

Use stable `objectName` values for the table, title column, import action, and diagnostic
surface. Update Sample Browser, Results, legends, and export labels through one resolved
display-name helper, while preserving stable IDs in tooltips/sidecars.

The Phase B7.4 extension makes this the sole normal annotation-editing surface. It adds
typed editable workspace/imported columns and column/provenance management inside Sample
Sheet; FCS keyword columns remain read-only. `sample_title` changes are display/export
only. Other annotation edits invalidate analysis only when a Group membership/binding
rule actually references the changed key.

The reference Qt surface exposes stable actions named `sampleSheetAddAnnotationColumnButton`,
`sampleSheetImportCsvButton`, `sampleSheetPasteButton`, `sampleSheetFindReplaceButton`,
`sampleSheetFillSeriesButton`, `sampleSheetUndoButton`, and `sampleSheetRedoButton`.
Each action delegates to `SampleSheetModel` and must not mutate raw FCS bytes/events.
Find/replace is restricted to workspace/imported annotations, and CSV/paste validation
must complete before the model records an undo snapshot. These actions remain inside the
Sample Sheet dialog; no competing top-level annotation editor is allowed.

### Tests

- Core: title resolution and fallback order, annotation round-trip, paste/import
  validation, fill series, and raw metadata/event immutability.
- Storage: old projects without `sample_title` retain their existing display names.
- GUI: multi-cell paste, undo/redo, filter/sort, cancel, and title refresh in Results.
- Headless: title resolution is identical through project load and CLI execution.

## Increment 2: Batch plot export

### Persisted definition

Add a typed `BatchPlotExportSpec` stored with project export/display definitions. It must
contain:

- stable export ID and display name;
- target selector: all samples, explicit stable sample IDs, or a resolved Group ID;
- one stable `PlotViewSpec`/plot-view reference and optional population/overlay selector;
- requested formats (`png` first; `svg`/`pdf` only through an already supported renderer),
  dimensions, DPI where relevant, and deterministic filename template;
- output collision policy (`fail`, `replace`, or a deterministic suffix policy);
- strictness policy for missing samples, incompatible/missing overlay sources, and
  renderer/font failures;
- analysis/plot revision and sidecar/provenance settings.

The filename template may use only explicit placeholders such as `{sample_id}`,
`{sample_title}`, `{sample_name}`, `{plot_id}`, and `{index}`. Sanitize title/name
substitutions to a portable filename slug, preserve the stable sample ID in every output
name, and detect collisions after sanitization. Never use a title as the identity or path
authority.

### Execution contract

Create a GUI-independent planner and runner in core-facing export code. It resolves the
target list in deterministic project sample order, validates every planned item, calls the
canonical `PipelineRunner` when a current authoritative report is unavailable, resolves
the existing plot presentation/overlay compatibility model, and invokes the existing
headless renderer. The CLI and GUI must only build the request and display the returned
report; neither may reimplement plotting, compatibility mapping, or statistics.

Each output receives a provenance sidecar containing export ID, sample ID and resolved
title, plot/population/parameter/transform IDs, resolved source order and styles,
analysis revision, renderer version, output hash, and structured diagnostics. A manifest
summarizes the batch and lists every requested sample, including failures/skips.

`partial_success` is an explicit status. A blank image, absent required file, unresolved
mandatory source, or renderer exception is failure, never success. The runner must report
per-sample status and a non-zero CLI exit for the selected strictness policy. It must not
delete unrelated pre-existing output files.

### Tests

- Planner selects all, explicit, and Group targets in deterministic order.
- A synthetic multi-sample project produces one nonblank PNG per successful sample, with
  unique names even when titles collide after slugging.
- GUI and CLI requests resolve identical plot/source/style/provenance data.
- Missing FCS, missing population, incompatible overlay, collision, blank output, and
  renderer failure are distinct structured outcomes.
- Changing export settings or display downsampling leaves raw arrays, memberships,
  counts, frequencies, and statistic results identical.

## Increment 3: Results statistic management

### Model and execution contract

Reuse `StatisticSpec`, `StatisticResult`, the metric dispatcher, project commands, and
the canonical pipeline/preview APIs. Do not introduce a Results-only metric enum. The
editor may expose only supported typed metrics: count/frequencies where applicable, mean,
median, geometric mean, SD, CV, MAD, and percentile, subject to the validation and
undefined-value policies in `statistics-definitions.md`.

Selecting a metric determines the required fields. Numeric metrics require a stable
parameter ID; percentile requires a finite percentile setting; count/frequency do not
silently accept an irrelevant parameter. Population and source-stage selections are
stable-ID values. Invalid definitions are rejected before execution with field-level
diagnostics.

Adding, editing, duplicating, or removing a statistic is a persisted project command and
invalidates applicable results. Results refresh only through `PipelineRunner` or the
existing revision-safe current-sample preview request. The Results workspace displays
returned value, formatted display value, unit, status, undefined reason, definition ID,
and analysis revision. Formatting must not affect the stored numeric value; Qt must not
recompute NaN/Inf, geometric-mean, CV, or percentile policies.

### GUI contract

Expose `Add Statistic...`, edit, duplicate, and remove from Results and existing
statistics entry points, all routed through the same command/validator. Provide a detail
or flat-table surface separate from population navigation, avoiding duplicate adjacent
statistic trees. Distinguish `current`, `stale`, `undefined`, `error`, and `not run`
without relying on color alone.

This increment's detail/child presentation is superseded by the Phase B7.5 plan in
[`results-statistics-matrix.md`](results-statistics-matrix.md): Population remains the row
dimension, named statistics become dynamic columns, and a long-form detail view exposes
QC fields without placing numeric metrics in `% Parent` or `% Total` columns.

### Tests

- Known full-resolution values for mean, median, percentile, and selected edge cases;
  policies for empty values, NaN/Inf, zero-mean CV, and nonpositive geometric mean.
- Definition save/load and migration preserve stable IDs, settings, format, and source
  stage.
- Add/edit/remove causes correct stale/current transitions without changing gates,
  transforms, compensation, or raw events.
- GUI Results values, Python API values, and CLI TSV/CSV statistic export agree after a
  project reload.

## Target files

- `src/flowdesk_core/annotations.py`, `models.py`, `project_commands.py`,
  `statistics.py`, `execution_report.py`, `plot_export.py`, `plot_presentation.py`, and
  `export.py`
- `src/flowdesk_storage/project.py`, relevant migration code, and
  `schemas/project.schema.json`
- `src/flowdesk_cli/run_project.py` (or a thin batch-plot command module)
- `src/flowdesk_qt/annotation_editor.py`, a Sample Sheet widget/model if needed,
  `sample_browser.py`, `results_workspace.py`, `statistics_editor.py`, `main_window.py`,
  and plot-export actions
- `tests/test_annotations.py`, `test_population_statistics.py`, `test_export.py`,
  `test_plot_export_reuse.py`, `test_project_storage.py`, `test_cli.py`, and focused GUI
  tests under `tests/gui/`

## Verification

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q \
  tests/test_annotations.py tests/test_population_statistics.py tests/test_export.py \
  tests/test_plot_export_reuse.py tests/test_project_storage.py tests/test_cli.py
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

## Acceptance criteria

- A title can be edited in a table for many samples, persisted, restored, and resolved
  identically outside the GUI without changing FCS input identity or data.
- A saved batch export definition generates reproducible per-sample plot files through
  the headless path, with explicit manifest/sidecar provenance and no silent omissions.
- Results can create and manage mean, median, and other supported `StatisticSpec` values;
  the displayed/exported values and statuses equal the canonical runner results.
- GUI code only edits definitions and displays outputs; the same project executes through
  CLI/Python without Qt.
