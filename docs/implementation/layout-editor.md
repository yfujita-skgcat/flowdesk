# Layout Editor and Headless Renderer

Spec: `S13`
ToDo: `Phase C2`

## Goal

Persist graphical report scenes and render the same scene through GUI preview and
headless PNG/SVG/PDF backends.

## Inspect first

- plot export code in `src/flowdesk_qt/plot_widget.py`
- core report/statistics/overlay/table models
- storage schema and export CLI
- GUI diagnostic and image tests

Prerequisites: Graph Window v2, overlays, Table Editor.

## Scene contract

Define page and objects using device-independent units. Object variants: plot, overlay,
table, statistic text, legend, shape, and annotation. Each has stable ID, bounds, z-order,
style, and data reference. Scene data contains no QWidget, QGraphicsItem, event array, or
membership mask.

## Increments

1. Add scene/page/object models, validation, and serialization.
2. Define a renderer-neutral resolved scene containing values and display data.
3. Implement one headless PNG backend with fixed size/font tests.
4. Add SVG, then PDF as separate adapters.
5. Add Qt canvas selection/move/resize and exact model updates.
6. Add align/distribute/group/lock/duplicate through undo commands.
7. Add sample/group/keyword iteration and filtered batch.
8. Add font fallback diagnostics and provenance metadata.

## Required tests

- Scene round trip retains object IDs, units, bounds, and references.
- Resolver uses headless statistics/table/plot definitions.
- PNG/SVG are nonblank and contain expected object/text counts.
- GUI edit changes serialized bounds, not rendered scientific values.
- Batch iteration produces deterministic filenames and sample bindings.
- Missing font/data reference is diagnosed without silently dropping the object.

## Do not do

- Do not serialize Qt objects.
- Do not use screenshots of widgets as the canonical renderer.
- Do not calculate statistics in text/legend objects.

## Verification

```bash
pytest -q tests/test_export.py tests/test_project_storage.py
./tools/run-gui-tests.sh -q
ruff check src tests
```

