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

The dialog is resizable with a sensible minimum size. The definition form is
inside a widget-resizable vertical `QScrollArea`, while the Save, Run, Queue,
and Cancel buttons remain outside the scroll area so they remain reachable at
small monitor heights. The scroll area must not implement export logic; it only
changes presentation and preserves the existing object names and signal paths.

#### Canvas sizing and definition switching

- `MainWindow._on_batch_plot_export()` passes the current `PlotWidget.width()`
  and `PlotWidget.height()` to the dialog as the initial logical Canvas Width
  and Canvas Height. The values are widget dimensions, not the main-window
  dimensions and not DPI-scaled raster pixels.
- `BatchPlotExportDialog` treats Canvas Width, Canvas Height, and the 1:1
  aspect toggle as the current dialog draft. Loading or switching a persisted
  Definition must not overwrite those three draft values; other Definition
  fields continue to reload normally.
- With 1:1 enabled, Canvas Height is disabled and follows Canvas Width. The
  saved `BatchPlotExportSpec` still contains both values and
  `aspect_1_to_1=True`; `resolve_export_canvas()` remains the authoritative
  core rule for the final square canvas.
- This synchronizes the requested canvas size with the GUI widget, but does
  not promise identical plot-area bounds: axis/title margins, font metrics,
  device pixel ratio, and export visibility options can consume different
  amounts of space. Exact display parity must be verified through the shared
  renderer/export tests.

The persisted plot view's `display_scene.view_range` is display state, not
scientific input. On project load, validate this range and apply it once after
the canonical processed display has been plotted. Invalid or absent ranges are
ignored so legacy projects retain their normal auto-range behavior.

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

### Increment 7: Headless renderer visual parity (implemented)

#### Observed failure

After Increment 6, Batch Plot Export uses the correct persisted FITC/APC axes,
transforms, overlays, and gate coordinates, but the PNG is still visibly unlike
the live plot. The core PNG adapter writes every event as an opaque 5x5 square
and only draws bare axis lines. It does not render title lines, axis labels, or
tick labels. This is a renderer-contract gap, not an FCS, transform, or gate
calculation issue.

#### Design

The headless export scene must carry renderer-neutral presentation primitives:
resolved title lines and their source colors, labels, transformed axis bounds,
major/minor tick coordinates and labels, marker size/opacity/shape, and solid
gate strokes. The CLI derives that scene from the same persisted plot view,
transform definitions, and resolved source styles used for data extraction.
The core adapters render the scene without importing Qt or capturing the GUI.

#### Work

1. Add typed/validated scene metadata to `PreparedPlotExport` for title-line
   colors and normalized ticks. Resolve `overlay_sample_titles` from the ordered
   visible sources rather than relying on a GUI-only title string.
2. Make PNG/JPEG use antialiased circular markers with each source's resolved
   color, alpha, and marker size. Reserve margins for title, tick labels, and
   axis labels; draw requested labels, major/minor ticks, and solid gates.
3. Bring SVG and PDF marker and text primitives in line with the same scene
   contract so formats do not silently diverge.
4. Add synthetic renderer and CLI tests for visual-scene metadata, title-line
   colors, log tick labels, raster text/tick regions, marker alpha/shape, and
   gate stroke visibility. Keep all assertions independent of GUI screenshots.

#### Acceptance

- With title, labels, ticks, gates, and legend enabled, a Batch PNG has the
  selected transformed axes, readable labels/ticks, source-colored title lines,
  small semi-transparent circular points, and solid gate outlines.
- SVG, PDF, PNG, and JPEG receive the same source order, colors, title/tick
  scene, and gate geometry; no format reverts to opaque square scatter points.
- The headless renderer remains deterministic and independent of PySide6.

### Increment 8: Current viewport and Qt-equivalent axis presentation (implemented)

#### Observed failure

Increment 7 still derives `current_view` bounds from all finite batch data and
uses raw FCS channel names. Consequently the exported image can have a wider
range and labels such as `FL1-A`/`FL3-A` while the live view shows
`FITC B525-A`/`APC R660-A`. Raster Y labels are horizontal and tick labels use
plain `1e3` rather than the GUI's `1 × 10³` display form.

#### Work

1. Persist the active plot widget's current transformed ViewBox bounds,
   resolved visible X/Y label strings, tick policy, and resolved font request
   in the active plot-view snapshot. These are display/export state only.
2. For `current_view`, normalize batch data and gate geometry against the
   persisted ViewBox bounds; retain `shared_ranges` as the explicit global
   range mode. Do not calculate gates or statistics from clipped display data.
3. Render tick labels using the same Unicode scientific notation as the Qt
   widget and rotate the raster Y-axis label by 90 degrees. Use the persisted
   presentation font sizes for title, axis, and ticks at the requested output
   resolution.
