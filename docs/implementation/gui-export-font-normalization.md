# GUI/export font normalization

## Purpose

Keep title, axis-label, and tick typography visually proportional between the
interactive Qt plot and raster/vector exports on monitors with different
logical DPI settings.  The scientific scene, coordinates, and event data are
unchanged; this is a presentation-only change.

## Root cause

The export renderer interprets presentation font sizes as points and converts
them with the fixed 96-DPI rule (`size * 96 / 72`).  Qt's `QFont(family,
point_size)` instead resolves points through the operating system's screen
logical DPI.  Consequently a high-DPI Windows/macOS display can make GUI
labels larger than the same exported canvas, while plot geometry remains the
same.

## Implementation rules

- Use `flowdesk_core.plot_scene.POINTS_TO_PX` as the single conversion constant.
- In `PlotWidget`, set title and axis-label CSS sizes in logical pixels, not
  `pt`, and construct tick/baseline fonts with `QFont.setPixelSize()`.
- Keep the existing presentation font size in the project model as a
  point-like value for backwards compatibility; only its rendering conversion
  changes.
- Do not import Qt or Pillow into `flowdesk_core`, and do not move scientific
  execution into the widget.
- Preserve font family, weight, title line count, layout measurements, and
  export scene metadata.  Only the platform-dependent point-to-pixel step is
  normalized.

## Target files

- `src/flowdesk_qt/plot_widget.py`: normalized pixel conversion for title,
  axis-label, tick, and title-baseline measurement.
- `tests/gui/test_qt_plot_export.py`: deterministic assertions for the 96-DPI
  conversion and Qt tick font metrics.
- `docs/user-manual/user_manual.md`: document that GUI and export use the same
  logical 96-DPI font scale.

## Verification

Run the focused Qt tests and the non-GUI suite.  Inspect a GUI screenshot and
the PNG rendered at 96 and high raster DPI after scaling them to the same
logical canvas.  The plot rectangle, title/axis/tick relative sizes, gate
coordinates, and event positions must agree; OS-specific glyph hinting may
still change individual edge pixels.

## Acceptance criteria

1. A presentation size of 14 renders as 19 logical pixels (`round(14*96/72)`)
   in both Qt and export, independent of monitor logical DPI.
2. Tick and axis-label `QFont.pixelSize()` values follow the same conversion.
3. Existing title-baseline and layout metadata tests remain green.
4. No scientific result, gate membership, or project-file semantic changes.
