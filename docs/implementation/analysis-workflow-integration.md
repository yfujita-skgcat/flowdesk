# Analysis Workflow Integration

Spec: `S02`, `S04`, `S05`, `S07`, `S09`, `S10`, `S11`, `S14`  
ToDo: `Phase B7.4`

## Goal

Finish the user-visible integration of analysis definitions without creating a second
scientific execution path. In particular:

1. acquired and derived parameters appear through one typed parameter catalog;
2. plots obtain compensation/derived/transform-aware data from the canonical runner;
3. the axis transform selector and the persisted analysis transform registry are one
   workflow, not two competing transform mechanisms;
4. statistic definitions are managed from Results;
5. sample titles and annotations are edited in one Sample Sheet surface;
6. analysis, data, results, and plot commands are placed according to their effect; and
7. Advanced Overlay is disabled until its persisted sources actually drive live
   rendering end to end.

Implement exactly one numbered increment per LLM/Codex run. Do not mark an increment
complete because a dialog opens or a definition round-trips. Its required execution,
rendering, persistence, error, and GUI/headless tests must also pass.

## Audited current boundary

The following is the implementation boundary at the time this guide was added:

- Derived definitions are persisted and executable by `PipelineRunner`, including use by
  downstream gates and statistics.
- `MainWindow._on_sample_selected()` supplies `sample.info.channels` to the axis selector.
  Derived outputs therefore do not appear in X/Y choices.
- `MainWindow._replot()` reads `_event_data`, and `_get_channel_index()` resolves the raw
  `SampleData.channels`. The normal plot does not consume the compensated/derived stage
  table that the runner uses.
- Transform and Statistic editors build parameter choices from acquired sample channels,
  not a shared acquired-plus-derived catalog.
- The legacy axis `linear`/`log`/`asinh` choice is not purely cosmetic: when no formal
  transform ID is bound, gate definitions retain the selected legacy scale and headless
  membership applies it. A formal analysis transform disables the legacy selector. This
  prevents simple double application but leaves two confusing authoring paths.
- Results `Add Statistic...` and Analysis `Population Statistics...` reach the same
  statistic editor.
- Sample Sheet title and Sample Annotations both persist through `AnnotationSpec`, but
  separate dialogs expose overlapping concepts.
- The live overlay path is built by `_render_manual_overlays()` from Samples-pane manual
  and comparison selections. Persisted `view["overlay_sources"]` is edited, saved, and
  included in export metadata, but it is not the source list used by this live renderer.

These are integration gaps. Earlier phase completion means the underlying models,
editors, resolvers, or core execution exist; it does not waive the acceptance criteria
in this guide.

## Non-goals

- Do not move compensation, derived expression evaluation, transforms, membership,
  statistics, or display downsampling algorithms into Qt.
- Do not add a second channel/parameter registry owned by widgets.
- Do not place processed arrays or caches in the project manifest.
- Do not mutate raw FCS event arrays.
- Do not silently convert a missing/stale/error derived output to zero or an acquired
  channel with the same label.
- Do not automatically calculate a statistic in transformed coordinates merely because
  the plot uses that transform.
- Do not enable arbitrary per-layer parameter or transform selection for overlay. A
  comparison plot must have common scientific axes.
- Do not delete or reinterpret persisted advanced overlay definitions while their UI is
  disabled. Preserve them for compatibility and diagnose them as inactive.

## Inspect first

Read completely before implementation:

- `AGENTS.md`, `docs/processing_pipeline.md`, and `docs/headless_execution.md`
- `docs/implementation/llm-task-protocol.md`
- `derived-parameter-editor.md`, `scientific-transforms-v2.md`,
  `statistics-definitions.md`, `groups-and-annotations.md`,
  `interactive-current-sample-preview.md`,
  `results-integrated-current-sample-recalculation.md`,
  `multi-sample-overlay-and-plot-presentation.md`, and
  `integrated-overlay-controls-and-plot-appearance.md`
- `.codex/skills/derived-parameters/SKILL.md`,
  `.codex/skills/qt-plot-widget/SKILL.md`, and
  `.codex/skills/scientific-review/SKILL.md`
