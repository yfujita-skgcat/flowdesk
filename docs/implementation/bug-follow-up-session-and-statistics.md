# Bug follow-up: sample order, statistics, and project session commands

## Scope

This guide converts the current entries in `docs/bug.md` into four completed
GUI/session increments and links the later Statistics value-selection defect to
one dedicated multi-increment guide.  Each increment must not alter raw events,
compensation, transforms, gate membership, or valid statistic numerical formulas
unless its authoritative guide explicitly defines and tests a typed error result.

Read `AGENTS.md`, `docs/implementation/llm-task-protocol.md`, this guide, and
the listed files before editing.  Implement exactly one increment per LLM run.

## Shared acceptance rules

- Preserve stable sample IDs, the order of samples in saved project manifests,
  and PipelineRunner's deterministic project-order merge.
- Do not rely on screen coordinates or fixed delays in GUI tests.
- Use stable Qt object names for new controls and verify callback teardown.
- Update `docs/user-manual/user_manual.md` in the same increment whenever the
  user-visible behavior changes.

## Increment 1 — Reorder samples deliberately

### Problem and current behavior

`SampleBrowser` owns canonical order in its private `_samples` list; that list
is serialized by `MainWindow._build_project_manifest()` and is also used by
headless execution and exports.  The current `Name`/`Path`/`Status` sort combo
mutates this canonical list.  There is no drag/drop or keyboard reordering,
and no callback for `MainWindow` to mark a project dirty after a reorder.

### Inspect first

- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/main_window.py` (`_build_project_manifest`, sample callbacks,
  save/load, and dirty-state helpers)
- `src/flowdesk_core/pipeline_runner.py` (project-order merge)
- `tests/test_pipeline_runner.py`, `tests/gui/test_gui_workflow.py`, and the
  relevant Sample Browser tests in `tests/test_qt_plot_widget.py`

### Required implementation

1. Add a canonical manual order and expose it as the default list mode.  Do not
   silently sort `_samples` just by selecting a display sort mode.  Either make
   sorting a display-only proxy or make choosing Name/Path/Status explicitly
   change the saved order; document the chosen behavior.  Manual ordering must
   always be recoverable.
2. Add internal drag-and-drop reordering to the sample list.  After a drop,
   update `_samples` by stable sample ID—not by display row/widget identity—then
   rebuild the list while retaining current sample, selected multi-selection,
   filter text, overlay IDs/colors/roles, and comparison sets.
3. Add keyboard movement using `Ctrl+Up` and `Ctrl+Down` (do not steal bare
   Up/Down, which remain selection navigation).  Move the current selected
   sample one visible/manual-order position; no-op at boundaries.  Multi-row
   moves must either be fully specified and tested or be disabled with a clear
   status message—never partially reorder an arbitrary selection.
4. Expose an order-changed callback.  `MainWindow` must mark the project dirty,
   refresh order-dependent views/groups, and preserve current sample identity.
   Reordering alone must not make scientific Results stale because it does not
   change values; it only changes deterministic presentation/execution order.
5. Save/load must round-trip the manual order.  Batch `{index}`, sample-sheet
   ordering, result/export ordering, and `PipelineRunner` merge order must use
   that same saved order.

### Required tests

- Drag/drop or direct list-model move updates the canonical sample-ID order.
- `Ctrl+Up`/`Ctrl+Down` move one sample, preserve bare-arrow selection behavior,
  and obey boundaries.
- Save/load and headless pipeline preserve reordered IDs and result order.
- Overlay state, active sample, and multi-selection stay attached to IDs.

## Increment 2 — Make Add Statistic parameter availability explainable

### Problem and current behavior

The parameter combo is intentionally disabled for count/frequency metrics by
`StatisticsEditorDialog._on_metric_changed()`.  Entries with invalid derived
definitions are also intentionally disabled from `ParameterCatalogEntry`.
Users therefore encounter an apparently unselectable parameter without a
distinction between metric policy, unavailable processed data, and invalid
definitions.  First reproduce the reported case before changing availability
rules.

### Inspect first

- `src/flowdesk_qt/statistics_editor.py`
- `src/flowdesk_qt/main_window.py` (`_open_statistics_editor` and catalog refresh)
- `src/flowdesk_core/parameter_catalog.py`
- `tests/gui/test_statistics_entrypoints.py`
- `tests/gui/test_parameter_catalog_gui.py`

### Required implementation

1. Add a visible, stable status/help label next to the parameter selector.
   It must state why selection is disabled: a count/frequency metric does not
   use a parameter; a derived parameter has invalid inputs; or no compatible
   acquired/derived parameters exist.
2. When a value metric is selected, enable the selector if at least one valid
   parameter exists.  Preserve an existing valid parameter selection when
   switching between value metrics.  Switching to count/frequency may clear
   the persisted parameter as today, but the UI must make that consequence
   explicit.
3. Keep invalid derived entries visible but disabled, with a tooltip containing
   the structured catalog diagnostic.  Do not enable an entry merely to make it
   selectable; the headless statistic definition must remain valid.
4. Audit the entrypoints from graph, Results, and the management dialog.  They
   must pass the same current `ParameterCatalogEntry` data and must not fall
   back to a stale/empty catalog when acquired channels are available.

### Required tests

- Count/frequency disables the combo with an explanatory message.
- Mean/median enables it and exposes acquired plus valid derived parameters.
- Invalid/missing derived parameters remain disabled with diagnostics.
- Graph and Results entrypoints preselect a valid current X parameter when one
  exists; a no-channel project gives an explicit empty-state message.
- Saving, loading, and headless statistic execution preserve valid selections.

## Increment 3 — Add Close Project without closing Flowdesk

### Problem and current behavior

Opening a project has a careful worker-cancellation and state-install path,
but File has no Close Project command.  Users cannot intentionally return to
an unsaved empty session while retaining the application window.

### Inspect first

- `src/flowdesk_qt/main_window.py` (`_load_project_from_path`,
  `_load_project_contents`, `closeEvent`, save/dirty/autosave helpers)
- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_storage/project.py` and recovery tests
- `tests/gui/test_gui_workflow.py`, `tests/test_project_storage.py`, and
  `tests/test_recovery.py`

