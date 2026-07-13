"""Derived parameter definitions and safe AST-based expression evaluation."""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import DerivedParameterSpec


class ExpressionError(FlowdeskError):
  """Raised when a derived parameter expression is invalid or unsafe."""


class DerivedParameterPlanningError(FlowdeskError):
  """Structured error raised before sample processing for an invalid graph."""

  def __init__(
    self,
    code: str,
    message: str,
    *,
    parameter_id: str | None = None,
    references: tuple[str, ...] = (),
    cycle_ids: tuple[str, ...] = (),
  ) -> None:
    self.code = code
    self.parameter_id = parameter_id
    self.references = references
    self.cycle_ids = cycle_ids
    super().__init__(message)

  def to_mapping(self) -> dict[str, Any]:
    """Return stable context without requiring message parsing."""
    return {
      "code": self.code,
      "message": str(self),
      "parameter_id": self.parameter_id,
      "references": self.references,
      "cycle_ids": self.cycle_ids,
    }


@dataclass(frozen=True)
class DerivedParameterPlan:
  """Display order plus deterministic dependency-safe execution order."""

  display_order: tuple[DerivedParameterSpec, ...]
  execution_order: tuple[DerivedParameterSpec, ...]
  dependencies: tuple[tuple[str, tuple[str, ...]], ...]


def _find_dependency_cycle(
  dependencies: Mapping[str, set[str]],
  display_index: Mapping[str, int],
) -> tuple[str, ...]:
  """Return one deterministic actual cycle, excluding merely blocked nodes."""
  state: dict[str, int] = {}
  stack: list[str] = []

  def visit(spec_id: str) -> tuple[str, ...]:
    state[spec_id] = 1
    stack.append(spec_id)
    for dependency in sorted(
      dependencies[spec_id], key=display_index.__getitem__
    ):
      if state.get(dependency, 0) == 0:
        cycle = visit(dependency)
        if cycle:
          return cycle
      elif state.get(dependency) == 1:
        start = stack.index(dependency)
        return tuple(stack[start:])
    stack.pop()
    state[spec_id] = 2
    return ()

  for spec_id in sorted(dependencies, key=display_index.__getitem__):
    if state.get(spec_id, 0) == 0:
      cycle = visit(spec_id)
      if cycle:
        return cycle
  return ()


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
  encoded = "".join(
    character
    if character.isalnum() or character == "_"
    else f"_{ord(character):x}_"
    for character in name
  )
  return f"_flowdesk_parameter_{encoded}_"


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


def extract_parameter_references(
  expression: str,
  known_parameters: Iterable[str],
) -> tuple[str, ...]:
  """Return exact known parameter IDs referenced by a safe expression.

  Unknown identifiers and unsafe syntax are rejected here so dependency
  planning completes before any sample event processing begins.
  """
  known = tuple(dict.fromkeys(known_parameters))
  placeholder_to_parameter: dict[str, str] = {}
  for parameter in known:
    aliases = [_normalize_parameter_name(parameter)]
    if parameter.isidentifier():
      aliases.append(parameter)
    for alias in aliases:
      previous = placeholder_to_parameter.get(alias)
      if previous is not None and previous != parameter:
        raise DerivedParameterPlanningError(
          "derived_parameter_placeholder_collision",
          "parameter IDs collide after safe expression normalization",
          references=(previous, parameter),
        )
      placeholder_to_parameter[alias] = parameter
  safe_expr = _preprocess_expression(
    expression,
    {parameter: 0.0 for parameter in known},
  )
  try:
    tree = ast.parse(safe_expr, mode="eval")
  except SyntaxError as exc:
    raise ExpressionError(f"invalid expression syntax: {exc}") from exc
  _check_ast_safety(tree)

  for node in ast.walk(tree):
    if isinstance(node, ast.Attribute):
      raise ExpressionError("attribute access is not supported")
    if isinstance(node, ast.Call):
      if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
        raise ExpressionError("function not allowed in derived expression")
      if node.keywords:
        raise ExpressionError("keyword arguments are not supported")

  references: list[str] = []
  unknown: list[str] = []
  function_nodes = {
    id(node.func)
    for node in ast.walk(tree)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
  }
  name_nodes = sorted(
    (node for node in ast.walk(tree) if isinstance(node, ast.Name)),
    key=lambda node: (node.lineno, node.col_offset),
  )
  for node in name_nodes:
    if id(node) in function_nodes:
      continue
    resolved_parameter = placeholder_to_parameter.get(node.id)
    if resolved_parameter is None:
      if node.id not in unknown:
        unknown.append(node.id)
    elif resolved_parameter not in references:
      references.append(resolved_parameter)
  if unknown:
    raise DerivedParameterPlanningError(
      "unknown_derived_input",
      f"expression references unknown parameters: {unknown}",
      references=tuple(unknown),
    )
  return tuple(references)