4. Test GUI snapshot persistence and CLI scene consumption for labels/ranges,
   plus headless raster helpers for superscript ticks, vertical Y labels, and
   font-size metadata.

#### Acceptance

- A `current_view` batch export has the same visible X/Y range and labels as
  the saved GUI view, including when FCS raw names differ from display labels.
- Log tick labels use `1 × 10ⁿ` formatting and raster Y labels are vertical.
- Font requests in output sidecars equal the saved resolved presentation;
  rendering remains Qt-independent and does not change scientific results.

### Increment 9: Canonical `PlotScene` contract (implemented)

#### Goal

Replace the current partial sharing of metadata and normalized layers with one
typed, renderer-neutral `PlotScene`. The GUI plot and every export adapter
must consume the same scene, so display data, coordinate system, plot rectangle,
ticks, labels, title, marker/gate styles, clipping, and source order have one
authoritative definition.

`PlotScene` is display state, not analysis state. It must be built only after
the canonical pipeline has completed:

```text
raw events -> compensation -> derived parameters -> transform
           -> full-resolution gate membership -> display selection -> PlotScene
```

No scene adapter may apply a transform, calculate gate membership, derive a
population count, or change raw events. Display clipping and deterministic
downsampling affect rendered points only.

#### Scene contract

The implementation adds an immutable core `PlotScene` model. It includes
`PlotSceneLayer`, `PlotSceneGate`, `PlotSceneTick`, and `PlotSceneText`. The
exact class names may differ, but the contract must include:

- stable source/sample/population IDs; X/Y parameter IDs; formal transform IDs;
  transformed viewport bounds; deterministic display-sampling identity; and a
  canonical coordinate convention;
- canvas dimensions, title/axis/tick/legend reservations, the plot rectangle,
  clipping rectangle, aspect policy, and z-order;
- source point coordinates in the one transformed coordinate system, marker
  shape/size/color/alpha, and resolved title/legend source colors;
- major/minor tick positions and already-resolved display labels, including
  Unicode exponent notation; title, axis-label, and font requests; and
- gate geometry in the same transformed coordinate system, resolved stroke/
  fill style, and a flag distinguishing export geometry from GUI-only editing
  handles or creation previews.

Project files retain a compact `PlotViewSpec` and current viewport snapshot;
they must not persist event coordinates or rendered images. Export sidecars
record a serialized scene summary and a deterministic scene hash for audit.

#### Work

1. Create the typed core scene model and a GUI-independent scene builder under
   `flowdesk_core`. It receives canonical `ProcessedDisplayResult` data plus a
   validated `PlotViewSpec`/presentation and rejects incomplete axes,
   incompatible overlays, non-finite viewport bounds, and transform mismatch
   with structured diagnostics.
2. Move range normalization, clipping, deterministic display sampling, tick
   generation, title resolution, text/layout reservations, source-style
   resolution, and gate-coordinate conversion into that builder. Apply each
   persisted transform exactly once and retain full-resolution gate membership
   outside the scene.
3. Make PNG/JPEG/SVG/PDF adapters accept only `PlotScene`; remove independent
   fallback range/tick/title/layout calculations from individual writers.
   Ensure all formats use the scene's plot rectangle and resolved font/style
   requests.
4. Make `PlotWidget` a scene display adapter: it maps scene primitives into
   pyqtgraph items and does not independently select points, resolve titles,
   derive ticks, or compute view bounds. Gate selection/creation handles stay
   in a separate Qt-only editing overlay and are excluded from `PlotScene`.
5. Make toolbar, context export, Batch Plot Export, and CLI build the same
   scene from the same saved plot-view definition. A GUI export may use its
   current scene directly, while CLI/batch reconstruct the equal scene through
   the canonical pipeline runner.

#### Required tests

- Core scene fixtures covering linear/log/asinh/logicle transforms, manual and
  advanced overlays, current/shared ranges, titles, all supported marker
  styles, ticks, rectangle/polygon/ellipse/range gates, and incompatible
  sources.
- Assertions that GUI and CLI scene serializations and scene hashes match for
  equal saved definitions; verify X/Y IDs, transform IDs, bounds, source order,
  point count/sampling indices, tick coordinates/labels, and gate paths.
- Adapter contract tests that pyqtgraph and every export writer receive the
  same primitive bounds, colors, alpha, fonts, and z-order. GUI-only handles
  and previews must be absent from exported scenes.
- Scientific regression tests proving that building/rendering a scene cannot
  change raw events, transformed caches, gate membership, counts, frequencies,
  statistics, or analysis revision.

#### Acceptance

- Equal plot definitions produce equal canonical scenes in GUI and headless
  paths. A batch export never has a different parameter, transform, viewport,
  gate coordinate, or source order from the selected saved view.
