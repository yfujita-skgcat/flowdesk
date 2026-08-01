# Windows GUI / PNG Font-Size Parity

## Purpose

Resolve the confirmed defect that a PNG produced by Batch Plot Export has
much smaller title, axis-label, and tick fonts than the Windows GUI plot.
The immediate task is to remove the packaged Windows font fallback defect.
The follow-up task is to make the comparison contract explicit and
deterministic on Windows high-DPI displays.

This is presentation/export work only. It must not change raw FCS events,
compensation, derived parameters, transforms, gate membership, statistics,
display-event sampling, or the saved analysis definitions.

## Evidence from the reported reproduction

The dialog shows:

- logical canvas: `657 × 657` at the 96-DPI reference;
- raster DPI: `300`;
- resolution mode: `dpi_scaled`;
- effective raster: approximately `2053 × 2053` pixels;
- the image viewer displays the PNG at `28%` zoom.

The viewer zoom means the two screenshots are not a 1:1 size comparison, but
it cannot explain why frame lines, ticks, and grid lines keep their expected
relative size while only text becomes extremely small. The 161% close-up
confirms that this is an intrinsic PNG defect. Normalized or 100% inspection
remains useful for regression measurements, not for explaining away the bug.

## Confirmed primary cause

The PNG writer currently resolves fonts through:

```python
ImageFont.truetype("DejaVuSans.ttf", requested_size)
ImageFont.truetype("DejaVuSans-Bold.ttf", requested_size)
```

and silently falls back to `ImageFont.load_default()` on `OSError`. The
PyInstaller specifications do not bundle either DejaVu font, and Pillow itself
does not ship these TTF files in the installed package. Linux succeeds only
because `/usr/share/fonts/truetype/dejavu/` is discoverable. A normal Windows
PyInstaller installation has no equivalent bundled file, so the fallback is
used.

The fallback bitmap font ignores the requested scaled size. In the reproduced
Linux inspection, a requested 58-pixel DejaVu font had a representative glyph
box approximately 44 pixels high, while `ImageFont.load_default()` was only
8 pixels high. This explains why frame lines, ticks, grid lines, and points
scale correctly at 300 DPI while only title/axis/tick text remains extremely
small. Viewer zoom is not the primary cause shown in the Windows screenshot.

There is a second contract gap: `_font()` ignores the requested font family
and returns DejaVu whenever available. The corrective work must define a
deterministic bundled fallback and must not pretend that an unavailable custom
family was rendered successfully.

## Additional technical causes to verify

1. `PlotWidget` uses Qt/pyqtgraph font requests such as CSS `font-size: Npt`
   and `QFont` point sizes. Windows may apply system logical DPI and Qt
   `devicePixelRatio` to these metrics.
2. The core raster exporter converts persisted point sizes with the fixed
   `96 / 72` points-to-logical-pixels conversion, then applies the resolved
   raster scale. This is correct only if the persisted presentation contract
   is a 96-DPI logical contract.
3. GUI layout measurements use `QFontMetrics`, while PNG text uses Pillow
   font metrics. Different font fallback, hinting, ascent/descent, and bold
   coverage can change apparent size and title/axis placement even when the
   nominal size is equal.
4. The GUI may be rendered on a Windows display scaled to 125%, 150%, or
   200%, while the export is intentionally independent of monitor scaling.
   This must not cause the export's logical geometry to change.
5. Image-viewer auto-fit still affects visual comparisons, but it cannot
   explain text being much smaller than the correctly scaled frame and ticks
   within the same image.

## Required diagnostic capture

Add a temporary or opt-in diagnostic record for one GUI export. Do not log
sample events or sensitive annotation values. Record only:

- OS and Qt/PySide6 versions;
- `QScreen.logicalDotsPerInchX/Y`, `QScreen.devicePixelRatio`,
  `QApplication.primaryScreen()` identity, and `QT_SCALE_FACTOR`;
- GUI canvas logical width/height and measured plot rectangle;
- resolved `FontSpec` for title, axis label, tick, and legend;
- GUI `QFont` family, point/pixel size, weight, ascent, descent, line height,
  and `QFontMetrics.boundingRect()` for representative strings;
- export `ExportCanvasSpec`, logical/raster dimensions, requested DPI,
  resolution mode, and output PNG metadata;
