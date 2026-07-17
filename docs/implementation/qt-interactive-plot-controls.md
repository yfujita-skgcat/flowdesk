# Qt Interactive Plot Controls Implementation Guide

## Goal

Implement the interactive plot behavior expected from a FlowJo-like flow cytometry GUI:
creating and editing gates directly on the plot, changing axis scale, customizing plot and
dot appearance, exporting the plot view, and keeping GUI-created analysis reproducible
through the headless pipeline runner.

This guide is for local LLM agents implementing the next GUI work. Read this file together
with:

- `AGENTS.md`
- `docs/implementation/qt-integration.md`
- `docs/implementation/gate-engine.md`
- `docs/implementation/transforms.md`
- `docs/implementation/project-storage.md`
- `docs/implementation/performance-and-review.md`

## Core Rule

Separate display state from analysis state.

### Gate coordinate scales

- A GUI-created geometric gate stores the X and Y axis scales in which its
  coordinates were drawn (`linear`, `log10`, or `asinh`).
- Headless gate evaluation transforms full-resolution parameter values into
  those coordinate scales before applying the stored thresholds or polygon.
- A gate overlay is displayed and editable only when the current X/Y display
  scales match the gate coordinate scales. Changing display scale never
  changes gate membership or rewrites gate coordinates.
- This avoids approximating a transformed polygon with a different raw-space
  polygon and keeps GUI-drawn straight edges identical to headless analysis.
- Legacy gates without scale metadata are interpreted as linear/linear.

- Analysis state changes results and must be represented in project data:
  gates, parent populations, compensation selection, analysis transforms, derived
  parameters, sample inclusion, and export settings.
- Display state does not change results:
  background color, dot color, selected-population highlight color, dot size,
  opacity, density mode, viewport range, robust-auto-range toggle, grid visibility,
  and PNG export dimensions.
- GUI code may edit project state and display state, but must not implement FCS parsing,
  compensation, derived parameter calculation, gate membership, population statistics,
  or export statistics.

## Target Files

Primary files:

- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/gate_editor.py`
- `src/flowdesk_qt/channel_selector.py`
- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/population_tree.py`

Likely new files:

- `src/flowdesk_qt/plot_style.py`
- `src/flowdesk_qt/plot_toolbar.py`
- `src/flowdesk_qt/gate_editing.py`
- `tests/test_qt_plot_widget.py`
- `tests/test_qt_gate_interactions.py`

Core/storage files only if project-persistent analysis or display settings need model
support:

- `src/flowdesk_core/models.py`
- `src/flowdesk_storage/serialization.py`
- `schemas/project.schema.json`
- `docs/project_file_schema.md`

Do not put scientific execution logic in `src/flowdesk_qt`.

## Required User Workflows

### 1. Plot Navigation

The plot should support:

- pan
- zoom in/out
- box zoom
- reset to robust auto-range
- reset to full data range
- preserve view range when changing cosmetic settings
- refresh view when changing sample, X/Y channel, axis scale, or population selection

Implementation notes:

- Use pyqtgraph ViewBox interaction where possible.
- Robust auto-range may use display percentiles, but only for viewport selection.
- Full range must use all finite display points.
- Never use display ranges for gate membership.

Acceptance criteria:

- `data/1_A1.fcs` opens with the main population visible.
- A user can return from zoomed/panned state to robust range and full range.
- Changing color or dot size does not change the view range.

### 2. Axis Scale Controls

The GUI should support at least:

- X/Y independently set to linear
- X/Y independently set to log10
- X/Y independently set to asinh

Implementation rules:

- Log axis rendering must use `PlotItem.setLogMode(x=..., y=...)` or an equivalent
  pyqtgraph API that transforms plotted points and axis ticks together.
- `ViewBox.setLogMode()` alone is not sufficient because it only updates ViewBox
  log-range state and does not transform PlotDataItem coordinates.
- Non-positive values on log axes must be handled explicitly for display. Count or report
  hidden points when practical.
- If an axis scale is meant to affect gate membership, persist it as an analysis
  `TransformSpec` and reference it from `GateSpec.transform_id`.
- If an axis scale is display-only, gates drawn on the plot must be converted back to
  raw data coordinates before storing, or must be stored with explicit transformed
  coordinate metadata that the pipeline runner can reproduce.

Acceptance criteria:

- Linear vs linear, linear vs log10, and log10 vs log10 PNG exports all show points.
- Axis ticks match the selected scale.
- Gate overlay geometry aligns with the plotted points for every supported scale.

### 3. Plot Appearance Controls

