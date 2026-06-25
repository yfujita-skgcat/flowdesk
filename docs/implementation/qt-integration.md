# Qt Integration Implementation Guide

## Goal

Implement Qt UI components that edit project state and call core APIs without embedding scientific execution logic.

## Target Files

- `src/flowdesk_qt/main_window.py`
- `src/flowdesk_qt/sample_browser.py`
- `src/flowdesk_qt/channel_selector.py`
- `src/flowdesk_qt/plot_widget.py`
- `src/flowdesk_qt/gate_editor.py`
- `src/flowdesk_qt/population_tree.py`
- GUI tests if a Qt test harness is introduced

## Implementation Rules

- Qt widgets may display data, collect user input, update project definitions, and call `PipelineRunner`.
- Qt widgets must not calculate compensation, derived parameters, gate membership, or population statistics.
- Gate editor must save data coordinates or transformed data coordinates, not screen pixels.
- Display downsampling is allowed only for rendering, never for analytical results.
- Keep GUI dependency optional under the `gui` extra.

## Required Behavior

- Load or receive a project model.
- Show samples and channels from core/storage state.
- Let user select plot parameters.
- Let user create/edit gate definitions as project data.
- Trigger pipeline execution through core runner and display `ExecutionReport`.

## Required Tests

- Core tests must pass before GUI tests are considered.
- Add import tests that `flowdesk_qt` imports only when GUI dependencies are installed.
- Add unit tests for coordinate conversion if gate editor maps screen to data coordinates.
- Add tests or screenshots only after a runnable GUI harness exists.

## Acceptance Criteria

- No scientific execution code is added to `src/flowdesk_qt`.
- `rg -n "compensat|derived|membership|frequency|export" src/flowdesk_qt` is reviewed for GUI-only usage.
- `pyenv exec ruff check src/flowdesk_qt` passes when GUI dependencies are installed.
- Core, pipeline, and CLI tests still pass after GUI changes.
