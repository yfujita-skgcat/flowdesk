# Persistent Statistics Definitions

Spec: `S11`
ToDo: `Phase A6`

## Goal

Represent every requested statistic as persisted analysis state and compute it from
full population membership in the headless pipeline.

## Inspect first

- `src/flowdesk_core/statistics.py`
- `src/flowdesk_core/populations.py`
- `src/flowdesk_core/models.py`
- `src/flowdesk_core/execution_report.py`
- `src/flowdesk_core/pipeline_runner.py`
- `src/flowdesk_core/export.py`
- `src/flowdesk_qt/population_tree.py`
- `tests/test_population_statistics.py`

Read `population-statistics.md`, `pipeline-runner.md`, and
`.codex/skills/scientific-review/SKILL.md`.

## Model contract

`StatisticSpec` contains stable ID/name, population ID, optional parameter ID,
metric, source/value-space policy, settings, and display format. Its persisted
`value_policy` is currently only `full_events`; display histogram bins are not a
valid source for numeric statistics. `StatisticResult`
contains sample/spec IDs, value, unit, status, and optional undefined reason.

Default numeric statistics operate on full event values after the configured
pipeline stage. Display histogram bins are never the default statistic source.

## Confirmed contract after source-stage implementation

- `raw` reads the immutable FCS input view; `compensated` reads the view after
  compensation and derived-parameter evaluation; and `transformed` materializes
  the configured analysis transforms into a separate derived view.
- Gate membership is always evaluated once against full event data and the same
  full-length mask is applied to the selected statistic value space. Statistics
  never use GUI-downsampled events or histogram bins.
- Transform materialization for statistics does not alter the gate evaluator's
  lazy transform handling, so a gate is never transformed twice.
- `frequency_of_parent` resolves the persisted gate parent ID and counts that
  parent's full membership mask; `frequency_of_total` uses the full sample
  event count. Neither frequency is inferred from display rows or ordering.
- Value metrics ignore `NaN` only when at least one finite value remains. An
  empty population is `empty_population`, all-`NaN` input is `all_nan`, and
  any `+Inf` or `-Inf` yields no value with `nonfinite_values`.
- Geometric mean excludes zero and negative finite values when positive values
  remain, otherwise it is `all_nonpositive_geometric_mean`; CV with a zero mean
  is `zero_mean_for_cv`.
- Headless statistic results retain the persisted definition ID and display
  name. Value metrics also retain the selected channel unit, and CSV/TSV export
  writes those fields with value, status, and undefined reason.

## Authoritative batch and interactive preview

`Run Pipeline` is the authoritative calculation boundary because statistic values depend
on every upstream stage and must match CLI/Python API execution over full events. A future
current-sample interactive preview may improve gate-edit feedback, but it must call the
same core statistic dispatcher, carry an analysis revision, and be labelled
`Preview — current sample only`. Preview statistics do not feed export, Group QC, or the
saved authoritative `ExecutionReport`. See `interactive-current-sample-preview.md` for
debounce, descendant invalidation, latest-wins scheduling, and stale-result rejection.

## Increments

1. Add types/schema for definitions, results, statuses, and undefined reasons.
2. Implement count and frequencies through the new dispatcher without changing values.
3. Add mean, median, SD, MAD, percentile with explicit NaN/Inf policy.
4. Add geometric mean and CV only after defining negative/zero and zero-mean behavior.
5. Add dependency invalidation and results to `ExecutionReport`.
6. Add Add Statistic dialog and population-tree nodes.
7. Extend CSV/TSV export using core results.

## Required tests

- Hand-computed values for every metric.
- Empty population, all-NaN, Inf, zero denominator, invalid percentile.
- Parent/total frequencies remain based on full masks.
- Save/load/CLI/API return the same result and undefined reason.
- Gate/matrix/transform edit marks dependent results stale.
- Display downsampling and histogram bin count do not affect values.

## Do not do

- Do not store only a formatted string.
- Do not treat `None`, NaN, and calculation error as the same status.
- Do not reproduce statistics in table/layout/Qt code.
- Do not claim FlowJo parity for binned statistics unless a separate policy is implemented.

## Final verification

```bash
pytest -q tests/test_population_statistics.py tests/test_pipeline_runner.py tests/test_export.py
./tools/run-gui-tests.sh -q
ruff check src tests
```
