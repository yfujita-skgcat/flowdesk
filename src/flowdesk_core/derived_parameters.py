"""Derived parameter definitions and safe AST-based expression evaluation."""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Mapping
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import DerivedParameterSpec


class ExpressionError(FlowdeskError):
  """Raised when a derived parameter expression is invalid or unsafe."""


# ---------------------------------------------------------------------------
# Safe math functions available to expressions
# ---------------------------------------------------------------------------

SAFE_FUNCTIONS: dict[str, Any] = {
  "log10": math.log10,
  "log": math.log,
  "sqrt": math.sqrt,
  "abs": abs,
  "exp": math.exp,
  "sin": math.sin,
  "cos": math.cos,
  "tan": math.tan,
  "asin": math.asin,
  "acos": math.acos,
  "atan": math.atan,
  "floor": math.floor,
  "ceil": math.ceil,
}

# ---------------------------------------------------------------------------
# AST node whitelist
# ---------------------------------------------------------------------------

_ALLOWED_NODE_TYPES: frozenset[type] = frozenset(
  [
    ast.Module,
    ast.Expression,
    ast.UnaryOp,
    ast.UAdd,
    ast.USub,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Attribute,
  ]
)

# ---------------------------------------------------------------------------
# Operator mappings
# ---------------------------------------------------------------------------

_BINARY_OPS: dict[type[ast.AST], Callable[[float, float], float]] = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.AST], Callable[[float], float]] = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
}

# ---------------------------------------------------------------------------
# Parameter name normalization
# ---------------------------------------------------------------------------

# Pattern that matches a parameter name: starts with letter, may contain
# alphanumeric, hyphens, underscores, dots (e.g. "FL1-A", "FSC-H", "SSC-W").
# We require at least one non-digit, non-operator character to avoid matching
# numeric constants.
_PARAM_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")

# Whitelisted function names that should NOT be treated as parameter references.
_FUNCTION_NAMES = frozenset(SAFE_FUNCTIONS.keys())


def _normalize_parameter_name(name: str) -> str:
  """Convert a flow-cytometry parameter name to a valid Python identifier.

  ``FL1-A`` becomes ``_p_FL1__A_``.
  """
  return "_p_" + name.replace("-", "__") + "_"


def _build_safe_variables(
  values: Mapping[str, float],
) -> dict[str, float]:
  """Return a dict with parameter names converted to valid Python identifiers."""
  return {_normalize_parameter_name(k): v for k, v in values.items()}


def _preprocess_expression(
  expression: str,
  known_params: Mapping[str, float],
) -> str:
  """Replace parameter names in the expression with safe Python identifiers.

  This allows names containing hyphens (e.g. ``FL1-A``) to be parsed by
  Python's AST without being interpreted as subtraction.
  """

  param_set = set(known_params.keys())

  def _replace_token(match: re.Match[str]) -> str:
    token = match.group(0)
    # Do not replace whitelisted function names.
    if token in _FUNCTION_NAMES:
      return token
    # Only replace if the token is a known parameter.
    if token in param_set:
      return _normalize_parameter_name(token)
    return token

  return _PARAM_NAME_RE.sub(_replace_token, expression)


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


