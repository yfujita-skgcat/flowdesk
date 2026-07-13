# Sample Catalog and Channel Identity

Spec: `S01`
ToDo: `Phase A1`

## Goal

Make every event column sample-specific and addressable by a stable channel ID so
channel order differences cannot silently change an analysis.

## Inspect first

- `src/flowdesk_core/models.py`
- `src/flowdesk_core/fcs_io.py`
- `src/flowdesk_core/channels.py`
- `src/flowdesk_core/sample.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/main_window.py`
- `schemas/project.schema.json`
- `tests/test_fcs_io.py`
- `tests/test_pipeline_runner.py`

Also read `fcs-io.md`, `pipeline-runner.md`, and `.codex/skills/fcs-io/SKILL.md`.

## Core contract

Add a frozen `SampleData`-like type containing `sample_id`, read-only 2-D
`events`, and an ordered tuple of `ChannelSpec`. Validate `events.shape[1] ==
len(channels)` at construction. Provide explicit lookup methods by stable ID and
reject ambiguous name/short-name lookups.

`ChannelSpec` must preserve FCS parameter index, `$PnN`, `$PnS`, detector/stain
metadata, and a stable project ID. Never use the visible label as the only identity.

## Increments

1. **Identity model and fixtures** — implemented
   - Extend the typed model and add constructor/lookup tests.
   - Keep old `ChannelSpec` fields readable through defaults.
   - Test duplicate label, duplicate ID, and shape mismatch errors.
2. **FCS adapter** — implemented
   - Build ordered channel specs from metadata without discarding original names.
   - Return immutable events and metadata separately or in the typed sample object.
   - Add two synthetic samples whose column order differs.
3. **Runner API** — implemented
   - Add `PipelineRunner.run_samples(context, samples)` or an equivalent typed API.
   - Keep `run(..., event_data, channel_names)` as a thin compatibility adapter.
   - Pass updated channel specs through every pipeline stage.
4. **Storage and migration** — implemented
   - Persist stable IDs and FCS identity fields.
   - Add a project-version migration; never guess when duplicate legacy labels exist.
5. **Catalog GUI**
   - Display selectable metadata columns and mismatch badges.
   - Add reconnect logic based on stored fingerprint; require confirmation on mismatch.

## Confirmed contract after increment 1

- `flowdesk_core.sample.SampleData` owns a defensive, read-only copy of one
  sample's 2-D event matrix and the ordered `ChannelSpec` tuple for its columns.
- Construction rejects a column/channel count mismatch and duplicate stable IDs.
- Exact stable-ID lookup is the analytical path. Label lookup is a compatibility
  aid and matches only the original `name` (`$PnN`) and `short_name` (`$PnS`)
  values; it performs no normalization or first-match fallback.
- Duplicate visible labels are retained. Resolving one raises
  `AmbiguousChannelReferenceError` with the sample ID and all candidate stable
  IDs, so metadata is not lost and the caller must disambiguate explicitly.
- `ChannelSpec.fcs_parameter_index` and `ChannelSpec.stain` are optional fields
  appended after the previous fields, preserving existing keyword and positional
  construction behavior.
- At the end of increment 1, the FCS adapter, pipeline runner, project storage,
  and GUI still used their pre-existing APIs. The adapter connection is covered
  below; runner, storage, and GUI work remains in increments 3–5.

## Confirmed contract after increment 2

- `read_fcs_sample(path, sample_id, preprocess)` is the preferred typed adapter.
  It returns `FcsFileInfo` separately from `SampleData`; `read_fcs_events()`
  remains compatible and is the adapter's only event-reading implementation.
- FCS parameter index is one-based and records the event-column order only. It
  is never used alone as channel identity.
- `ChannelSpec.name` preserves exact `$PnN`. Despite the legacy Python field
  names, `ChannelSpec.short_name` preserves exact `$PnS`, which FCS 3.1 defines
  as the optional long display name and does not require to be unique.
- `detector` comes only from explicit `$PnT`, `unit` from explicit `$PnU`, and
  `stain` only from an explicit vendor `PnSTAIN` value. Flowdesk does not infer
  detector or stain from `$PnN` or `$PnS`.
