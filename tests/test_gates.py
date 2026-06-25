import pytest

from flowdesk_core.gates import point_in_rectangle
from flowdesk_core.models import GateSpec


def test_rectangle_gate_membership_placeholder() -> None:
  gate = GateSpec(
    id="g1",
    name="live",
    gate_type="rectangle",
    x_parameter="FSC-A",
    y_parameter="SSC-A",
    thresholds={"x_min": 1.0, "x_max": 3.0, "y_min": 2.0, "y_max": 4.0},
  )

  assert point_in_rectangle(gate, 2.0, 3.0)
  assert not point_in_rectangle(gate, 4.0, 3.0)


@pytest.mark.xfail(reason="polygon membership engine is not implemented yet")
def test_polygon_gate_membership_future() -> None:
  raise NotImplementedError
