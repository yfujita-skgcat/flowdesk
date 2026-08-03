# Current-view Export / Batch Export parity repair

## Purpose

Make plot-area context-menu export and toolbar single-plot export use the same
GUI-independent preparation and writer path as Batch Plot Export. The Batch
output currently used by users is the regression baseline and must not change
while this work is introduced.

This is display/export work only. It must not modify raw FCS events,
compensation, derived parameters, transforms, gate membership, population
statistics, sample selection, or analysis revisions.

## Target files and ownership

The implementing LLM must confirm the current call graph before editing. The
expected ownership after migration is:

- `src/flowdesk_core/plot_scene.py`: renderer-neutral scene and typed layout,
  semantic order, draw order, and coordinate-space contracts;
- `src/flowdesk_core/plot_export.py`: prepared render payload validation and
  the only PNG/JPEG/SVG/PDF format dispatcher;
- a focused new `flowdesk_core` preparation module, or an existing core module
  with the same responsibility: range/tick/gate/style/title preparation shared
  by Batch and current-view export;
- `src/flowdesk_cli/batch_plot.py`: load Batch definitions and data, then call
  the core preparation service without locally resolving ticks or gates;
- `src/flowdesk_qt/main_window.py`: capture the current display snapshot and
  call the core service, without reconstructing renderer input;
- `src/flowdesk_qt/qt_plot_export.py`: temporary compatibility boundary only;
  remove its scene-reconstruction branch after migration; and
- `tests/test_cli_batch_plot.py`, `tests/test_plot_export_reuse.py`,
  `tests/gui/test_qt_plot_export.py`, and `tests/test_qt_plot_widget.py`: Batch
  characterization, payload equivalence, current-view integration, and GUI
  snapshot coverage.

Do not import `flowdesk_cli` from `flowdesk_qt` or `flowdesk_core`. Shared code
must move downward into `flowdesk_core`; the dependency direction must remain
GUI/CLI -> core.

## Confirmed root causes

Calling the same PNG/SVG/PDF writer is not sufficient. At present the two paths
construct different renderer inputs before calling that writer.

### 1. Title order uses painter order instead of semantic source order

The GUI title is built by `MainWindow._current_plot_sample_ids()` in semantic
display order: active sample first, followed by visible overlay samples in the
Samples-list/title order. Overlay points are deliberately painted in a different
back-to-front order so upper Samples-list rows appear in front.

`MainWindow._current_plot_export_metadata()` instead reads
`PlotWidget.export_data_layers()` and uses `rendered_overlay_ids` as
`ordered_source_ids`. Those IDs are in painter order. The code then uses the
same tuple for titles, title colors, source metadata, and positional layer
zipping. Reversing overlay paint order therefore also reverses title order.

Required model change:

- `semantic_source_order`: title, legend, metadata, filename, and Sample Sheet
  order;
- `source_draw_order`: back-to-front point rendering order; and
- `layers_by_source_id`: event arrays keyed by stable source ID, never parallel
  positional arrays.

For old scenes, `source_draw_order` defaults to `semantic_source_order`, so
existing Batch output remains unchanged.

### 2. Current-view layout omits the live plot-area contract

`_current_plot_export_metadata()` creates a `PlotScene` without
`display_scene.plot_area`, live axis-label anchors, or other resolved layout
geometry. `PlotScene` therefore falls back to `(60, 50, 20, 60)` logical-pixel
margins. `_export_current_plot_core()` later passes
`PlotWidget.plot_area_margins()` to `render_batch_plot_qt()`, but that value is
ignored when a prebuilt `prepared` payload is supplied.

For a long bold Y label, the default left margin places the rotated label anchor
outside the canvas. DPI scaling magnifies the already incorrect logical layout;
it is not the root cause.

Required behavior:

- resolve one logical-canvas `PlotLayoutSpec` before format dispatch;
- include finite live/current-view `plot_area`, title baseline, axis-label
  anchors, and tick-label geometry in the canonical snapshot;
- when requested Width/Height differs from the GUI canvas, recompute layout
  from the canonical margin/font contract rather than reusing mixed-size
  absolute coordinates; and
- fail with a structured layout error if any required label bounding box lies
  outside the logical canvas. Do not silently clip it.

### 3. Tick generation takes a stale/empty route

The GUI displays transform-aware ticks returned by `PlotWidget.scene_ticks()`.
Batch export uses `_normalized_ticks()` with the active transformed bounds,
transform ID, transform definition, and tick policy. Current-view export reads
persisted `view["display_scene"]` instead of taking the live tick snapshot. When
the persisted tick list is absent or stale, the writer sees transformed numeric
coordinates without transform-aware tick labels and produces linear labels
such as `2`, `4`, and `6` instead of `10^n`.

Required behavior:

