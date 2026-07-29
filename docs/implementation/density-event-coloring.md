# Single-sample density event coloring

ToDo: `Phase B7.2.Density`

## Current state and required replacement

`PlotPresentationSpec.colormap == "density"` already persists a display-only density
color request for `dot` and `scatter` plots. It is active only for a single base sample;
an overlay keeps the request saved but falls back to the normal source/population colors.
Gate outlines stay visible, while per-event population/gating colors are ignored only
when density color is active.

The first implementation in `flowdesk_core.density_colors.density_event_colors` is an
intentionally simple fixed 128 x 128 occupancy lookup over display-downsampled points.
It causes visible square blocks and five flat color levels. **Do not tune its bin count
or palette as the final fix. Replace it using the increments below.**

This work is display-only. It must never change raw events, compensation, derived
parameters, transforms, gate geometry or membership, counts, frequencies, statistics,
pipeline revision, or headless analytical results.

## Required reading before every increment

Read in full before editing:

1. `AGENTS.md`
2. `ToDo.md`, `Phase B7.2.Density`
3. `docs/implementation/llm-task-protocol.md`
4. this document
5. `.codex/skills/qt-plot-widget/SKILL.md`
6. `.codex/skills/performance-benchmark/SKILL.md`
7. `.codex/skills/scientific-review/SKILL.md`
8. `src/flowdesk_core/density_colors.py`
9. `src/flowdesk_qt/plot_widget.py`, `src/flowdesk_qt/main_window.py`
10. `src/flowdesk_cli/batch_plot.py`, `src/flowdesk_core/plot_export.py`
11. `tests/test_density_colors.py`, `tests/test_qt_plot_widget.py`,
    `tests/test_plot_export_reuse.py`, `tests/test_cli_batch_plot.py`

One LLM run implements exactly one increment. Do not combine core estimator, Qt cache,
and export integration in one run.

## Fixed user-visible contract

- UI wording remains **Event colors → Single color / Density color (single sample)**.
- Density uses the active sample's selected display population and its current transformed
  X/Y coordinates. It is a local visual estimate, not a new plot type or scientific
  density result.
- With any resolved visible overlay, density mode is inactive and existing color
  precedence applies. Do not blend base density colors with overlay or gating colors.
- The visible density field follows the current ViewBox range and plot-area aspect ratio.
  Pan, zoom, robust/full reset, resize, axis/transform/population/sample change, or
  display-point-limit change must not leave stale colors on screen.
- The same resolved data bounds and estimator configuration are used by batch PNG, SVG,
  and PDF. DPI alone must not alter density values or the color distribution; it only
  changes raster sharpness.
- Invalid/non-finite display coordinates are excluded from density estimation exactly as
  they are excluded from scatter rendering. They are not silently turned into a density
  value.

## Target files

Expected production files (do not add Qt imports to core):

- `src/flowdesk_core/density_colors.py`: pure NumPy estimator, configuration/result types,
  deterministic interpolation and continuous palette mapping.
- `src/flowdesk_qt/plot_widget.py`: cache ownership, ViewBox/resize invalidation, and
  recoloring of already selected display points. It calls the core estimator only.
- `src/flowdesk_qt/main_window.py`: passes canonical processed display data and keeps the
  overlay/gating-color exclusion policy.
- `src/flowdesk_cli/batch_plot.py` and `src/flowdesk_core/plot_export.py`: use the same
  core estimator with the export viewport; retain vector-scatter mode semantics.
- `tests/test_density_colors.py`, `tests/test_qt_plot_widget.py`,
  `tests/test_plot_export_reuse.py`, `tests/test_cli_batch_plot.py`, and focused GUI
  tests.
- `docs/user-manual/user_manual.md`: update behavior and any performance limitation only
  after the final increment.

Do not change `PlotPresentationSpec.colormap == "density"`, project migration behavior,
or the existing no-overlay restriction unless a separately reviewed UX requirement says
so.

## Canonical estimator contract

The core API must receive:

- all finite, transformed coordinates in the selected display population;
- explicit viewport bounds `(x_min, x_max, y_min, y_max)`;
- explicit logical plot pixel width/height (not raster DPI pixels);
- a deterministic configuration version; and
- a separate array of display-sampled points at which colors are requested.

It must return one RGB/`#RRGGBB` color per requested display point plus inspectable
metadata: grid dimensions, bounds, smoothing sigma, normalization low/high values,
valid input count, and algorithm version. A small frozen dataclass is preferred over an
unstructured dictionary. The core API raises clear `ValueError`s for unequal dimensions,
non-positive viewport size, or invalid bounds.

### Algorithm, in required order

1. Apply the existing display transform once, and use the same finite/log-domain filter
   as the scatter renderer. Never transform gate coordinates or source data again.
2. Clip estimator input to the current viewport. Points outside it do not contribute to
   the visible local density. Keep the existing scatter clipping behavior unchanged.
3. Build a 2D histogram from **all valid input points**, before deterministic scatter
   downsampling. This is O(N) and bounded-memory; it is not permission to render all N
   markers. Use pixel-aspect-aware grid dimensions, preserving the plot aspect ratio.
   Start from approximately one density cell per 2 logical pixels and clamp each axis to
   128..512 cells. The grid must be reproducible from bounds, logical size, and config.
4. Smooth the histogram with a separable Gaussian kernel in grid/pixel units. Start with
   `sigma = 1.25` logical pixels, radius `ceil(3 * sigma)`, normalized kernel, and a
   documented edge policy. Implement with NumPy only unless adding an optional dependency
   has explicit approval; separable `np.convolve`/padding or deterministic FFT is valid.
5. Evaluate the smoothed field at each display-sampled point using bilinear interpolation,
   not nearest-cell lookup. Points on bounds must be clamped safely; no index wrapping.
6. Apply `log1p` to positive sampled density. Normalize using deterministic robust
   percentiles of positive in-viewport grid values (initial policy: 1st and 99.5th
   percentiles). Define the equal/empty-field fallback explicitly. Do not compute
   percentiles from the downsampled points.
7. Map normalized values through a continuous, at-least-256-level blue → cyan → green →
   yellow → red palette. Interpolate fixed RGB stop values; do not use a five-entry
   nearest-color palette. Keep the palette stops and estimator version centrally defined.

The final field should resemble ordinary cytometry density plots: compact populations
have smooth concentric color changes instead of rectangular color islands. It need not
claim numerical equivalence to FlowJo, KDE, or a particular commercial palette unless a
separate validated comparison is added.

## Increment 1 — Pure core estimator and numerical tests

**Status: completed.** `smooth-density.v1` provides the pure NumPy typed result,
aspect-aware grid, Gaussian smoothing, bilinear interpolation, robust normalization, and
continuous palette. Increment 2 must now connect full pre-downsample input and viewport
invalidation; it must not reimplement the estimator.

Non-goals: Qt signals, cache, project schema, batch export, and UI changes.

1. Add failing tests for a synthetic dense Gaussian cluster plus sparse background:
   central points are warmer than equally located sparse points; colors vary smoothly
   across adjacent coordinates; at least 32 distinct colors are produced for a suitable
   non-degenerate fixture; and results are bit-for-bit deterministic.
2. Add tests for viewport clipping, non-finite values, empty/singleton/equal-density
   fields, reversed/zero ranges, non-square viewport, bounds-edge interpolation, and
   invalid shape/config diagnostics.
3. Implement the typed pure-NumPy contract above. Keep old helper callers compatible only
   through a thin wrapper with explicit legacy defaults; do not retain two estimators.
4. Record an estimator metadata snapshot in the tests so configuration changes cannot
   silently alter published figures.

Acceptance: no rectangular nearest-cell assignment remains in the canonical path; no
Qt import exists in `flowdesk_core`; all scientific arrays supplied to the helper remain
unchanged.

## Increment 2 — Qt preview data flow, cache, and invalidation

