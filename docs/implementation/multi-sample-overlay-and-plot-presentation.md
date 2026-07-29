# Multi-Sample Overlay and Plot Presentation

Spec: `S09`, `S10`, `S13`, `S24`
ToDo: `Phase B7.1`

## Goal

Allow one persisted plot to compare explicitly selected populations from multiple samples
and to use one validated presentation definition in GUI preview, PNG/SVG/PDF export,
Layout, and later Template reuse.

The feature is display-only. It consumes stable project definitions, full-length
pipeline memberships, and GUI-independent display preparation. It must never change
channel identity, transforms, gate membership, counts, frequencies, statistics, or raw
events.

Implement only one numbered increment from this guide per LLM/Codex run. Do not combine
model/schema work, source-selection GUI, full style editing, and renderer integration in
one run.

## B7.1 foundation and post-completion audit correction

The checked B7.1 history covers typed cross-sample source and presentation models,
compatibility resolution, generic editors, definition-only Undo/Redo, persistence,
provenance, export metadata, and their focused tests.

A later static end-to-end audit found that the normal live plot does **not** consume the
persisted `view["overlay_sources"]` list. `MainWindow._render_manual_overlays()` constructs
layers from Samples-pane manual and comparison selections instead. The advanced editor
therefore changes and saves a definition that is not the source of live plot layers.
Metadata/round-trip tests do not establish live renderer integration.

Until Phase B7.4 supplies live-layer, reload, and export E2E evidence, the advanced action
must be disabled and labelled `(Not implemented)` in development/alpha builds, hidden in
release builds, and moved from Analysis to Plot/View. Existing persisted definitions are
preserved unchanged. See
[`analysis-workflow-integration.md`](analysis-workflow-integration.md). Routine manual
overlay through the Samples-pane `Ov` controls remains the supported workflow.

## Inspect first

Read completely before implementation:

- `AGENTS.md`
- `specs.md`: `S09`, `S10`, `S13`, `S24`
- `ToDo.md`: `Phase B7.1`
- `docs/implementation/llm-task-protocol.md`
- this guide
- `docs/implementation/graph-window-v2.md`
- `docs/implementation/overlay-and-backgating.md`
- `docs/implementation/layout-editor.md`
- `docs/implementation/preferences-and-accessibility.md`
- `src/flowdesk_core/models.py`: plot/overlay definitions
- `src/flowdesk_core/display_data.py`
- `src/flowdesk_core/overlays.py`
- `src/flowdesk_core/channels.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/plot_style.py`
- plot composition/persistence code in `src/flowdesk_qt/main_window.py`
- project schema, migrations, plot/overlay/storage/export tests

Read the `qt-plot-widget`, `scientific-review`, and, where rendering downsampling or
large overlays are changed, `performance-benchmark` skills.

## B7.1 implementation boundary

The repository retains the B6/B7 foundation and has completed the B7.1 extension:

- `PlotViewSpec` persists population, X/Y parameter IDs, transform IDs, plot type,
  viewport, free-form style, aggregation, and rendering-downsample fields.
- GUI-independent display preparation supports dot/scatter, histogram, CDF, density,
  pseudocolor, and contour data contracts.
- `OverlaySpec` persists multiple population IDs for one parameter, normalization,
  bins, and free-form population style dictionaries.
- overlay/backgating preparation reads full-length `ExecutionReport` memberships and
  does not re-evaluate gates in Qt.
- the 2D display layer can render multiple prepared layers with population color/alpha.
- `PlotStyleSettings` can change GUI-local scatter color/size/opacity, background,
  gate outline/fill color, grid, and range behavior without changing analysis.
- plot view/overlay/backgating dictionaries are included in MainWindow project
  save/load state.
- PNG/SVG/PDF widget export and a basic JSON sidecar exist.

The B7.1 extension adds stable source/sample/Population/axis/transform identity, typed
presentation and support validation, generic source and full presentation editors,
compatibility diagnostics, definition-only Undo/Redo, shared GUI/export resolution,
Layout/Template reuse contracts, persistence, and provenance.