- move `_normalized_ticks()` and transform/tick-policy resolution out of
  `flowdesk_cli.batch_plot` into `flowdesk_core`;
- both Batch and current-view preparation call that one core function;
- current-view may provide live tick geometry only as an explicitly typed
  snapshot with the same transform ID and bounds; and
- never apply a transform twice. Every layer and range must declare whether it
  is raw, compensated, or transformed display space.

### 4. Gate definitions are passed without Batch normalization

Current-view export serializes `GateSpec` with `asdict()` and passes raw
thresholds/coordinates to the writer. The writers consume normalized
`gate["points"]` coordinates. Batch export alone calls `_gate_overlays()`, which
filters gates by axis and transform IDs, converts rectangles to vertices,
normalizes them against the active bounds, and clips the polygon to the unit
plot square. Consequently current-view gates can disappear completely.

Required behavior:

- move `_gate_overlays()`, `_unit_range()`, polygon clipping, and boundary
  intersection from `flowdesk_cli.batch_plot` into a GUI-independent core
  module;
- call that function for both Batch and current-view export;
- preserve gate ID, color, width, and line style in the normalized result;
- use full-resolution analytical gate definitions, never display-downsampled
  events or editable Qt handle geometry; and
- gate normalization must not recalculate membership.

### 5. The Qt compatibility adapter has two conflicting contracts

`render_batch_plot_qt()` accepts both Qt-shaped fields (`title_lines`,
`title_colors`, `plot_area`, `scene_metadata`, `gates`) and an optional prepared
core payload. When `prepared` is present, several Qt-shaped arguments are
ignored. This makes call sites appear correct while the effective scene lacks
those values.

The adapter also normalizes arrays separately from Batch preparation. It is
therefore not the Batch path even though both eventually call
`write_plot_png()`.

Required end state:

- one typed `PreparedPlotRenderPayload` in `flowdesk_core`, containing the
  prepared scene, keyed normalized layers, keyed event colors, semantic source
  order, draw order, canvas/options, and provenance;
- one core format dispatcher accepting only that payload plus output path;
- Batch and current-view call the same preparation service and dispatcher;
- Qt supplies a current-view snapshot and starts the service, but contains no
  title/color/tick/gate precedence logic; and
- remove the dual-mode compatibility branch after all callers migrate. Do not
  retain ignored parameters.

## Incremental implementation plan

Implement one increment per change. Run the Batch regression tests after every
increment. Do not combine the baseline freeze and behavior change in one
commit.

### Increment 0: Freeze current Batch behavior

Before refactoring production code, add characterization tests for the existing
Batch path:

1. single source and three-source manual overlay;
2. distinct blue/red/green source colors and Sample Sheet titles;
3. Log10 X/Y transforms with `10^n` and `m x 10^n` ticks;
4. rectangle and polygon gates crossing and not crossing plot boundaries;
5. custom long X/Y labels and one/two/three-line titles;
6. 600x600 at 96 and 300 DPI with `dpi_scaled`; and
7. PNG plus at least one vector format.

Record and assert Batch `semantic_source_order`, source styles, title
text/colors, axis text, normalized ticks, normalized gate points/style,
view range, plot rectangle, scene hash, displayed-event count, and point-plan
hash. Use small synthetic FCS fixtures. External real FCS/project paths may be
used for local evidence but must not be committed.

Acceptance: all new tests pass before any Batch preparation code moves.

### Increment 1: Add the typed core payload

Add a frozen GUI-independent payload with explicit coordinate-space and order
fields. Require unique source IDs and exact layer/color alignment. Reject
missing, duplicate, non-finite, or positionally ambiguous input.

Do not change a writer or Batch call site in this increment. Add serialization,
validation, and deterministic hash tests only.

### Increment 2: Extract Batch preparation without behavior changes

Move transform-aware tick generation, persisted/current range resolution, gate
normalization/clipping, source-style resolution, title resolution, normalized
layer preparation, and render dispatch from `flowdesk_cli.batch_plot` into a
core service. Batch remains the first caller.

Compare Increment 0 sidecars and images before/after. Scene hashes, title and
axis strings, normalized gates/ticks, source orders, event counts, and point-plan
hashes must be identical. If any Batch output changes, stop and fix the
extraction before proceeding.

### Increment 3: Define one current-view snapshot

Create a display-only snapshot carrying:

- active sample ID;
- semantic source order from the same model used for GUI titles;
- painter/source draw order from rendered layers;
- rendered arrays keyed by source ID;
- X/Y parameter and transform IDs plus coordinate-space declaration;
- live finite ViewBox range;
- live axis labels, tick policy, and canvas/layout measurements;
- current Sample Sheet titles and overlay colors by source ID; and
- gate-definition IDs, not Qt handle positions.