- parameter, pipeline, preview, transform, statistic, annotation, plot-view, overlay,
  project-command, migration, and GUI test modules named below

If a change affects rendering volume or caches, also read the performance guide and
skill. If it changes project JSON, read `project-migration-and-recovery.md` before code.

## 1. Shared parameter catalog contract

Add one GUI-independent catalog/resolver for every parameter that may be selected by an
analysis or display definition. It is a derived view of the selected sample metadata and
the persisted project definitions; it is not a second persisted source of truth.

Each catalog entry must expose at least:

```text
parameter_id                 stable acquired channel or derived output ID
display_name
kind                         acquired | derived
unit                         optional, with provenance
source_stage                 acquired/raw or derived raw/compensated
definition_id                derived definition ID when applicable
expression                   display/provenance only; never evaluated by the catalog
input_parameter_ids
availability                 available | missing_input | stale | error | not_run
diagnostics                  stable codes and relevant sample/definition IDs
sample_id or applicability evidence
```

Rules:

- Identity is `parameter_id`, never display label, array position, or combo-box index.
- Acquired and derived entries may share a display label but may not share a stable ID.
- Catalog order is deterministic: acquired sample order first, then persisted derived
  display order. Dependency execution order does not reorder the UI.
- A derived entry remains visible when stale or in error. Disable selection where the
  consumer cannot execute it and show the reason; do not make it disappear.
- Cross-sample consumers must request an explicit compatibility resolution. A parameter
  present in one sample is not assumed present in another by name.
- The catalog validates/plans definitions through the existing safe derived planner. It
  does not evaluate event values.

All of these consumers must use the same catalog or a typed filtered view of it:

- X/Y axis selectors;
- Parameter/Channel Information;
- gate parameter selectors;
- Transform editor;
- Results statistic editor;
- simple overlay compatibility resolution;
- future advanced overlay and export planners.

The former Channels tab should become `Parameters` or `Channel / Parameter Information`
and show, at minimum, `Parameter`, `Type`, `Source`, `Expression`, `Unit`, and `Status`.
Acquired-only FCS metadata may remain in a detail panel.

## 2. Canonical processed display result

Qt must not append derived columns or reproduce pipeline stages. Add a synchronous,
GUI-independent request/result API before changing widgets. It may extend the current
preview/display-preparation contracts, but must not overload authoritative
`ExecutionReport` with a mutable GUI cache.

A request must identify:

```text
analysis_revision and immutable project snapshot
sample_id
population_id
x_parameter_id and optional y_parameter_id
x_transform_id and optional y_transform_id
plot type and display sampling policy
```

The core execution path must:

1. start from immutable `SampleData`;
2. apply compensation;
3. evaluate derived parameters;
4. resolve the requested transform definitions exactly once;
5. evaluate or reuse full-resolution membership for the same revision;
6. select the requested population from the full mask; and
7. only then prepare/downsample display coordinates.

The immutable result must include stable parameter/channel metadata, transformed display
coordinates or renderer-neutral prepared data, revision, population identity, sampling
provenance, and structured diagnostics. It must distinguish:

- `current` with zero events;
- `stale` revision;
- missing parameter/input/population;
- derived evaluation error;
- transform domain/convergence error; and
- unavailable sample.

Do not fall back to raw `_event_data` when a requested derived/compensated view fails.
Keep the last valid plot with a clear stale/error banner or show a non-success placeholder.
Never label that fallback as current.

## 2.1 Non-finite values are analytical QC, not a display detail

Derived expressions and transforms can create values outside their numerical domain:
`log(0)`, `log(negative)`, a ratio with denominator zero, overflow, and compensated
fluorescence below a log domain are distinct scientific conditions. Do not silently turn
them into a successful statistic by dropping the affected events.

The project model must persist an explicit non-finite policy for every value-based
statistic and derived definition. The default statistic policy is `strict`: any `NaN`,
`+Inf`, or `-Inf` in the selected population produces an `undefined` result with a stable
reason. `exclude_invalid` is an explicit opt-in policy, never an implicit consequence of
using a NumPy `nan*` function. It calculates from finite values only and records:

```text
n_total, n_valid, n_invalid, invalid_fraction,
non_finite_policy, undefined_reason
```

