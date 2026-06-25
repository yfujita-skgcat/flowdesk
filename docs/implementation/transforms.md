# Transforms Implementation Guide

## Goal

Implement transform definitions and numeric application for linear, log, asinh, and logicle-like placeholders.

## Target Files

- `src/flowdesk_core/transforms.py`
- `src/flowdesk_core/models.py`
- `tests/test_transforms.py`

## Implementation Rules

- Transforms are analysis definitions, not GUI display settings only.
- Store all parameters needed to reproduce the transform.
- Handle non-positive values for log transforms according to an explicit policy.
- Do not silently drop `NaN` or infinite values.
- Logicle-like transform can start as a documented approximation, but it must be named honestly and tested.

## Required Behavior

- Linear transform returns input values unchanged or applies configured scale/offset.
- Log transform applies configured base and invalid-value policy.
- Asinh transform applies configured cofactor.
- Unknown transform type raises a clear error.

## Required Tests

- Existing transform model test remains.
- Linear, log, and asinh numeric examples match expected values.
- Log invalid input behavior is tested.
- Unknown transform type is rejected.

## Acceptance Criteria

- `pytest tests/test_transforms.py` passes.
- Transform behavior is documented in `docs/processing_pipeline.md` if policies change.
- `pyenv exec ruff check src/flowdesk_core/transforms.py tests/test_transforms.py` passes.
- `pyenv exec mypy src/flowdesk_core tests` passes.
