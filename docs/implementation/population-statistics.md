# Population Statistics Implementation Guide

## Goal

Compute population counts and frequencies reproducibly from gate membership results.

## Target Files

- `src/flowdesk_core/populations.py`
- `src/flowdesk_core/statistics.py`
- `src/flowdesk_core/models.py`
- `tests/test_population_statistics.py`

## Implementation Rules

- `event_count` is the number of events in the population after parent filtering.
- `frequency_of_parent` is `event_count / parent_event_count`.
- `frequency_of_total` is `event_count / total_event_count`.
- If parent or total count is zero, return `None` or a documented `NaN` policy. Do not divide by zero.
- Keep sample id and population id attached to every result.

## Required Behavior

- Compute root population statistics.
- Compute child population statistics.
- Preserve hierarchical parent relationships.
- Convert statistics to export records.

## Required Tests

- Existing frequency test remains.
- Zero parent count behavior is tested.
- Child population frequency differs correctly between parent and total.
- Export record conversion includes event count, frequency of parent, and frequency of total.

## Acceptance Criteria

- `pytest tests/test_population_statistics.py` passes.
- `pyenv exec ruff check src/flowdesk_core/statistics.py src/flowdesk_core/populations.py tests/test_population_statistics.py` passes.
- `pyenv exec mypy src/flowdesk_core tests` passes.
