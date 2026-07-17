from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.magnetic_gates import fit_magnetic_gate
from flowdesk_core.models import MagneticGateTemplateSpec


def test_magnetic_fit_uses_largest_gap_and_is_deterministic() -> None:
  values = np.array([[1.0], [1.1], [1.2], [9.0], [9.1], [9.2]])
  template = MagneticGateTemplateSpec(
    id="beads", name="Beads", algorithm="largest_gap_range", parameter="FSC",
    parameters={"minimum_events": 2},
  )
  result = fit_magnetic_gate(template, values, ["FSC"], "s1")
  repeated = fit_magnetic_gate(template, values, ["FSC"], "s1")
  assert result.status == "success"
  assert result.gate is not None
  assert result.gate.thresholds["min"] == pytest.approx(5.1)
  assert result == repeated


def test_magnetic_fit_excludes_nonfinite_and_fails_explicitly_when_small() -> None:
  values = np.array([[1.0], [np.nan], [np.inf]])
  template = MagneticGateTemplateSpec(
    id="beads", name="Beads", algorithm="largest_gap_range", parameter="FSC",
    parameters={"minimum_events": 2},
  )
  result = fit_magnetic_gate(template, values, ["FSC"], "s1")
  assert result.status == "failed"
  assert result.failure_reason is not None
  assert result.diagnostics[0]["excluded_nonfinite_count"] == 2