- PNG/JPEG/SVG/PDF and the live plot have equal plot-rectangle geometry, text
  strings, tick positions, marker/gate style values, clipping, and z-order.
- The scientific pipeline remains executable without Qt. `flowdesk_core` does
  not import Qt; Qt only renders the scene it receives.

### Increment 10: Visual-equivalence verification and renderer decision (implemented)

The common scene guarantees semantic and geometric parity, but separate Qt,
Pillow, SVG, and PDF backends can still differ in font rasterization and
anti-aliasing. Define visual equivalence as the scene contract plus measured
geometry/style agreement; do not use cross-platform pixel hashes as a
scientific correctness test.

The GUI-triggered Batch Plot Export now selects the Qt/pyqtgraph adapter. It
constructs a temporary `PlotWidget` from the same processed display arrays,
transform specifications, viewport, presentation, and gate definitions used
by the live GUI, then asks that widget to render the PNG. Direct CLI execution
continues to use the Qt-independent renderer unless `renderer_backend="qt"`
is explicitly selected, so headless execution remains available on systems
without PySide6.

For `current_view` exports, the transformed X/Y ViewBox range is captured
before the temporary export resize/aspect operation and restored for the
render. This prevents a 1:1 export canvas from silently expanding an axis.
Population display colors are applied to the canonical preview membership
mask, while overlay colors use the persisted source/manual color before
falling back to the GUI overlay palette.

#### Work

1. Add a fixed-size visual regression fixture that verifies GUI/export scene
   serialization and PNG/SVG adapter output retain identical plot rectangle,
   tick, gate, title, source-order, and resolved-color values.
2. Keep font requests and fallback diagnostics in the scene and sidecar.
   Cross-platform font rasterization remains an explicit diagnostic.
3. Keep a shared optional rendering backend as a future product decision if
   publication workflows require pixel identity. `flowdesk_core` remains Qt
   independent and the headless adapter remains supported.

#### Acceptance

- The documented visual-equivalence suite passes on Linux, macOS, and Windows
  with backend-specific font diagnostics but no silent range/style drift.
- Exact pixel identity is required only when both outputs explicitly use the
  same optional rendering backend; otherwise the supported guarantee is equal
  canonical scene plus bounded visual geometry/style differences.

### Increment 11: Resolution semantics and publication-quality export (implemented)

#### Observed problem

The former batch dialog exposed Width, Height, and DPI, but the Qt PNG path
uses only Width and Height as final raster pixels. Increasing DPI therefore
does not increase PNG detail. The Qt PDF path also fixes its writer to 96 DPI
and an A4 page, then renders the widget directly; the plot viewport and
`pxMode=True` scatter-symbol cache can be embedded as raster images. Increasing
Width/Height alone increases the plot rectangle while leaving fonts, tick
lengths, pen widths, and marker sizes effectively screen-pixel sized, so the
visual proportions are not preserved.

The implementation now resolves one `ExportCanvasSpec` for each export,
shows effective dimensions in the batch dialog, persists the compatibility mode,
and writes the resolved canvas to per-file sidecars and the batch manifest.
Batch SVG/PDF uses the Qt-independent vector renderer; the single-plot Qt PDF
adapter remains a separate legacy path and is not covered by this guarantee.

The Qt raster adapter keeps the widget at the logical canvas size and paints it
onto a `QImage` whose device-pixel ratio is the resolved raster scale. This is
required to keep pyqtgraph layout geometry independent of DPI. Cosmetic axis,
grid, and gate pens are scaled once for the paint device, while Qt text and
scatter symbols follow the device-pixel ratio directly. Tick levels are frozen
from the logical canvas before painting so a higher DPI cannot add extra grid
or tick levels. A normalized-image regression test compares low- and high-DPI
output after resizing both to the same logical canvas.

This increment changes only display/export rendering. It must not change raw
events, processing order, gate membership, statistics, or the deterministic
display-sampling selection.

#### Target terminology and persisted contract

Use one reference density, `96 DPI`, for logical layout units.

| Field | Meaning | Raster PNG/JPEG behavior | Vector SVG/PDF behavior |
|---|---|---|---|
| `width` | Logical canvas width in px at 96 DPI | Defines layout width before raster scaling | Defines page/artboard width as `width / 96` inch |
| `height` | Logical canvas height in px at 96 DPI | Defines layout height before raster scaling | Defines page/artboard height as `height / 96` inch |
| `dpi` | Requested raster density | `pixel_width = round(width * dpi / 96)` and equivalent height; write matching image density metadata | Not a raster-quality control; the vector page geometry is independent of it |

All scene geometry is expressed in logical units: plot rectangle and margins,
font point requests, tick length, axis/gate pen width, marker diameter, and
legend spacing. A raster renderer applies one `raster_scale = dpi / 96` to
every logical visual quantity. DPI must never change event sampling, ranges,
transforms, gate geometry, colors, alpha, or z-order.

