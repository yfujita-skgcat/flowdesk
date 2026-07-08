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
python -m pip install -e '.[io,gui,dev]'
```

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

Implemented: core dataclasses, pipeline runner, FCS I/O, compensation, derived parameters, transforms, gates, population statistics, TSV/CSV export, CLI commands, and synthetic tests (237 tests passing). `mypy` and `ruff` checks pass for all source files.

Not yet implemented: complete FlowJo compatibility, full GatingML support, production GUI behavior, and large-file FCS rendering.
