# Performance, Cache, and Scientific Review

Spec: `S23`
ToDo: `Performance track`

## Goal

Measure load, analysis, and rendering separately; add safe cache/cancellation behavior;
and prevent performance work from changing scientific results.

## Inspect first

- `src/flowdesk_core/pipeline_runner.py`, all stage modules, execution report/context
- `src/flowdesk_storage/cache.py`
- `src/flowdesk_qt/plot_widget.py`, worker lifecycle, diagnostics
- `tools/run-gui-tests.sh`, benchmark/test configuration
- `.codex/skills/performance-benchmark/SKILL.md`
- `.codex/skills/scientific-review/SKILL.md`

## Dataset contract

Add a deterministic synthetic generator under `benchmarks/` or `tests/support/` with
recorded seed, event count, channel count, population proportions, and expected gate
counts. Standard profiles are 100k, 1M, and 10M events. Do not commit generated arrays.

## Measurement contract

Measure separately: FCS load, compensation, derived parameters, transforms, gating,
statistics, table/layout resolution, and rendering. Record Python/NumPy/Qt versions,
platform, CPU, memory metric, event/channel counts, seed, and code revision where available.
Rendering FPS/time is not an analysis benchmark.

## Cache contract

A cache key includes input fingerprint, pipeline/software version, execution profile, and
hashes of every upstream definition. Cached arrays/results are derived and disposable.
Changing compensation invalidates all downstream stages; derived changes invalidate
derived onward; transform changes invalidate transform onward; gate changes invalidate the
affected gate descendants/statistics/reports.

## Scatter rendering contract

- `PlotViewSpec.rendering_downsample.max_points` is the persisted display-only
  scatter limit. The default is `20_000`; `0` disables display sampling.
- The Plot Parameters control edits this view definition and never changes the
  analysis revision, gate membership, counts, frequencies, or statistics.
- Sampling is deterministic. When resolved population colors are available, the GUI
  allocates points by final display color so a non-empty rare color receives at least
  one point whenever the configured limit can represent every color.
- Population-colored events render as disjoint uniform-color scatter layers. Do not
  pass a brush array with one entry per event to pyqtgraph.
- Presentation updates compare the previous style and do not reapply scatter brushes
  when only labels, background, or gate appearance changed.
- Histograms, density/contour aggregation, gates, and statistics continue to consume
  full selected events.

## Increments

1. Add deterministic generator and correctness-only profile tests.
2. Add benchmark harness/report JSON without performance thresholds.
3. Establish baseline memory/time and then add documented regression thresholds.
4. Add cache-key builder and invalidation unit tests before enabling cache reads.
5. Enable one cached stage at a time and compare exact/accepted numeric results.
6. Add cooperative progress/cancel between samples/stages; never terminate a numeric step
   while it is mutating shared state.
7. Add sample-level parallelism only after deterministic ordering and memory budgets.
8. Optimize rendering independently using downsampling/density; preserve full-data counts.

## Required tests

- 100k/1M/10M profiles have identical expected population proportions/count rules.
- Cached and uncached results/status/provenance match.
- Every upstream edit invalidates exactly the documented downstream entries.
- Cancellation returns explicit partial/cancelled status and no authoritative partial cache.
- Display sampling seed/resolution does not change gate/statistic results.
- Rare-event visibility limitation is reported in GUI when sampling may omit points.

## Scientific review checklist

- Raw data immutable and sample/channel alignment explicit.
- Approximation named honestly with uncertainty/reference.
- Transform/gate boundary and invalid numeric policies tested.
- GUI/CLI/Python use the same analysis definitions and results.
- Reproducibility metadata records algorithm/version/seed.

## Do not do

- Do not weaken correctness assertions to meet timing targets.
- Do not cache by project path or gate name alone.
- Do not treat display aggregates as analytical inputs.
- Do not add parallel writes to the same project/report object.

## Verification

```bash
pytest -q tests/test_pipeline_runner.py tests/test_gates.py tests/test_population_statistics.py
./tools/run-gui-tests.sh -q
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
```
