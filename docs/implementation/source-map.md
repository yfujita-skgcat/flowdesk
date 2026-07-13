# Flowdesk Source and Test Map for Local LLMs

## Purpose

Use this map to decide where a change belongs before editing. Paths marked **proposed**
do not exist yet; create them only in the increment that needs them. Do not create a
second module when an existing module already owns the behavior.

## Dependency direction

```text
flowdesk_qt  ─┐
flowdesk_cli ─┼─> flowdesk_core
              └─> flowdesk_storage

flowdesk_core must not import flowdesk_qt or flowdesk_storage.
flowdesk_storage must not import flowdesk_qt.
```

Scientific execution belongs in `flowdesk_core`. Persistence belongs in
`flowdesk_storage`. CLI and Qt are adapters.

## `src/flowdesk_core`

| File | Current owner responsibility | Extend here for |
|---|---|---|
| `models.py` | Frozen serializable analysis/result dataclasses | Small shared specs/results; split when file becomes hard to review |
| `fcs_io.py` | FCS metadata/events and spillover extraction | Parser adapters and immutable FCS load results |
| `channels.py` | Channel naming/identity helpers | Stable identity resolution and ambiguity errors |
| `sample.py` | Sample-level helpers | Typed sample event/channel container |
| `compensation.py` | Matrix validation/application | Alignment, diagnostics; calculation may move to proposed `compensation_fit.py` |
| `derived_parameters.py` | Safe expression parsing/evaluation | Dependency plan and typed evaluation errors |
| `transforms.py` | Numeric transforms | Forward/inverse protocols and Logicle |
| `gates.py` | One gate's vectorized membership | New geometric/Boolean node evaluators |
| `gating_strategy.py` | Gate graph ordering and parent masking | Strategy/override resolution, dependency validation |
| `populations.py` | Population tree/result queries | Pure hierarchy traversal only |
| `statistics.py` | Numeric population statistics | Metric dispatcher; definitions/results may use proposed `statistic_specs.py` |
| `pipeline.py` | Pipeline step definitions | Stage metadata, not project execution loops |
| `pipeline_runner.py` | Canonical project/sample execution | Typed sample inputs, stage orchestration, report collection |
| `execution_context.py` | Run configuration | cancellation/progress/cache policy references |
| `execution_report.py` | Reproducibility and run results | diagnostics, statistics, platform result references |
| `export.py` | Core CSV/TSV serialization | Value/status formatting, never Qt image export |
| `errors.py` | Flowdesk exception hierarchy | Stable typed errors/diagnostic conversion |

### Proposed core modules

Create only when the selected guide requires them:

- `diagnostics.py`: structured execution diagnostics shared by runner/CLI/Qt
- `sample_data.py`: only if `sample.py` cannot cleanly own typed sample arrays
- `statistics_runner.py`: resolve `StatisticSpec` over memberships
- `table_runner.py`: resolve table definitions to typed rows
- `layout_model.py` and `layout_resolver.py`: Qt-independent scene data
- `groups.py`: safe group membership rules/resolution
- `commands.py`: GUI-independent project mutations/undo payloads
- `platforms/`: one module per validated specialized analysis; do not add empty packages

## `src/flowdesk_storage`

| File | Responsibility | Must not contain |
|---|---|---|
| `project.py` | Bundle load/save and referenced analysis files | Numeric analysis |
| `manifest.py` | Manifest validation | Qt dialogs |
| `serialization.py` | JSON read/write/time/merge helpers | Scientific defaults |
| `cache.py` | Disposable derived cache metadata | Authoritative raw/project state |

Proposed modules: `migrations.py`, `archive.py`, and `template.py`. Keep migrations pure
on parsed data and archive extraction path-safe.

## `src/flowdesk_cli`

| File | Responsibility |
|---|---|
| `main.py` | Argument routing and exit codes |
| `run_project.py` | Load project, call runner, export/report |
| `inspect_fcs.py` | Present core FCS metadata |
| `batch_gate.py` | Batch adapter over the same runner |

Add thin command modules for template/archive/interoperability operations. CLI modules
must not implement formulas, matrix operations, gate membership, or platform fits.

## `src/flowdesk_qt`

| File | Current owner responsibility | Extend here for |
|---|---|---|
| `main_window.py` | App composition, project state, worker orchestration | New docks/actions and core runner calls |
| `sample_browser.py` | Sample list and channel metadata | Catalog/group/annotation presentation |
| `channel_selector.py` | X/Y and display transform selection | Stable ID selection, not transform math |
| `plot_widget.py` | pyqtgraph rendering and ROI interaction | Plot types, overlays, display preparation consumption |
| `plot_toolbar.py` | Plot actions/display toggles | Exclusive interaction modes |
| `plot_style.py` | Display-only plot settings | Theme/style defaults |
| `gate_editor.py` | Gate definition editing/hierarchy UI | New gate editors and command dispatch |
| `population_tree.py` | Population/result presentation | Statistics/platform child nodes |
| `diagnostics.py` | Strict callbacks/logging/debug state | New observable UI state, not scientific diagnostics calculation |

Prefer one new widget module per major editor: `compensation_workspace.py`,
`derived_parameter_editor.py`, `table_editor.py`, `layout_editor.py`,
`plate_workspace.py`, and platform-specific views. Widgets edit specs and display core
results. They do not own alternate analysis models.

## Schemas and examples

- `schemas/project.schema.json`: manifest-level definitions and references
- `schemas/gating_strategy.schema.json`: gate/hierarchy definitions
- `examples/example_project.flowdesk/`: minimal valid current-version example

Every schema change requires a migration fixture, load-save-load test, and example update.
Unknown fields remain preserved unless a documented migration removes them.

## Test routing

| Changed area | Minimum focused tests |
|---|---|
| FCS/channels/sample input | `test_fcs_io.py`, `test_pipeline_runner.py` |
| Compensation | `test_compensation.py`, runner test |
| Derived parameters | `test_derived_parameters.py`, runner test |
| Transforms | `test_transforms.py`, transform-aware gate test |
| Gates/hierarchy | `test_gates.py`, `gui/test_gate_hierarchy_ui.py` |
| Statistics/export | `test_population_statistics.py`, `test_export.py` |
| Storage/migration | `test_project_storage.py`, headless round trip |
| Plot/Qt | `test_qt_plot_widget.py`, relevant `tests/gui/*` |
| CLI | `test_cli.py` plus the core test for the called behavior |

New scientific platforms should get one core numeric test file and one GUI integration
file. Reference fixtures and their provenance belong under `tests/fixtures/` or a small
documented generator, never as a large opaque binary.

## Change routing examples

- “Show a new compensation heat map”: matrix values/diagnostics in core; heat map in a
  new Qt workspace; binding in project storage.
- “Add ellipse gate”: model/evaluator in core, schema/migration in storage, ROI in Qt,
  numeric tests before GUI tests.
- “Add table formula”: safe expression/dependency evaluation in core table runner; cells
  and column dialogs in Qt; export reads core rows.
- “Make 10M points faster”: runner/cache benchmark separately from plot downsampling;
  prove gate/statistic counts are unchanged.

