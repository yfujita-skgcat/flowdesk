# Population Comparison

Spec: `S21`
ToDo: `Phase D4`

## Goal

Compare test and control population distributions with persisted methods, minimum-event
policies, plots, and numeric reference tests.

## Inspect first

- population membership and statistics
- overlay/CDF display preparation
- table/layout integration and project schema

## Model contract

`PopulationComparisonSpec` references test/control populations, parameters, value-space
transforms, normalization, methods, minimum events, and multiple-comparison policy.
Results contain method/version, statistic, p-value where applicable, event counts, status,
and diagnostic assumptions.

## Increments

1. Add spec/result/schema and histogram/CDF overlay definitions.
2. Implement two-sample KS through a validated library or documented equation.
3. Implement Overton percent positive with explicit control subtraction/binning policy.
4. Add multiple controls and aggregation policy.
5. Add GUI control assignment and result/difference views.
6. Add Table/Layout adapters.
7. Treat probability binning as a later independent algorithm/reference task.

## Required tests

- Identical, shifted, disjoint, empty, and below-minimum distributions.
- Exact event counts and transform identity are recorded.
- Multiple controls produce deterministic configured behavior.
- Method results match an independent reference within documented tolerance.
- GUI and headless result/status match after reload.

## Do not do

- Do not interpret a p-value as biological effect size.
- Do not pool controls without a persisted policy.
- Do not use plotted/downsampled histograms for the numeric test.

## Verification

```bash
pytest -q tests/test_population_statistics.py tests/test_pipeline_runner.py
./tools/run-gui-tests.sh -q
```