The existing project schema has historically treated Width/Height as final
pixels and ignored DPI for PNG. To preserve reproducibility, add a persisted
`raster_resolution_mode` with values:

- `legacy_pixel_dimensions`: Width/Height remain final output pixels and DPI is
  metadata only. Missing values in existing projects resolve to this mode.
- `dpi_scaled`: Width/Height are 96-DPI logical canvas units and DPI controls
  the effective raster dimensions. Newly created definitions default to this
  mode.

The dialog must label the controls as `Canvas width (logical px @ 96 DPI)`,
`Canvas height (logical px @ 96 DPI)`, and `Raster DPI`. It must display the
effective PNG/JPEG dimensions and physical size before execution, for example
`800 × 600 @ 300 DPI -> 2500 × 1875 px (2.67 × 2.00 in)`. For SVG/PDF, show
`DPI not applicable to vector geometry` rather than implying that it changes
vector detail.

#### Renderer design

1. Add a Qt-independent `ExportCanvasSpec` or equivalent to the core export
   contract. It resolves the logical canvas, raster scale, actual raster size,
   physical size, and compatibility mode once. GUI, CLI, PNG/JPEG/SVG/PDF
   adapters consume this resolved object; no adapter reinterprets DPI.
2. Keep `PlotScene` in logical coordinates. Raster adapters create a
   high-resolution paint device, set its density metadata, and map the painter
   by `raster_scale`, or render an equivalently scaled scene. Fonts, tick
   lengths, marker diameters, line widths, margins, title reservation, and
   clipping must scale together. Do not render a low-resolution widget and
   upsample it.
3. Make SVG/PDF true vector adapters. Page/artboard dimensions come from the
   logical canvas, never a hard-coded A4 page. Render scatter symbols, lines,
   text, ticks, and gates as vector primitives; do not embed a full-canvas
   QPixmap or pyqtgraph symbol atlas. If a future performance policy requires
   raster fallback for a very large layer, it must be explicit in the UI and
   sidecar, include its effective pixels/DPI, and never be silently selected.
4. Keep the live `PlotWidget` as a Qt scene adapter only. Export construction,
   canvas resolution, and display-sampling identity belong in the
   GUI-independent export contract. The Qt adapter may receive a resolved
   scene and canvas but must not calculate scientific values or choose a
   different event subset.
5. Treat event-count/display-sampling limits separately from image resolution.
   A sidecar must record input event count, rendered event count, sampling
   policy/indices identity, logical canvas, actual raster dimensions, density,
   and any explicit raster fallback.

#### Target files

- `src/flowdesk_core/models.py`, `plot_scene.py`, `plot_export.py`, and
  `batch_plot_export.py`
- storage schema/migration and project serialization
- `src/flowdesk_qt/batch_plot_export_dialog.py`, `plot_widget.py`, and
  `qt_plot_export.py`
- `src/flowdesk_cli/batch_plot.py`
- core, CLI, and GUI export tests; `docs/user-manual/user_manual.md`

#### Required tests and acceptance criteria

- A 800 × 600 logical canvas at 96 DPI produces 800 × 600 px; at 300 DPI in
  `dpi_scaled` mode it produces 2500 × 1875 px. Legacy definitions retain
  their historical final pixel dimensions.
- PNG/JPEG density metadata matches the requested DPI within the format's
  integer rounding rules. Raster dimensions, physical size, and resolution
  mode appear in every sidecar and batch manifest.
- A 96-DPI export and a 300-DPI export, resized to the same logical canvas,
  have equivalent scene geometry: title/axis/tick font proportions, tick
  lengths, marker diameters, pen widths, margins, plot rectangle, clipping,
  colors, alpha, and gate geometry.
- SVG/PDF page dimensions derive from the logical canvas and contain vector
  scatter/gate/text primitives. A fixture inspection must reject a full-canvas
  embedded raster image or cached marker atlas for normal scatter export.
- GUI, CLI, and batch paths resolve equal `ExportCanvasSpec` and `PlotScene`
  values for the same saved definition. DPI/resolution changes do not change
  raw events, transforms, gate membership, counts, frequencies, statistics,
  or selected display-event identities.
- Update the user manual only with the implemented behavior, compatibility
  mode, effective-size preview, and vector-format limitation/guarantee.

### Follow-on: lightweight SVG/PDF scatter representation

The planned `full_vector`, `compact_vector`, and `hybrid_raster` scatter modes
are specified in `docs/implementation/lightweight-vector-scatter-export.md`.
That guide supersedes only the scatter representation rules after its numbered
increments are implemented. Until then, the current no-raster SVG/PDF
acceptance contract in this guide remains authoritative.

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
