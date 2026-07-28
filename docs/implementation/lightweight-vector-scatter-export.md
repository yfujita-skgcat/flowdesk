# Lightweight Vector Scatter Export

Status: Increments 12-15 implemented; Increments 16-17 planned

This guide defines the implementation contract for lightweight SVG/PDF scatter
export. It extends `docs/implementation/plot-export-completion.md` without
changing analytical execution.

An implementing LLM must read this file completely before changing production
code. Implement exactly one numbered increment per LLM run, update `ToDo.md`
and the user manual for completed user-visible behavior, run the tests listed
for that increment, and stop before starting the next increment.

## 1. Purpose

Flow-cytometry plots can contain tens of thousands to millions of displayed
events. Writing one editable SVG/PDF object per event provides unlimited zoom,
but produces large files and makes vector editors slow.

Implement three explicit scatter representations:

1. `full_vector`: one independently addressable marker placement per rendered
   event.
2. `compact_vector`: exact or bounded-equivalent vector geometry grouped into
   deterministic compound paths.
3. `hybrid_raster`: one lossless transparent raster for the scatter layer,
   with axes, grid, gates, title, labels, ticks, and legend remaining vector.

The modes change only export representation. They must not change raw events,
compensation, derived parameters, transforms, gate membership, statistics,
display-event selection, point coordinates, source order, colors, or alpha.

PNG/JPEG are already raster formats and do not use these three modes.

## 2. Scientific and reproducibility boundary

Keep the existing processing order:

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> deterministic display-event selection
  -> PlotScene
  -> export representation only
```

The vector scatter planner consumes an already resolved `PlotScene` and the
same selected display-point identities used by GUI/batch export. It must never:

- read or parse FCS files;
- run compensation, transforms, gates, or statistics;
- select a different event subset for a particular format or mode;
- use raster occupancy, density, or merged geometry as analytical input;
- replace a rare population by an aggregate without an explicit display mode;
- silently change mode because a file is large.

Counts, frequencies, statistics, analysis revision, and display-sampling
identity must be byte-for-byte/equality-test identical across all three modes.

## 3. Persisted contract

Add these fields to `BatchPlotExportSpec`, project schema, storage
serialization, dialog mapping, CLI parsing, sidecars, and batch manifests:

```python
VectorScatterMode = Literal[
  "full_vector",
  "compact_vector",
  "hybrid_raster",
]

vector_scatter_mode: VectorScatterMode = "hybrid_raster"
hybrid_scatter_dpi: int = 600
```

Validation:

- `vector_scatter_mode` must be one of the three exact values.
- `hybrid_scatter_dpi` must be an integer in `[72, 2400]`.
- `hybrid_scatter_dpi` applies only to the embedded scatter image in
  `hybrid_raster`; it does not affect vector page geometry.
- SVG/PDF Width/Height remain 96-DPI logical canvas units.
- PNG/JPEG continue using the existing raster-resolution contract.

Compatibility:

- A saved definition missing `vector_scatter_mode` resolves to
  `full_vector`, preserving the current all-vector SVG/PDF representation.
- A newly created definition defaults to `hybrid_raster`.
- A missing `hybrid_scatter_dpi` resolves to `600`.
- Loading an old project must not rewrite it until the user saves.
- The resolved mode and settings must always be written to output provenance.

Do not introduce an implicit `auto` mode in this increment series. A default is
allowed, but the resolved output mode must be explicit and reproducible.

## 4. Shared renderer-neutral plan

Create a Qt-independent vector scatter plan in `flowdesk_core`, for example:

```python
@dataclass(frozen=True)
class VectorScatterPlan:
  mode: VectorScatterMode
  logical_canvas: ExportCanvasSpec
  clip_rect: tuple[float, float, float, float]
  source_order: tuple[str, ...]
  layers: tuple[VectorScatterLayer, ...]
  rendered_event_count: int
  sampling_identity: str
  algorithm_version: str
  diagnostics: tuple[dict[str, Any], ...] = ()