- core export font family, effective pixel size, ascent/descent if available;
- image-viewer zoom only when the comparison tool controls the viewer.

The diagnostic must be written to the existing GUI debug log or a sidecar
under `artifacts/gui`; never make diagnostics part of the scientific project
manifest by default.

## Implementation plan

### Increment 1: Reproduce and measure the confirmed discrepancy

Target files:

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/qt_plot_export.py`
- `src/flowdesk_core/plot_export.py`
- `tests/gui/test_qt_plot_export.py`
- a diagnostic helper under `tools/` or `tests/helpers/`

Steps:

1. Generate the same synthetic plot at logical 657 × 657 and 300 DPI.
2. Save GUI screenshot and core PNG, record all dimensions and font metrics.
3. Compare the PNG at 100% and after deterministic downsampling to 657 × 657;
   never compare an auto-fit screenshot to a GUI screenshot.
4. Measure title/axis/tick glyph bounding boxes and plot rectangle positions
   rather than relying only on visual inspection.
5. Repeat with `QT_SCALE_FACTOR=1`, `1.25`, `1.5`, and `2` on Linux where
   possible, then run the same recipe on native Windows.
6. Confirm that the packaged Windows run resolves to Pillow's fixed bitmap
   fallback and measure any additional logical-DPI or layout discrepancy after
   the bundled scalable font is used.

Acceptance: a report records the resolved font path/type and a before-image
comparison at equal logical scale. It must distinguish the confirmed font
fallback defect from any remaining metric/layout difference.

### Increment 2: Define one font-size contract

Target files:

- `src/flowdesk_core/models.py`
- `src/flowdesk_core/plot_scene.py`
- `src/flowdesk_core/plot_export.py`
- `src/flowdesk_qt/plot_widget.py`

Rules:

1. Persist font requests in points for user-facing settings, but resolve them
   once to explicit logical 96-DPI canvas units for a `PlotScene`.
2. Store the resolved family, weight, logical pixel size, and line metrics in
   the scene's presentation/layout snapshot when GUI measurement is required.
3. Do not read Windows monitor DPI when resolving headless export geometry.
   Monitor DPI may affect physical display size, never logical scene geometry.
4. Do not multiply font sizes by raster DPI twice. Exactly one
   `raster_scale = requested_dpi / 96` is applied to text, ticks, lines, dots,
   and margins by raster adapters.
5. Keep font fallback explicit. If the requested family is unavailable in a
   headless exporter, record the fallback family and allow only a documented
   metric tolerance; do not silently substitute a smaller size.

Preferred implementation: use a typed `ResolvedFontSpec` or equivalent in
the canonical scene, with `logical_px_size` and optional ascent/descent. Qt
and Pillow adapters consume this logical contract. If exact cross-backend
metrics cannot be shared, use the same logical size and compare geometry with
font-rendering tolerance while enforcing no clipping/overlap.

### Increment 2A: Bundle a deterministic scalable raster font

This packaging correction may be implemented before the broader font-contract
refactor because it directly fixes the confirmed Windows regression.

Target files:

- a repository-owned font asset directory under `src/flowdesk_core/assets/`;
- `src/flowdesk_core/plot_export.py`;
- `packaging/flowdesk.spec` and `packaging/flowdesk-cli.spec`;
- `tests/packaging/test_pyinstaller_spec.py`;
- `THIRD_PARTY_NOTICES.md` plus the exact font license text;
- raster export and packaged smoke tests.

Rules and steps:

1. Bundle regular and bold variants of one scalable font with redistribution
   terms compatible with the project. DejaVu Sans is the current expected
   default, but its exact license and copyright notice must be committed and
   shipped with every package.
2. Resolve the font through `importlib.resources` or another source/frozen-safe
   resource helper. Do not depend on the current working directory, Linux
   `/usr/share/fonts`, Windows `%WINDIR%/Fonts`, or Pillow's search behaviour.
3. Add the font assets to both GUI and CLI PyInstaller specifications because
   headless Batch Plot Export uses the same PNG writer.
4. Replace silent `ImageFont.load_default()` fallback. If the bundled scalable
   fallback cannot be opened, raise a structured `PlotExportError` containing
   the requested family/weight/size; do not publish a visually invalid PNG as
   success.
5. Resolve regular and bold files explicitly. Do not synthesize bold by
   changing stroke width unless that becomes a documented presentation rule.
6. Record requested family, resolved family, resource identity/hash, requested
   point size, logical pixel size, and raster pixel size in export provenance.
7. A custom requested family may resolve to the bundled deterministic fallback
   only with an explicit diagnostic in the sidecar. Future platform font
   discovery must not make output silently platform-dependent.

Acceptance:

- a clean Windows onedir package with no system DejaVu installation renders
  title/axis/tick text at the same normalized size as Linux;
- 300-DPI text dimensions are approximately `300 / 96` times their 96-DPI
  pixel dimensions before normalization, within raster rounding tolerance;
- missing or corrupt bundled fonts fail the output structurally instead of
  using Pillow's fixed bitmap default;
- the package smoke test inspects a rendered PNG and rejects glyph coverage
  consistent with `ImageFont.load_default()`;
- font licenses and notices are present in both GUI and CLI artifacts.

### Increment 3: Align GUI and PNG rendering

Target files:

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/qt_plot_export.py`
- `src/flowdesk_core/plot_export.py`
- `src/flowdesk_core/plot_scene.py`

