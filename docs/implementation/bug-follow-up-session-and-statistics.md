# Bug follow-up: sample order, statistics, and project session commands

## Scope

This guide converts the current entries in `docs/bug.md` into four isolated,
implementable increments.  Each increment is GUI/session behavior only unless
explicitly stated otherwise.  It must not alter raw events, compensation,
transforms, gate membership, or statistic numerical formulas.

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
