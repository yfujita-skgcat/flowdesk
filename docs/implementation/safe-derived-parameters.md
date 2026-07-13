# Safe Derived Parameters Implementation Guide

## Goal

Implement a safe expression evaluator for derived parameters such as `FL1-A / FL2-A` without arbitrary Python `eval`.

## Target Files

- `src/flowdesk_core/derived_parameters.py`
- `src/flowdesk_core/models.py`
- `docs/processing_pipeline.md`
- `tests/test_derived_parameters.py`

## Implementation Rules

- Never use `eval`, `exec`, `compile`, or unrestricted AST execution.
- Use an explicit parser, restricted AST walker, or small expression grammar.
- Supported MVP operations should include numeric constants, parameter references, parentheses, unary minus, `+`, `-`, `*`, `/`, and safe functions such as `log10` only if explicitly whitelisted.
- Parameter names such as `FL1-A` must be handled unambiguously. If Python identifier syntax is used internally, create a safe mapping layer.
- Division by zero must produce `NaN`, not crash.
- Invalid input values must follow `invalid_value_policy`.
- Keep the scalar API compatible and provide a separate vectorized evaluator for
  full event-aligned `float64` columns. Validate shape and row count before a
  derived column can enter downstream analysis.

## Required Behavior

- Evaluate simple ratios.
- Evaluate parenthesized normalized differences.
- Reject unknown functions and attribute access.
- Reject attempts to access Python internals.
- Report missing input parameters clearly.
- Preserve source stage metadata.
- Extract exact parameter references through the same restricted AST and build
  dependencies before event evaluation. Unknown references and cycles are
  definition errors, not per-event NaN policy cases.

## Required Tests

- `FL1-A / FL2-A` returns expected values.
- `(FL1-A - FL2-A) / (FL1-A + FL2-A)` returns expected values.
- `log10(FL1-A / FL2-A)` works only if `log10` is whitelisted.
- Division by zero returns `math.nan`.
- Unknown parameter raises a clear error.
- Malicious expressions such as `__import__("os")` are rejected.
- No test should rely on Python `eval` semantics.

## Acceptance Criteria

- `pytest tests/test_derived_parameters.py` passes.
- Add at least one malicious-expression rejection test.
- `rg -n "eval|exec|compile" src/flowdesk_core/derived_parameters.py` shows no unsafe usage.
- `pyenv exec ruff check src/flowdesk_core/derived_parameters.py tests/test_derived_parameters.py` passes.
- `pyenv exec mypy src/flowdesk_core tests` passes.