Steps:

1. Ensure the GUI scene snapshot and Batch PNG use identical title lines,
   axis labels, tick labels, plot rectangle, title baselines, and visibility.
2. Ensure Qt GUI font application uses the resolved logical scene size rather
   than an implicit monitor-DPI conversion. If Qt point units are retained,
   document and test the conversion at each platform scale.
3. Ensure Pillow/core export uses the same family/weight/size contract and
   does not apply a second DPI conversion.
4. Keep raster dimensions controlled by `ExportCanvasSpec`; changing DPI may
   increase pixel count, but must not alter normalized font/plot proportions.
5. Preserve the existing `legacy_pixel_dimensions` compatibility behavior for
   old definitions.

### Increment 4: Windows-focused regression tests

Add tests for:

- 657 × 657 logical canvas at 96, 150, 300, and 600 DPI;
- `QT_SCALE_FACTOR` values 1, 1.25, 1.5, and 2 where the test environment
  supports them;
- title, axis label, tick, and legend font sizes and bold weights;
- one-line, multi-line, long-title, and superscript tick labels;
- GUI scene/export scene equality for logical plot rectangle and anchors;
- normalized PNG comparisons after resizing high-DPI images to logical size;
- no title/axis clipping or overlap;
- output PNG dimensions and density metadata;
- unchanged point-plan hash, rendered event count, gate geometry, and analysis
  results.

Native Windows/PyInstaller visual validation should run in the release
workflow when available. When no Windows host is available, Linux tests with
controlled Qt scale factors are useful but cannot claim native Windows font
fallback parity.

### Increment 5: Documentation and user-facing comparison guidance

Update `docs/user-manual/user_manual.md` only after the implementation is
verified. Explain that a high-DPI PNG has more pixels and may be shown at a
smaller viewer zoom, while its logical font/plot proportions remain constant.
Document how to inspect at 100% or compare normalized images. Do not describe
the viewer zoom as an export setting.

## Prohibited fixes

- Do not simply enlarge export fonts until a 28% screenshot looks like the
  GUI; that would make 100% output and 96-DPI output incorrect.
- Do not retain `ImageFont.load_default()` as a successful production fallback;
  it does not preserve requested font size across DPI.
- Do not rely on a font installed by the build runner or end user's OS.
- Do not use monitor DPI to change scientific ranges, gate coordinates,
  event sampling, or canvas logical geometry.
- Do not change DPI, width, height, `Display max points`, or vector scatter
  mode automatically to hide the discrepancy.
- Do not replace the canonical scene with a screenshot or screen capture.
- Do not weaken parity assertions to accept clipped labels or missing title
  lines.

## Verification commands

```bash
python -m pytest tests/test_plot_export_reuse.py tests/gui/test_qt_plot_export.py -q
python -m ruff check src/flowdesk_core/plot_scene.py src/flowdesk_core/plot_export.py \
  src/flowdesk_qt/plot_widget.py src/flowdesk_qt/qt_plot_export.py tests
```

Native Windows verification must additionally record the Windows display
scale, Qt logical DPI, PNG dimensions, and the viewer zoom used for every
comparison.
