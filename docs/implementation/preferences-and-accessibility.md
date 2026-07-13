# Preferences, Help, and Accessibility

Spec: `S24`
ToDo: `Phase D7`

## Goal

Provide durable user preferences and accessible controls without allowing global defaults
to change existing project scientific definitions.

## Inspect first

- Qt widgets/actions/object names and plot styles
- project display settings and storage
- autosave/recovery guide
- GUI diagnostics/tests and README user guide

## State contract

Global preferences contain theme/font, default plot appearance, number display, autosave,
performance, and export UI defaults. Project display settings override presentation only.
Scientific definitions in an existing project always win over new global defaults.

## Increments

1. Add typed preference schema, defaults, validation, and atomic user-level storage.
2. Add import/export/reset and unknown/newer-version handling.
3. Connect plot/number/theme settings without pipeline rerun.
4. Connect autosave/performance defaults only when a project has no explicit setting.
5. Add Preferences dialog with Apply/Cancel and stable object names.
6. Audit keyboard focus/order, labels, shortcuts, and non-color-only status indicators.
7. Add context help links to Flowdesk user documentation.

## Required tests

- Invalid preference value falls back with a diagnostic, not a crash.
- Cancel leaves live settings unchanged; Apply updates only intended state.
- New global scientific-looking default cannot change an existing project transform/gate.
- Keyboard navigation reaches primary workflows.
- Status can be distinguished by text/icon, not color alone.
- Import/export round trip and newer-version refusal.

## Do not do

- Do not store credentials or sensitive sample metadata in preferences.
- Do not use `flowjo-manual.md` as Flowdesk operational help.
- Do not make theme/font changes invalidate analysis caches.

## Verification

```bash
./tools/run-gui-tests.sh -q
pytest -q tests/test_project_storage.py
ruff check src tests
```

