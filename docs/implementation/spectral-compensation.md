# Spectral Compensation, AutoSpill, and Autofluorescence Extensions

Spec: `S03`
ToDo: `Phase D5`

## Goal

Extend the completed traditional compensation workspace with separately modeled spectral
unmixing, AutoSpill, autofluorescence extraction, and spreading diagnostics.

## Prerequisite

`compensation-workspace.md` Phases A4/A5 must be complete. Do not reuse a conventional
spillover matrix type for unmixing coefficients without explicit semantics.

## Scientific contract

Each algorithm has a distinct spec/result type, control/endmember assignments, preprocessing,
optimizer/regression settings, residual metrics, version, and provenance. AutoSpill may be
named as such only when implemented from the publication and validated against reference data.

## Increments

1. Document conventional vs spectral matrix orientation and equations.
2. Add spectral reference/endmember model and synthetic mixture fixtures.
3. Implement unmixing with rank/condition/residual diagnostics.
4. Add spectral assignment and residual GUI.
5. Implement AutoSpill as a separate publication-driven project.
6. Add autofluorescence reference/extraction with explicit unstained control.
7. Add spillover-spreading result as a diagnostic, not a replacement matrix.

## Required tests

- Synthetic spectra recover known component abundances.
- Missing/rank-deficient/endmember mismatch is diagnosed.
- Raw events and reference controls remain immutable.
- Algorithm/provenance survives round trip and appears in execution report.
- GUI preview equals headless output.

## Stop condition

If publication details or licensed validation data are unavailable, retain the feature as
unimplemented. Never label a generic regression as AutoSpill.

## Verification

```bash
pytest -q tests/test_compensation.py tests/test_pipeline_runner.py
./tools/run-gui-tests.sh -q
```