These capabilities must remain compatible. They intentionally do not provide B7.2's
dedicated Samples `Ov`/Color/Relation controls, Gate hierarchy Population Color column,
plot-area context appearance menu, generalized Comparison Sets, or automatic paired
overlay mode.

## Responsibility boundary with B6 and B7

Phase B6 owns plot types, viewport, display aggregation, duplicate view state,
interaction modes, and the initial raster/vector export foundation.

Phase B7 owns population overlay/backgating definitions, normalization, membership-based
display preparation, basic layer style dictionaries, and the initial display-layer API.

Phase B7.1 owns:

- stable cross-sample overlay source identity and compatibility;
- source-list editing and ordering;
- a typed plot presentation model and editor;
- one presentation resolution path for GUI/export/Layout;
- complete presentation persistence and provenance.

Phase B7.2 owns integrated daily-operation controls, active/manual/automatic state
separation, Population presentation colors, Comparison Sets, route deduplication, and the
additional color-precedence contract. It reuses the B7.1 definitions and editors rather
than replacing them.

B7.1 extends B6/B7. It must not rewrite their completed history or introduce a second
gate/statistics implementation.

## Source identity model

Add a typed source definition, either by extending `OverlaySpec` compatibly or by adding
an `OverlaySourceSpec` referenced by a new-version overlay definition. Minimum concepts:

```text
source_id
sample_id or template_source_role
population_id or template_population_path/role
display_name
x_parameter_id
y_parameter_id (optional for 1D)
x_transform_id
y_transform_id (optional for 1D)
unit/semantic parameter evidence
visible
order
style override reference/value
```

Stable source IDs identify list entries and Undo operations. Duplicate sample/population
sources are invalid unless an explicit use case and unique source IDs are supported.

The overlay source list is independent of `active_sample_id`. Changing the active sample
must not rewrite source sample IDs, source order, visibility, or style.

Population identity may be an explicit population ID. Template-oriented definitions may
also carry a mapping role/path, but must not silently replace an explicit missing ID at
runtime. The mapping result and evidence must be explicit.

## Compatibility resolver

Implement compatibility as a GUI-independent resolver. Qt displays its result and does
not guess channel mappings.

For every visible source, resolve:

1. sample ID or confirmed template sample role;
2. population ID/path and a current full-length membership;
3. stable X/Y parameter IDs for that sample;
4. transform IDs and transform semantics;
5. parameter semantic identity and unit compatibility.

Channel array order is not compatibility evidence. Use `ChannelSpec` stable identity and
existing channel-resolution rules.

Minimum resolver states:

- `compatible`: all required identities resolve uniquely and match the view contract;
- `incompatible`: identities resolve but parameter semantics, dimensions, transform, or
  unit cannot share the view;
- `ambiguous`: more than one mapping is plausible and user confirmation is required;
- `missing`: sample, population, membership, channel, or transform does not exist;
- `stale`: required membership does not match the current analysis revision;
- `error`: malformed definition or resolver failure.

Return stable diagnostic codes plus source/sample/population/parameter/transform context.
Do not convert missing/incompatible sources into empty arrays, zero events, `All Events`,
or the active sample. A true current population with zero events remains distinguishable
from a missing source.

All visible sources in one plot must resolve to compatible dimensions, semantic axes,
transforms, and units. A hidden source may retain an unresolved definition for repair,
but its unresolved status remains visible in the editor and export provenance.

## Scientific separation

Source selection and presentation definitions are display state. They may select which
already-computed memberships and values to render, but may not mutate:

- sample/channel identity;
- compensation, derived parameter, or transform definitions;
- gate definitions or memberships;
- population counts/frequencies;
- Statistic definitions/results;
- authoritative pipeline revisions.

Overlay preparation uses full selected memberships before display sampling. Scatter
rendering may downsample each resolved layer deterministically for display. Histogram
normalization, density aggregation, contour grids, counts, and statistics must not use
scatter-downsampled points unless a separately named display-only approximation is
explicitly specified and diagnosed.

## Plot presentation model

### Overlay title mode

The persisted `PlotPresentationSpec.title_mode` controls only title rendering:

- `overlay_sample_titles` (default) displays the active sample followed by visible
  overlay sample titles, joined with newline characters.
