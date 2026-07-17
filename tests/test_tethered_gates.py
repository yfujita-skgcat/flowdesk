from flowdesk_core.models import GateSpec, TetheredGateTemplateSpec
from flowdesk_core.tethered_gates import fit_tethered_gate


def test_tethered_rectangle_translates_anchor_geometry() -> None:
  anchor = GateSpec(
    id="anchor", name="Anchor", gate_type="rectangle", x_parameter="X", y_parameter="Y",
    thresholds={"x_min": 1.0, "x_max": 3.0, "y_min": 4.0, "y_max": 8.0},
  )
  template = TetheredGateTemplateSpec(
    id="child", name="Child", algorithm="translated_rectangle", anchor_gate_id="anchor",
    x_offset=2.0, y_offset=-1.0,
  )
  result = fit_tethered_gate(template, anchor, "s1")
  assert result.status == "success"
  assert result.gate is not None
  assert result.gate.thresholds == {"x_min": 3.0, "x_max": 5.0, "y_min": 3.0, "y_max": 7.0}
