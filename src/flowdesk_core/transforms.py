"""Transform functions for linear, log, asinh, and logicle-like views.

Transforms are analysis definitions, not merely GUI display settings.
All parameters needed to reproduce a transform are stored in the spec.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import TransformSpec


class TransformError(FlowdeskError):
  """Raised when a transform definition or application is invalid."""


# ---------------------------------------------------------------------------
# Invalid-value policies for log transforms
# ---------------------------------------------------------------------------

_INVALID_VALUE_POLICIES = frozenset({"to_nan", "to_zero", "clip_to_one"})


# ---------------------------------------------------------------------------
# Individual transform implementations
# ---------------------------------------------------------------------------


def _apply_linear(
  values: NDArray[np.float64],
  settings: dict[str, float],
) -> NDArray[np.float64]:
  """Linear transform: y = x * scale + offset."""
  scale = float(settings.get("scale", 1.0))
  offset = float(settings.get("offset", 0.0))
  return values * scale + offset


def _apply_log(
  values: NDArray[np.float64],
  settings: dict[str, float],
) -> NDArray[np.float64]:
  """Log transform with configurable base and invalid-value policy.

  Policy controls how non-positive values are handled:
    - "to_nan" (default): replace with NaN
    - "to_zero": replace with 0.0
    - "clip_to_one": clip non-positive values to 1.0 before taking log
  """
  base = float(settings.get("base", 10.0))
  policy = settings.get("invalid_value_policy", "to_nan")

  if policy not in _INVALID_VALUE_POLICIES:
    raise TransformError(
      f"unknown invalid_value_policy: {policy!r}. "
      f"Must be one of {sorted(_INVALID_VALUE_POLICIES)}"
    )

  if base <= 0 or base == 1.0:
    raise TransformError(
      f"log base must be positive and != 1, got {base}"
    )

  result = np.empty_like(values)

  if policy == "clip_to_one":
    clipped = np.maximum(values, 1.0)
    result = np.log(clipped) / np.log(base)
  else:
    mask = values > 0
    result[mask] = np.log(values[mask]) / np.log(base)

    if policy == "to_zero":
      result[~mask] = 0.0
    else:
      # to_nan (default)
      result[~mask] = np.nan

  return result


def _apply_asinh(
  values: NDArray[np.float64],
  settings: dict[str, float],
) -> NDArray[np.float64]:
  """Arcsinh transform: y = asinh(x / cofactor) * cofactor.

  The cofactor controls the dynamic range. Default is 1.0 (pure asinh).
  Typical flow-cytometry cofactors are 0.001-0.5.
  """
  cofactor = float(settings.get("cofactor", 1.0))

  if cofactor <= 0:
    raise TransformError(
      f"asinh cofactor must be positive, got {cofactor}"
    )

  return np.arcsinh(values / cofactor) * cofactor


def _apply_logicle_like(
  values: NDArray[np.float64],
  settings: dict[str, float],
) -> NDArray[np.float64]:
  """Approximate logicle transform.

  This is a simplified approximation of the logicle transform described by
  Clark et al. (2008). It blends log-like behavior for positive values with
  linear behavior near zero, allowing negative values.

  Parameters (all optional, with defaults):
    - ``w``: width of the linear region (default 0.25)
    - ``td``: top display value (default 1000000)
    - ``tn``: top negative value (default 10000)
  """
  w = float(settings.get("w", 0.25))
  td = float(settings.get("td", 1e6))
  tn = float(settings.get("tn", 1e4))

  if w < 0 or w >= 1:
    raise TransformError(f"logicle w must be in [0, 1), got {w}")

  if td <= 0:
    raise TransformError(f"logicle td must be positive, got {td}")

  if tn <= 0:
    raise TransformError(f"logicle tn must be positive, got {tn}")

  # Simplified logicle: scale to [0, 1], apply transformation, rescale.
  log_td = math.log10(td) if td > 0 else 0.0

  result = np.empty_like(values)

  pos_mask = values >= 0
  neg_mask = ~pos_mask

  # Positive region: log-like scaling
  pos_vals = values[pos_mask]
  log_pos = np.log10(np.maximum(pos_vals, 1e-300))
  result[pos_mask] = (
    (1.0 - w) * pos_vals / td + w * log_pos / (log_td if log_td != 0 else 1)
  ) * td

  # Negative region: linear scaling
  result[neg_mask] = values[neg_mask] * tn / td

  return result


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TransformFn = Callable[
  [NDArray[np.float64], dict[str, float]],
  NDArray[np.float64],
]

_TRANSFORM_REGISTRY: dict[str, TransformFn] = {
  "linear": _apply_linear,
  "log": _apply_log,
  "asinh": _apply_asinh,
  "logicle_like": _apply_logicle_like,
}


def apply_transform(
  spec: TransformSpec,
  values: NDArray[np.float64],
) -> NDArray[np.float64]:
  """Apply a transform defined by ``spec`` to ``values``.

  Args:
    spec: Transform definition (type, parameter, settings).
    values: 1-D array of numeric values to transform.

  Returns:
    A new array of the same shape with the transform applied.

  Raises:
    TransformError: If the transform type is unknown or settings are invalid.
  """

  if spec.transform_type not in _TRANSFORM_REGISTRY:
    raise TransformError(
      f"unknown transform type: {spec.transform_type!r}. "
      f"Supported: {sorted(_TRANSFORM_REGISTRY.keys())}"
    )

  func = _TRANSFORM_REGISTRY[spec.transform_type]
  return func(values, spec.settings)


def apply_transform_to_column(
  spec: TransformSpec,
  data: NDArray[np.float64],
  channel_names: list[str],
) -> NDArray[np.float64]:
  """Apply a transform to a single column of a 2-D event array.

  Only the column matching ``spec.parameter`` is transformed; all other
  columns are copied unchanged.

  Args:
    spec: Transform definition.
    data: 2-D array of shape ``(n_events, n_channels)``.
    channel_names: Column names aligned with ``data`` columns.

  Returns:
    A new array with the target column transformed.

  Raises:
    TransformError: If the target parameter is not found in ``channel_names``.
  """

  if spec.parameter not in channel_names:
    raise TransformError(
      f"parameter {spec.parameter!r} not found in channel names: "
      f"{channel_names}"
    )

  result = data.copy()
  col_idx = channel_names.index(spec.parameter)
  result[:, col_idx] = apply_transform(spec, result[:, col_idx])
  return result