**Status: completed.** Qt retains full transformed finite coordinates solely as density
input, limits marker drawing through the existing deterministic sampler, and debounces
ViewBox/resize recoloring. The one-entry immutable-array cache is keyed by input identity,
viewport, and logical plot size and is cleared on resize/plot clear.

Non-goals: changing gate membership, display downsampling policy, export adapters, or
overlay behavior.

1. Refactor `PlotWidget.plot_events` so it calculates density from full transformed valid
   display data before `_display_sample_indices`, then assigns colors only to sampled
   markers. Preserve deterministic sample indices and the existing `display_state`
   counts.
2. Add a debounced ViewBox range/resize update. The initial auto/manual range must settle
   before the first density field is calculated; avoid recursive range-change rendering.
3. Cache the estimator result only with this complete key: sample/analysis revision,
   display population, X/Y stable parameter IDs, transform IDs and settings, full-input
   identity or deterministic content/revision identity, viewport bounds, logical plot
   width/height, density configuration version, and density-mode flag. Clear the cache
   on every listed contract change and on `clear_plot`/widget destruction.
4. Do not cache QGraphicsItems or mutable event arrays. Cache only immutable NumPy
   density-grid/result data. Document memory accounting and cap/evict old entries.
5. Add Qt tests using stable object state/signal processing: zoom or resize changes the
   cache key and recolors; repeated unchanged renders reuse cache; switching density off
   restores normal population colors; overlay keeps density inactive; gate membership,
   count, and result revision do not change.

Acceptance: the preview has no 128-cell block pattern on the synthetic fixture and uses
at most the configured display-marker limit while density input remains full population.

## Increment 3 — Headless export parity, vector behavior, and documentation

**Status: completed.** Batch export estimates density from the full normalized source,
clips to the logical export viewport, and passes the resulting event-order colors to all
PNG/SVG/PDF adapters. Sidecars record the estimator metadata or the overlay fallback.

Non-goals: changing export page geometry, DPI semantics, gate coordinates, or the three
existing vector-scatter modes.

1. Give the batch renderer the resolved export bounds and logical plot area size, then
   call the same core estimator and configuration version as preview. Do not calculate
   density from SVG/PDF physical DPI or from an already rasterized image.
2. PNG/SVG/PDF must receive exactly the colors assigned for their visible event order.
   With density colors, `compact_vector` must not silently drop points or collapse
   different colors. Preserve draw order for translucent markers; if this prevents
   compaction, record the deliberate fallback in sidecar provenance and document it.
3. Add parity tests with a fixed synthetic scene: identical per-event colors/order in
   PNG/SVG/PDF input, same gate coordinates and labels, no density colors with overlays,
   and equal color assignment for 96 vs 600 DPI at the same logical width/height.
4. Add/update sidecar metadata with estimator version, bounds, grid, sigma, normalization,
   and whether density was inactive because of overlays.
5. Update the user manual after tests pass. Explain that density is display-only, uses all
   valid selected-population events for estimation, displays at most `Display max points`,
   and is unavailable with overlays.

Acceptance: GUI and batch scene semantics agree; PNG/SVG/PDF do not exhibit new square
block artifacts on the visual regression fixture; project reload preserves the request.

## Performance and regression evidence

For every increment, use synthetic arrays and record median runtime and peak/allocation
evidence for 20k, 100k, and 1M valid events on the development machine. A 2D grid is
bounded memory; do not allocate one object, brush, or kernel result per full-resolution
event. Benchmark full-density calculation separately from marker drawing and from gate
membership. A change may not use display-downsampled points for density merely to improve
the benchmark.

Run focused tests first, then at final completion:

```bash
python -m pytest -q tests/test_density_colors.py tests/test_qt_plot_widget.py \
  tests/test_plot_export_reuse.py tests/test_cli_batch_plot.py
./tools/run-gui-tests.sh -q
python -m pytest -m "not gui"
ruff check src tests
git diff --check
```

Report benchmark command/environment, median timings, cache hit/miss behavior, peak
memory evidence, remaining GUI/backend differences, and the next uncompleted increment.
