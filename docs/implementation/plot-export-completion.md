# Plot Export Completion

Source: [`docs/bug.md`](../bug.md)  
ToDo: `Phase B7.3.E`

## Goal

Complete plot-image export so a single export, a right-click export, and a
batch export reproduce the same resolved display definition. Exports preserve
visible sources, presentation, gates, axis configuration, and provenance.

This is display/export work only. It must not alter raw events, compensation,
derived parameters, transforms, gate membership, statistics, or result
revisions.

## Current baseline and gaps

Existing toolbar PNG/SVG/PDF export, an export-only 1:1 toggle, a persisted
`BatchPlotExportSpec`, and a CLI batch renderer do not yet satisfy all of
`docs/bug.md`:

- plot-area context-menu export actions and JPEG;
- a typed options contract shared by toolbar, context menu, GUI batch, and CLI;
- well-prefix and multi-source filename rules;
- canonical multi-sample overlay rendering in the headless batch renderer;
- shared batch layout/range policy for side-by-side comparison; and
- export-time inclusion options for title, labels, ticks, gates, and legend.

## Invariants

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> full-resolution gate membership
  -> display selection / export rendering
```

- `flowdesk_core` remains independent of Qt/PySide6.
- Batch export uses the canonical processed-display request path; it must not
  substitute direct raw-array plotting.
- Interactive single export may render the current Qt view, but its metadata
  states that fact. Batch/CLI export uses a renderer-neutral core contract.
- Definitions store stable IDs, never UI row positions or filenames as identity.
- Existing presentation remains authoritative for title, label, font, source
  order, and color. Export options may suppress an element but not replace its
  definition.
- Missing/incompatible visible sources, missing FCS, renderer/font failures,
  and blank required outputs are structured failures, never empty successes.

## Export contract

Add a typed persisted `PlotExportOptions` (or backwards-compatible extension
of `BatchPlotExportSpec`) with:

- formats `png`, `jpg`, `svg`, `pdf`;
- raster width, height, DPI, and `aspect_1_to_1`;
- `layout_policy`: `current_view` for interactive export or `shared_ranges` for
  batch export. Shared ranges are calculated from the complete selected set in
  canonical transformed coordinates;
- `include_title`, `include_axis_labels`, `include_ticks`, `include_gates`,
  `include_legend`, and `include_status_banner`. Transient stale/status banners
  default to off; and
- target/overlay selectors plus collision and strictness policies.

These fields are export-layer visibility controls. They must not edit
`PlotPresentationSpec`, annotations, gates, or GUI state, and must be written
to every sidecar and batch manifest.

## Filename contract

Use one portable slugging implementation for GUI and CLI. A display title is
never sufficient identity for a filename.

1. Resolve each source sample's well from a persisted plate/well assignment.
   Until the plate workspace exists, a conservative parser may recognize only
   unambiguous filename tokens such as `A1`, `B02`, and `H12`, and records
   `well_source = filename_token` in provenance. Ambiguous strings are not
   wells.
2. One visible source uses `A1_<rendered-template>.png`; no known well leaves
   the rendered template unchanged.
3. Multiple visible sources collect unique wells in display/source order and
   use `A1_B2_<rendered-template>.png`. With no wells, use ordered stable sample
   IDs as the collision-safe source prefix.
4. Slug after template expansion and before collision detection. Sidecars
   record source IDs, well IDs/sources, template, and final filename.

Existing templates remain readable; migration must not rename historical files.

## Numbered increments

Implement one increment per change.

### Increment 1: Typed export options and deterministic naming

Target files:

- `src/flowdesk_core/models.py`, `batch_plot_export.py`, `plot_export.py`
- storage schema, validation, migration, serialization
- `tests/test_batch_plot_export.py`, `tests/test_project_storage.py`

Work:

- Add typed options, format validation/defaults, and optional schema fields.
- Implement core well resolution, multi-source prefix generation, slugging, and
  collision detection.
- Keep prior `BatchPlotExportSpec` valid; missing fields use documented defaults.

Acceptance:

- `A1` and `A1_B2` names are deterministic and portable on Linux/macOS/Windows.
- Missing/ambiguous wells do not produce false well prefixes.
- Project save/load and CLI planning preserve options and provenance exactly.

Status: complete. The renderer execution details are completed in Increment 2;
this increment established the persisted options and deterministic naming
contract.

### Increment 2: Renderer-neutral export scene and shared layout

Status: complete. Export dimensions, 1:1 aspect, title/axis-label/legend
visibility, JPEG dispatch, canonical transformed shared X/Y bounds, visible
manual overlays, persisted gate geometry, and a shared plot-area/axis scene
are implemented for the core and CLI renderer.

Target files:

- `src/flowdesk_core/plot_export.py`, `batch_plot_export.py`, processed-display
  and overlay resolution helpers
- `src/flowdesk_cli/batch_plot.py`
- `tests/test_plot_export_reuse.py`, `tests/test_batch_plot_export.py`,
  `tests/test_cli_batch_plot.py`

Work:

- Build one prepared scene from canonical processed data for the active source
  and all visible simple/advanced overlays.
- Render PNG/JPEG/SVG/PDF with requested gates, colors, title lines, labels,
  ticks, and legend.
- Preflight a batch's transformed X/Y ranges, margins, tick policy, and
  label/title reservations before any output is written.

Acceptance:

- GUI and CLI metadata have identical source order, transforms, presentation,
  and gate definitions.
- `shared_ranges` images share axes, tick positions, plot origin, and margins.
- Overlay, gate, and title colors match live resolved display styles.

### Increment 3: GUI export options and plot-area context menu

Status: complete. Toolbar and plot-area context requests use the same
format-aware request builder and options dialog; batch export is delegated to
the existing headless entry point.

Target files:

- `src/flowdesk_qt/plot_widget.py`, `plot_toolbar.py`, `main_window.py`
- an export-options dialog/widget if needed
- user manual and focused GUI tests

Work:

- Add an `Export` submenu to the plot-area right-click menu: PNG, JPEG, SVG,
  PDF, and `Batch Plot Export...`.
- Route toolbar/context-menu actions through one options dialog and one
  GUI-independent request builder.
- Expose format, output path/directory, 1:1 aspect, inclusion toggles, and
  batch layout policy with stable object names and keyboard access.

Acceptance:

- Equivalent toolbar and context-menu requests produce equal metadata and
  visually equivalent plots.
- Cancel does not change project or display state.
- The dialog distinguishes current-view export from batch shared-layout export
  and reports each batch failure.

### Increment 4: End-to-end verification and documentation

Status: complete. Synthetic core, CLI, and GUI tests cover overlays, gates,
colors, titles, wells, collisions, incompatible sources, renderer failures,
JPEG output, and display-only state preservation.

GUI exports additionally suppress interactive ROI handles and use solid gate
outlines temporarily; the editing view is restored after rendering.

Target files:

- core/CLI/GUI export tests, user manual, this guide

Work:

- Add synthetic fixtures for single source, manual/advanced overlays, gates,
  explicit colors, title/label suppression, wells, collisions, and failures.
- Verify raster dimensions/DPI, nonblank pixels, metadata/manifest hashes,
  ordering, and no analysis-state mutation.
- Document formats, filename rules, layout policy, and limitations.

Acceptance:

- PNG/JPEG/SVG/PDF single/batch export pass appropriate core, CLI, and GUI tests.
- No image drops a requested visible gate/overlay or changes resolved color/range.
- A manifest accounts for every requested sample and source combination.

### Increment 5: Batch Plot Export definition dialog (implemented)

The existing Results and plot-area entries now use a shared
`BatchPlotExportSpec` editor and execution controller. A new project opens a
default definition instead of requiring a preconfigured definition.

Target files:

- `src/flowdesk_qt/batch_plot_export_dialog.py`, `main_window.py`, and
  `plot_widget.py`
- `src/flowdesk_core/models.py`, `batch_plot_export.py` only if a missing
  typed validation helper is required
- `tests/test_batch_plot_export.py`, `tests/gui/test_batch_plot_export_dialog.py`,
  and Results/plot-widget entry-point tests
- `docs/user-manual/user_manual.md`

#### Dialog contract

The dialog edits an in-memory typed `BatchPlotExportSpec`; it must never
execute analysis or render images itself. The Run action persists the chosen
definition to the project first, then invokes `batch_plot_command()` with its
stable ID. Cancel, validation failure, output-directory cancellation, and
project-save failure leave project state unchanged.

The dialog contains:

- a saved-definition selector, `New`, and definition name. Existing projects
  without a definition open with a new default definition rather than an
  error;
- target selector: all samples, explicit sample selection, or an existing
  sample group. Explicit selection shows stable sample ID plus display title;
- plot-view selector, defaulting to the currently displayed view. Visible
  overlays and presentation are read from that persisted plot view; they are
  not copied into a GUI-only export model;
- format checkboxes for PNG, JPEG, SVG, and PDF; width, height, DPI, and 1:1
  aspect; batch layout (`shared_ranges` default, or `current_view`);
- visibility controls for title, axis labels, ticks, gates, legend, and status
  banner;
- filename template help for `{sample_title}`, `{sample_id}`, `{sample_name}`,
  `{plot_id}`, and `{index}`, plus collision policy and strict mode; and
- an output-directory chooser. This value is deliberately session-local (it
  may be remembered in `QSettings`) and is never written into the project,
  preserving project portability across Windows, macOS, and Linux.

`Save Definition` validates through
`batch_plot_export_spec_from_mapping()`, replaces only the selected definition
by stable ID, and marks the project dirty. `Run` performs the same save plus
the mandatory project save, then reports the structured batch manifest status
and any failures. A project that has not yet been saved uses the normal Save
Project flow before invoking the headless runner.

#### Implemented steps

1. Add a Qt-only `BatchPlotExportDialog` and a GUI-neutral mapping-to-typed
   validation boundary. Give every control a stable object name.
2. Replace both `Results -> Batch Plot Export...` and the plot context-menu
   route with one MainWindow controller that opens the dialog, persists a
   selected definition atomically, and calls the existing CLI adapter by ID.
3. Add tests for creation from an empty project, edit/reopen/select among
   multiple definitions, target validation, cancellation/no mutation,
   save-before-run, output-directory non-persistence, and partial-failure
   reporting.
4. Update the user manual with the batch workflow, filename tokens, and the
   distinction between project-persisted definition and machine-local output
   directory.

Acceptance:

- Neither Batch Plot Export entry point displays a configuration error merely
  because the project has no prior definition; both open the same dialog.
- The saved project contains only serializable `BatchPlotExportSpec` fields;
  reopening it on another platform preserves the definition without retaining
  the prior output directory.
- GUI execution and direct CLI execution of the saved definition produce the
  same target order, source order, options, and provenance.
- The GUI has no FCS parsing, gate evaluation, transform, or image-rendering
  implementation beyond dispatching the existing headless runner.

### Increment 6: Persisted plot-view snapshot parity (implemented)

#### Observed failure and evidence

The Batch Plot Export dialog can save an export definition, but its selected
`plot_view_id` does not yet reliably identify the current display definition.
For the reported project, `plot_display_settings` records the active FITC/APC
channel IDs, while `plot_views/main-view` contains only rendering downsampling
and manual-overlay fields. The CLI then executes this fallback:

```text
x_parameter = view.x_parameter or first FCS channel
y_parameter = view.y_parameter or second FCS channel
x_transform_id = view.x_transform_id (missing)
y_transform_id = view.y_transform_id (missing)
```

This explains all observed symptoms: the output plots FSC-H/FSC-A instead of
FITC/APC, gates are filtered out because their parameter IDs no longer match,
and the resolved presentation has null axis labels even though the visibility
checkboxes are enabled. The generated PNG sidecar confirms the fallback
parameter IDs, null labels, and an empty `gate_overlays` list.

The transform stage is represented lazily: `PipelineRunner.prepare_display_sample()`
validates and carries the transform definitions, while the returned event array
still requires the selected display transform to be materialized for renderer
coordinates. The fix must therefore apply the persisted X/Y transform exactly
once after the canonical processed-display result, and must test against double
application rather than removing this required materialization.

#### Implemented design

`PlotViewSpec` is the sole persisted identity of a batch-rendered plot. The
GUI may construct a serializable snapshot from current UI selections, but the
snapshot must be validated through core model contracts and rendered only by
the existing headless path. `plot_display_settings` remains UI restoration
state; it must not be a second, competing batch-rendering definition.

#### Implemented work

1. The GUI synchronizes a complete active `PlotViewSpec` mapping: stable X/Y
   parameter IDs, formal transform IDs,
   selected population, scatter/histogram type, rendering downsampling,
   overlay state, and presentation. Invoke it before project serialization and
   before creating/running a Batch Plot Export definition.
2. Make the CLI require a complete persisted view for batch scatter export.
   The first/second-channel fallback is removed and validation failure names
   the missing field and view ID.
3. Consume the canonical processed-display array and materialize each persisted
   X/Y transform exactly once for renderer coordinates. Align gate selection
   and gate coordinates with the exact persisted X/Y parameter and transform
   IDs; incompatible gates are diagnostics, never silently rendered in a
   different coordinate system.
4. Build axis-label defaults from the resolved persisted view and channel
   metadata. `include_axis_labels` and `include_ticks` control visibility only;
   they must not turn a missing scene definition into empty labels or axes.
5. Add fixture-based core/CLI/GUI E2E tests that save FITC/APC with log10/log10
   and a rectangle gate, then assert the export sidecar, raster/SVG scene, and
   manifest use those axis IDs, transform IDs, labels, gate geometry, visible
   overlays, colors, and no double transformation. Cover incomplete legacy
   views as a clear failure and a GUI save-time synchronization path.

#### Acceptance

- A batch export created from the screenshot's FITC B525-A / APC R660-A
  log10/log10 display records those stable IDs and transform IDs in both the
  saved view and sidecar; it never plots unrelated FSC channels.
- With title, labels, ticks, and gates enabled, output has channel labels,
  ticks, and the matching rectangle/polygon geometry in the same transformed
  coordinate system as the displayed plot.
- Exported values equal the single canonical processed-display view, with each
  transform applied exactly once. Missing persisted axes fail before writing an
  image and do not fall back silently.
- The GUI remains a project-state editor and CLI dispatcher; no FCS processing
  or image rendering is added to Qt code.

## Non-goals

- Report/layout editing belongs to Phase C2.
- Filename well-token fallback changes neither plate metadata nor scientific data.
- Display-downsampled points never feed gate or statistic calculation.
- No separate GUI-only plot model or image-OCR correctness path is introduced.

## Verification

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q tests/test_batch_plot_export.py tests/test_plot_export_reuse.py tests/test_cli_batch_plot.py tests/test_qt_plot_widget.py
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
