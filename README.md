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

## Current Status

Initial project skeleton, core dataclasses, pipeline runner placeholders, project bundle schema notes, and synthetic tests are present. Real FCS parsing, GUI analysis, and production gate execution are not implemented yet.
