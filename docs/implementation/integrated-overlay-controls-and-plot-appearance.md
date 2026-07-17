# Integrated Overlay Controls and Plot Appearance

Spec: `S07`, `S09`, `S10`, `S24`
ToDo: `Phase B7.2`

## Goal

Move the common display operations used during daily gating into the plot area, Gate
hierarchy, and Samples pane while preserving the completed B7.1 source, presentation,
renderer, export, persistence, and generic-editor foundation.

This phase is display UX. It may select and style already-computed full-resolution
memberships, but it must not alter or duplicate scientific execution. Implement exactly
one numbered increment per LLM/Codex run.

## Current implementation boundary

Phase B7.1 already provides:

- `OverlaySourceSpec`, `PlotPresentationSpec`, `SourceStyleSpec`, stable source order,
  visibility, source style, and plot/view persistence;
- GUI-independent compatibility states for missing, ambiguous, incompatible, stale, and
  compatible sources;
- definition-only Undo/Redo commands for overlay sources and presentation;
- the advanced `Overlay Sources...` dialog and full `Plot Presentation...` dialog;
- shared presentation resolution, GUI/headless export metadata, and PNG/SVG/PDF
  foundations.

The current Samples pane is a single-selection `QListWidget`. It has no sample checkbox:
row selection changes `active_sample_id`. Therefore B7.2 adds a dedicated Overlay role/
column; it does not reinterpret an existing checkbox. If a future sample-enabled,
pipeline-target, or batch checkbox exists, that meaning remains independent.

The current Gate hierarchy has `Gate definition`, `Type`, `Axes / Scale`, and
`Expression` columns but no population color control. Plot appearance and sources are
reached through separate Analysis-menu dialogs. These integrated controls are unfinished
B7.2 work; B7.1 completion must remain checked.

The requested `src/flowdesk_qt/plot_presentation_editor.py` does not exist in the current
tree; `src/flowdesk_qt/plot_style_editor.py` is the implemented full presentation editor.

## Inspect first

Read completely before implementation:

- `AGENTS.md`
- `specs.md`: `S07`, `S09`, `S10`, `S24`
- `ToDo.md`: `Phase B7.1`, `Phase B7.2`
- `docs/implementation/llm-task-protocol.md`
- this guide
- `docs/implementation/gating-and-results-workspaces.md`
- `docs/implementation/graph-window-v2.md`
- `docs/implementation/overlay-and-backgating.md`
- `docs/implementation/multi-sample-overlay-and-plot-presentation.md`
- `docs/implementation/groups-and-annotations.md`
- `docs/implementation/preferences-and-accessibility.md`
- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/gate_editor.py`
- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/overlay_source_editor.py`
- `src/flowdesk_qt/plot_style_editor.py`
- `src/flowdesk_qt/plot_style.py`
- sample, overlay, plot view, presentation, and gate hierarchy core models, schema,
  commands, migrations, and tests

Read the `qt-plot-widget` and `scientific-review` skills. Read the performance guide if
layer resolution or high-volume rendering changes.

## Independent state contract

Keep these states separately observable and serializable at their stated scope:

```text
active_sample_id
display_population_id
selected_gate_id

manual_overlay_sample_ids
manual_overlay_colors
automatic_overlay_sources
comparison_set_definitions
overlay_mode

population_display_colors
plot_presentation
```

- `active_sample_id` selects the base sample. It is not an overlay checkbox.
- `display_population_id` selects the base membership shown in the plot.
- `selected_gate_id` selects the editable gate and its selection highlight.
- manual overlay state is persisted per plot/view and survives active-sample navigation.
- automatic sources are resolved from the active sample's Comparison Set and persisted
  relation definitions; they are not copied into manual checkbox state.
- population colors and plot presentation are display definitions, not gate definitions.

An explicit UI command may update more than one display field atomically, but no field
aliases another and navigation must not rewrite persisted sources or relations as an
undocumented side effect.

## Persistence ownership

Use existing B7.1 models when they express the contract. Add the smallest typed model only
where comparison relations, population presentation, or per-view manual selection cannot
be represented without ambiguity. Do not keep durable choices only in widgets.

| Setting | Persistence owner |
|---|---|
| population display color | plot/view or strategy presentation metadata |
| manual overlay checkbox | plot view |
| manual overlay color | sample × plot view source override |
| comparison set membership and member role | project metadata |
| comparison role default color | project display settings |
| background/title/font/legend/default events | plot presentation for the view |
| global initial appearance | user preferences |