```

Mode-specific layers may be separate typed dataclasses or a tagged union:

- `FullVectorScatterLayer`
- `CompactVectorScatterLayer`
- `HybridRasterScatterLayer`

The planner receives normalized/logical point centers, resolved marker shape,
marker size, color, alpha, clipping rectangle, and z-order. It does not receive
raw event arrays.

Both SVG and PDF adapters consume the same plan. Do not implement independent
point-selection, grouping, or fallback logic in each adapter.

The scatter plan hash must include:

- mode and algorithm version;
- ordered source IDs;
- selected display-event identity/hash;
- point centers in deterministic order;
- marker shape and logical size;
- color and alpha;
- clip rectangle and z-order;
- hybrid raster DPI when applicable.

## 5. Common visual contract

All modes must preserve:

- logical point centers;
- marker shape and diameter;
- source/population color;
- per-marker/source alpha;
- point-layer order;
- clipping to the plot area;
- grid below points;
- gates, labels, ticks, title, and legend above/beside points as defined by
  `PlotScene`;
- background color;
- deterministic display sampling.

For equal styles, event order may be rearranged only when source-over
compositing is mathematically commutative for that group. Never reorder across
different colors, alpha values, sources, populations, or z-order groups.

Do not use the geometric union of overlapping circles as a general
optimization. A union loses repeated-alpha density and may create more path
vertices than the source markers.

## 6. Mode definition: `full_vector`

### SVG

- Define marker geometry once in `<defs>` using `<symbol>` or `<path>`.
- Emit one `<use>` placement per rendered event.
- Keep source/style groups ordered according to `PlotScene`.
- Apply plot clipping with one shared `<clipPath>`.
- A marker remains independently addressable in a vector editor.
- Do not emit a separate repeated circle/path definition for every event.

This reduces repeated geometry text but intentionally keeps O(N) placements
and O(N) editable nodes.

### PDF

- Define each unique marker geometry as a reusable Form XObject.
- Emit one placement command per event in an ordered, Flate-compressed content
  stream.
- Reuse graphics state resources for color/alpha.
- Keep axes/text/gates in separate vector commands/resources.

PDF has no SVG DOM, but placement/rendering cost remains O(N). Record placement
count in provenance.

### Full-vector acceptance

- Every planned point has exactly one placement.
- Point center, style, source, and z-order match the plan.
- SVG contains no embedded scatter image.
- PDF contains no scatter Image XObject.
- Parsed placement count equals `rendered_event_count`.
- Full-vector output is the semantic reference for compact-vector comparison.

## 7. Mode definition: `compact_vector`

### Why a naive compound path is incorrect

Applying one translucent fill to a compound path composites the union as one
object. Overlapping subpaths do not necessarily accumulate alpha as separately
painted markers. Therefore, putting all semi-transparent dots into one path
can erase density information.

### Required deterministic grouping algorithm

Group points first by an exact style key:

```text
source/z-order group
marker shape
logical marker size
fill color
fill alpha
stroke properties, if any
clip identity
```

For each style group:

1. Preserve original deterministic point identity/order in provenance.
2. If alpha is exactly `1.0` and markers have the same opaque paint, overlapping
   markers may share one compound-path batch because repeated painting cannot
   change the final color.
3. If alpha is less than `1.0`, partition markers into deterministic
   non-overlapping batches:
   - build a logical-coordinate spatial hash using a cell size no larger than
     the marker footprint;
   - process markers in stable input order;
   - assign a marker to the first batch whose existing footprints do not
     overlap it;
   - create a new batch when no existing batch is valid;
   - use marker-shape-aware overlap tests, not center equality alone.
4. Emit one compound path per batch, split into chunks of at most
   `COMPACT_VECTOR_CHUNK_POINTS = 4096` markers.
5. Keep chunks in a deterministic order.
6. Record batch count, chunk count, maximum overlap depth, and algorithm
   version.

The chunk constant is an implementation limit, not initially a user setting.
Changing it must change the renderer algorithm version and be covered by
reproducibility tests.

### Exact duplicate optimization

An optional later optimization may replace `n` markers with identical center,
shape, color, and alpha by one marker with:

```text
effective_alpha = 1 - (1 - alpha) ** n
```

Use this only when the markers are contiguous within the same style/z-order
group and no intervening layer changes compositing. Record the duplicate count.
Do not quantize merely close centers into duplicates.

### Coordinates and numeric precision

- Use one deterministic decimal serializer for SVG and PDF coordinates.
- The serialized point-center error must be at most `1e-4` logical pixel.
- Do not round points into occupancy bins in compact-vector mode.
- The same input plan must produce byte-identical geometry ordering on Linux,
  macOS, and Windows, excluding explicitly documented PDF metadata.

### Compact-vector acceptance

- No point identity is dropped.
- Parsed compound subpath count equals the planned marker count, except for
  explicitly proven exact-duplicate optimization.
- No two translucent marker footprints overlap inside the same compound-path
  batch.
- Same-backend rasterization of compact and full vector at 96, 300, and
  600 DPI has normalized RMSE `<= 0.01`.
- Rare-color/source markers remain present.
- SVG DOM node count is materially lower than full vector for the benchmark
  fixtures.

## 8. Mode definition: `hybrid_raster`

Only the scatter layer is rasterized. The following remain true vector
geometry:

- page/background and plot clipping;
- axes and grid;
- ticks and tick labels;
- title, axis labels, and legend;
- gate outlines/fills;
- annotations and status elements that are enabled for export.

### Raster dimensions

Use the 96-DPI logical canvas contract:

```text
full_pixel_width  = round(logical_width  * hybrid_scatter_dpi / 96)
full_pixel_height = round(logical_height * hybrid_scatter_dpi / 96)
```

The embedded image should cover only the clipped plot rectangle when practical.
Its logical placement must exactly match the `PlotScene` plot rectangle.

### Compositing

- Render all scatter sources into a transparent RGBA surface in canonical
  source/z-order.
- Use lossless PNG/Flate compression; never JPEG.
- Use the same marker geometry, center, color, and source-over alpha rules as
  the canonical raster renderer.
- Precompose point layers into one image when points are contiguous in z-order.
- If vector elements are interleaved between point groups, emit one raster
  image per contiguous point z-order group.
- Do not rasterize gates, text, axes, or the full canvas.
- Use tiled internal rendering if the temporary RGBA allocation exceeds the
  documented memory budget; tiles must not create seams.

### SVG

- Embed a self-contained lossless image by default.
- A linked-image option is out of scope unless separately designed with
  portability and missing-resource validation.
- Apply the same vector clip path as full/compact modes.

### PDF

- Use an Image XObject with a soft mask or equivalent lossless alpha support.
- Compress image data with Flate and an appropriate predictor.
- Place it once at the logical plot rectangle.

### Hybrid acceptance

- The vector document contains no full-canvas raster.
- Exactly the intended scatter z-order groups are Image XObjects/`<image>`
  nodes.
- Axes, text, ticks, gates, and grid remain inspectable vector primitives.
- At `hybrid_scatter_dpi`, same-backend comparison with the canonical raster
  scatter layer has normalized RMSE `<= 0.01`.
- Cross-backend comparison may use normalized RMSE `<= 0.03`, with the
  backend/font difference documented.
- A rare marker selected for display remains visible when its raster footprint
  is at least one pixel.
- Hybrid rendering does not select a different event subset.

## 9. UI and CLI behavior

Add a `Scatter representation` selector to Batch Plot Export when SVG or PDF
is enabled:

- `Hybrid raster scatter (recommended)`
- `Compact vector scatter`
- `Full vector scatter`

Show `Scatter raster DPI` only for hybrid mode.

Display a preflight estimate before execution:

- rendered point count;
- estimated full-vector placements;
- estimated compact path/chunk count when available;
- hybrid scatter pixel dimensions and estimated uncompressed RGBA memory;
- warnings for large output.

Do not silently switch mode after preflight. If the requested mode exceeds a
hard resource limit, fail with a structured diagnostic and suggest another
mode. The user must choose and save that mode explicitly.

CLI uses the persisted definition without a separate default:

```text
flowdesk batch-plot ... --export-id <saved-definition>
```

If a future one-shot CLI override is added, the resolved override must be
written to sidecars/manifests.

## 10. Provenance

Every SVG/PDF sidecar and batch manifest item must include:

```json
{
  "vector_scatter": {
    "requested_mode": "hybrid_raster",
    "resolved_mode": "hybrid_raster",
    "algorithm_version": "hybrid_raster.v1",
    "input_event_count": 31552,
    "rendered_event_count": 20000,
    "sampling_identity": "...",
    "source_order": ["..."],
    "point_plan_hash": "...",
    "scatter_image_dpi": 600,
    "scatter_pixel_width": 3250,
    "scatter_pixel_height": 3063,
    "lossless": true,
    "full_canvas_raster": false,
    "placement_count": 0,
    "compound_path_count": 0,
    "chunk_count": 0,
    "maximum_overlap_depth": null,
    "diagnostics": []
  }
}
```

Fields not applicable to a mode may be `null` or zero, but must not be omitted
when omission would make the representation ambiguous.

The batch-level manifest must summarize total bytes, export time, and resolved
mode counts without treating benchmark data as scientific results.

## 11. Failure and warning policy

Structured diagnostic codes must distinguish at least:

- unsupported mode/format;
- missing point-plan identity;
- hybrid raster allocation limit;
- hybrid image encoding failure;
- SVG/PDF resource write failure;
- compact grouping failure;
- vector placement/path limit;
- output validation failure;
- explicit user cancellation.

Strict export fails the affected item when the requested representation cannot
be produced. Non-strict export may continue other samples but may not replace
the mode with another representation.

## 12. Increment 12: contract, schema, planner skeleton

Target files:

- `src/flowdesk_core/models.py`
- `src/flowdesk_core/plot_scene.py`
- new `src/flowdesk_core/vector_scatter.py` or equivalent
- `src/flowdesk_core/batch_plot_export.py`
- `schemas/project.schema.json`
- storage migration/round-trip tests
- `tests/test_vector_scatter.py`

Tasks:

1. Add persisted fields, validation, compatibility defaults, and schema.
2. Add typed plan/layer models and deterministic plan hashing.
3. Build a planner from `PlotScene` plus already-selected point layers.
4. Add provenance mapping without changing existing SVG/PDF output.
5. Test old-project defaults, new-definition defaults, invalid values, stable
   hashes, source order, point identity, and scientific-result invariance.

Acceptance:

- No renderer behavior changes yet.
- Planner contains the same point identities/coordinates/styles for every
  mode.
- Old projects resolve to `full_vector`.
- New definitions resolve to `hybrid_raster` at 600 DPI.

## 13. Increment 13: `full_vector`

Target files:

- `src/flowdesk_core/vector_scatter.py`
- `src/flowdesk_core/plot_export.py`
- SVG/PDF parser/inspection test helpers
- `tests/test_vector_scatter.py`
- `tests/test_plot_export_reuse.py`

Tasks:

1. Implement SVG symbol reuse plus one `<use>` per marker.
2. Implement PDF marker Form XObjects, graphics-state reuse, placement
   commands, and Flate-compressed streams.
3. Keep all non-scatter elements vector.
4. Validate placement count and absence of scatter images.
5. Preserve existing output semantics for migrated definitions.

Acceptance:

- Full-vector tests in section 6 pass.
- Existing SVG/PDF scene and scientific invariance tests pass.
- Output uses reusable marker resources rather than repeated definitions.

Stop after completing this increment.

## 14. Increment 14: `compact_vector`

Target files:

- `src/flowdesk_core/vector_scatter.py`
- SVG/PDF adapters in `plot_export.py`
- spatial-index and overlap unit tests
- compact/full visual comparison fixtures

Tasks:

1. Implement exact style grouping.
2. Implement deterministic spatial-hash non-overlap partitioning.
3. Implement shape-aware footprint tests.
4. Implement 4096-marker path chunks and deterministic coordinate
   serialization.
5. Emit SVG compound paths and equivalent PDF compound path operations.
6. Record overlap/batch/chunk provenance.
7. Benchmark sparse, dense, duplicate, rare-color, and multi-source layers.

Acceptance:

- Compact-vector tests in section 7 pass.
- Semi-transparent overlap density matches full vector within tolerance.
- No point is dropped or moved beyond the numeric error bound.
- DOM/object count decreases on the required benchmark fixtures.

Stop after completing this increment.

## 15. Increment 15: `hybrid_raster`

Target files:

- `src/flowdesk_core/vector_scatter.py`
- canonical core raster-scatter compositor
- SVG/PDF adapters in `plot_export.py`
- image/XObject inspection tests
- hybrid/full/canonical-raster comparison fixtures

Tasks:

1. Implement transparent scatter-only rendering at
   `hybrid_scatter_dpi`.
2. Share point geometry/compositing with the canonical raster renderer.
3. Embed lossless scatter images in SVG and PDF.
4. Preserve vector grid, axes, text, ticks, gates, and legend.
5. Add tiled rendering with seam tests if allocation may exceed the memory
   budget.
6. Record pixel dimensions, DPI, encoding, and raster bounds.

Acceptance:

- Hybrid tests in section 8 pass.
- No full-canvas raster is present.
- Scatter alpha/color/order matches the canonical raster reference.
- Rare displayed populations remain visible.

Stop after completing this increment.

## 16. Increment 16: GUI, CLI, preview, provenance

Target files:

- `src/flowdesk_qt/batch_plot_export_dialog.py`
- GUI request/project synchronization
- `src/flowdesk_cli/batch_plot.py`
- batch sidecar/manifest writer
- schema/storage migration tests
- GUI and CLI E2E tests
- `docs/user-manual/user_manual.md`

Tasks:

1. Add mode selector and conditional hybrid-DPI control.
2. Add resource/size preflight estimates and explicit warnings.
3. Persist definitions and restore old/new defaults.
4. Use the same planner for GUI-triggered and CLI/headless export.
5. Write complete per-file and batch provenance.
6. Add structured errors without silent fallback.
7. Update the user manual with mode choice, limitations, and reproducibility.

Acceptance:

- GUI and CLI resolve identical plans for the same saved definition.
- Cancel/save/restore/strict/partial-failure behavior is tested.
- Every output identifies its actual scatter representation.

Stop after completing this increment.

## 17. Increment 17: benchmark and release acceptance

Add a benchmark harness that generates deterministic fixtures with:

- 1k, 5k, 20k, 100k, and 1M rendered points;
- sparse and dense distributions;
- identical and partially overlapping centers;
- alpha `1.0`, `0.6`, and `0.1`;
- one and multiple colors/sources;
- a rare population with one and ten displayed points;
- rectangle/polygon gates and transformed ticks.

Measure for every mode and format:

- output bytes;
- export wall time;
- peak RSS;
- SVG DOM element count;
- PDF placement/path/image resource count;
- parse/open time using documented available tools;
- same-backend rasterization time;
- pan/zoom responsiveness when an automatable viewer benchmark exists;
- normalized visual RMSE;
- exact scientific report equality.

Workflow:

1. Record an unoptimized baseline without pass/fail performance thresholds.
2. Store benchmark environment and JSON results under `artifacts/benchmark/`.
3. Choose documented regression thresholds from the baseline.
4. Add thresholds only for stable CI metrics; keep viewer-dependent metrics as
   reported evidence.
5. Verify Linux, Windows, and macOS packaging paths.

Release acceptance:

- All global and mode-specific acceptance criteria pass.
- Full/compact/hybrid scientific results and sampling identities are equal.
- No benchmark mode silently drops events or changes style.
- Hybrid is demonstrably smaller/faster for the large fixtures.
- Compact reduces object count for sparse/typical fixtures without losing
  overlap density.
- Full vector remains available with a clear large-file warning.

Stop after completing this increment.

## 18. Required verification commands

Run the narrow tests for each increment, then before Increment 17 completion:

```bash
python -m pytest -m "not gui"
./tools/run-gui-tests.sh -q
ruff check src tests
mypy src/flowdesk_core src/flowdesk_storage src/flowdesk_cli
git diff --check
```

If the repository provides wrapped commands for the current environment, use
those wrappers instead of bypassing them.

## 19. Forbidden shortcuts

- Do not use full-canvas screenshots inside SVG/PDF.
- Do not call hybrid output “fully vector”.
- Do not merge all translucent circles into one compound path.
- Do not use JPEG for the scatter layer.
- Do not change display sampling based on output format or mode.
- Do not calculate gates/statistics from raster or compact geometry.
- Do not silently switch modes or lower hybrid DPI.
- Do not omit provenance because the image appears correct.
- Do not weaken scientific correctness assertions to satisfy performance
  targets.
- Do not make Qt a dependency of the core planner/headless renderer.

## 20. Definition of done

The feature is complete only when:

- all three modes are persisted, selectable, headless-executable, and tested;
- SVG and PDF consume one renderer-neutral scatter plan;
- mode-specific representation is inspectable in the output file;
- sidecars/manifests fully identify representation and event selection;
- visual fidelity satisfies the documented tolerances;
- analytical outputs and sampling identities are unchanged;
- benchmark evidence documents size, time, memory, and object-count tradeoffs;
- `ToDo.md`, this guide, and the user manual match implementation.