- `current_sample` displays only the active sample title.

The joined title is resolved at display time from the current sample annotations
and overlay state. It is not copied into the project presentation, so moving or
reconnecting FCS files does not create stale title data. The same display-only
resolution is used when the GUI applies the presentation; it does not change
pipeline inputs, gate membership, statistics, or result records.

Replace ad hoc unvalidated style usage with typed or strictly validated presentation
definitions. Analysis/view identity and presentation should be separate types even when
serialized together.

Minimum plot-level fields:

- title;
- optional subtitle or annotation;
- X axis display label;
- Y axis display label;
- plot background;
- legend visibility and position;
- ordered legend source IDs;
- title, axis-label, tick, and legend font settings;
- gate outline color, width, and line style;
- plot-type-specific colormap;
- automatic style assignment policy/version.

Minimum source-level fields:

- legend label;
- visible;
- color and alpha;
- marker shape and marker size;
- line color, line width, and line style;
- histogram fill color, outline color, and alpha;
- automatic/manual provenance per field or per source.

Colors require format and alpha validation. Sizes and widths require finite bounded
values. Enumerations must be explicit. Unknown or unsupported fields are preserved only
when migration compatibility requires it and are reported; they are not silently applied.

`x_parameter_id`/`y_parameter_id` and `x_axis_display_label`/
`y_axis_display_label` are distinct. Editing a display label changes rendered text only.
It must not change channel lookup, transform binding, gate coordinates, or scientific
results.

## Style support matrix

Define one validator/renderer support matrix and share it with the editor. The first
implementation may support fewer cells than the target, but unsupported cells must be
disabled with explanatory text or rejected with a diagnostic.

| Style group | Scatter/dot | Histogram/1D overlay | CDF/line | Density/pseudocolor | Contour |
|---|---|---|---|---|---|
| marker shape/size/color/alpha | supported | not applicable | optional/unsupported initially | not applicable | not applicable |
| line color/width/style | optional | outline | supported | not applicable | contour lines |
| fill color/alpha | not applicable | supported | optional/unsupported initially | colormap-driven | optional/unsupported initially |
| colormap | not applicable | not applicable | not applicable | supported | supported |
| title/axis/legend/fonts/background | supported | supported | supported | supported | supported |
| gate outline style | supported where geometry axes match | supported only when a meaningful gate overlay exists | same | supported where geometry axes match | supported where geometry axes match |

Density, pseudocolor, and contour style may be split into smaller subincrements inside
increment 3 or 4. Implement and test one renderer path at a time; do not mark the whole
increment complete while listed plot types silently ignore fields.

## Automatic styles and precedence

Automatic source styles must be deterministic for a stable source order and a versioned
palette/assignment policy. Reordering may intentionally reassign only automatic fields;
manual fields remain fixed unless the user explicitly resets them.

For a single visible source, an explicit population display color may override the base
dot color on an event-by-event basis. Once any non-base overlay source is visible, the
plot is a source comparison: render every source, including the active base source, in
one resolved source color and ignore all population/gating event colors. Keep gate
outlines independent. Apply this same rule in the live Qt preview and every batch export
format; it is display-only and does not affect memberships or statistics.

Resolve presentation values in this order:

1. explicit plot/view override;
2. project display default;
3. global user preference;
4. built-in default.

Retain provenance for each resolved value or coherent style block. Reset removes the
selected higher-priority override and reveals the next layer. It must not copy a global
value into every existing view or modify scientific definitions.

## Source-selection GUI

This section records the B7.1 editor target. It is not an authorization to expose the
current editor while its sources are absent from live rendering. Phase B7.4 further
restricts a future enabled advanced editor to a common active-plot parameter/transform
coordinate; arbitrary per-layer scientific axes require a separately documented
canonical mapping/calibration design.

Provide a stable-ID-driven editor with:

- source add from sample and Population hierarchy;
- explicit X/Y parameter and transform selection;
- remove, drag/button reorder, visibility toggle;
- compatibility status as text/icon plus details, not color alone;
- source legend label, base color, and alpha in increment 2;
- later access to full source style in increment 3;
- repair/relink action for missing or ambiguous sources;
- Cancel/Apply semantics appropriate to the selected command model.

