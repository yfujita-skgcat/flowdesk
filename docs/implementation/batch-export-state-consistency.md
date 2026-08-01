# Batch Export state consistency

## Purpose

Ensure that GUI rendering and Batch Plot Export resolve the same sample titles,
annotations, plot presentation, and saved definitions when the user starts an
export from the current window.

## Root cause

`MainWindow._on_edit_sample_sheet()` updates the in-memory annotation table and
marks the project dirty. The normal `Run Export` path persists the project
before starting the worker, but the `Run Saved Queue` branch starts
`_BatchPlotExportWorker` immediately. The worker and CLI queue then reload the
project bundle from disk, so they can use an older title such as the FCS/sample
name while the GUI already displays the new workspace `sample_title`.

## Implementation rules

1. Before either a single-definition export or a saved-queue export starts, make
   the current GUI project state available to the disk-backed worker.
2. Reuse the existing atomic project save API and manifest builder; do not add
   title-resolution logic to Qt or duplicate annotation precedence in the CLI.
3. If the project has no path, use the existing Save Project workflow. If a save
   fails or is cancelled, do not create a worker or start any output.
4. Preserve the current dirty state and show a user-visible error when saving
   fails. Successful persistence may clear the dirty flag as normal Save Project
   does.
5. Keep scientific execution in `flowdesk_core`/the headless pipeline. The Qt
   layer only persists state and starts the existing worker.

## Target files

- `src/flowdesk_qt/main_window.py`: shared pre-export persistence boundary.
- `tests/gui/test_statistics_entrypoints.py` or `tests/gui/test_gui_workflow.py`:
  queue-start and save-failure regression tests.
- `docs/user-manual/user_manual.md`: document that Saved Queue persists current
  dirty GUI annotations before execution.

## Required tests

- Change an in-memory workspace `sample_title`, start `Run Saved Queue`, and
  assert the save hook runs before the queue worker starts.
- Assert a failed/cancelled save starts no worker and leaves the project dirty.
- Retain existing tests for single-definition export and queue worker arguments.

## Acceptance criteria

- A title edited to `A5_s2` is used by both GUI and every queued PNG/JPEG/SVG/PDF
  export without requiring a separate manual Save Project action.
- Saved queue output is based on one persisted manifest snapshot and does not
  silently use an older sample title.
- `python -m pytest tests/gui/test_statistics_entrypoints.py tests/gui/test_gui_workflow.py`
  passes in the Linux CI environment.