These fields belong in `StatisticResult`, Results, long/wide CSV/TSV exports, and export
provenance. A displayed numeric result without its valid-event denominator is incomplete.
`Inf` must never be treated as a large valid measurement.

Rendering may omit non-finite coordinates because graphics backends cannot place them.
It must instead expose a status/tooltip with affected count grouped by parameter ID,
derived expression/source stage, transform ID, and invalid reason. Gate membership for a
non-finite coordinate is false for that gate; the exclusion count is QC/provenance, not
a zero-event success or an unreported fallback.

The renderer-neutral display preparation emits `display_nonfinite_excluded` diagnostics
with `parameter_id`, expression, source stage, axis transform ID, and separate counts for
`NaN`, `+Inf`, and `-Inf`. Geometric gating emits `gate_nonfinite_excluded` diagnostics
with gate ID, axis parameters/transforms, and the number excluded from that gate. These
diagnostics are attached to the headless `ExecutionReport`, so GUI and CLI adapters can
show the same QC rather than inferring it from a downsampled image.

The derived stage also emits `derived_parameter_nonfinite_values` when an expression
successfully evaluates but produces non-finite values. The diagnostic preserves the
expression, output channel ID, selected non-finite policy, and reason-specific counts;
an expression-domain failure remains a separate `derived_parameter_evaluation_failed`
diagnostic governed by `invalid_value_policy`.

`log(x + 1)` is not a generic error recovery. It is a separate persisted expression,
appropriate only when `x` is a non-negative quantity and including zero has a documented
scientific meaning. For compensation-corrected fluorescence, which can legitimately be
negative, use an explicit asinh/logicle definition or a documented censoring/LOD policy.
Never introduce an epsilon, clipping, or `log(x+1)` migration automatically. Such a
choice must persist its constant, unit, rationale, policy/version, and provenance, and
must reproduce identically in GUI, headless runner, CLI, and export.

Required fixtures cover zero and negative log input, `log(x+1)`, division by zero,
overflow, all-invalid and mixed-valid populations, and raw-event immutability. Existing
projects retain their historical behavior through an explicit compatibility mode or a
confirmed migration; no silent change in NaN handling is allowed.

The current-sample scheduling rules remain latest-wins and revision checked. Worker
output is adopted atomically on the GUI thread, and window/project shutdown must leave no
thread running.

## 3. Derived parameter GUI integration

After a definition is accepted:

- the derived output immediately appears in Parameter Information with `not_run` or
  `stale` status;
- every catalog-backed selector refreshes without requiring project reload;
- selecting it on an axis requests canonical processed display data;
- selecting it for a transform or statistic stores its stable output ID;
- editing/deleting it uses dependency checks for transforms, gates, statistics, views,
  and other derived definitions;
- failures remain visible with diagnostics and do not silently switch an axis; and
- save/reload/CLI reproduces the same definition and scientific result.

Delete must be blocked while referenced, or use an explicit dependency-aware removal
operation that lists every affected definition. Do not cascade-delete silently.

## 4. One transform authoring workflow

The axis transform selector and `Manage Parameter Transforms...` edit/select the same
persisted transform registry.

User-facing axis control:

```text
Parameter: FL1-A
Transform: Linear | Log10 | Asinh | Logicle | Custom...
```

Required semantics:

- `Linear` means identity coordinates. It is represented by a formal identity definition
  or a documented null identity binding, not a second display-scale calculation.
- Choosing a non-linear quick option reuses an exact matching immutable `TransformSpec`
  for that parameter or creates a new versioned definition through a project command.
- `Custom...` edits complete parameters and previews with core forward/inverse APIs.
- A plot axis references the selected transform ID; a newly drawn gate captures that
  exact ID. Event display, gate coordinates, membership, inverse coordinate display, and
  ticks use the same implementation.
- Referenced transform definitions are immutable. Editing means duplicate/new version,
  followed by an explicit gate/view migration preview.
- No hidden legacy scale remains active underneath a formal transform.

