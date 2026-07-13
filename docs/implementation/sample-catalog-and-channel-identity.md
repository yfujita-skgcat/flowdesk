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
3. **Runner API**
   - Add `PipelineRunner.run_samples(context, samples)` or an equivalent typed API.
   - Keep `run(..., event_data, channel_names)` as a thin compatibility adapter.
   - Pass updated channel specs through every pipeline stage.
4. **Storage and migration**
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
- Pipeline execution, persisted project IDs/migration, and GUI mapping remain
  increments 3–5 and are not implied by this adapter.

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
