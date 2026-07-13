# Cell Cycle Platform

Spec: `S20`
ToDo: `Phase D3`

## Goal

Fit a documented DNA-content model and report phase fractions with convergence and
residual diagnostics.

## Inspect first

- transform/membership/statistics/pipeline models
- project schema and platform extension interfaces
- graph/table/layout rendering APIs

## Scientific contract

Persist DNA parameter/value space, model family, G1/G2 constraints, background/debris,
doublet policy, optimizer/initial values, seed, and implementation version. Return G0/G1,
S, G2/M fractions, fit curve/components, residual, convergence status, and exclusions.

## Increments

1. Select/document a published model and create reference/synthetic fixtures.
2. Add spec/result/schema validation; no fitting yet.
3. Implement the simplest fixed-constraint fit and component fractions.
4. Add optional constraints/background one feature per increment.
5. Add doublet/debris handling only with separate validated policies.
6. Add GUI initial-value editor, component/residual plot, and failure display.
7. Add Table/Layout result adapters.

## Required tests

- Known phase mixtures and fraction conservation.
- Failed convergence, boundary solution, low events, negative/NaN values.
- Changing display transform does not silently change model value space.
- GUI/headless result and diagnostics match.

## Stop condition

Do not invent a model or copy proprietary behavior. If the chosen algorithm lacks a
verifiable reference, stop before the fitter and document the gap.

## Verification

```bash
pytest -q tests/test_pipeline_runner.py tests/test_population_statistics.py
./tools/run-gui-tests.sh -q
```