For legacy projects, continue reading `gate.x_scale`/`gate.y_scale`. Provide an explicit,
tested migration to formal linear/log/asinh definitions that preserves membership and
gate geometry. Until migrated, show `Legacy Log10`/`Legacy Asinh` visibly. Never silently
rewrite legacy Logicle approximation to formal Logicle.

### Axis quick-transform implementation boundary

The visible X/Y `Transform` selectors are the normal authoring entry point. `Log10`,
`Asinh`, and `Logicle` create one versioned analysis `TransformSpec` for the selected
stable parameter through `MainWindow`; the widget itself only emits the request. The
core registry is then the only source used by plotting, gate creation, membership, and
ticks. `Linear` is the documented null/identity binding when no analysis transform is
registered. Once a parameter has a formal definition, changing it in place is blocked:
the user must use `Manage Parameter Transforms...` to create a new ID and the explicit
gate-migration preview. Hidden legacy `x_scale`/`y_scale` controls remain read-compatible
for old project fixtures only and are not visible as a new authoring workflow.

Statistics stay explicit. The default numeric domain is the persisted native source
stage (normally compensated values after derived evaluation, before display transform).
`mean(FL1-A)` must not become `mean(logicle(FL1-A))` when the user changes a plot. A
transformed statistic is allowed only when its `StatisticSpec` explicitly selects that
value space and transform ID.

`StatisticSpec.transform_id` is therefore required for `source_stage="transformed"`.
The runner materializes only that definition's parameter column with that exact
`TransformSpec`; it never applies every plot transform implicitly. Raw and compensated
statistics retain their native source values when a user changes a plot axis.

## 5. Results-owned statistic workflow

Remove the top-level `Analysis -> Population Statistics...` entry. Results is the
primary management surface:

```text
Add Statistic...
Edit Statistic...
Duplicate Statistic...
Remove Statistic...
Manage Statistics...
```

Population/graph context actions may remain as shortcuts, but they dispatch the same
project commands and validator. Selecting a Results population pre-fills its stable ID;
selecting a graph may pre-fill its parameter ID. There is one `StatisticSpec` collection
and one editor contract.

`Events`, `% Parent`, and `% Total` remain normal Results columns. Named count/frequency
specifications are created only when a persisted/exportable named result is requested.
For many custom statistics, offer a long-form detail table rather than an unrelated
second definition UI.

Every parameter selector uses the shared catalog, including derived outputs. Add/edit/
duplicate/remove marks dependent results stale and refreshes only through canonical
preview or Run Pipeline.

## 6. Unified Sample Sheet and annotation invalidation

Use one normal GUI surface under `Data -> Sample Sheet...`:

```text
Sample ID | File | Sample name | Title | Condition | Dose | Batch | ...
```

- Sample ID, file/path, FCS name, and FCS keyword sources are read-only.
- `Title` maps to the workspace `sample_title` annotation and affects display/export
  labels only.
- Other workspace/imported annotation columns may be editable and may be referenced by
  Group rules.
- `Columns...`, `Add Annotation Column...`, `Import CSV...`, find/replace, fill series,
  clipboard paste, Undo/Redo, and field-level diagnostics operate through the existing
  GUI-independent annotation commands.
- Advanced provenance/type editing may remain as an action inside Sample Sheet; do not
  keep a competing top-level `Sample Annotations...` command.

Invalidation must be dependency aware:

- changing only `sample_title` does not increment analysis revision;
- changing an annotation referenced by a Group membership/binding rule invalidates the
  affected assignments and results;
- changing an unreferenced annotation updates display/export metadata only;
- changing a rule or binding remains an analysis-definition change.

Never edit raw FCS metadata or bytes.

## 7. Menu and ownership contract

The normal menu should express effects, not implementation history:

```text
Analysis
  Run Pipeline
  Compensation...
  Derived Parameters...
  Manage Parameter Transforms...
  Analysis Groups...                 [Advanced]

Results
  Add Statistic...
  Manage Statistics...
  Export Results...
  Batch Plot Export...

Data
  Sample Sheet...
  Channel / Parameter Information...

Plot (or View)
  Plot Appearance...
  Overlay Samples
  Advanced Overlay Sources... (Not implemented)
```

Do not add duplicate data models when moving actions. Context actions and menu actions
must invoke the same command. Moving a display-only action must not increment analysis
revision or run the pipeline.