### Required implementation

1. Add `File -> Close Project` with stable object name `actionCloseProject`.
   It closes the project session, not the application.
2. If the project is dirty, present Save / Discard / Cancel.  Save failure or
   cancellation keeps every current state value unchanged.  Never overwrite a
   project without the existing save confirmation behavior.
3. Refactor project-session clearing into one private helper used by Close
   Project and carefully separated from loading a different project.  It must
   cancel/release Pipeline and Batch workers, suspend/cancel preview, prefetch,
   processed-display, and density requests, clear event/display/result caches,
   samples, gates, annotations, definitions, overlays, groups, selected
   population/channels/view state, and stale diagnostics.
4. After success, create a fresh unsaved project identity, set `_project_path`
   to `None`, clear dirty/recovery association, and show an empty-session status.
   Do not delete the project bundle or recovery copy.
5. Opening FCS files/directory after Close Project starts a new unsaved project;
   opening another project must remain isolated from old asynchronous callbacks.

### Required tests

- Clean project closes into an empty session while the main window remains open.
- Dirty Save, Discard, and Cancel branches preserve the specified state.
- Running/cancelled workers do not survive a close-project transition.
- Save/load after closing opens a new bundle rather than overwriting the former
  project; recovery data is not deleted.

## Increment 4 — Clarify File import commands instead of removing them

### Investigation finding

`Open Directory...` calls `SampleBrowser.add_samples_from_directory()` and
loads FCS files found in one directory.  `Open Files...` calls
`add_samples_from_paths()` for explicitly selected FCS files.  They are useful
import commands and are distinct from `Open Project...`, which restores a
saved `.flowdesk` bundle.  Do not remove their functionality.

### Required implementation

1. Rename the File actions and toolbar action to make their add-to-current-
   session behavior explicit: `Add FCS Directory...`, `Add FCS Files...`, and
   `Add FCS Samples`.  Preserve shortcuts or update the user manual if a
   shortcut changes.
2. Add concise tooltips/status tips explaining that these commands add FCS
   samples to the current session; they do not open a saved project and do not
   clear existing samples.
3. Ensure their behavior after Close Project is an unsaved new session, while
   behavior in an existing project marks it dirty and leaves existing project
   path semantics explicit.

### Required tests

- Actions retain stable object names and invoke the current loading methods.
- Labels/tooltips distinguish FCS import from Open Project.
- Add-directory/add-files preserve existing samples and produce the documented
  dirty-state behavior.

## Increment 5 — Make derived-output statistic domains explicit

> **Superseding implementation guide:** the investigation and root cause below
> remain valid, but the user-facing design has been expanded after review.
> Implement this work only through
> [`statistic-value-selection.md`](statistic-value-selection.md).  Its unified
> `Statistic value` selector, four increments, compatibility matrix, and
> non-regression requirements are authoritative.  Do not implement the older
> three-control GUI instructions below independently.

### Reproduced problem and root cause

