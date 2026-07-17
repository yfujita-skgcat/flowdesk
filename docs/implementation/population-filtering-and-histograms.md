# Population Filtering and Histograms Implementation Guide

## Goal

Enable the GUI to filter plot display to a selected population using membership masks
produced by the headless pipeline, and provide 1D histogram and marginal histogram
display modes. All scientific computation remains in `flowdesk_core`; display logic
resides in `flowdesk_qt`.

## Target Files

### Core (Phase 2)
- `src/flowdesk_core/models.py` — `PopulationMembership` dataclass
- `src/flowdesk_core/gating_strategy.py` — membership-aware evaluation API
- `src/flowdesk_core/execution_report.py` — membership field on `ExecutionReport`
- `src/flowdesk_core/pipeline_runner.py` — collect and forward membership masks

### GUI (Phase 3)
- proposed `src/flowdesk_qt/results_workspace.py` — executed results navigation
- transitional `src/flowdesk_qt/population_tree.py` — existing selection callback API
- `src/flowdesk_qt/main_window.py` — apply membership filter to plot
- `src/flowdesk_qt/plot_widget.py` — accept filtered event data

### GUI (Phase 4)
- `src/flowdesk_qt/channel_selector.py` — "Count" option for Y axis
- `src/flowdesk_qt/plot_widget.py` — 1D histogram mode

### GUI (Phase 5)
- `src/flowdesk_qt/plot_toolbar.py` — marginal histogram toggle
- `src/flowdesk_qt/plot_widget.py` — marginal histogram layout

## Scientific Computation vs Display Computation Boundary

### Scientific (flowdesk_core)
- `PopulationMembership` dataclass carrying read-only boolean masks
- `evaluate_gating_strategy_with_membership()` returning both `PopulationResult`
  and membership masks
- `ExecutionReport.population_membership` carrying per-sample membership tuples
- Pipeline runner collecting membership masks after the canonical pipeline steps
  (compensation → derived parameters → transforms → gating)

### Display (flowdesk_qt)
- Results workspace selection callback emitting `(population_id, sample_id)`
- `MainWindow` storing `display_population_id` independently from `selected_gate_id`
- `MainWindow._replot()` applying the membership mask to X/Y columns before
  passing to `PlotWidget.plot_events()`
- Histogram binning, marginal histogram layout, and "Count" display option
- Display downsampling applied **after** membership filtering
- Marginal histogram toggle saved under `plot_display_settings` (not in gates
  or transforms)

### Never mix
- Histogram bin counts must never affect population statistics
- Display downsampling must never affect membership counts
- Membership masks must be derived from full event data, never from downsampled data
- Population selection is display state; it must not trigger pipeline re-execution
  or modify gate definitions

## Phase 2: Population Membership Core API

### Rules
1. `PopulationMembership(sample_id, population_id, mask)` — frozen dataclass.
   The mask must be set read-only via `setflags(write=False)`.
2. `evaluate_gating_strategy_with_membership()` returns
   `tuple[list[PopulationResult], dict[str, NDArray[np.bool_]]]`.
3. Existing `evaluate_gating_strategy()` is kept as a backward-compatible wrapper.
4. `ExecutionReport` gains `population_membership: tuple[PopulationMembership, ...]`
   with default empty tuple. Summary, placeholder mode, and JSON export must not
   include raw mask data.
5. `PipelineRunner._step_gating` collects per-sample membership and attaches it
   to the report.
6. `MainWindow.debug_state()` includes `population_id`, `mask_length`, `event_count`
   but **never** the raw mask array.

### Required Core Tests
- Root mask is all-True.
- Child mask is False outside parent mask.
- Boolean gate mask matches existing event count.
- `PopulationResult.event_count == membership.mask.sum()` for every population.
- Mask shape, dtype, read-only flag verified.
- Multi-sample: sample IDs do not mix.
- Importable and runnable without Qt/PySide6.
- Raw input array is unchanged after gating.

## Phase 3: Population Filtering Display

### Rules
1. Results workspace emits `(population_id, sample_id)` on population row selection via
   `flowdesk_qt.diagnostics.invoke_callback()`.