## 8. Advanced Overlay safety boundary

### Immediate behavior

Until end-to-end rendering is implemented:

- remove Overlay Sources from Analysis;
- in development/alpha builds, show
  `Advanced Overlay Sources... (Not implemented)` under Plot/View, disabled;
- set a tooltip/status tip explaining that Samples-pane `Ov` controls are the supported
  overlay workflow;
- in release builds, hide the action rather than exposing a disabled unfinished feature;
- do not instantiate the editor from an enabled action or imply Apply affected the live
  plot; and
- preserve existing persisted `overlay_sources` unchanged on load/save.

Use one explicit capability flag/build policy, not scattered environment checks. Add a
GUI test for label, location, enabled/visible state, tooltip, and the absence of project
mutation.

### Scientific scope of a future implementation

The active plot owns common X/Y parameters, transform IDs, dimensionality, range,
histogram bins, and normalization contract. Advanced sources may initially vary only:

- sample;
- population;
- label;
- color/opacity/style;
- visibility; and
- order.

Per-source arbitrary X/Y parameters and display transforms are not enabled. Different
sample channel IDs that measure the same quantity require an explicit canonical parameter
mapping. Different calibration functions are allowed only through a separate calibrated
common-unit definition followed by the common plot transform.

To enable the action, all of the following must exist:

1. one resolver combines simple and advanced source definitions deterministically;
2. visible sources are validated against common parameter semantics, units, transforms,
   plot type, binning, normalization, membership revision, and population intent;
3. invalid required sources make the render non-success, not silently partial;
4. resolved advanced sources create actual live layers and legend entries;
5. simple and advanced controls synchronize without deleting advanced-only state;
6. save/reload restores the same live plot;
7. GUI and PNG/SVG/PDF/headless export use the same ordered resolved sources; and
8. E2E tests inspect plotted layers/data, not only dialog state or sidecar metadata.

## Target files

Core/model candidates:

- `src/flowdesk_core/channels.py` or a focused `parameter_catalog.py`
- `src/flowdesk_core/pipeline_runner.py`, `preview.py`, and `display_data.py`
- `src/flowdesk_core/transforms.py`, `statistics.py`, `annotations.py`, and
  dependency/invalidation/project-command modules
- `src/flowdesk_core/overlays.py` only in the future advanced-rendering increment

Qt candidates:

- `src/flowdesk_qt/main_window.py`, `channel_selector.py`, and `channel_metadata.py`
- `src/flowdesk_qt/derived_parameter_editor.py`, `transform_editor.py`,
  `statistics_editor.py`, `results_workspace.py`, and `sample_sheet.py`
- `src/flowdesk_qt/sample_browser.py`, `plot_widget.py`, and preview scheduler/state
- `src/flowdesk_qt/overlay_source_editor.py` only after the capability is enabled

Storage/schema candidates:

- `src/flowdesk_storage/project.py`, schema, and migration modules when persisted
  transform bindings/menu capability require a format change

Tests:

- focused core tests for parameter catalog, pipeline display preparation, transforms,
  statistics, annotations, dependency invalidation, overlays, and project round trips
- GUI tests for derived axes, selector refresh/status, menu ownership, Results statistic
  workflow, unified Sample Sheet, disabled Advanced Overlay, rendering, revision handling,
  and strict teardown

## Numbered implementation increments

### Increment 1: Guard unfinished features and correct menu ownership

- Add the explicit build/capability policy for unfinished actions.
- Disable and relabel Advanced Overlay in development; hide it in release.
- Remove it from Analysis and route display commands to Plot/View.
- Remove Analysis Population Statistics and top-level Sample Annotations entry points;
  keep supported Results and Sample Sheet workflows reachable.
- Rename Analysis Transforms to Manage Parameter Transforms without changing its model.
- Add menu/object-name/tool-tip/no-mutation GUI tests.

This increment changes discoverability only. It does not claim derived-axis, transform,
Sample Sheet integration, or advanced overlay rendering is complete.

### Increment 2: Parameter catalog and information surface

