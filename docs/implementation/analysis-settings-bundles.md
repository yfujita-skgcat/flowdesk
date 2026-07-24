# Analysis Settings Bundles

ToDo: Phase B8.1

## Goal

Allow a user to save reusable analysis definitions without copying FCS paths or
computed results, then apply those definitions to the samples already open in
another project.  A normal `.flowdesk` project must also be usable as an input
source for this operation.

This is an analysis-definition transfer feature, not a project merge, a sample
importer, or a cache/result restore mechanism.

## User workflow

1. `File > Save Analysis Settings...` writes an `.flowdesk-settings` directory
   bundle from the current project definitions.
2. `File > Load Analysis Settings...` accepts either an `.flowdesk-settings`
   bundle or an existing `.flowdesk` project bundle.
3. The dialog shows a preflight summary: source type/version, definitions to
   replace, definitions intentionally excluded, and channel/ID incompatibilities
   with the currently open samples.
4. After confirmation, Flowdesk atomically replaces the current project's
   analysis definitions while retaining its samples and their file references.
   It clears authoritative Results and Current Sample Preview, marks results
   stale, and requires `Run Pipeline` before Results/export are available.

The command must be disabled when there is no current project/sample session to
receive the settings.  Saving settings is allowed without samples only when all
definition references validate.

## Bundle format and boundaries

Use a directory bundle with the suffix `.flowdesk-settings`, not a JSON file
with a `.flowdesk` suffix.  Its root `manifest.json` has a distinct
`document_kind: "analysis_settings"`, an independent format version, creation
time, and optional non-authoritative source-project/version provenance.  It has
no sample paths, file fingerprints, raw events, execution reports, result
caches, recovery state, or selected-sample/UI session state.

The stored `analysis_definition` contains only reusable definitions:

- gating strategy data and its ordered population/gate hierarchy;
- analysis transforms and derived-parameter definitions;
- unbound compensation matrices and their provenance;
- statistics definitions, auto-gate templates, and plot views whose references
  are inside the exported definition.

It excludes sample IDs and paths, sample/group membership, annotations, gate
overrides, compensation bindings/calculation control assignments, batch-export
output paths, result rows/caches, plot display preferences, and project identity.
Those objects either identify a particular acquisition or cannot be applied to
another project's samples without a separate mapping decision.  A saved
compensation matrix remains available after import but is never implicitly bound
to a sample.

Loading an existing `.flowdesk` project uses the same extractor.  It therefore
does **not** copy its FCS references, Results, current-sample preview, or
sample-specific override/binding state.

## Import semantics

Version 1 is **replace, not merge**.  The target keeps its `project_id`, sample
catalog, paths, fingerprints, and target-only display/session state.  Reusable
definition collections are replaced as one validated state transition.  This
avoids silently choosing between colliding gate/transform/derived IDs and makes
the imported definition reproducible.

Before changing the target, core code must:

1. parse and validate the source document/project using its own version
   migration path;
2. extract a typed `AnalysisSettingsSpec` with no sample references;
3. validate all internal references (gate parent/transform/parameter,
   statistic population/parameter, derived dependencies, and matrix channels);
4. resolve every referenced channel against the target sample catalog and
   report missing/ambiguous channels; and
5. construct and validate the full candidate target manifest.

Any validation error aborts the import without changing definitions, samples,
Results, or the undo clean marker.  A successful import is one undoable
definition-only project command.  It invalidates all result/cache revisions and
sets an explicit stale reason such as `analysis_settings_loaded`; it must not
reuse source-project Results even where fingerprints happen to match.

For the initial release, a missing/ambiguous channel is a blocking error.  Do
not guess mapping by display label and do not partially apply a subset of gates.
Channel mapping and template-style remapping belong to the later Templates and
Mapping work (C3).

## Architecture and target files

- `src/flowdesk_core/analysis_settings.py`: typed extraction, validation, and
  pure replacement of analysis definitions; no Qt imports.
- `src/flowdesk_storage/analysis_settings.py`: format validation, migration,
  and atomic save/load for `.flowdesk-settings` bundles.
- `schemas/analysis_settings.schema.json`: document-kind and definition schema.
- `src/flowdesk_qt/main_window.py`: File actions, source chooser, preflight /
  confirmation dialog, one undoable apply command, and stale-results handling.
- `src/flowdesk_qt/...`: a small Qt dialog only if the existing diagnostics /
  confirmation infrastructure cannot present the required summary.
- `tests/test_analysis_settings.py`, `tests/test_project_storage.py`,
  `tests/test_pipeline_runner.py`, and focused GUI tests under `tests/gui/`.
- `docs/user-manual/user_manual.md`: menu operations, replacement semantics,
  exclusions, incompatibility handling, and mandatory pipeline rerun.

GUI code may select files, display the preflight, update project state, and call
the same core runner as headless execution.  It must not calculate membership,
statistics, or channel mapping.

## Implementation increments

1. Define `AnalysisSettingsSpec`, the schema/version/migration contract, a
   pure project-to-settings extractor, and atomic storage APIs.  Add no GUI.
2. Implement pure target replacement and strict target channel preflight.
   Add headless tests for project-source extraction, settings round-trip, source
   result exclusion, collision-free replacement, and all-or-nothing failure.
3. Add File menu actions and a preflight/confirmation UI with stable object
   names.  Apply through the project command/undo mechanism, clear previews and
   Results, then update the user manual.
4. Add GUI/headless end-to-end coverage: source project with results applied to
   a different sample project; ensure target samples remain, source Results do
   not appear, results are stale until rerun, and rerun equals a headless runner
   on the imported candidate manifest.

## Acceptance criteria

- A settings bundle contains no absolute/relative FCS path, sample ID,
  fingerprint, result value, cache, or selected-sample state.
- A `.flowdesk` project and an `.flowdesk-settings` bundle produce the same
  extracted definition when their reusable definitions are equal.
- Import preserves target sample references byte-for-byte and never imports
  source Results or bindings/overrides.
- Failed preflight leaves the target project and its current Results unchanged.
- Successful import is undoable/redoable and marks Results stale; export cannot
  emit pre-import result rows.
- A post-import Pipeline run uses the core `PipelineRunner` and matches the
  equivalent headless execution.
- Save/load work with Unicode and spaces in paths on Windows, macOS, and Linux;
  settings storage itself contains no platform-dependent sample path.

## Non-goals

- Merging definitions or resolving ID collisions interactively.
- Automatic channel/marker mapping, group membership transfer, or per-sample
  compensation/override transfer.
- Exporting/importing raw FCS files or cached Results.
