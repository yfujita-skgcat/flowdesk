# flowdesk

Flowdesk is an early-stage Python project for a Linux-first FlowJo-like flow cytometry analysis application.

## MVP Scope

- Represent FCS samples, channels, compensation matrices, derived parameters, transforms, gates, population trees, and export records.
- Keep scientific execution in GUI-independent core modules.
- Store projects as `.flowdesk` directory bundles that can be run from GUI, CLI, or Python API.
- Provide initial documentation, schemas, agent guidance, and synthetic tests.

## Non-goals

- Complete FlowJo compatibility.
- Complete GatingML support.
- Production GUI behavior.
- Production FCS parsing or large-file rendering.

## Expected Stack

Python 3.11+, NumPy, Polars or pandas, FlowIO and/or FlowKit, PySide6, pyqtgraph, Datashader, pytest, ruff, and mypy.

## Development Setup

```bash
direnv allow
# load the virtual environment if not already loaded
. .direnv/python-3.12.13/bin/activate
python -m pip install -e '.[dev]'
```

Optional groups:

```bash
python -m pip install -e '.[gui,dev,gui-test]'
```

## Building desktop packages

Flowdesk currently builds native PyInstaller `onedir` packages. The build
produces both the GUI (`flowdesk`) and headless CLI (`flowdesk-cli`) artifacts
under `dist/`. These are development/portable directory packages; Windows
installers and signed/notarized macOS DMG files are not generated yet.

