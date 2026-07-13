"""Tests for safe derived parameter expression evaluation."""

from __future__ import annotations

import math

import pytest

from flowdesk_core.derived_parameters import (
    DerivedParameterPlanningError,
    ExpressionError,
    describe_derived_parameter,
    evaluate_binary_expression,
    evaluate_expression,
    extract_parameter_references,
    plan_derived_parameters,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import DerivedFailurePolicy, DerivedParameterSpec

VALUES = {
    "FL1-A": 10.0,
    "FL2-A": 2.0,
    "FSC-A": 100.0,
    "SSC-A": 50.0,
}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_derived_parameter_model_defaults() -> None:
    spec = DerivedParameterSpec(
        id="fl1_over_fl2",
        name="FL1_over_FL2",
        expression="FL1-A / FL2-A",
        input_parameters=("FL1-A", "FL2-A"),
    )
    assert spec.source_stage == "compensated"
    assert (
        spec.invalid_value_policy
        is DerivedFailurePolicy.EMIT_NAN_WITH_WARNING
    )


def test_derived_parameter_rejects_unknown_failure_policy() -> None:
    with pytest.raises(ValueError, match="invalid derived failure policy"):
        DerivedParameterSpec(
            id="ratio",
            name="Ratio",
            expression="A / B",
            invalid_value_policy="keep_going",  # type: ignore[arg-type]
        )


def test_legacy_division_policy_maps_to_explicit_nan_warning_policy() -> None:
    spec = DerivedParameterSpec(
        id="ratio",
        name="Ratio",
        expression="A / B",
        invalid_value_policy="division_by_zero_to_nan",  # type: ignore[arg-type]
    )

    assert spec.invalid_value_policy is DerivedFailurePolicy.EMIT_NAN_WITH_WARNING


def test_extract_parameter_references_uses_exact_safe_ids() -> None:
    references = extract_parameter_references(
        "log10(FL1-A / ratio.previous)",
        ("FL1-A", "ratio.previous"),
    )

    assert references == ("FL1-A", "ratio.previous")


def test_extract_references_distinguishes_subtraction_from_hyphenated_ids() -> None:
    references = extract_parameter_references(
        "signal-reference + FL1-A",
        ("signal", "reference", "FL1-A"),
    )

    assert references == ("signal", "reference", "FL1-A")


def test_dependency_plan_keeps_display_order_and_topologically_reorders() -> None:
    dependent = DerivedParameterSpec(
        id="normalized",
        name="Normalized",
        expression="ratio + signal",
        input_parameters=("ratio", "signal"),
    )
    prerequisite = DerivedParameterSpec(
        id="ratio",
        name="Ratio",
        expression="signal / reference",
        input_parameters=("signal", "reference"),
    )

    plan = plan_derived_parameters(
        (dependent, prerequisite),
        ("signal", "reference"),
    )

    assert [spec.id for spec in plan.display_order] == ["normalized", "ratio"]
    assert [spec.id for spec in plan.execution_order] == ["ratio", "normalized"]
    assert plan.dependencies == (
        ("normalized", ("ratio",)),
        ("ratio", ()),
    )


def test_dependency_plan_rejects_unknown_input_with_context() -> None:
    spec = DerivedParameterSpec(
        id="ratio",
        name="Ratio",
        expression="signal / missing",
    )

    with pytest.raises(DerivedParameterPlanningError) as error:
        plan_derived_parameters((spec,), ("signal",))

    assert error.value.code == "unknown_derived_input"
    assert error.value.parameter_id == "ratio"
    assert error.value.references == ("missing",)


def test_dependency_plan_rejects_cycle_with_all_ids() -> None:
    first = DerivedParameterSpec("first", "First", "second + 1")
    second = DerivedParameterSpec("second", "Second", "first + 1")

    with pytest.raises(DerivedParameterPlanningError) as error:
        plan_derived_parameters((first, second), ())

    assert error.value.code == "derived_dependency_cycle"
    assert error.value.cycle_ids == ("first", "second")


def test_cycle_diagnostic_excludes_nodes_only_blocked_by_cycle() -> None:
    first = DerivedParameterSpec("first", "First", "second + 1")
    second = DerivedParameterSpec("second", "Second", "first + 1")
    blocked = DerivedParameterSpec("blocked", "Blocked", "first + 1")

    with pytest.raises(DerivedParameterPlanningError) as error:
        plan_derived_parameters((first, second, blocked), ())

    assert error.value.cycle_ids == ("first", "second")


def test_describe_derived_parameter() -> None:
    spec = DerivedParameterSpec(
        id="ratio",
        name="Ratio",
        expression="FL1-A / FL2-A",
        input_parameters=("FL1-A", "FL2-A"),
    )
    desc = describe_derived_parameter(spec)
    assert "Ratio" in desc
    assert "FL1-A / FL2-A" in desc


# ---------------------------------------------------------------------------
# Basic arithmetic
# ---------------------------------------------------------------------------


def test_simple_ratio() -> None:
    assert evaluate_expression("FL1-A / FL2-A", VALUES) == 5.0


def test_addition() -> None:
    assert evaluate_expression("FL1-A + FL2-A", VALUES) == 12.0


def test_subtraction() -> None:
    assert evaluate_expression("FL1-A - FL2-A", VALUES) == 8.0


def test_multiplication() -> None:
    assert evaluate_expression("FL1-A * FL2-A", VALUES) == 20.0


def test_power() -> None:
    assert evaluate_expression("FL1-A ** 2", VALUES) == 100.0


def test_unary_minus() -> None:
    assert evaluate_expression("-FL1-A", VALUES) == -10.0


def test_unary_plus() -> None:
    assert evaluate_expression("+FL1-A", VALUES) == 10.0


def test_numeric_constant() -> None:
    assert evaluate_expression("3.14", VALUES) == 3.14


def test_mixed_constant_and_param() -> None:
    assert evaluate_expression("FL1-A * 2", VALUES) == 20.0


# ---------------------------------------------------------------------------
# Parentheses and complex expressions
# ---------------------------------------------------------------------------


def test_parenthesized_ratio() -> None:
    assert evaluate_expression("(FL1-A) / (FL2-A)", VALUES) == 5.0


def test_normalized_difference() -> None:
    result = evaluate_expression(
        "(FL1-A - FL2-A) / (FL1-A + FL2-A)",
        VALUES,
    )
    assert math.isclose(result, 8.0 / 12.0)


def test_nested_parentheses() -> None:
    result = evaluate_expression(
        "((FL1-A * 2) + FL2-A) / 3",
        VALUES,
    )
    assert math.isclose(result, (20.0 + 2.0) / 3)


# ---------------------------------------------------------------------------
# Division by zero
# ---------------------------------------------------------------------------


def test_division_by_zero_returns_nan() -> None:
    result = evaluate_expression(
        "FL1-A / FL2-A",
        {"FL1-A": 10.0, "FL2-A": 0.0},
    )
    assert math.isnan(result)


def test_division_by_zero_in_complex_expr() -> None:
    result = evaluate_expression(
        "(FL1-A + FL2-A) / FL2-A",
        {"FL1-A": 10.0, "FL2-A": 0.0},
    )
    assert math.isnan(result)


# ---------------------------------------------------------------------------
# Whitelisted functions
# ---------------------------------------------------------------------------


def test_log10_whitelisted() -> None:
    result = evaluate_expression("log10(FL1-A)", VALUES)
    assert math.isclose(result, math.log10(10.0))


def test_log10_of_ratio() -> None:
    result = evaluate_expression("log10(FL1-A / FL2-A)", VALUES)
    assert math.isclose(result, math.log10(5.0))


def test_sqrt_whitelisted() -> None:
    result = evaluate_expression("sqrt(FL1-A)", VALUES)
    assert math.isclose(result, math.sqrt(10.0))


def test_abs_whitelisted() -> None:
    result = evaluate_expression("abs(-FL1-A)", VALUES)
    assert math.isclose(result, 10.0)


def test_exp_whitelisted() -> None:
    result = evaluate_expression("exp(0)", VALUES)
    assert math.isclose(result, 1.0)


def test_unknown_function_rejected() -> None:
    with pytest.raises(ExpressionError, match="not allowed"):
        evaluate_expression("sum(FL1-A, FL2-A)", VALUES)


def test_functions_disabled_flag() -> None:
    with pytest.raises(ExpressionError, match="not allowed in this context"):
        evaluate_expression(
            "log10(FL1-A)",
            VALUES,
            allow_functions=False,
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_unknown_parameter() -> None:
    with pytest.raises(ExpressionError, match="unknown parameter"):
        evaluate_expression("FL1-A / FL3-A", VALUES)


def test_syntax_error() -> None:
    with pytest.raises(ExpressionError, match="invalid expression syntax"):
        evaluate_expression("FL1-A / ", VALUES)


def test_expression_error_is_flowdesk_error() -> None:
    assert issubclass(ExpressionError, FlowdeskError)


# ---------------------------------------------------------------------------
# Malicious expression rejection
# ---------------------------------------------------------------------------


MALICIOUS_EXPRESSIONS = [
    '__import__("os")',
    "__import__('os').system('echo pwned')",
    "__class__",
    "__globals__",
    "__builtins__",
    "().__class__.__bases__[0].__subclasses__()",
    "chr(97)",
    "eval('1+1')",
    "exec('pass')",
    "compile('1', '', 'eval')",
    "open('/etc/passwd').read()",
    "[x for x in y]",
    "lambda: 1",
    "1 if True else 0",
    "not True",
    "True and False",
    "1 + 2 == 3",
]


@pytest.mark.parametrize("expr", MALICIOUS_EXPRESSIONS)
def test_malicious_expressions_rejected(expr: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate_expression(expr, VALUES)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_evaluate_binary_expression_backward_compat() -> None:
    result = evaluate_binary_expression("FL1-A / FL2-A", VALUES)
    assert result == 5.0


def test_evaluate_binary_expression_nan_compat() -> None:
    result = evaluate_binary_expression(
        "FL1-A / FL2-A",
        {"FL1-A": 10.0, "FL2-A": 0.0},
    )
    assert math.isnan(result)
