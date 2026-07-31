# PDF export performance and renderer parity

Status: Increments 1-2 implemented; remaining increments planned

This guide is the implementation contract for the remaining PDF batch-export
latency and GUI/export visual-parity defects. It is deliberately separate from
the completed lightweight-vector-scatter increments: those increments define
scatter representation, whereas this guide removes divergent layout and
writer paths without changing the selected events or scientific results.

An implementing LLM must read this document, `docs/implementation/plot-export-completion.md`, and
`docs/implementation/lightweight-vector-scatter-export.md` completely before
changing production code. Implement exactly one numbered increment per run,
update `ToDo.md` and `docs/user-manual/user_manual.md` when user-visible
behaviour changes, run the stated tests, commit, and stop before the next
increment.

## 1. Observed facts and confirmed causes

The reported batch run is producing a PDF while PNG/JPEG complete quickly.
For `hybrid_raster`, PDF generation first creates a transparent high-DPI
scatter raster, then compresses and embeds its RGB image and alpha mask as PDF
Image XObjects. This is qualitatively different from PNG/JPEG output and can
dominate the duration of one output.

The current progress counter intentionally increments only after a complete
file is atomically published. Consequently `rendering_started: 0/60` means
that one or more outputs have started but no PDF is complete; it is not proof
that no work is being done. `max_workers` parallelises prepared output items,
not the per-event rasterisation inside one PDF. Thread workers therefore do
not bypass Python/GIL-bound marker compositing, and the effective worker count
may additionally be reduced by the memory budget.

The visual-parity audit found actual divergent code paths:

1. `MainWindow._BatchPlotExportWorker` explicitly requests
   `renderer_backend="headless"`, while `batch_plot_command()` currently does
   not consume `renderer_backend` at all. The parameter is dead API, not a
   backend selector.
2. GUI uses pyqtgraph `PlotItem` and reserves its title row from
   `QFontMetrics`. Batch PNG, SVG, and PDF use separate core writers.
3. The core `PlotScene` transfers only a plot-area margin. It has no typed
   title block/baseline geometry.
4. `_draw_raster_text()` and `_pdf_scene_text()` place title lines at fixed
   20-unit offsets. They do not derive their baselines from the actual title
   block or plot rectangle.
5. `write_plot_svg()` still draws one `selected.title` at fixed `y=32`; it
   does not use `scene.title_lines`, `scene.title_colors`, or a shared title
   layout. This is legacy rendering code and must not remain authoritative.

Thus the current guarantee is only partial shared *scene data*, not one
physical renderer backend. A headless SVG/PDF backend is required for CLI and
must remain Qt-independent; forcing a temporary Qt widget into worker threads
would be unsafe. The correct convergence point is a complete canonical scene
and layout contract consumed by every backend, not screen capture or Qt-only
export.

## 2. Non-negotiable boundaries

- Preserve raw FCS data, compensation, derived parameters, transforms, gate
  membership, population statistics, deterministic display-event selection,
  source order, point coordinates, colors, alpha, and gate geometry.
- Do not silently lower `hybrid_scatter_dpi`, change vector mode, or change
  selected display points to make a PDF faster.
- Keep `flowdesk_core` independent of Qt. Qt may render a resolved core layout
  but may not become the headless/PDF implementation.
- Do not make batch workers paint a live or temporary `QWidget`, `QPixmap`, or
  pyqtgraph object.
- Do not claim pixel-identical fonts across independent rendering libraries.
  Require equal logical text/layout geometry and bounded raster comparison.
- Do not add a process pool merely because CPU utilisation looks low. Any
  process design must avoid pickling large event arrays and must work with
  Windows `spawn`, cancellation, and bounded aggregate memory.

## 3. Required baseline evidence

Before choosing an optimisation, add or extend a benchmark command that can
run one saved definition and emit JSON. It must measure each format separately
and record:

- requested and effective workers plus limiting factors;
- event count per source, source count, overlay count, canvas dimensions,
  vector mode, hybrid DPI, and memory budget;
- planning, source preparation, scene construction, hybrid-raster generation,
  RGB/alpha compression, PDF object/stream writing, and atomic publish time;
- wall time, CPU time if available, peak RSS, output size, and cancellation
  latency;
- scene hash, point-plan hash, and output hashes for repeatability.