The GUI should allow users to configure:

- plot background color
- axis text/tick color if needed for contrast
- dot color
- dot opacity
- dot size
- selected population highlight color
- gate outline color
- gate fill color and fill opacity
- optional grid visibility

Implementation rules:

- Store these settings in a GUI display settings object, not in gate membership logic.
- Prefer a small typed object such as `PlotStyleSettings` in `flowdesk_qt`, unless
  project persistence is implemented.
- If display settings are saved in `.flowdesk`, add schema/storage support and keep them
  under a clearly display-only key such as `plot_display_settings`.
- Cosmetic settings must be applied without reloading FCS data or recomputing gates.

Suggested defaults:

- background: black or dark neutral
- dot color: light blue with moderate opacity
- selected population: brighter contrasting color
- gate outline: yellow or white
- gate fill: transparent by default

Acceptance criteria:

- Background and dot color can be changed and are visible in PNG export.
- Dot size and opacity can be changed without changing event count or pipeline results.
- Gate colors remain readable on light and dark backgrounds.

### 4. Gate Creation on Plot

The GUI should support creating gates directly on the plot:

- rectangle gate by drag
- polygon gate by click-to-add-vertices and finish action
- range gate on one axis
- boolean gates from existing populations, at least through a dialog or editor

Implementation rules:

- Store gate coordinates in data coordinates or explicitly transformed data coordinates,
  never screen pixels.
- Mouse events must be mapped using pyqtgraph scene/view conversion, for example
  `ViewBox.mapSceneToView()`.
- Gate creation must know the current X/Y parameters and current scale mode.
- New gates must include:
  - stable `id`
  - user-visible `name`
  - `gate_type`
  - `parent_population_id`
  - `x_parameter`
  - `y_parameter` when needed
  - thresholds or coordinates
  - `transform_id` when coordinates are transformed
- After gate creation, emit a gates-changed signal, refresh overlays, and make the gate
  available to the pipeline runner.

Acceptance criteria:

- Rectangle gate can be drawn by dragging on the plot.
- Polygon gate can be drawn with at least three vertices and finished explicitly.
- Range gate can be created for the selected X or Y axis.
- Running the pipeline after drawing a gate produces a population result for that gate.
- GUI-created gate counts match headless `PipelineRunner` counts on synthetic test data.

### 5. Gate Editing

The GUI should support:

- select gate from plot or gate list
- move rectangle gate
- resize rectangle gate
- move polygon vertices
- add polygon vertex
- remove polygon vertex
- rename gate
- delete gate
- change parent population
- copy/duplicate gate
- show selected gate with highlight

Implementation rules:

- Gate definition selection updates `selected_gate_id` and outline highlight only. It
  must not implicitly set the plot's `display_population_id` to the gate's child result.
- `Show Gate` is explicit: navigate to matching axes/scales and display the gate's parent
  population so events outside the boundary remain visible while editing.
- `Show Population` is a separate explicit action for displaying the gate's child
  membership after a successful, non-stale pipeline run.
- Editing a gate changes project analysis state and must invalidate cached results.
- Editing must emit a gates-changed signal.
- Store edited coordinates in the same coordinate system used by gate creation.
- A gate drawn for one X/Y parameter pair must not be shown as editable on an unrelated
  X/Y pair unless transformed/mapped intentionally.
- If the plot is currently display-transformed, editing must either:
  - convert display edits back to raw coordinate storage, or
  - store transformed coordinates with `transform_id` and ensure headless evaluation
    uses the same transform.

Acceptance criteria:

- Moving or resizing a gate changes subsequent pipeline counts.
- Deleting a gate removes its overlay and result.
- Renaming a gate preserves its id unless a deliberate id change is needed.
- Parent-child gate behavior remains correct: child gates are restricted to the parent
  population in headless execution.

### 6. Population Selection and Backgating

The GUI should support:

- selecting a population from the Results workspace
- highlighting events in the selected population
- optionally showing all events dimmed and selected population in a stronger color
- showing gate overlays relevant to the selected population

Implementation rules:

- Population membership must come from pipeline runner results or core gate evaluation,
  not from display-downsampled points.
- If membership masks are cached for display, invalidate them when compensation,
  derived parameters, transforms, gates, sample, or channel selection changes.
- Do not change analytical results when toggling highlight/backgate display.

Acceptance criteria:

- Selecting a population visibly changes dot coloring.
- The selected population event count shown in the table matches the full-data pipeline
  count.

### 7. Plot Export

The GUI should support:

- exporting current plot view to PNG
- choosing output path
- respecting current display settings, axis scale, gate overlays, and highlight colors
- optional fixed dimensions for reproducible screenshots

Implementation rules:

- PNG export is display export, not statistical export.
- Do not confuse plot PNG export with `flowdesk_core.export` population statistics export.
- Existing `PlotWidget.export_png()` should remain display-only.

Acceptance criteria:

- Exported PNG matches the visible plot.
- Linear/log combinations export nonblank images.
- Exported PNG includes gate overlays when overlays are visible.

## Data and Model Recommendations

### Display Settings

Start with a GUI-local dataclass:

```python
@dataclass
class PlotStyleSettings:
  background_color: str = "#000000"
  dot_color: str = "#b8c7ff"
  selected_dot_color: str = "#ffffff"
  dot_size: float = 3.0
  dot_opacity: float = 0.75
  gate_outline_color: str = "#ffff00"
  gate_fill_color: str = "#ffff00"
  gate_fill_opacity: float = 0.0
  show_grid: bool = False
```

Only persist this to project storage after basic interaction works.

### Gate Editing State

Keep transient GUI interaction state out of core models:

- active tool: pan, rectangle gate, polygon gate, range gate, select/edit
- in-progress drag start/end
- in-progress polygon vertices
- hovered gate/vertex
- selected gate id
- active sample id
- displayed population id

The selected gate and displayed population are independent. Do not reuse one variable for
both concepts.

Once a gate is finished or edited, convert it to `GateSpec`.

### Qt graphics item lifetime

- Reuse the rectangle and polygon preview item while an interaction is active. Do not
  allocate a new ROI for every mouse-move event.
- Native pyqtgraph log mode returns mouse positions in ViewBox log coordinates. Polygon
  preview items must opt out of `PlotDataItem` log mapping, otherwise preview vertices are
  transformed twice while the final `PolyLineROI` is transformed once.
- Before replacing a gate ROI, disconnect its stored signal callback, remove it from the
  plot, and call `deleteLater()` so the C++ object is destroyed after event dispatch.
- Do not synchronously destroy or replace the ROI that is currently emitting an edit
  signal. Queue persistence and redraw until the signal handler has returned.
- Flush completed queued ROI edits before building a project manifest. Pipeline execution,
  save, autosave, and export must never observe the pre-edit gate geometry.

## Implementation Order

1. Add a plot toolbar with modes: pan/select, rectangle gate, polygon gate, range gate,
   reset robust range, reset full range, export PNG.
2. Add plot style settings and UI controls for background/dot/gate colors, dot size, and
   opacity.
3. Implement scene-to-data coordinate conversion with tests.
4. Implement rectangle gate drag creation in linear scale.
5. Connect gate creation to `GateEditor`, gate overlays, and pipeline runner.
6. Implement rectangle gate edit handles.
7. Implement polygon gate creation and editing.
8. Implement range gate creation/editing.
9. Make gate overlay and gate editing correct under log10/asinh scale.
10. Add population highlighting/backgating.
11. Persist display settings and GUI-created analysis state if not already persisted.

## Required Tests

Add GUI tests that skip when PySide6 or pyqtgraph are unavailable.

Minimum tests:

- `PlotWidget.export_png()` writes a PNG with requested dimensions.
- Linear vs linear, linear vs log10, and log10 vs log10 plots are nonblank.
- Scene/view coordinate conversion maps a known scene point to the expected data point.
- Rectangle gate created from two plot points stores expected data coordinates.
- Polygon gate created from three plot points stores expected vertices.
- Editing rectangle thresholds changes headless pipeline population counts.
- Changing dot color/background does not change headless pipeline population counts.
- Gate overlay is hidden or disabled when X/Y channels do not match the gate parameters.

Manual checks:

- Launch: `.direnv/python-3.12.13/bin/flowdesk-gui --data-dir data/`
- Select `data/1_A1.fcs`.
- Change X/Y scale through linear/log10/log10 combinations.
- Draw rectangle and polygon gates.
- Run pipeline and confirm population rows appear.
- Change dot/background/gate colors.
- Export PNG and confirm it matches the visible plot.

## Acceptance Criteria

- A user can create, edit, rename, delete, and run gates without typing numeric thresholds
  manually.
- GUI-created gates are reproducible by the headless pipeline runner.
- Display settings affect only visualization and PNG export.
- Linear/log/asinh display modes render points and gate overlays consistently.
- Existing core tests still pass.
- `ruff check src tests` passes.
- GUI code contains no scientific execution logic beyond display mapping and project-state
  editing.
