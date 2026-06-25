# FCS I/O Implementation Guide

## Goal

Implement FCS loading, metadata parsing, channel mapping, and spillover extraction behind a stable core API.

## Target Files

- `src/flowdesk_core/fcs_io.py`
- `src/flowdesk_core/channels.py`
- `src/flowdesk_core/sample.py`
- `src/flowdesk_core/models.py`
- `tests/test_fcs_io.py`
- `tests/fixtures/README.md`

## Implementation Rules

- Prefer FlowIO or FlowKit for real FCS parsing.
- Keep raw events immutable after load.
- Keep metadata separate from event arrays.
- Normalize channel ids while preserving original channel names.
- Extract FCS spillover metadata into `CompensationMatrixSpec` when present.
- Do not commit large FCS fixtures.
- Use synthetic or very small licensed fixtures only.

## Required Behavior

- Load metadata and channel specs from an FCS file.
- Load event data through a stable return type.
- Extract spillover matrix if available.
- Produce clear errors for unsupported or malformed files.

## Required Tests

- Synthetic parser-adapter tests can use fake metadata without real FCS files.
- Channel mapping preserves original and normalized names.
- Spillover extraction creates a valid compensation matrix.
- Missing spillover returns `None` or an empty result according to documented API.

## Acceptance Criteria

- `pytest tests/test_fcs_io.py tests/test_compensation.py` passes.
- No large `.fcs` fixture is added to git.
- `pyenv exec ruff check src/flowdesk_core/fcs_io.py src/flowdesk_core/channels.py tests/test_fcs_io.py` passes.
- `pyenv exec mypy src/flowdesk_core tests` passes.
