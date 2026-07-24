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