- Add the GUI-independent typed catalog and diagnostics.
- Add catalog tests for acquired/derived order, duplicate labels, missing inputs, cycles,
  sample applicability, stale/error visibility, and save/reload reconstruction.
- Convert Parameter Information and every non-plot parameter combo to filtered catalog
  views, including Transform and Results Statistic editors.
- Keep selectors on the current stable ID across a refresh; otherwise show an explicit
  unresolved status rather than silently selecting the first channel.

### Increment 3: Canonical processed display request/result

- Add the synchronous core request/result and known-value tests first.
- Prove raw -> compensation -> derived -> transform ordering and raw immutability.
- Integrate with current-sample latest-wins revision scheduling.
- Convert the base plot to renderer-neutral processed data; remove raw `_event_data` as
  the scientific coordinate source while retaining raw input only as runner input.
- Test zero events, NaN, missing inputs, stale completions, errors, downsampling, and
  thread shutdown.

### Increment 4: Derived parameters on axes, gates, statistics, and simple overlays

- Supply X/Y selectors from the catalog and render a synthetic derived ratio.
- Create/edit gates on derived coordinates and match preview/batch/CLI membership.
- Define a transform and mean/median statistic on the same derived stable ID.
- Resolve the derived axis for a compatible simple overlay sample.
- Refresh statuses after edit/run/failure/reload without hiding failed entries.
- Add dependency-protected delete tests.

### Increment 5: Unified transform selector and legacy migration

- Replace the second legacy authoring combo with the single workflow described above.
- Add quick-create/reuse, immutable definition editing, and gate/view binding commands.
- Migrate legacy linear/log/asinh explicitly and verify geometry/membership equality.
- Test Logicle negative/zero regions, ticks, inverse coordinate display, no double
  application, project reload, and GUI/headless agreement.
- Prove a plot transform change does not alter a native-domain Statistic result.

### Increment 6: Results statistic and unified Sample Sheet workflows

- Complete Results-only add/edit/duplicate/remove/manage UX using the catalog.
- Merge title and arbitrary editable annotation columns into Sample Sheet.
- Add annotation provenance/type controls within that surface.
- Implement dependency-aware invalidation for title, referenced, and unreferenced fields.
- Test GUI/preview/batch/CLI/export equality and raw FCS immutability.

### Increment 7: Future Advanced Overlay end-to-end implementation

Do not start unless a concrete scientific workflow requires more than Samples-pane `Ov`
controls. Restrict its initial source differences to sample/population/style. Implement
the eight enablement conditions above, remove the capability guard only after all tests
pass, and document any canonical mapping/calibration feature in its own guide before
production code.

## Required acceptance tests

- A saved derived parameter appears in Parameter Information and every applicable
  selector, can be plotted on X or Y, gated, transformed, summarized, overlaid through
  the simple compatible path, exported, and reproduced by CLI/Python after reload.
- GUI plot coordinates and memberships equal the canonical runner for acquired and
  derived axes after compensation and transform.
- Changing a definition during work cannot let an obsolete processed result become
  current.
- There is one visible axis transform selector and one persisted transform registry;
  every new gate records the exact selected transform or identity binding.
- No transform is applied twice, and legacy migration preserves fixed membership
  fixtures.
- Plot transform changes do not silently change native-domain mean/median results.
- Statistic definition management is reachable from Results and not duplicated in the
  Analysis menu.
- Sample title and annotations are edited in one Sample Sheet; invalidation follows
  actual Group-rule dependencies.
- Advanced Overlay is disabled/hidden until persisted sources drive live layers,
  reload, and export through one resolver.
- No GUI scientific calculation, raw-event mutation, silent fallback, stale-as-current
  display, display-downsampled statistic, or live QThread remains.

## Verification

Run the smallest focused tests for each increment. Before completing Phase B7.4 run:

```bash
.direnv/python-3.12.13/bin/python -X faulthandler -m pytest -q
./tools/run-gui-tests.sh -q
.direnv/python-3.12.13/bin/ruff check src tests
.direnv/python-3.12.13/bin/mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

Record test commands, exit codes, remaining platform/display limitations, unresolved
scientific assumptions, and the next single increment. Do not weaken numerical,
membership, or stale-state assertions to make the GUI pass.