- The source-derived stable ID hashes exact `$PnN`, `$PnS`, detector, and stain
  values but excludes array index. Therefore a pure column permutation retains
  identity, while a label or instrument-identity change remains distinct until
  a later explicit project mapping says otherwise.
- Per-parameter keyword values exposed by flowio remain available under
  flowio-normalized keys in `ChannelSpec.metadata`; whole-file unknown keywords
  exposed by flowio remain in `FcsFileInfo.metadata`.
- Duplicate `$PnN` is rejected as malformed FCS metadata instead of receiving a
  positional fallback ID. Missing required `$PnN` is rejected for the same
  reason.
- At the end of increment 2, pipeline execution, persisted project IDs, and GUI
  mapping still remained in increments 3–5. The runner connection is covered
  below; storage and GUI work remains in increments 4 and 5.

## Confirmed contract after increment 3

- `PipelineRunner.run_samples(context, samples)` is the typed headless API.
  Duplicate input sample IDs are rejected, project profile selection still
  determines which samples execute, and missing selected inputs retain the
  existing warning behavior.
- Each pipeline stage receives events paired with ordered `ChannelSpec`.
  Compensation, derived expressions, transforms, and gates use
  `ChannelSpec.id` aligned to the current event columns; analytical execution
  does not fall back to `$PnN` or `$PnS` labels.
- Derived output appends a new `ChannelSpec` carrying the derived parameter ID
  before transform and gate execution. An ID collision raises `PipelineError`.
- `run(context, event_data, channel_names)` is a compatibility adapter. It
  constructs `SampleData` whose IDs equal the legacy names and delegates to
  `run_samples()`; it contains no separate scientific pipeline.
- Synthetic compensation and rectangle-gate tests confirm identical full-event
  membership and counts when two samples contain the same stable IDs in
  different column orders. Raw `SampleData.events` remain byte-identical.
- Storage still does not persist these channel definitions and the GUI still
  calls the legacy adapter; those remain increments 4 and 5.
- The existing derived evaluator's multi-event scalar limitation and broad NaN
  fallback are unchanged. They belong to Phase A2, so the increment 3 test only
  verifies identity propagation with a scalar constant.

## Confirmed contract after increment 4

- Current project version is `1.1.0`. Loading legacy `0.1` and GUI-produced
  `1.0.0` manifests returns a migrated in-memory copy; loading never rewrites
  the source bundle. Unsupported versions raise `ProjectMigrationError`.
- Current samples persist an ordered `channels` array. Each entry preserves
  stable ID, `$PnN`/`$PnS` fields, detector, stain, unit, one-based FCS index,
  metadata, and unknown extension fields.
- Migration is pure and deep-copies parsed JSON. Project-, sample-, channel-,
  and metadata-level unknown fields survive load-save-load.
- A legacy sample with unique `channel_names` receives compatibility channel
  IDs exactly equal to those names and an `identity_source=legacy_name` marker.
  Existing gate references therefore retain their historical meaning.
- Duplicate legacy names raise `ProjectMigrationError` with stable code
  `ambiguous_legacy_channel_label`, sample ID, and candidate labels. No first
  match or positional ID is chosen.
- A legacy sample without channel metadata receives an empty `channels` array.
  Storage does not open the referenced FCS file or invent identities during
  migration; the catalog import/reconnect layer must populate them explicitly.
- The current manifest validator rejects missing channel arrays, duplicate
  stable IDs, malformed metadata, and invalid FCS parameter indexes.
- The example bundle and JSON schema now describe version `1.1.0`. A synthetic
  `0.1` fixture proves migration, round-trip preservation, and headless gate
  execution.
- Catalog GUI binding and reconnect UX remain increment 5.

## Required tests

- Same marker analysis gives the same count after channel permutation.
- `$PnN`/`$PnS` disagreements are resolved only by documented rules.
- Ambiguous reference raises a typed error with sample and candidate IDs.
- Load-save-load preserves IDs and unknown FCS metadata.
- GUI selection passes the same channel ID used by the headless runner.
- Raw arrays remain read-only and byte-identical.

## Do not do

- Do not create IDs from array position alone.
- Do not normalize away punctuation without retaining the original value.
- Do not place FCS parsing in Qt.
- Do not silently select the first duplicate label.

## Final verification

```bash
pytest -q tests/test_fcs_io.py tests/test_pipeline_runner.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
