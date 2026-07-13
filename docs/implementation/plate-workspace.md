# Plate Workspace

Spec: `S17`
ToDo: `Phase C7`

## Goal

Map samples and annotations to plate wells and make plate metadata available to groups,
tables, layouts, and deterministic heat maps.

## Inspect first

- sample/group/annotation models and resolvers
- statistics and table definitions
- project schema/storage
- GUI sample browser/main window

## Model contract

`PlateSpec` contains format, rows/columns, well assignments, and typed experimental
factors. `WellAssignment` references a sample ID; no event data is stored. Canonical well
IDs are validated (for example `A01`) and presentation labels are separate.

## Increments

1. Add 6/12/24/48/96/384 format geometry and well-ID tests.
2. Add assignments, factors, duplicate/missing validation, schema round-trip.
3. Add CSV parser with preview, explicit column mapping, and atomic apply.
4. Add Qt well grid, multi-selection, paste/edit, and status badges.
5. Resolve plate factors in groups and Table Editor iteration.
6. Add statistic heat-map display and Layout object using existing StatisticResults.

## Required tests

- 96/384 boundaries, partial plates, invalid row/column, duplicate sample/well.
- CSV delimiter/header/type errors leave state unchanged.
- Heat map value equals headless StatisticResult for each well.
- Missing sample/result is visible and not rendered as zero.
- Save/reload retains factors and assignments.

## Do not do

- Do not infer well solely from filename without a reviewed import mapping.
- Do not compute statistics in the heat-map widget.
- Do not require every well to contain a sample.

## Verification

```bash
pytest -q tests/test_project_storage.py tests/test_population_statistics.py
./tools/run-gui-tests.sh -q
```

