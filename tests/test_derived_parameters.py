import math

from flowdesk_core.derived_parameters import evaluate_binary_expression
from flowdesk_core.models import DerivedParameterSpec


def test_derived_parameter_model_can_be_created() -> None:
  spec = DerivedParameterSpec(
    id="fl1_over_fl2",
    name="FL1_over_FL2",
    expression="FL1-A / FL2-A",
    input_parameters=("FL1-A", "FL2-A"),
  )

  assert spec.source_stage == "compensated"
  assert spec.invalid_value_policy == "division_by_zero_to_nan"


def test_simple_derived_parameter_expression_specification() -> None:
  result = evaluate_binary_expression("FL1-A / FL2-A", {"FL1-A": 10.0, "FL2-A": 2.0})

  assert result == 5.0


def test_division_by_zero_returns_nan() -> None:
  result = evaluate_binary_expression("FL1-A / FL2-A", {"FL1-A": 10.0, "FL2-A": 0.0})

  assert math.isnan(result)
