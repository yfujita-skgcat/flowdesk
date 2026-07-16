# Group Gating and Sample Overrides

Spec: `S08`
ToDo: `Phase B4`

## Goal

Apply one group strategy across samples while recording sample-specific geometry changes
as explicit, auditable overrides.

## Prerequisites and inspect first

Complete A1, B1, B2, and B3. Inspect group models, gate models, runner strategy assembly,
workspace tree, gate editor, and all hierarchy tests before editing.

## Model contract

`GateOverrideSpec` contains sample ID, base gate ID/version hash, replacement geometry or
minimal typed delta, author/time/reason, and transform IDs. It cannot change gate type,
parameters, parent, or Boolean sources; those require a strategy edit.

The current core representation stores the override separately from `GateSpec` and
`GatingStrategySpec`. `geometry_mode` is either `full` or `delta`; a delta replaces
coordinates when supplied and merges threshold keys onto the shared thresholds. An
override is enabled only when it is explicitly present and enabled for the selected
sample. `gate_purpose` is `technical_cleanup` or `comparison_critical` and is retained
for the later warning/audit commands.

Resolution is deterministic: group strategy → selected sample override → validation →
execution. A stale base hash makes the override invalid until explicitly rebased.

## Increments

1. Add override model/schema/resolver and stale-base tests.
2. Apply resolved gates per sample in the headless runner.
3. Add channel-mapping preflight for group subtree application.
4. Add sample navigator preserving population path, axes, scales, and viewport.
5. Add shared/override/stale badges and an override audit table.
6. Add separate commands: reset to group, promote to group, copy to selected, rebase.
7. Add QC checks for clipped gates, missing populations, and frequency outliers.

## Required tests

- Two samples share a strategy but produce different intended override geometry.
- Override cannot escape parent or change transform identity silently.
- Base edit invalidates/rebases overrides according to explicit command.
- Group application is atomic when one sample lacks a channel.
- GUI review count equals per-sample headless count.

## Do not do

- Do not clone an entire hidden strategy per sample.
- Do not infer overrides from the last displayed ROI.
- Do not promote one sample to the group without a confirmation preview.

## Verification

```bash
pytest -q tests/test_gates.py tests/test_pipeline_runner.py tests/gui/test_gate_hierarchy_ui.py
./tools/run-gui-tests.sh -q
```