Comparison metadata is reusable across plots, while each plot can retain different manual
sources and source-color overrides. Loading an old B7.1 project preserves every explicit
source and presentation definition. Migration must not infer that the active sample is a
manual overlay or convert a scientific Group to a Comparison Set.

## Plot context appearance interaction

Right-clicking an idle plot area opens a context menu equivalent to:

```text
Plot Appearance...
Background Color...
Edit Title...
Axis Labels...
Fonts...
Legend >
  Show Legend
  Position >
Default Event Style...
Reset View Appearance
```

`Plot Appearance...` opens the existing full editor or a shared facade over the same
`PlotPresentationSpec`. The context menu and Analysis menu dispatch the same commands and
must never create separate setting models. Quick actions edit the same view override.

The common surface exposes title, subtitle, X/Y display labels, background, font, legend,
default event color, dot size, and opacity. A reset removes the view override and reveals
the project/global/built-in value with provenance; it does not copy the lower value into
the view.

Context-menu activation is suppressed while a gate draw, rectangle/polygon creation,
ROI/handle drag, or active pan drag is in progress. A keyboard menu key or documented
shortcut reaches the same actions. Appearance changes are display-only and do not submit
a preview or pipeline run. GUI and PNG/SVG/PDF use the same resolved presentation.

Editing title or axis display labels never changes stable parameter IDs, transforms, gate
coordinates, membership, counts, frequencies, statistics, or analysis revision.

## Population presentation colors

Add a `Color` column to the Gate hierarchy:

```text
Gate definition       Type        Color
All Events             root
  rect_1               rectangle    ■
    singlets           polygon      ■
      viable           ellipse      ■
```

Clicking a swatch opens `QColorDialog`; Cancel leaves project and live state unchanged.
The row context menu offers:

- `Population Color...`
- `Gate Outline Color...`
- `Use Population Color for Outline`
- `Reset Population Color`

Population color is attached to the population presentation identity even though the
control appears beside its producing gate. It is not stored in `GateSpec` geometry or
membership. Gate outline color is a separate display field, with an explicit opt-in link
to the population color.

For the active sample base layer, choose a color per event from memberships produced by
the runner:

1. among containing populations, prefer greatest hierarchy depth;
2. for multiple containing populations at the same depth, prefer the lowest explicit
   persisted population display z-order;
3. if z-order is absent or tied, prefer stable hierarchy preorder as produced by the
   persisted gate list; use stable population ID as the final tie-breaker;
4. if no colored population contains the event, use the plot default event color.

Thus `GFP+ color > viable color > default event color` for `All Events / viable / GFP+`.
Sibling overlap is never blended or dependent on dictionary/set iteration. A future UI may
edit z-order, but Increment 3 must at least persist or deterministically derive it.

Selected-gate state does not overwrite population colors. Use outline width/style,
handles, and selection markers for selection. Changing any population or outline color
must leave gate ID, geometry, parent, membership, event count, frequency, statistics, and
pipeline revision unchanged.

## Integrated Samples overlay controls

Replace or adapt the current list with a stable-ID model/view that exposes at least:

```text
Ov | Color | Relation | Name
```

- row selection changes only `active_sample_id`;
- `Ov` toggles only membership in the view's manual overlay set;
- `Color` is a clickable swatch that opens `QColorDialog`; routine use does not require
  typing `#RRGGBB`;
- `Relation` shows Comparison Set/control role using text/icon in addition to color;
- active, overlay, relation, warning, and error states have accessible text/tooltips;
- the active sample is excluded from resolved overlay layers. Disable its checkbox or
  explain in a tooltip that the base sample is already displayed.

The advanced Overlay Sources editor may retain hexadecimal input and complete per-source
sample/population/axis/transform/style editing.

### Simple source resolution

For each manually checked sample, create or update a B7.1-compatible source request using:

- the same stable population ID when available, otherwise the saved population path or
  explicit mapping role under the existing mapping contract;
- the current stable X/Y parameter IDs;
- the current X/Y transform IDs and semantics;
- the current plot type.