def plan_derived_parameters(
  specs: Sequence[DerivedParameterSpec],
  available_input_ids: Iterable[str],
) -> DerivedParameterPlan:
  """Validate and topologically order derived definitions deterministically."""
  display_order = tuple(specs)
  by_id: dict[str, DerivedParameterSpec] = {}
  display_index: dict[str, int] = {}
  for index, spec in enumerate(display_order):
    if spec.id in by_id:
      raise DerivedParameterPlanningError(
        "duplicate_derived_parameter_id",
        f"duplicate derived parameter ID: {spec.id!r}",
        parameter_id=spec.id,
      )
    by_id[spec.id] = spec
    display_index[spec.id] = index

  available = set(available_input_ids)
  collisions = tuple(spec_id for spec_id in by_id if spec_id in available)
  if collisions:
    raise DerivedParameterPlanningError(
      "derived_output_id_collision",
      f"derived output IDs collide with input channels: {list(collisions)}",
      references=collisions,
    )

  known = available | set(by_id)
  dependencies: dict[str, set[str]] = {}
  for spec in display_order:
    try:
      expression_references = extract_parameter_references(
        spec.expression, known
      )
    except DerivedParameterPlanningError as exc:
      if exc.parameter_id is not None:
        raise
      raise DerivedParameterPlanningError(
        exc.code,
        str(exc),
        parameter_id=spec.id,
        references=exc.references,
        cycle_ids=exc.cycle_ids,
      ) from exc
    except ExpressionError as exc:
      raise DerivedParameterPlanningError(
        "invalid_derived_expression",
        f"invalid expression for derived parameter {spec.id!r}: {exc}",
        parameter_id=spec.id,
      ) from exc
    all_references = tuple(dict.fromkeys(
      (*spec.input_parameters, *expression_references)
    ))
    unknown = tuple(reference for reference in all_references if reference not in known)
    if unknown:
      raise DerivedParameterPlanningError(
        "unknown_derived_input",
        f"derived parameter {spec.id!r} has unknown inputs: {list(unknown)}",
        parameter_id=spec.id,
        references=unknown,
      )
    dependencies[spec.id] = {
      reference for reference in all_references if reference in by_id
    }

  remaining = {key: set(value) for key, value in dependencies.items()}
  ordered_ids: list[str] = []
  while remaining:
    ready = sorted(
      (spec_id for spec_id, deps in remaining.items() if not deps),
      key=display_index.__getitem__,
    )
    if not ready:
      cycle_ids = _find_dependency_cycle(remaining, display_index)
      raise DerivedParameterPlanningError(
        "derived_dependency_cycle",
        f"derived parameter dependency cycle: {list(cycle_ids)}",
        cycle_ids=cycle_ids,
      )
    for spec_id in ready:
      ordered_ids.append(spec_id)
      remaining.pop(spec_id)
    for deps in remaining.values():
      deps.difference_update(ready)

  return DerivedParameterPlan(
    display_order=display_order,
    execution_order=tuple(by_id[spec_id] for spec_id in ordered_ids),
    dependencies=tuple(
      (
        spec.id,
        tuple(sorted(dependencies[spec.id], key=display_index.__getitem__)),
      )
      for spec in display_order
    ),
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