def _safe_eval_node(
  node: ast.AST,
  variables: Mapping[str, float],
  _depth: int = 0,
) -> float:
  """Recursively evaluate a single AST node against ``variables``.

  Only nodes in ``_ALLOWED_NODE_TYPES`` are accepted. All other node types
  raise ``ExpressionError``.
  """

  if _depth > 64:
    raise ExpressionError("expression too deeply nested")

  if isinstance(node, ast.Constant):
    if isinstance(node.value, (int, float)):
      return float(node.value)
    raise ExpressionError(
      f"unsupported constant type: {type(node.value).__name__}"
    )

  if isinstance(node, ast.Name):
    if node.id not in variables:
      raise ExpressionError(f"unknown parameter: {node.id}")
    return float(variables[node.id])

  if isinstance(node, ast.BinOp):
    if type(node.op) not in _BINARY_OPS:
      raise ExpressionError(
        f"unsupported binary operator: {type(node.op).__name__}"
      )
    left = _safe_eval_node(node.left, variables, _depth + 1)
    right = _safe_eval_node(node.right, variables, _depth + 1)
    try:
      return float(_BINARY_OPS[type(node.op)](left, right))
    except ZeroDivisionError:
      return math.nan

  if isinstance(node, ast.UnaryOp):
    if type(node.op) not in _UNARY_OPS:
      raise ExpressionError(
        f"unsupported unary operator: {type(node.op).__name__}"
      )
    operand = _safe_eval_node(node.operand, variables, _depth + 1)
    return float(_UNARY_OPS[type(node.op)](operand))

  if isinstance(node, ast.Call):
    # Only allow calls to whitelisted functions with no keyword arguments.
    if not isinstance(node.func, ast.Name):
      raise ExpressionError(
        "function calls must reference a top-level name"
      )
    func_name = node.func.id
    if func_name not in SAFE_FUNCTIONS:
      raise ExpressionError(f"function not allowed: {func_name}")
    if node.keywords:
      raise ExpressionError("keyword arguments are not supported")
    args = [
      _safe_eval_node(arg, variables, _depth + 1) for arg in node.args
    ]
    try:
      return float(SAFE_FUNCTIONS[func_name](*args))
    except (ValueError, TypeError, OverflowError):
      return math.nan

  if isinstance(node, ast.Expression):
    return _safe_eval_node(node.body, variables, _depth + 1)

  if isinstance(node, ast.Module):
    if len(node.body) != 1:
      raise ExpressionError("module must contain exactly one expression")
    return _safe_eval_node(node.body[0], variables, _depth + 1)

  raise ExpressionError(
    f"unsupported expression node: {type(node).__name__}"
  )


def _check_ast_safety(tree: ast.AST) -> None:
  """Ensure the parsed AST contains only allowed node types.

  This is a defense-in-depth check: even if ``_safe_eval_node`` rejects
  unknown nodes, we fail fast on obviously malicious trees.
  """

  for node in ast.walk(tree):
    if type(node) not in _ALLOWED_NODE_TYPES:
      raise ExpressionError(
        f"unsafe expression node: {type(node).__name__}"
      )


def evaluate_expression(
  expression: str,
  values: Mapping[str, float],
  *,
  allow_functions: bool = True,
) -> float:
  """Evaluate a derived-parameter expression safely.

  Parses ``expression`` into an AST, verifies that only allowed node types
  are present, and evaluates against ``values``.

  Args:
    expression: A mathematical expression string such as
      ``"(FL1-A - FL2-A) / (FL1-A + FL2-A)"``.
    values: Mapping from parameter names to numeric values.
    allow_functions: If ``False``, function calls (including whitelisted
      ones like ``log10``) are rejected.

  Returns:
    The computed float value. Division by zero produces ``NaN``.

  Raises:
    ExpressionError: On syntax errors, unsafe nodes, or unknown parameters.
  """

  # Normalize parameter names (e.g. "FL1-A" -> "_p_FL1__A_") so that
  # Python's AST parser can handle names with hyphens.
  safe_expr = _preprocess_expression(expression, values)
  safe_vars = _build_safe_variables(values)

  try:
    tree = ast.parse(safe_expr, mode="eval")
  except SyntaxError as exc:
    raise ExpressionError(
      f"invalid expression syntax: {exc}"
    ) from exc

  _check_ast_safety(tree)

  if not allow_functions:
    for node in ast.walk(tree):
      if isinstance(node, ast.Call):
        raise ExpressionError(
          "function calls are not allowed in this context"
        )

  return _safe_eval_node(tree, safe_vars)


# ---------------------------------------------------------------------------
# Backward-compatible alias kept for existing callers
# ---------------------------------------------------------------------------


def evaluate_binary_expression(
  expression: str,
  values: Mapping[str, float],
) -> float:
  """Evaluate a derived-parameter expression (backward-compatible wrapper).

  This now delegates to ``evaluate_expression`` which uses the full AST
  evaluator. The name is preserved for existing callers.
  """

  return evaluate_expression(expression, values)


# ---------------------------------------------------------------------------
# Human-readable description helper
# ---------------------------------------------------------------------------


def describe_derived_parameter(spec: DerivedParameterSpec) -> str:
  """Return a compact human-readable description."""

  inputs = ", ".join(spec.input_parameters) or "unspecified inputs"
  return f"{spec.name}: {spec.expression} from {spec.source_stage} ({inputs})"