Do not silently fall back for missing population, ambiguous population path, missing
channel, incompatible unit, incompatible transform, stale membership, or unresolved
sample. Display a warning icon plus text/tooltip near the checkbox or row. A missing
source is not zero events and is not omitted as successful. A genuinely resolved current
population with zero events remains a distinct valid state.

Different populations or independently selected axes/transforms remain advanced operations
in `Overlay Sources...`. Both surfaces edit or derive from the same plot-view source state;
an advanced source that cannot be represented by the simple row remains visible with an
`Advanced` relation/status rather than being destroyed by a checkbox refresh.

## Persistent control overlays

Manual checked state is view-persistent and therefore supports positive control, negative
control, and reference overlays while the active sample changes. Do not add a separate Pin
column unless an implementation increment proves that one checkbox cannot express the
mode contract; document that evidence before adding Pin.

Optional sample-row actions are:

```text
Use as Persistent Overlay
Set Overlay Role >
  Positive control
  Negative control
  Reference
Clear Overlay Role
```

The role supplies human-readable relation state and automatic display style. It never
changes `SampleGroupSpec`, treatment/control analysis grouping, strategy binding, gate
strategy, compensation assignment, or statistics.

## Comparison Sets and overlay mode

Persist a generalized display relation, not a pair-only tuple. A conceptual definition is:

```text
comparison_set_id: dose_001
members:
  - sample_id: vehicle
    role: reference
  - sample_id: low
    role: target
  - sample_id: high
    role: target
```

One-to-one sets may be labelled `Pair` in the UI. The model supports one-to-many without
schema reinterpretation. Comparison Sets are display/navigation metadata and must not be
stored as or automatically converted to scientific Groups.

With multiple selected sample rows, the context menu provides:

- `Create Comparison Set...`
- `Pair Selected Samples...`
- `Add to Comparison Set...`
- `Edit Comparison Relation...`
- `Remove from Comparison Set`

The normal mode selector offers `Manual only` and `Manual + comparison set`. Add
`Comparison set only` only if a demonstrated workflow requires it; avoid mode proliferation.

`Manual + comparison set` resolves the union of manually checked samples and all other
members of the active sample's Comparison Set. When the active sample changes, re-resolve
that set. The active sample is removed from the source union after resolution.

## Deduplication and style precedence

Canonicalize resolved sources by stable sample plus resolved population/axes/transforms/
plot type identity. If the same sample/source arrives through manual, persistent control,
pinned/automatic legacy, or comparison routes, draw it once.

Resolve route-level source definition and label in this order:

```text
manual source override
> comparison source override
> comparison role style
> automatic source style
```

Resolve the final event color in this order:

1. explicit overlay source color;
2. comparison role color;
3. sample automatic overlay color;
4. population/gate display color;
5. plot default event color.

Overlay source color applies uniformly to that overlay and therefore outranks population
color. If it is absent, fallback may use automatic or population style. Expose whether a
fallback occurred and the resolved style provenance in the advanced editor/status and
export sidecar.

Example: the active sample uses per-population colors, a positive-control overlay uses one
blue overlay color, and a negative-control overlay uses one gray overlay color.

Deduplication must be deterministic before rendering, legend construction, or export.
Manual overrides win conflicting route labels/styles. Remaining ties use Comparison Set
order, then stable source/sample ID; they never depend on selection order or hash order.

## Atomic rendering and failure behavior

Resolve manual and automatic candidates, remove the active sample, deduplicate, validate
compatibility, and resolve style against one immutable project/report revision. Replace
the complete layer list and legend together on the GUI thread. Qt must not re-gate an
overlay source.

For an invalid required visible source, retain the last valid plot with a visible stale/
error banner or show a non-success placeholder according to the existing B7.1 atomic
rendering policy. Do not display a silently incomplete overlay as success.

## Numbered implementation increments

### Increment 1: Interaction-state and precedence contract

Implement typed GUI-independent state and resolution contracts only.

- Add failing tests first for active/manual separation, display-only population color,
  generalized Comparison Sets/roles, source deduplication, style precedence/provenance,
  round-trip, and old B7.1 defaults.
- Reuse B7.1 types and commands where sufficient; add only the missing typed project/view
  fields and migration defaults.
- Define persistence ownership and preserve unknown/newer fields according to the project
  migration policy.
- Confirm mutations do not change gate definitions, report values, or pipeline revision.

Non-goals: no context menu, Samples columns, Gate hierarchy Color column, QColorDialog,
automatic paired-overlay GUI, renderer change, or advanced-dialog removal.

