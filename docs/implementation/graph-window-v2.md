# Graph Window v2

Spec: `S09`
ToDo: `Phase B6`

## Goal

Provide persisted plot definitions and multiple scientifically honest visualization modes
without coupling rendering aggregates to gate/statistic calculations.

## Inspect first

- `src/flowdesk_qt/plot_widget.py`, `plot_toolbar.py`, `plot_style.py`
- `src/flowdesk_qt/channel_selector.py`, `main_window.py`
- `src/flowdesk_core/models.py`, `statistics.py`
- plot and GUI tests

Read `qt-interactive-plot-controls.md`, `population-filtering-and-histograms.md`,
`scientific-transforms-v2.md`, and `.codex/skills/performance-benchmark/SKILL.md`.

## Display contract

`PlotViewSpec` stores population reference, axes/transform IDs, plot type, viewport, and
style. It is display state except where transform IDs define gate coordinate context.
Render input is the full selected membership; display sampling/aggregation is a separate,
versioned setting and never changes scientific counts.

## Increments

1. Add PlotViewSpec serialization and restore existing scatter/histogram state.
2. Refactor render preparation into a Qt-independent display-data adapter.
3. Add CDF with finite-value and normalization tests.
4. Add density/pseudocolor aggregation with deterministic bin edges.
5. Add contour rendering from the same density grid; document smoothing.
6. Add duplicate tabs/views and linked sample navigation.
7. Add exclusive pan/select/gate modes and visible status.
8. Add SVG/PDF export plus provenance sidecar after PNG parity.

## Required tests

- Every plot type handles empty, NaN/Inf, log/asinh/logicle, and constant data.
- Density bin sum equals finite selected full-population count.
- Changing rendering resolution does not change runner statistics.
- Restored view keeps axes, transforms, plot type, and viewport.
- Gate overlay remains aligned and editable only in matching coordinates.
- Export is nonblank and includes labels/visible gates.

## Do not do

- Do not call pyqtgraph aggregation output a scientific statistic.
- Do not implement a new transform inside the renderer.
- Do not save transient mouse state in PlotViewSpec.

## Verification

```bash
pytest -q tests/test_qt_plot_widget.py tests/gui/test_population_filtering.py
./tools/run-gui-tests.sh -q
```

