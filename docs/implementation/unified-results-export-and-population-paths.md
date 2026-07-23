# Unified Results Export and Population Full Paths

## Status

Planned. This guide records the remaining work; the current GUI still has
separate population and statistics exports.

## Goal and invariants

Expose one `Export Results...` operation while keeping
`ExecutionReport.population_results` and `ExecutionReport.statistic_results`
separate internally. Core must first build a typed unified row model, then write
CSV/TSV. Qt may select options and display errors, but must never recalculate
scientific values from table cells.

Rows in the default wide format are keyed by `(sample_id, population_id)` and
use these columns:

```text
Sample, Population, Events, % Parent, % Total, <custom statistic columns>
```

`Population` is a display path, not an identity. The root `all_events` is
`All Events`; child gate names are joined in hierarchy order with ASCII `/`,
such as `All Events/Live/GFP+`. Parent-child resolution and joins always use
IDs. A rename changes the path but not the ID. Saved gate order determines a
stable preorder, with parents before children. Unknown parents, cycles,
duplicate IDs, and impossible hierarchy resolution are explicit errors.

The path must be resolved from the strategy actually applied to each sample,
including group/analysis-strategy binding. The strategy currently visible in
the Qt window must not be reused for every sample.

## Gate-name contract

Create one core `validate_gate_name(name: str)` (or equivalent) and invoke it
from `GateSpec`, `CreateGateCommand`, `EditGateCommand`, `RenameGateCommand`,
`DuplicateGateCommand`, `CopySubtreeCommand`, manifest validation, project
loading, and every GUI creation/edit/inline-rename path. Reject empty or
whitespace-only names and ASCII `/` with the shared meaning:

```text
Gate name must not contain '/'; '/' is reserved for population paths.
```

JSON schemas should additionally use `minLength: 1` and `pattern: ^[^/]+$`.
Full-width `／` is not forbidden. Legacy projects containing `/` must report
the strategy ID, gate ID, and gate name; they must not be silently rewritten.
Failed dialog and inline edits must retain/focus the previous valid value.

## Wide and long output

The wide writer combines built-in population metrics and custom statistics in
one row. Events remain integers; 0--1 frequencies are written as percentages,
the root `% Parent` is blank, and root `% Total` is `100`. Missing cells are
blank by default and must remain distinguishable from numeric zero. Resolve
`Sample` through the existing `resolve_sample_title()` rules while retaining
the sample ID as the internal row key.

Custom statistic columns follow persisted definition order. Duplicate display
names receive a stable statistic-ID suffix rather than overwriting each other.
An unassigned statistic cell is blank. The optional internal metadata option
adds `Sample ID`, `Population ID`, `Population Name`, `Parent Population ID`,
and `Population Depth`.

The long writer uses the same report and row model and includes both
`Result Type=population` and `Result Type=statistic`, population path/ID,
statistic identity, value/unit, status, undefined reason, and existing QC
fields (`n valid`, `n total`, `n invalid`, invalid fraction, non-finite policy).

## GUI and CLI

Remove the two user-facing Results export actions and any hidden dead action;
keep old core writers only as compatibility APIs after reference audit. The
new dialog supports Wide/Long, population metrics, custom statistics, internal
IDs, QC/status metadata, and TSV/CSV. At least one result category is required.
No run, absent authoritative results, stale results, or path-resolution errors
must block export with an understandable dialog message. Population-only data
must still export when zero custom statistics exist.

`flowdesk run project.flowdesk --output results.tsv` is the standard unified
wide export. Add `--layout wide|long`, `--include-internal-ids`, and
`--include-qc` as needed. If `--statistics-output` remains, mark it deprecated
on stderr and preserve its statistic-only compatibility semantics. Align
`batch-gate --output` with the core writer where its execution context permits.

## Files and tests

Expected production areas are `models.py`, `populations.py`, `export.py`,
`project_commands.py`, `manifest.py`, both project schemas, execution/group
strategy resolution, `main_window.py`, `gate_editor.py`, `run_project.py`,
`main.py`, and `batch_gate.py`. Add focused core, storage/schema, CLI, and GUI
tests.

Tests must cover valid/invalid gate names, direct GateSpec construction, every
command, manifest/project load, GUI rollback, nested/same-named paths, rename
stability, unknown parent/cycle/duplicate path, per-sample strategy binding,
wide/long content, percentages, blank versus zero, duplicate statistic names,
sample titles, metadata/QC, row order, delimiters, stale rejection, menu and
toolbar routing, cancellation, CLI layouts, and deprecated-option warning.

Do not change gate geometry, membership, compensation, transforms, statistic
formulas, group scientific semantics, or population-ID generation. Completion
requires the repository's prescribed pytest, ruff, mypy, and GUI checks without
deleting, skipping, or xfail-ing failures.