### Increment 2: Plot context appearance menu

Implement shared quick commands and conflict-safe plot context activation. Reuse the full
presentation editor and command path. Test display-only behavior, keyboard access,
save/load, and GUI/PNG/SVG/PDF semantic agreement.

Non-goals: no Samples overlay columns, population color column, or Comparison Set GUI.

### Increment 3: Gate hierarchy population colors

Implement the Color column, swatch/dialog, row actions, deterministic deepest-descendant/
sibling resolution, separate outline link, and separate selection highlight. Add
full-membership color-assignment tests and scientific-invariance tests.

Non-goals: no Comparison Set GUI or change to gate evaluation.

### Increment 4: Samples manual overlay controls

Implement dedicated Ov/Color/Relation/Name roles, persistent manual controls, simple
source resolution, diagnostics, active-sample exclusion, advanced-dialog synchronization,
and renderer/E2E connection.

Non-goals: no automatic Comparison Set overlay yet and no removal of generic editors.

### Increment 5: Comparison sets and automatic paired overlays

Implement project Comparison Sets/roles, row context operations, the minimal mode
selector, union resolution, deduplication, route/style precedence, active-sample updates,
and pair/one-to-many/missing-member tests.

### Increment 6: Persistence, export, migration, and final UX cleanup

Complete reload, old-B7.1 migration, GUI/PNG/SVG/PDF/sidecar parity, accessibility,
strict Qt teardown, menu cleanup, user guide, and screenshots. Keep advanced editors for
their declared responsibilities.

## Required tests

### Plot appearance

- Open the appearance editor from a plot-area context menu.
- Change background, title, axis labels, fonts, legend, and default event style.
- Verify no pipeline/preview run and no changes to parameter ID, gate membership, or
  statistics.
- Restore after project reload and reproduce semantics in PNG/SVG/PDF.
- Suppress the menu during pan drag, gate drawing, and ROI drag.

### Population color

- Select/reset population color from Gate hierarchy.
- Prefer deepest descendant color.
- Resolve overlapping same-depth siblings deterministically.
- Keep selected-gate highlight separate.
- Verify gate definition, membership, count, frequency, statistics, and revision are
  unchanged.

### Manual and control overlays

- Toggle a different sample through the dedicated Overlay checkbox and edit its adjacent
  swatch.
- Never draw the active sample twice; preserve manual sources when active sample changes.
- Preserve positive/negative/reference overlays across navigation without changing Group
  or analysis binding.
- Prefer explicit overlay color to population color and use fallback only when unset.
- Resolve same path/stable axes/transforms and diagnose missing/incompatible sources as
  non-success, distinct from zero events.
- Synchronize simple state with the advanced Overlay Sources editor without losing
  advanced-only definitions.

### Comparison Sets

- Create a pair from two samples and resolve the partner in both navigation directions.
- Save/reload a one-to-many set.
- Use manual and comparison overlays together.
- Draw a duplicate reached through multiple routes only once.
- Resolve role color and source override deterministically.
- Diagnose a missing member rather than omitting it.

### Accessibility and lifecycle

- Convey active, overlay, relation, warning, and error state by text/icon as well as color.
- Give checkbox, swatch, relation icon, context actions, and diagnostics stable object
  names, accessible names, and tooltips.
- Reach primary actions by keyboard.
- Cancelled QColorDialog does not mutate state.
- Close dialogs/windows without live QThreads or callback exceptions.

## Acceptance criteria

- Daily overlay, population color, and appearance operations are available in context,
  while advanced source/axis/transform editing remains available.
- All independent state fields are testable and survive their defined persistence scope.
- Active sample and overlay selection never alias; active sample is never double drawn.
- Comparison Sets remain separate from scientific Groups and bindings.
- Population color remains separate from gate geometry/membership and follows the defined
  deterministic overlap rule.
- Manual and automatic source union is deduplicated with inspectable style provenance.
- Missing/incompatible content is never zero, All Events, or a silent omission.
- GUI and exports consume the same resolved presentation and ordered sources.
- One increment per run remains mandatory.

## Verification

Run the smallest tests for the current increment. Before completing B7.2 run:

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

Report source-resolution diagnostics, remaining renderer/accessibility limitations, and
the next single increment. Never weaken scientific assertions for display convenience.
