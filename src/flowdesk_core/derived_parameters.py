"""Derived parameter definitions and safe-evaluation placeholders."""

from __future__ import annotations

import math
import operator
from collections.abc import Mapping

from flowdesk_core.models import DerivedParameterSpec

_OPERATORS = {
  "+": operator.add,
  "-": operator.sub,
  "*": operator.mul,
  "/": operator.truediv,
}


def describe_derived_parameter(spec: DerivedParameterSpec) -> str:
  """Return a compact human-readable description."""

  inputs = ", ".join(spec.input_parameters) or "unspecified inputs"
  return f"{spec.name}: {spec.expression} from {spec.source_stage} ({inputs})"


def evaluate_binary_expression(expression: str, values: Mapping[str, float]) -> float:
  """Evaluate a deliberately tiny binary expression subset.

  This is not the final expression engine. It exists to capture MVP behavior without
  using arbitrary Python eval. Supported form: `<parameter> <op> <parameter>`.
  Division by zero returns NaN.
  """

  parts = expression.split()
  if len(parts) != 3:
    raise ValueError("only simple binary expressions are supported in the MVP placeholder")
  left_name, op_symbol, right_name = parts
  if op_symbol not in _OPERATORS:
    raise ValueError(f"unsupported operator: {op_symbol}")
  left = values[left_name]
  right = values[right_name]
  if op_symbol == "/" and right == 0:
    return math.nan
  return float(_OPERATORS[op_symbol](left, right))