PyInstaller is not a cross-compiler. Build on the same OS and CPU architecture
that the package will run on. Use a clean virtual environment with Python
3.11 or newer (Python 3.12 is used by the repository's development setup).
The build machine needs Git, a working C/C++ toolchain for any native wheels,
and enough disk space for the temporary `build/` directory and `dist/`
artifacts. On macOS, install Apple's Command Line Tools (`xcode-select
--install`) before creating the environment. On Windows, use a current
64-bit Python installation and PowerShell or Command Prompt.

Install the package and packaging dependencies from the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Windows cmd.exe:    .venv\Scripts\activate.bat
# macOS/Linux:        source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui,dev]"
```

Build both artifacts:

```bash
python tools/package.py build
```

On macOS or Linux, the equivalent Make target is:

```bash
make package
```

On Windows, run the Python command directly because the repository Makefile
is intended for POSIX shells. The resulting directories are:

```text
dist/flowdesk/       GUI application (flowdesk or flowdesk.exe)
dist/flowdesk-cli/   headless CLI (flowdesk-cli or flowdesk-cli.exe)
```

Run the package smoke test after building. It checks that the GUI starts with
the packaged Qt plugins. If a project and FCS file are supplied, it also runs
the packaged CLI pipeline:

```bash
python tools/package.py smoke
python tools/package.py smoke \
  --project path/to/project.flowdesk \
  --fcs path/to/sample.fcs
```

Smoke-test reports are written to `artifacts/package-smoke/` by default. A
build provenance file can be created with:

```bash
python tools/package.py manifest \
  --output artifacts/package-smoke/build-manifest.json
```

For a single build-and-smoke operation, use `make package-check` on macOS or
Linux. The package must be tested on a clean machine for the target OS before
distribution. In particular, verify Japanese and space-containing paths,
project save/load, exports, recovery/log directories, and that GUI population
counts agree with headless `PipelineRunner` results.

Platform-specific signing and installer steps are not part of the current
build entry point:

- Windows: `dist/flowdesk/` can be wrapped by an installer such as Inno Setup,
  but no installer configuration is included yet.
- macOS: the onedir output can be assembled into an `.app`; Developer ID
  signing, hardened runtime, notarization, and DMG creation still require a
  separate release workflow.
- Linux: AppImage generation is not included yet.

Do not commit `build/`, `dist/`, or package smoke artifacts. Use a native
runner for each supported OS and keep the Python, PySide6, NumPy, and FlowIO
versions recorded in the manifest when sharing a package.

### Windows build with GitHub Actions

The repository includes `.github/workflows/package-windows.yml`. It runs on a
native `windows-latest` runner and builds both the GUI and CLI packages, runs
core tests and the packaged smoke test, writes a build manifest, and uploads
`Flowdesk-Windows-x64.zip` as an Actions artifact.

Run it from **Actions → Package Windows → Run workflow**, or push a tag such
as `v0.1.0`. The workflow creates a portable ZIP, not an installer, and the
artifact is available from the completed workflow run. The package is
unsigned; code signing, SmartScreen reputation, and an Inno Setup installer
require a later release workflow.

The repository also includes `package-linux.yml` and `package-macos.yml`.
They run on `ubuntu-22.04` and `macos-14`, respectively, and upload
`Flowdesk-Linux-x86_64.tar.gz` and `Flowdesk-macOS-arm64.zip` as separate
artifacts. These are native PyInstaller directory packages. AppImage,
macOS `.app`/DMG packaging, signing, and notarization are not included yet.

To create and push a tag from the version in `pyproject.toml`, first commit
the version change and then run:

```bash
make pushtag
```

This creates and pushes `v<project version>`. Existing tags are never
overwritten.

## Tests

```bash
pytest
```

### Using Makefile

A `Makefile` is provided for convenience:

```bash
make test        # Run all tests (pytest -v)
make lint        # Run ruff linter on src/ and tests/
make type-check  # Run mypy type checker on core, storage, and CLI modules
make check       # Run lint + type-check
make fmt         # Run ruff formatter on src/ and tests/
make all         # Run fmt + check + test
make clean       # Remove build artifacts and caches
make help        # Show available targets
```

## CLI Usage

After installing the package (`pip install -e .`), the `flowdesk` command is available:

```bash
# Run a saved project and export results
flowdesk run path/to/project.flowdesk --output results.tsv

# Inspect FCS file metadata
flowdesk inspect path/to/sample.fcs

# Apply gates to multiple FCS files in batch
flowdesk batch-gate path/to/project.flowdesk --fcs file1.fcs file2.fcs
```

### Export Formats

The CLI `run` command exports population statistics as TSV by default. Use `--csv` to produce CSV output.

`NaN` values (e.g., undefined frequencies) can be controlled via `--nan-policy`:

- `string_nan` (default): write the literal string `NaN`
- `empty`: leave the cell empty
- `zero`: write `0`

## GUI Usage

The PySide6-based GUI is available as an optional dependency. Install the `gui` extra:

```bash
python -m pip install -e '.[gui,dev]'
```

### Launching the GUI

```bash
# Launch with no data
python -m flowdesk_qt

# Launch and auto-load FCS files from a directory
python -m flowdesk_qt --data-dir data/
```

### GUI Testing and Debugging

```bash
./tools/run-gui-tests.sh
./tools/run-single-gui-test.sh tests/gui/test_gui_workflow.py::test_load_gate_run_and_match_headless
make test-all
./tools/run-gui-debug.sh --data-dir data/
```

GUI tests use the offscreen Qt backend by default. For X11-specific behavior, use
`FLOWDESK_GUI_BACKEND=xvfb ./tools/run-gui-tests.sh`. When the GUI is launched
normally, logs and debug artifacts are written below the OS-specific user
application-data directory. Use `--debug-artifacts-dir` to select an explicit
directory during development or CI. Recovery copies use the OS-specific user
cache directory.

### GUI Layout

```
+-----------+--------------------------+----------------+
| Samples   |  Plot Parameters         |  Gates         |
| Browser   |  +------------------+    |  Editor        |
|           |  | 2D Scatter Plot  |    |                |
| - File    |  |  (pyqtgraph)     |    |  - Create Gate |
|   list    |  |                  |    |  - Delete      |
|           |  |  + Gate overlays |    |  - Polygon     |
| - Channel |  +------------------+    +----------------+
|   metadata|                                |          |
+-----------+                                |          |
                                             +----------------+
                                             | Population     |
                                             | Results        |
                                             | (table)        |
                                             +----------------+
```

- **Sample Browser** (left): lists loaded FCS files and shows channel metadata.
- **Channel Selector** (center top): choose X and Y parameters for the 2D plot.
- **Plot Widget** (center): pyqtgraph-based scatter plot with gate overlays in data coordinates.
- **Gate Editor** (right top): create rectangle, range, and polygon gates.
- **Population Results** (right bottom): displays pipeline execution results.

### Creating derived parameters

1. Load and select a sample, then choose **Analysis → Derived Parameters**.
2. Enter a definition ID, display name, stable output channel ID, expression,
   source stage (`compensated` or `raw`), optional unit, and failure policy.
3. Select explicit inputs or use **Insert parameter** to insert a measured or
   previously defined channel ID at the expression cursor.
4. Click **Validate** to run core syntax/dependency validation. Errors include a
   diagnostic code and, for syntax errors, line and column.
5. Click **Preview** to evaluate at most 200 events through the same compensation,
   source-view, dependency, and expression pipeline used by headless execution.
6. Confirm the dialog and rerun the pipeline. The stable output channel ID can
   then be referenced by transforms and gates.

Preview values are only a bounded diagnostic view. Gates, statistics, and
exports always use the full event table through `PipelineRunner`.

### Analysis transforms and Logicle gates

1. Load a sample and choose **Analysis → Analysis Transforms**.
2. Create one transform for each parameter that needs formal analysis
   coordinates. Choose `linear`, `log`, `asinh`, or the published Gating-ML
   `logicle`, enter every displayed parameter, and click **Preview** to inspect
   the inverse round-trip error on up to 200 finite events.
3. Confirm the dialog. When a transformed parameter is selected on an axis,
   the old display-scale combo is fixed to `linear`; the plot, ticks, and newly
   drawn gate all use the same persisted transform ID.
4. Draw a rectangle or polygon normally and run the pipeline. The gate's X/Y
   transform IDs make the same membership reproducible through the CLI and
   Python runner.

A transform already referenced by a gate cannot be changed or deleted in
place. Create a new transform ID, select the old gate in **Gate hierarchy**,
and click **Migrate Transform**. The preview shows source/candidate event
counts plus gained and lost events. Choose **Duplicate** to preserve the old
gate or **Migrate** to replace it. Polygon migration is explicitly approximate:
reprojected vertices do not make straight edges scientifically equivalent
between nonlinear coordinate systems.

Migration preview currently stops, rather than using raw-event estimates, when
the project includes compensation or derived parameters. Those projects need
a future canonical pipeline-stage preview before this analysis-changing action
can be enabled safely.

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open directory with FCS files |
| `Ctrl+Shift+O` | Open specific FCS files |
| `Ctrl+R` | Run analysis pipeline |
| `Ctrl+G` | Clear all gates |
| `Ctrl+Q` | Quit application |

### Creating gates and population hierarchies

Flowdesk evaluates gates as a parent-child population hierarchy. Gate
membership is calculated by the GUI-independent pipeline against full event
data; displayed/downsampled points are never used for population counts.

#### Create the first gate

1. Load one or more FCS files and select a sample in **Sample Browser**.
2. Select the X and Y channels and their axis scales.
3. In **Gate Editor**, select `rectangle`, `polygon`, or `range` as the gate
   type.
4. Set **Parent population** to `All Events`.
5. Click **Create Gate**.
6. For a rectangle, drag over the plot. For a polygon, click each vertex and
   double-click the final vertex. A range gate is entered in its dialog.
7. Run the pipeline with `Ctrl+R` or **Run Pipeline**.

The resulting population appears in **Population Results**. Selecting its row
filters the scatter plot or Count histogram to that population's full
membership. Selecting `All Events` restores the unfiltered view.

#### Create a child gate

To create a hierarchy such as:

```text
All Events
└─ Cells
   └─ Singlets
      └─ CD45+
```

create `Cells` with `All Events` as its parent. Then select `Cells` in the
**Gate hierarchy** tree and click **Create Child Gate** to create `Singlets`.
Select `Singlets` and repeat the operation to create `CD45+`. The creation
context banner shows the fixed parent id, sample, channels, and scales before
drawing. Run the pipeline again after gate changes.

Selecting a row in **Population Results** changes the displayed population,
but currently does not automatically change the **Parent population** combo.
The parent must be selected explicitly through **Create Child Gate** or the
**Parent population** combo in Gate Editor.

Select a gate and click **Show Gate** to navigate to its channel pair and axis
scales without changing analysis results. To change an existing parent, choose
the new parent in the selected-gate parent control and click **Apply Parent**.
Invalid self/descendant/cyclic relationships are rejected atomically.

#### Axis scales and gate coordinates

Legacy geometric gates record the X and Y scales in which they were created:
`linear`, `log10`, or `asinh`. New formal analysis transforms instead persist
stable per-axis transform IDs. In both cases the headless pipeline applies the
same coordinate definition to full-resolution values before evaluating the
gate.

A gate overlay is shown and editable only when the current channel pair and
axis scales match the gate definition. For example, a linear/linear gate is
hidden after switching the view to linear/log10, but its definition and
population membership are unchanged. Switch back to linear/linear to display
and edit it again. Create a separate gate while viewing linear/log10 when that
coordinate system is scientifically intended.

#### Create Boolean gates

Boolean gates combine existing populations without evaluating display points.

1. Create the source gates and choose the intended **Parent population**.
2. Select `boolean` in the **Gate type** combo.
3. Click **Create Gate**.
4. Select `and`, `or`, or `not` in the dialog.
5. Select source populations from the hierarchy tree. Use Ctrl-click to select
   multiple sources.
6. Confirm the dialog and rerun the pipeline.

Operations have the following meanings:

- `AND`: events present in every selected source population.
- `OR`: events present in at least one selected source population.
- `NOT`: events absent from the selected source population.

The Boolean result is also restricted to its selected parent population. For
example, `Parent = Cells`, `Operation = NOT`, and `Source = CD45+` produces
events inside `Cells` that are not in `CD45+`.

Existing Boolean gates can be selected in the hierarchy and changed with
**Edit Boolean**. Operations, source ids, axes/scales, counts, and frequencies
are available from the hierarchy columns and tooltips. Drag-and-drop reparenting
is intentionally not enabled; the validated **Apply Parent** operation prevents
partial or cyclic graph updates.

## Architecture

```text
raw FCS events
  -> compensation
  -> derived parameters
  -> transform
  -> gate membership
  -> population statistics
  -> export
```

- `flowdesk_core`: Scientific logic (GUI-independent).
- `flowdesk_storage`: Project bundle I/O (`.flowdesk` directories).
- `flowdesk_cli`: CLI entry points (`run`, `inspect`, `batch-gate`).
- `flowdesk_qt`: PySide6 GUI (optional dependency).

## Current Status

### Integrated overlay and appearance controls

During routine gating, use the plot-area context menu for display-only appearance
changes, the Gate hierarchy `Color` swatch for population display colors, and the
Samples pane `Ov` checkbox/swatch for manual overlays. The Samples pane also supports
comparison sets and `Manual + comparison set` mode. Active-sample selection remains
separate from overlay selection; missing or incompatible overlay sources are reported
instead of being treated as zero events. The advanced `Overlay Sources...` and
`Plot Presentation...` dialogs remain available for explicit population/axis/transform
configuration.

Implemented: core dataclasses, pipeline runner, FCS I/O, compensation, derived parameters, transforms, gates, population statistics, TSV/CSV export, CLI commands, and synthetic tests. PySide6 GUI with sample browser, scatter and histogram plots, hierarchy-tree and Boolean gate editing, population filtering, validated reparenting, and pipeline execution. The current suite has 325 passing tests, and `ruff` passes for all source and test files.

Not yet implemented: complete FlowJo compatibility, full GatingML support, production GUI behavior, and large-file FCS rendering.
