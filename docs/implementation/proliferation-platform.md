# Proliferation Platform

Spec: `S19`
ToDo: `Phase D2`

## Goal

Fit dye-dilution generations with a documented model and report standard proliferation
metrics plus fit quality.

## Inspect first

- transforms, membership, statistics/result models
- project schema and pipeline extension points
- graph/table/layout interfaces

## Scientific contract

Persist dye parameter, value-space transform, generation-0 definition, generation count,
peak-ratio/CV constraints, background model, optimizer settings, seed, and algorithm
version. Results include convergence, residuals, uncertainty where available, per-generation
counts, division index, proliferation index, and percent divided.

## Increments

1. Write formula/reference section and synthetic mixture generator before production code.
2. Add spec/result/schema and validation.
3. Fit fixed generation centers/widths; then constrained centers; then optional background.
4. Compute metrics from fitted/assigned generations with independent expected fixtures.
5. Expose generation-gate proposals as a separate command; do not auto-commit gates.
6. Add GUI fit editor, residual/status display, and manual initial values.
7. Add Table/Layout integration from stored result IDs.

## Required tests

- Known 3–6 generation mixtures recover expected metrics within justified tolerances.
- No-division, overlapping peaks, low events, failed convergence, and all-NaN cases.
- Fixed seed/algorithm version is reproducible.
- Failed fit never emits success metrics without status.
- Generated gates retain fit provenance and require explicit acceptance.

## Stop condition

No model may be called FlowJo-compatible without a versioned external comparison fixture.
If no published definition is selected, create xfail reference tests and stop.

## Verification

```bash
pytest -q tests/test_pipeline_runner.py tests/test_population_statistics.py
./tools/run-gui-tests.sh -q
```

