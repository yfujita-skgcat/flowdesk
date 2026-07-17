"""Numeric and provenance tests for the B5 automatic gate subphase."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.automatic_gates import (
  AUTO_GATE_ALGORITHM_VERSION,
  AutoGateFitError,
  fit_auto_gate,
)
from flowdesk_core.models import AutoGateTemplateSpec


def _template(**parameters) -> AutoGateTemplateSpec:
  return AutoGateTemplateSpec(
    id="auto", name="Auto", algorithm="quantile_rectangle",
    x_parameter="X", y_parameter="Y", parameters=parameters,
  )


def test_auto_quantile_rectangle_is_deterministic_and_full_data() -> None:
  data = np.column_stack((np.arange(100.0), np.arange(100.0) * 2.0))
  result = fit_auto_gate(
    _template(q_low=0.1, q_high=0.9, minimum_events=20),
    data, ["X", "Y"], "s1",
  )
  repeated = fit_auto_gate(
    _template(q_low=0.1, q_high=0.9, minimum_events=20),
    data, ["X", "Y"], "s1",
  )
  assert result.status == repeated.status == "success"
  assert result.gate == repeated.gate
  assert result.input_hash == repeated.input_hash
  assert result.algorithm_version == AUTO_GATE_ALGORITHM_VERSION
  assert result.gate is not None
  assert result.gate.thresholds == {
    "x_min": 9.9, "x_max": 89.10000000000001,
    "y_min": 19.8, "y_max": 178.20000000000002,
  }


def test_auto_fit_uses_parent_population_full_mask_and_excludes_nonfinite() -> None:
  data = np.array([
    [0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0],
    [1000.0, 1000.0], [np.nan, 4.0],
  ])
  parent = np.array([False, True, True, True, False, True])
  result = fit_auto_gate(
    _template(q_low=0.0, q_high=1.0, minimum_events=3),
    data, ["X", "Y"], "s1", population_mask=parent,
  )
  assert result.status == "success"
  assert result.gate is not None
  assert result.gate.thresholds == {
    "x_min": 1.0, "x_max": 3.0,
    "y_min": 1.0, "y_max": 3.0,
  }
  summary = result.diagnostics[0]
  assert summary["event_count"] == 4
  assert summary["finite_event_count"] == 3
  assert summary["excluded_nonfinite_count"] == 1


def test_auto_fit_failure_is_explicit_and_not_an_empty_success() -> None:
  result = fit_auto_gate(
    _template(minimum_events=5),
    np.ones((4, 2)), ["X", "Y"], "s1",
  )
  assert result.status == "failed"
  assert result.gate is None
  assert result.failure_reason == "insufficient finite events: 4 < minimum_events 5"
  assert result.diagnostics[-1]["code"] == "auto_fit_failed"


def test_auto_fit_rejects_invalid_algorithm_parameters() -> None:
  with pytest.raises(AutoGateFitError, match="quantiles"):
    fit_auto_gate(
      _template(q_low=0.9, q_high=0.1),
      np.ones((20, 2)), ["X", "Y"], "s1",
    )
  with pytest.raises(AutoGateFitError, match="minimum_events"):
    fit_auto_gate(
      _template(minimum_events=0),
      np.ones((20, 2)), ["X", "Y"], "s1",
    )