The snapshot builder may query Qt geometry, but it may not resolve scientific
transforms, gate geometry, title precedence, or export styles.

### Increment 4: Route current-view export through the Batch core service

Convert the snapshot to the same `PreparedPlotRenderPayload` used by Batch and
call the same core dispatcher. Remove positional `zip(source_ids, layers)` and
all duplicate title/color/tick/gate construction from
`MainWindow._current_plot_export_metadata()` and
`MainWindow._export_current_plot_core()`.

Do not import CLI code into Qt. The shared service belongs in `flowdesk_core`.

### Increment 5: Remove the legacy split path

After PNG/JPEG/SVG/PDF callers migrate:

- remove or reduce `render_batch_plot_qt()` to a thin typed-payload forwarder;
- delete the `prepared is None` reconstruction branch;
- delete ignored Qt-shaped parameters;
- audit direct `PlotWidget.export_png()`, `export_jpg()`, and vector export
  paths and remove or redirect any remaining user-facing split path; and
- keep screenshot/grab APIs for tests only, never publication export.

### Increment 6: End-to-end parity verification

For the same saved/in-memory definition, produce a Batch PNG and a right-click
PNG. Compare:

- title line text, order, and RGB color;
- semantic source order and draw order independently;
- dot color, alpha, size, and point-plan hash;
- X/Y label text and complete bounding boxes inside the canvas;
- tick label text, major/minor status, and normalized positions;
- gate ID, normalized geometry, style, color, and width;
- view range and plot rectangle; and
- normalized 96/300-DPI images with a documented pixel tolerance.

Also capture a GUI screenshot and compare the same structural measurements.
Image pixels alone are not the source of truth; sidecar scene equality is
required. Platform font antialiasing may use a tolerance, but text/order/color,
scene geometry, and gate/tick coordinates require exact equality.

## Batch-protection rules

- Treat current Batch output as the baseline until Increment 2 proves exact
  equivalence.
- Do not alter Batch defaults, naming, queue behavior, worker scheduling,
  collision policy, vector-scatter mode, DPI semantics, or file manifests.
- Do not make Batch depend on PySide6, pyqtgraph, monitor DPI, widget geometry,
  or screenshots.
- Do not fix current-view parity by changing global writer constants until the
  two paths demonstrably provide the same payload.
- Preserve the processing order and raw-event immutability.
- Display filtering of NaN/Inf may remove only unrenderable points. Record
  input and displayed counts; never change membership/statistics.
- If a migration is needed for `source_draw_order`, default old projects to the
  former Batch `source_order` so old Batch images remain unchanged.

## Forbidden shortcuts

- Do not reorder `rendered_overlay_ids` merely to repair titles. That would
  still couple semantic order to painter order and can change point occlusion.
- Do not hard-code larger left/top margins for the reported screenshot. Layout
  must use measured font metrics and the requested logical canvas.
- Do not replace Log10 labels after rendering or infer them from screenshot
  pixels. Generate ticks from transform ID, transform definition, bounds, and
  tick policy before dispatch.
- Do not draw gates from Qt handle coordinates. Normalize analytical gate
  definitions through the same core function as Batch.
- Do not repair current-view export by changing writer-wide constants or Batch
  defaults. First make both callers provide an equivalent payload.
- Do not keep a fallback that silently reconstructs a second scene when fields
  are missing. Payload validation must report the missing or inconsistent
  source ID, coordinate space, transform, tick, gate, or layout field.

## Required tests

- Core payload validation and deterministic hashing.
- Batch characterization tests from Increment 0.
- Semantic-order versus draw-order overlay test.
- Log10 tick parity test preventing linear `2,4,6` fallback.
- Rectangle/polygon normalized-gate parity test.
- Long-Y-label non-clipping test at 600x600, 96 and 300 DPI.
- Current-view adapter and Batch service sidecar equivalence.
- PNG normalized-image comparison and SVG/PDF structural comparison.
- Scientific invariance: memberships, counts, frequencies, statistic values,
  and raw events are identical before and after export.

## Verification commands

```bash
python -m pytest tests/test_cli_batch_plot.py tests/test_plot_export_reuse.py -q
python -m pytest tests/gui/test_qt_plot_export.py tests/test_qt_plot_widget.py -q
python -m pytest -m "not gui" -q
ruff check src tests
```

Where available, run the real project locally and retain uncommitted comparison
artifacts under `artifacts/gui/`; do not add external FCS files to Git.

## Acceptance criteria

- GUI, right-click export, toolbar export, and equivalent Batch export show the
  same blue/red/green title order and source colors.
- Long Y labels remain fully inside the output canvas.
- Log-transformed axes retain the same `10^n` tick labels and positions.
- Every visible GUI gate appears in export with matching geometry and style.
- Batch characterization output remains unchanged.
- No scientific result or project analysis revision changes because of export.