Source add/remove/reorder/visibility and persisted style edits are display-definition
project mutations and must be Undo/Redo capable. Undo payloads contain definition data,
not event arrays, memberships, pipeline reports, active-sample navigation, or widgets.
Transient hover/selection in the editor is not project Undo state.

## Atomic rendering behavior

Resolve all visible sources against one immutable project/report revision before changing
the plot. Build prepared layers locally, then replace the complete layer list and legend
on the GUI thread. Do not show a new parent/source layer with old labels or style from a
different revision.

If one required visible source is invalid, keep the last valid plot only with an explicit
stale/error banner, or show a non-success placeholder. Do not present a partially missing
overlay as successfully complete unless an explicit partial-display policy is designed,
persisted, and diagnosed.

## Export contract

GUI preview and PNG/SVG/PDF export consume the same resolved presentation definition and
ordered source layers. Backend adapters may differ in antialiasing, font metrics, and
minor stroke rasterization, but must preserve semantic content.

Metadata sidecars include at least:

- plot/view/presentation IDs and definition version;
- ordered source IDs and visibility;
- source sample IDs or template roles;
- population IDs/paths/roles;
- X/Y parameter IDs and transform IDs;
- normalization/aggregation/rendering-downsample policy;
- resolved style plus automatic/manual/default provenance;
- font requests and actual fallback diagnostics when available;
- source compatibility/missing/stale diagnostics;
- software/pipeline version and authoritative/preview result provenance as applicable;
- an explicit statement that presentation settings and display sampling do not alter
  scientific results.

Do not claim pixel-identical output across Qt, SVG, PDF, platform font stacks, or
headless backends. Tests compare source order, labels, validated style semantics,
nonblank output, expected object/text presence, and diagnostics. A blank render, missing
required source, missing glyph that removes meaning, or backend exception is not success.

## Layout and Template reuse

Layout plot objects should reference a plot/presentation ID when live reuse is intended.
An intentional copy stores a new presentation ID plus `copied_from` provenance. Layout
may override scene bounds, clipping, caption, or selected presentation fields, but uses
the same resolver and renderer-neutral definition. It does not independently calculate
overlay memberships, normalization, or statistics.

Project-specific overlay sources may use sample IDs. A reusable Template may instead use
explicit source roles, Group/sample selectors, population paths/roles, and parameter
roles. Template application produces a mapping plan with exact/suggested/ambiguous/
missing states. Ambiguous mapping requires user confirmation; missing required sources
remain diagnostics and cannot be converted to zero events.

## Numbered implementation increments

### Increment 1: Model and compatibility contract

Implement model/schema/migration and GUI-independent resolver only.

- Add failing tests for typed source identity, typed presentation, stable ordering,
  validation, compatibility diagnostics, and round trips before production changes.
- Extend the existing model compatibly; define migration from B6/B7 population-only
  overlays without inventing sample identity when it cannot be known.
- Resolve channel-order differences by stable identity.
- Separate axis display labels from parameter IDs.
- Add the support matrix and style validation contract.
- Preserve the authoritative `ExecutionReport` and existing overlay preparation APIs;
  compatibility wrappers contain no second scientific implementation.

Non-goals: no new widget/editor, no source-list GUI, no full renderer restyle, no Layout
integration.

### Increment 2: Overlay source selection GUI

Implement source-list editing and basic source presentation only.

- Add/remove/reorder/toggle sources using stable IDs.
- Select sample, Population, parameter, and transform.
- Show resolver states and structured diagnostic details without silent fallback.
- Edit basic legend label, color, and alpha.
- Persist changes through display-definition commands with Undo/Redo.
- Verify selection edits do not mutate scientific definitions or trigger scientific
  calculation in Qt.

Non-goals: no complete plot style editor, no new export renderer, no Layout integration.

### Increment 3: Plot style editor

Implement shared plot/source style editing and display-only preview.

- Title, subtitle/annotation, independent axis display labels, legend order/visibility/
  position.