Use a deterministic synthetic fixture in automated tests and document a manual
command for the reported real-FCS project without committing that project or
its FCS files. Benchmark PNG, JPEG, PDF, and SVG independently, then PDF in
`full_vector`, `compact_vector`, and `hybrid_raster` modes at 150, 300, and
600 DPI where applicable. Repeat with workers 1, 2, 4, and a bounded high
value. Report effective rather than requested workers.

The acceptance decision is evidence-based: identify whether the dominant PDF
cost is source-over scatter compositing, PNG/alpha compression, PDF stream
construction, or filesystem I/O. Do not choose a worker/backend change before
this report exists.

### Baseline implementation evidence

The current sidecar records `scatter_composite_seconds`,
`scatter_png_encode_seconds`, `pdf_scatter_cache_seconds`,
`pdf_command_seconds`, `pdf_publish_seconds`, and `pdf_total_seconds` for
hybrid PDF output. `tools/benchmark_batch_plot.py` aggregates these values by
format and run. A Linux synthetic run with 10,000 events, a 640×480 logical
canvas, and 300-DPI hybrid scatter measured approximately 3.0 seconds in
scatter cache preparation and 0.06 seconds in PDF command/write work. This is
diagnostic evidence only; it is not a universal performance threshold and must
be repeated for the user's real FCS workload.

## 4. Increment 1: canonical logical text and plot layout

Add a typed, serialisable renderer-neutral layout object to the core scene,
for example `PlotLayoutSpec` with:

- logical canvas rectangle;
- plot rectangle (`left`, `top`, `width`, `height`);
- title block rectangle and one logical baseline/top position per title line;
- title line height, title alignment, font request, and title colors;
- axis-label anchors, tick-label bands, legend rectangle/anchors, and the
  visibility flags used to reserve each band.

The layout resolver must be a pure core function. It receives `PlotScene`,
`PlotPresentationSpec`, logical canvas size, and visibility options, and
returns deterministic logical coordinates. It must reserve title height from
the number of non-empty title lines. It must never use Qt font metrics as its
only source of truth. Use an explicit, documented line-height policy so every
backend has the same baselines; font metrics may be retained only as a
diagnostic indicating clipping/fallback.

Change the GUI to consume this resolved layout when allocating its title row
and ViewBox. Do not continue to snapshot only `PlotWidget.plot_area_margins()`
from an already-laid-out widget. For each batch item, resolve layout after its
own title lines and visibility are known. This prevents an active GUI title
with a different number or length of lines from determining another sample's
exported plot rectangle.

Required tests:

- one, two, and three overlay title lines, including long sample titles;
- title on/off, axis labels on/off, ticks on/off, legend on/off, and 1:1;
- no title glyph/bounding box may intersect the plot rectangle;
- GUI ViewBox rectangle equals the resolved logical plot rectangle within a
  documented tolerance;
- scene/save/load/CLI construction retains layout values without changing
  analysis results.

## 5. Increment 2: remove divergent legacy writer layout

Make SVG, PDF, PNG, and JPEG consume the same resolved layout object. Remove
all hard-coded title coordinates and duplicated margin constants from writer
code, including the current SVG `selected.title`/`y=32` path and the
PNG/PDF 20-unit title offsets. SVG must use `scene.title_lines` and
`scene.title_colors`; PDF and raster writers must use exactly the same line
anchors and visibility policy.

Centralise renderer-independent command construction where practical:

1. Build canonical layout/text/tick/gate draw records in `flowdesk_core`.
2. Let PNG/JPEG, SVG, and PDF adapt those records only to native primitives.
3. Keep scatter representation adapters mode-specific, but prohibit them from
   recomputing title, axes, ticks, clipping, or plot geometry.

Audit all public export entry points and delete or refactor code that bypasses
the canonical record path. This includes `write_plot_svg`, `write_plot_png`,
`write_plot_pdf`, `write_plot_jpg`, single-export actions, batch/CLI dispatch,
and any Qt-only export adapter. Remove the unused `renderer_backend` parameter
unless a real, tested backend strategy is introduced. Update old documentation
that says GUI batch export uses a Qt adapter: the supported design is a common
core scene/layout with independent Qt preview and headless output adapters.

Add an explicit `renderer_contract_version` plus resolved layout to sidecars.
This makes old artifacts diagnosable without making output files depend on
runtime Qt availability.

Required tests:

- a route test proves every GUI/CLI/batch format reaches the canonical layout
  builder exactly once and no worker creates a Qt plotting object;
- SVG contains every title line, its resolved color, and its logical anchor;
- PDF text commands and raster text use the same anchors;
- a deleted legacy helper cannot be reached by normal export paths;
- project migration preserves old projects until re-save and assigns the
  documented layout contract version.