2. Every sample has separate sample and `all_events` rows. A sample row changes only the
   active sample; selecting `all_events` restores full-event display.
3. On report clear/stale, sample removal, or project reload, invalidate selection.
4. `MainWindow._replot()` fetches the full-length mask for the current sample
   and selected population, applies it to X/Y columns, then calls `plot_events()`.
5. Switching samples: if the same population ID exists in the new sample's report,
   use that sample's mask; otherwise fall back to `all_events`.
6. Gate edit/add/delete marks results stale; old membership must not be displayed.
7. Plot status or Results workspace status shows selected population name and
   full event count.
8. Gate definition selection does not change `display_population_id`; `Show Gate` displays
   the parent population, while explicit `Show Population` displays child membership.

### Required GUI Tests
- 4-event synthetic FCS, gate selects 2 events → scatter receives exactly 2 points.
- Changing X/Y channels still shows 2 points.
- Selecting `all_events` restores 4 points.
- Results workspace event count matches membership sum and displayed full count.
- Gate edit stale-ifies report; old 2-point display is not reused.
- GUI and headless runner population counts match exactly.
- Changing display downsampling does not change headless counts.

## Phase 4: 1D Histogram Display

### Rules
1. ChannelSelector Y candidates include a display-only "Count" option with a
   non-colliding internal value (e.g., `__count__`).
2. X = normal channel, Y = Count → 1D histogram mode.
3. Histogram is a display feature; bin count/bin width are display settings.
4. Histogram input uses Phase 3 filtered (population membership applied) data.
5. NaN/Inf excluded; exclusion count visible in debug state or status.
6. X transform (linear/log10/asinh) must not produce empty or invalid ranges.
7. Y axis label is "Count"; bin counts are non-negative.
8. Mode switch clears old scatter, ROI, and histogram items to avoid overlap.
9. In histogram mode, 2D gate creation is disabled or explicitly rejected;
   range gates on X axis are allowed and saved in raw/data coordinates.
10. PNG export includes histogram.
11. Sample/channel/population/robust/full range switches must not crash.

### Required Tests
- Y="Count" → histogram item exists, not scatter.
- Histogram bin count sum equals finite selected population event count.
- Switching between all_events and gate population changes the sum.
- Returning Y to normal channel restores 2D scatter, old histogram item is gone.
- PNG is non-blank for linear/log10/asinh X.
- 2D gate cannot be erroneously created in histogram mode.
- `debug_state()` includes plot mode, excludes raw values.

## Phase 5: Marginal Histograms

### Rules
1. `PlotToolbar` has a checkable toggle with objectName `toggleMarginalHistogramsButton`.
2. Layout: main plot at center/bottom-left, X marginal on top, Y marginal on right.
3. Uses pyqtgraph `GraphicsLayoutWidget`, `PlotItem`, linked axis.
4. Top histogram X axis linked to main X; right histogram Y axis linked to main Y.
5. Main plot pan/zoom is preserved; linked histograms follow.
6. Marginal histogram input is Phase 3 filtered population data.
7. Histogram aggregation uses full selected population, not scatter-downsampled points.
8. NaN/Inf and log10 non-positive values are handled explicitly.
9. Marginal ON/OFF does not break gate overlay, ROI editing, rectangle drag,
   polygon click.
10. In 1D Count mode, marginal histograms are hidden or disabled.
11. PNG export includes marginal histograms when enabled.
12. `debug_state()` includes marginal mode, bin count, selected population ID,
    but not event arrays.

### Required Tests
- Toggle OFF → only 2D plot; ON → top/right histogram items exist.
- Top and right histogram count sums equal finite selected population event count.
- Population and sample switches update both histograms.
- Main ViewBox range changes are reflected in linked axis ranges.
- Default mouse drag delegates to ViewBox even with marginals ON.
- Existing rectangle/polygon gate and ROI tests still pass.
- PNG with marginals ON is non-blank and differs from OFF image.
- Multi-sample FCS switch tests do not crash, ranges are finite.

## Acceptance Criteria

Per phase:
- All required tests pass.
- `ruff check src tests` passes.
- Core modules importable without Qt.
- No regression in existing tests.
- `MainWindow.debug_state()` is JSON-serializable and excludes raw arrays.