A statistic can select a valid derived output and still produce a `-` cell for
every sample/population after a successful `Run Pipeline`.  The reported
configuration has a derived definition whose **input source stage** is `raw`,
and a `mean` statistic whose **value domain** is also `raw`.

Those settings do not mean the same thing:

```text
derived source_stage = raw
  -> read the definition's input channels from immutable raw FCS events
  -> append the calculated output after compensation/derived processing

statistic source_stage = raw
  -> read only immutable raw FCS channels
  -> derived output channel does not exist in this table
```

The current runner reaches `_step_statistics()`, cannot find the derived
`parameter_id` in `data_by_stage["raw"].channel_ids`, and executes `continue`.
It therefore emits no `StatisticResult` and no diagnostic.  Results renders a
missing result as `-`, making this indistinguishable from an empty population
or a numerical undefined value.  The current Statistics editor also accepts
the incompatible combination and shows the unhelpful generic text `Select a
valid acquired or derived parameter...` even when the selected derived entry
is structurally valid.

This is a statistics-domain compatibility defect.  It is not solved by
rerunning the pipeline, changing the derived definition's input stage, or
using the definition ID instead of the output channel ID.  Downstream
statistics must continue to bind the derived **output channel ID**.

### Scientific and persistence contract

1. A derived definition with `source_stage="raw"` reads raw inputs, but its
   output remains a derived channel materialized after compensation.  Its
   output is valid for Statistics `compensated` and, with an explicit matching
   transform, `transformed`; it is never valid for Statistics `raw`.
2. Acquired parameters retain their existing domains: raw acquired channels
   may be measured in `raw`, compensated acquired channels in `compensated`,
   and transformed statistics require their explicit transform ID.  Do not
   change their values or silently coerce their selected domain.
3. A newly edited incompatible derived/raw statistic must not be saved.  The
   editor should select `compensated` automatically when the user selects a
   derived parameter while `raw` is active, and explain why.  The user may then
   intentionally select a valid transformed domain/transform where applicable.
4. Existing persisted derived/raw statistic definitions must **not** silently
   migrate to `compensated`: that would change a stored scientific definition.
   They remain loadable for repair, but headless execution must report an
   explicit per-statistic error rather than omit all results.
5. Every requested statistic/population/sample combination must produce either
   a `StatisticResult` or a structured execution failure.  A missing column
   must never be represented by a bare `continue`.

### Inspect first

- `src/flowdesk_core/models.py` (`StatisticSource`, `StatisticResult`, and
  undefined/error reason types)
- `src/flowdesk_core/parameter_catalog.py` (`ParameterCatalogEntry.kind`,
  `parameter_id`, `definition_id`, `source_stage`, and availability semantics)
- `src/flowdesk_core/pipeline_runner.py` (`_step_derived_parameters`,
  `_step_statistics`, and report/diagnostic merge)
- `src/flowdesk_core/statistics.py`
- `src/flowdesk_qt/statistics_editor.py` (parameter and value-domain combos,
  status text, persisted-definition loading, and validation)
- `src/flowdesk_qt/results_workspace.py` (missing/error cell formatting and
  tooltips)
- `src/flowdesk_qt/main_window.py` (`_open_statistics_editor` and manifest
  construction)
- `tests/test_pipeline_runner.py`, `tests/test_population_statistics.py`,
  `tests/gui/test_parameter_catalog_gui.py`, and
  `tests/gui/test_statistics_entrypoints.py`

Read `derived-parameter-editor.md`, `statistics-definitions.md`,
`analysis-workflow-integration.md`, `pipeline-runner.md`, and
`.codex/skills/derived-parameters/SKILL.md` before editing.  Also read
`.codex/skills/scientific-review/SKILL.md`: this change must make an invalid
domain explicit without modifying raw events, derived values, gates, or valid
statistic values.

### Required implementation

1. Add one GUI-independent compatibility resolver for a statistic parameter
   and requested value domain.  It must use stable `parameter_id`, not a
   display label or derived definition ID.  It returns the allowed domains and
   a stable reason/message.  Acquired entries preserve current rules; derived
   outputs allow `compensated` and `transformed`, never `raw`.
2. Apply that resolver in `StatisticsEditorDialog`.
   - When a valid derived parameter is selected while the domain is `raw`, set
     the draft domain to `compensated` before saving and show a clear status:
     `Derived outputs are evaluated from compensated/derived data; raw is an
     input source, not an output value domain.`
   - Disable or otherwise prevent selecting `raw` for a selected derived
     output.  Keep a stable object name and accessible tooltip/reason.
   - For an existing persisted incompatible definition, keep the selected
     values visible, mark the row invalid, and require repair before `OK`; do
     not overwrite it merely by opening the dialog.
   - Replace the generic valid-parameter status with a positive ready message
     that names the selected parameter and compatible domain.  Preserve the
     existing explanatory messages for count/frequency and invalid catalog
     entries.
