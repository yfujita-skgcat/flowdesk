# Local LLM Task Protocol

## Purpose

This protocol is mandatory for Qwen3.6 27B-class local agents implementing any
guide in this directory. It keeps each run small, testable, and recoverable.

## One-run limit

One run may complete only one numbered increment from one implementation guide.
Do not combine schema migration, core algorithms, GUI, and reports in one run.
If an increment changes more than 8 production files, split it before editing.

## Required reading order

1. `AGENTS.md`
2. `specs.md`, only the referenced `Sxx` section
3. `ToDo.md`, only the current Phase
4. this protocol
5. the selected implementation guide
6. every existing file listed under **Inspect first**
7. the matching `.codex/skills/*/SKILL.md`

Do not start production edits until all selected files have been read completely.

## Start report

Before editing, report:

- current increment and explicit non-goals
- files expected to change
- current API that will remain compatible
- acceptance tests to add first
- any dirty worktree files that overlap

## Implementation sequence

1. Run the smallest relevant baseline tests.
2. Add a failing test for one required behavior.
3. Add or change typed core/project definitions.
4. Implement the smallest core behavior that passes the test.
5. Add serialization and migration only after the core contract is stable.
6. Add CLI/Python adapter.
7. Add GUI last; GUI calls the same core API.
8. Run focused tests after every layer.
9. Run the guide's final verification commands.

## Compatibility rules

- Prefer a new API plus a thin compatibility wrapper over changing all callers at once.
- Deprecation wrappers must contain no second scientific implementation.
- Preserve unknown project fields during migrations unless the schema explicitly rejects them.
- Never infer a channel, matrix, transform, or population reference when more than one match exists.
- Never convert an execution error to zero, empty, or NaN unless a persisted policy requests it.

## Test rules

- Test public behavior, stable IDs, numeric values, error codes, and round trips.
- Do not assert private widget layout unless it is the behavior under test.
- Use synthetic arrays/FCS fixtures with hand-computable expected values.
- Record numeric tolerances and why they are scientifically acceptable.
- GUI tests use stable `objectName`, strict callbacks, and signal/event-loop waits.
- Full event results must be identical regardless of display downsampling.

## Stop conditions

Stop editing and report a blocker when:

- the guide conflicts with `AGENTS.md` or the canonical pipeline order
- a required scientific equation/reference is unavailable
- an existing project cannot be migrated without changing its meaning
- two channel/population references are ambiguous
- the baseline already fails in an overlapping area and the cause is unknown
- an optional dependency would become mandatory without approval

Do not invent a scientific policy to keep moving.

## Completion report

Report changed files, tests with exit codes, GUI/headless comparison where relevant,
remaining limitations, and the next single increment. Mark a ToDo checkbox only when
the entire checkbox—not merely the current increment—is complete.