- Marker, line, histogram fill/outline, plot background, gate outline, colormap, fonts.
- Automatic/manual provenance and reset behavior.
- Shared support-matrix validation and clear unsupported-state UI.
- Split density/pseudocolor/contour into explicit subincrements if needed; do not mark
  increment 3 complete until its declared support matrix is implemented and tested.

Non-goals: no Layout/Template completion and no alternate scientific executor.

### Increment 4: Renderer, export, persistence, and reuse

Complete one-definition rendering and project/report reuse.

- Resolve presentation defaults and provenance.
- Use the same resolved definition in GUI and GUI-independent/headless export adapters.
- Complete PNG/SVG/PDF sidecars and failure diagnostics.
- Restore/duplicate plots through project save/load.
- Integrate references/copies with Layout.
- Define and test Template source-role mapping.
- Add GUI/headless/export consistency and font-fallback tests.

Do not complete this increment if any required backend silently omits a visible source or
supported style.

## Required tests

The tests below are necessary model/editor/export tests. In addition, Phase B7.4 requires
an E2E assertion over actual live plotted layers/data. A dialog state, project JSON, or
metadata sidecar assertion cannot satisfy that renderer acceptance test.

- Overlay at least two populations from different samples.
- Resolve correct axes by stable channel identity when sample channel order differs.
- Never silently fallback for ambiguous, missing, or incompatible channels/transforms.
- Save/load source add, remove, reorder, and visibility.
- Save/load source color, alpha, marker, and legend label.
- Save/load title, independent axis display labels, and legend settings.
- Verify axis display-label edits leave parameter/transform IDs and scientific output
  unchanged.
- Verify plot style edits leave gate membership, count, frequency, and Statistic results
  unchanged.
- Verify rendering-downsample changes leave all scientific values unchanged.
- Verify GUI preview and PNG/SVG/PDF use identical source order, labels, and supported
  style semantics.
- Validate or diagnose unsupported style instead of silently ignoring it.
- Distinguish a missing source from a current zero-event Population.
- Restore overlay sources and presentation after project reload.
- Verify a Layout plot reference/copy matches the intended presentation definition.
- Diagnose font fallback in headless rendering and reject blank output or missing required
  sources as success.
- Verify editor compatibility state is distinguishable by text/icon, not color alone.
- Verify no GUI source/style operation changes the authoritative result revision.

## Target files by increment

Likely increment 1:

- `src/flowdesk_core/models.py`
- a small GUI-independent compatibility/presentation resolver module
- `schemas/project.schema.json`
- `src/flowdesk_storage/migrations.py`
- model, storage, channel-order, and diagnostic tests

Likely increments 2-3:

- new focused Qt editor modules rather than expanding `main_window.py` indefinitely
- `src/flowdesk_qt/main_window.py` composition/persistence callers
- `src/flowdesk_qt/plot_widget.py`
- GUI tests with stable object names

Likely increment 4:

- renderer-neutral resolved presentation module
- PNG/SVG/PDF adapters and metadata sidecar code
- Layout/Template models when their owning phases are available
- storage/export/GUI/headless consistency tests

Exact files must be confirmed at the start of each increment. If increment 1 requires
more than eight production files, split schema/migration from resolver implementation
without starting GUI work.

## Acceptance criteria

- Cross-sample sources are stable, explicit, ordered, and diagnosable.
- Display labels never replace stable parameter identity.
- Source compatibility uses stable channel identity and refuses ambiguity.
- Presentation is typed, plot-type-aware, persisted, and provenance-bearing.
- GUI/export/Layout consume the same resolved source order and presentation semantics.
- Missing or unsupported content is not silently dropped or converted to zero.
- Rendering downsampling and all style settings remain scientifically inert.
- Existing B6 plot types and B7 membership-based overlays/backgating remain compatible.
- One increment per agent run is preserved.

The advanced GUI action remains unavailable until persisted source edits also satisfy the
Phase B7.4 live renderer, simple/advanced synchronization, reload, and GUI/headless export
acceptance criteria.

## Verification

Each increment runs the smallest relevant baseline plus its new tests. Before marking the
phase complete, run:

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

Report backend/font limitations, unsupported style cells, performance limits, and the
next single increment. Never weaken scientific assertions to accommodate rendering.