## 6. Increment 3: PDF hybrid-raster performance work

Use the Increment 0 profile to select the smallest correct change. Candidate
work is ordered as follows:

1. Reuse one immutable hybrid raster for SVG/PDF format bundles when the
   resolved scene and point plan are identical; verify cache keys include all
   visual inputs and never cross samples or cancelled jobs.
2. For a source/style group where source-over composition is mathematically
   commutative, replace per-marker Python work with a tiled/vectorised count or
   coverage accumulator. Preserve repeated-alpha density exactly using
   `1 - (1 - alpha) ** count`. Never combine different colors, alpha values,
   shapes, z-order groups, or per-event density colors.
3. If compression is dominant, measure and tune only deterministic lossless
   compression/chunking. Do not substitute JPEG or discard the PDF alpha mask.
4. Consider process execution only after a prototype proves shared-memory or
   memory-mapped immutable arrays, bounded memory, deterministic ordering,
   cancellation, and native Windows `spawn` behaviour. Threads remain
   appropriate only where the measured native work releases the GIL.

Expose sub-stages in progress: `rasterising scatter`, `compressing scatter`,
`writing PDF`, and `publishing`. Keep completed-file count truthful, but show
the current output path, elapsed duration, requested/effective workers, and
the active sub-stage so `0/N` is not mistaken for a hang.

Required correctness tests:

- compare old/reference and optimised hybrid raster output at 150 and 600 DPI
  for opaque, translucent, duplicate, dense, sparse, multi-source, and
  per-event-density colors;
- preserve point-plan hash/event count and all analytical results;
- prove cancellation publishes neither partial PDF nor sidecar;
- record benchmark before/after values rather than a fabricated universal
  speedup threshold.

## 7. Increment 4: visual-parity regression suite and cleanup gate

Create an offscreen GUI fixture and export the identical resolved scene to
PNG, SVG, and PDF. Rasterise PDF with `pdftoppm` when available. The suite must
compare logical plot rectangle, title/axis/tick anchors, gate vertices,
normalized point centers, source order, title colors, and visibility before
using image tolerances. Allow font anti-aliasing differences but fail on title
overlap, title clipping, shifted plot rectangles, missing title lines, changed
labels, changed colors, or gate displacement.

Exercise single sample, manual overlay, population display colors, density
color, long multi-line titles, saved/reloaded project, and a batch definition
whose active GUI sample differs from the exported sample. Store only small
synthetic fixtures. Add a manual real-FCS verification recipe, screenshots,
and timing JSON outside version control.

Do not mark this guide complete until:

- the reported title/plot overlap is reproduced by a regression test and is
  fixed in GUI, PNG/JPEG, SVG, and PDF;
- all normal routes use the canonical scene/layout contract;
- the dead/legacy backend selector and bypass paths are removed or have a
  documented, tested purpose;
- the PDF benchmark identifies the dominant stage and the selected optimisation
  improves it without changing visual or scientific contracts;
- user manual text accurately distinguishes common layout/scene from separate
  physical renderers.

## 8. Target files and verification

Likely production files are `src/flowdesk_core/plot_scene.py` (or the current
scene model module), `models.py`, `plot_export.py`, `vector_scatter.py`,
`batch_plot_export.py`, `src/flowdesk_cli/batch_plot.py`, and
`src/flowdesk_qt/plot_widget.py` / `main_window.py`. Do not modify pipeline,
gate, compensation, or FCS parsing modules for this work.

Likely tests are `tests/test_plot_export_reuse.py`,
`tests/test_vector_scatter.py`, `tests/test_cli_batch_plot.py`,
`tests/test_batch_plot_export.py`, and focused GUI export/widget tests. Add a
dedicated visual-layout test module if that makes failure messages clearer.

Run at least:

```bash
python -m pytest tests/test_plot_export_reuse.py tests/test_vector_scatter.py \
  tests/test_cli_batch_plot.py tests/test_batch_plot_export.py \
  tests/gui/test_qt_plot_export.py tests/gui/test_batch_plot_export_dialog.py -q
python -m ruff check src/flowdesk_core/plot_export.py src/flowdesk_cli/batch_plot.py \
  src/flowdesk_qt/plot_widget.py src/flowdesk_qt/main_window.py tests
```

Run GUI visual checks under the project's Qt test runner as well. Windows and
PyInstaller validation remain a required release follow-up, but do not block
the core Linux implementation when no native Windows environment is available.
