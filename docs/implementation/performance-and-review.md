# Performance and Scientific Review Guide

## Goal

Define performance and scientific correctness checks that apply across implementation tasks.

## Target Files

- `docs/processing_pipeline.md`
- `docs/headless_execution.md`
- `.codex/skills/performance-benchmark/SKILL.md`
- `.codex/skills/scientific-review/SKILL.md`
- benchmark scripts under a future `benchmarks/` directory

## Implementation Rules

- Do not use display-downsampled events for analysis.
- Benchmark with deterministic synthetic data before using real large FCS files.
- Keep reproducibility metadata in execution reports.
- Treat compensation alignment, transform behavior, gate boundary semantics, and frequency definitions as scientific review points.
- Record uncertain assumptions in docs and tests.

## Required Performance Tests

- Add synthetic benchmarks only when an implementation has measurable behavior.
- Compare full-data gate counts against any accelerated or cached path.
- Test cache invalidation after changing compensation, derived parameters, transforms, or gates.

## Required Scientific Review Checks

- Does the implementation preserve raw data immutability?
- Is channel alignment explicit?
- Are invalid numeric values handled intentionally?
- Are gate coordinates stored in data space?
- Do GUI/headless paths produce the same population counts?

## Acceptance Criteria

- Any result-affecting change includes at least one focused test.
- Any approximation is named as an approximation and documented.
- Pipeline runner tests confirm GUI-independent reproducibility for the changed behavior.
- Existing `pytest`, ruff, and mypy checks pass.
