# Kinetics Platform

Spec: `S18`
ToDo: `Phase D1`

## Goal

Compute time-window response metrics on a selected full-data population with explicit
time assumptions, fit diagnostics, and headless reproducibility.

## Inspect first

- pipeline stage/result models and population membership
- statistics definitions and Table/Layout integration points
- derived parameter handling for Time/Event Number
- plot rendering and project schema

Read `scientific-review` skill before selecting formulas.

## Model contract

`KineticsSpec` references population, time parameter, response parameter/statistic,
ordered windows, baseline policy, metric settings, and algorithm version.
`KineticsResult` includes metrics, per-window counts, finite exclusions, status, and
diagnostics. Event-number-derived time records assumed flow rate and is never labeled
measured Time.

## Increments

1. Add spec/result/schema and manual-window validation.
2. Add deterministic window assignment and baseline calculation.
3. Implement max, time-to-max, slope, and AUC with hand-computed fixtures.
4. Implement responding fraction only after threshold definition is persisted.
5. Add automatic windows as a separate versioned algorithm with fit diagnostics.
6. Add GUI editor/plot using core results.
7. Add Statistic/Table/Layout adapters without duplicating calculation.

## Required tests

- Irregular/duplicate/non-monotonic Time, empty windows, NaN/Inf, low event count.
- Measured Time and derived-Time provenance differ.
- Membership restricts all input events.
- GUI, CLI, and Python result values/status match after reload.
- Automatic algorithm is deterministic for a fixed input/version.

## Stop condition

Do not implement responding fraction or automatic ranges until their scientific rule and
reference fixtures are written in this guide.

## Verification

```bash
pytest -q tests/test_pipeline_runner.py tests/test_population_statistics.py
./tools/run-gui-tests.sh -q
```