3. Enforce the same contract in core/headless execution, not just Qt.
   - Remove the silent `col_idx is None: continue` behavior for a requested
     value statistic.
   - For an unavailable parameter/domain combination, append one result for
     each requested population with `status="error"`, `value=None`, and a
     precise stable reason such as `parameter_unavailable_at_source_stage`.
     Add the reason to the typed model/schema as needed; do not overload
     `empty_population` or `calculation_error`.
   - Emit a structured `ExecutionDiagnostic` with a stable code such as
     `statistic_parameter_unavailable_at_source_stage`, including sample ID,
     statistic ID, parameter ID, requested source stage, available channel IDs,
     and derived definition/output provenance.
   - Keep running other statistics and samples.  This invalid configuration is
     reportable per-statistic data, not a reason to discard unrelated results.
4. Make Results distinguish a missing historic result from an explicit error.
   The cell may still display `-`, but error color/status and tooltip must state
   the exact incompatibility and diagnostic/reason.  Do not calculate values in
   Qt or infer a zero.
5. Preserve project/CLI behavior.
   - New valid definitions persist their selected output channel ID and value
     domain unchanged through save/load.
   - Legacy incompatible derived/raw definitions load unchanged and are
     reported/repairable; no automatic scientific reinterpretation occurs.
   - CLI/Python API and GUI `Run Pipeline` produce the same result count,
     status, diagnostic code, and valid numeric values.
6. Update `docs/user-manual/user_manual.md`, this guide's implementation
   record, and the ToDo checkbox in the implementation commit.  Explain the
   distinction between a derived definition's input source and a statistic's
   value domain in user-facing terms.

### Required tests

- Core: raw-source ratio derived from two acquired channels, with a
  `compensated` mean statistic on its output ID, yields the hand-computed value.
- Core: that same ratio with a `raw` statistic produces exactly one error
  `StatisticResult` per targeted population/sample plus the stable diagnostic;
  it never disappears from the report.
- Core: acquired raw mean remains valid and numerically unchanged.
- Core: transformed derived statistic requires and uses its explicit transform;
  no double transform occurs.
- GUI: selecting a derived parameter changes an active raw draft to
  compensated, disables/rejects raw, and shows the specific ready/help text.
- GUI: an existing incompatible saved definition remains visible for repair and
  cannot be silently accepted unchanged.
- Results: explicit error cells have an error state and tooltip containing the
  source-stage incompatibility; a valid derived statistic displays a number.
- Save/load/CLI/Python API: output channel ID (not definition ID), domain,
  result values, error status, and diagnostics round-trip identically.
- Regression: a derived definition using raw *inputs* still computes correctly
  when its statistic uses the compensated value domain.

### Acceptance criteria

- The screenshot configuration cannot silently yield an all-`-` column after a
  successful pipeline.
- A user can see, before accepting the dialog, that `raw` is invalid for a
  derived output and why.
- Existing invalid projects remain recoverable and diagnostically explicit;
  valid scientific results are unchanged.
- No Qt widget performs derived expression evaluation, statistics calculation,
  or raw-event mutation.

## Implementation verification (2026-08-02)

- Increment 1 is implemented in `SampleBrowser` with stable-ID manual ordering,
  internal drag/drop, `Ctrl+Up`/`Ctrl+Down`, and a `MainWindow` dirty-state
  callback.  Reordering does not invalidate scientific Results.
- Increment 2 is implemented in `StatisticsEditorDialog` with a visible
  parameter-status explanation and regression coverage for count/frequency and
  value metrics.  Invalid catalog entries remain disabled.
- Increment 3 is implemented with `File -> Close Project`; it cancels project
  workers without shutting down reusable schedulers, clears project state, and
  creates a fresh unsaved session identity.  Dirty-state confirmation uses the
  existing Save/Discard/Cancel behavior.
- Increment 4 retains both FCS import paths and renames their visible actions to
  `Add FCS Directory...`, `Add FCS Files...`, and `Add FCS Samples`, with
  tooltips distinguishing them from `Open Project...`.
- Focused reorder, statistics, Close Project, and ruff checks pass.  A broader
  Qt GUI suite still has an existing intermittent native Qt teardown
  segmentation fault in an unrelated batch-export cancellation test; rerun
  that suite on the target CI platforms before release.
