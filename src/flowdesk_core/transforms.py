"""Transform functions for linear, log, asinh, and logicle-like views.

Transforms are analysis definitions, not merely GUI display settings.
All parameters needed to reproduce a transform are stored in the spec.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import TransformSpec


class TransformError(FlowdeskError):
  """Raised when a transform definition or application is invalid."""

  def __init__(self, code: str, message: str) -> None:
    self.code = code
    super().__init__(message)


# ---------------------------------------------------------------------------
# Invalid-value policies for log transforms
# ---------------------------------------------------------------------------

_INVALID_VALUE_POLICIES = frozenset({"to_nan", "to_zero", "clip_to_one"})


# ---------------------------------------------------------------------------
# Individual transform implementations
# ---------------------------------------------------------------------------


def _apply_linear(
  values: NDArray[np.float64],
  settings: Mapping[str, Any],
) -> NDArray[np.float64]:
  """Linear transform: y = x * scale + offset."""
  scale = float(settings.get("scale", 1.0))
  offset = float(settings.get("offset", 0.0))
  return values * scale + offset


def _apply_log(
  values: NDArray[np.float64],
  settings: Mapping[str, Any],
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
      "invalid_transform_settings",
      f"unknown invalid_value_policy: {policy!r}. "
      f"Must be one of {sorted(_INVALID_VALUE_POLICIES)}"
    )

  if base <= 0 or base == 1.0:
    raise TransformError(
      "invalid_transform_settings",
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
  settings: Mapping[str, Any],
) -> NDArray[np.float64]:
  """Arcsinh transform: y = asinh(x / cofactor) * cofactor.

  The cofactor controls the dynamic range. Default is 1.0 (pure asinh).
  Typical flow-cytometry cofactors are 0.001-0.5.
  """
  cofactor = float(settings.get("cofactor", 1.0))

  if cofactor <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"asinh cofactor must be positive, got {cofactor}"
    )

  return np.arcsinh(values / cofactor) * cofactor


def _apply_legacy_logicle_approximation(
  values: NDArray[np.float64],
  settings: Mapping[str, Any],
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
    raise TransformError(
      "invalid_transform_settings",
      f"logicle w must be in [0, 1), got {w}",
    )

  if td <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"logicle td must be positive, got {td}",
    )

  if tn <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"logicle tn must be positive, got {tn}",
    )

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

TransformSettings = Mapping[str, Any]
NormalizedTransformSettings = dict[str, Any]
TransformFn = Callable[
  [NDArray[np.float64], TransformSettings],
  NDArray[np.float64],
]
SettingsValidator = Callable[
  [TransformSettings],
  NormalizedTransformSettings,
]


class TransformImplementation(Protocol):
  """Typed numeric contract shared by analysis transform implementations."""

  def validate_settings(
    self,
    settings: TransformSettings,
  ) -> NormalizedTransformSettings:
    """Validate and return complete settings without mutating the input."""

  def forward(
    self,
    values: NDArray[np.float64],
    settings: TransformSettings,
  ) -> NDArray[np.float64]:
    """Map event values into transform coordinates."""

  def inverse(
    self,
    values: NDArray[np.float64],
    settings: TransformSettings,
  ) -> NDArray[np.float64]:
    """Map transform coordinates back into event-value coordinates."""


@dataclass(frozen=True)
class _RegisteredTransform:
  validator: SettingsValidator
  forward_fn: TransformFn
  inverse_fn: TransformFn | None

  def validate_settings(
    self,
    settings: TransformSettings,
  ) -> NormalizedTransformSettings:
    return self.validator(settings)

  def forward(
    self,
    values: NDArray[np.float64],
    settings: TransformSettings,
  ) -> NDArray[np.float64]:
    return self.forward_fn(values, settings)

  def inverse(
    self,
    values: NDArray[np.float64],
    settings: TransformSettings,
  ) -> NDArray[np.float64]:
    if self.inverse_fn is None:
      raise TransformError(
        "transform_inverse_unavailable",
        "transform has no scientifically defined inverse",
      )
    return self.inverse_fn(values, settings)


def _finite_setting(
  settings: TransformSettings,
  name: str,
  default: float,
) -> float:
  try:
    value = float(settings.get(name, default))
  except (TypeError, ValueError) as exc:
    raise TransformError(
      "invalid_transform_settings",
      f"transform setting {name!r} must be numeric",
    ) from exc
  if not math.isfinite(value):
    raise TransformError(
      "invalid_transform_settings",
      f"transform setting {name!r} must be finite, got {value}",
    )
  return value


def _validate_linear(settings: TransformSettings) -> NormalizedTransformSettings:
  scale = _finite_setting(settings, "scale", 1.0)
  offset = _finite_setting(settings, "offset", 0.0)
  if scale == 0:
    raise TransformError(
      "invalid_transform_settings",
      "linear scale must be non-zero for an invertible transform",
    )
  return {"scale": scale, "offset": offset}


def _validate_log(settings: TransformSettings) -> NormalizedTransformSettings:
  base = _finite_setting(settings, "base", 10.0)
  if base <= 0 or base == 1:
    raise TransformError(
      "invalid_transform_settings",
      f"log base must be positive and != 1, got {base}",
    )
  policy = settings.get("invalid_value_policy", "to_nan")
  if policy not in _INVALID_VALUE_POLICIES:
    raise TransformError(
      "invalid_transform_settings",
      f"unknown invalid_value_policy: {policy!r}. "
      f"Must be one of {sorted(_INVALID_VALUE_POLICIES)}",
    )
  return {"base": base, "invalid_value_policy": policy}


def _validate_asinh(settings: TransformSettings) -> NormalizedTransformSettings:
  cofactor = _finite_setting(settings, "cofactor", 1.0)
  if cofactor <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"asinh cofactor must be positive, got {cofactor}",
    )
  return {"cofactor": cofactor}


def _validate_legacy_logicle_approximation(
  settings: TransformSettings,
) -> NormalizedTransformSettings:
  normalized = {
    "w": _finite_setting(settings, "w", 0.25),
    "td": _finite_setting(settings, "td", 1e6),
    "tn": _finite_setting(settings, "tn", 1e4),
  }
  w = normalized["w"]
  if w < 0 or w >= 1:
    raise TransformError(
      "invalid_transform_settings",
      f"logicle w must be in [0, 1), got {w}",
    )
  if normalized["td"] <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"logicle td must be positive, got {normalized['td']}",
    )
  if normalized["tn"] <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"logicle tn must be positive, got {normalized['tn']}",
    )
  return normalized


def _inverse_linear(
  values: NDArray[np.float64],
  settings: TransformSettings,
) -> NDArray[np.float64]:
  return (values - float(settings["offset"])) / float(settings["scale"])


def _inverse_log(
  values: NDArray[np.float64],
  settings: TransformSettings,
) -> NDArray[np.float64]:
  return np.power(float(settings["base"]), values)


def _inverse_asinh(
  values: NDArray[np.float64],
  settings: TransformSettings,
) -> NDArray[np.float64]:
  cofactor = float(settings["cofactor"])
  return np.sinh(values / cofactor) * cofactor


_TRANSFORM_REGISTRY: dict[str, TransformImplementation] = {
  "linear": _RegisteredTransform(
    _validate_linear, _apply_linear, _inverse_linear
  ),
  "log": _RegisteredTransform(_validate_log, _apply_log, _inverse_log),
  "asinh": _RegisteredTransform(
    _validate_asinh, _apply_asinh, _inverse_asinh
  ),
  "legacy_logicle_approximation": _RegisteredTransform(
    _validate_legacy_logicle_approximation,
    _apply_legacy_logicle_approximation,
    None,
  ),
}


def _implementation_for(spec: TransformSpec) -> TransformImplementation:
  implementation = _TRANSFORM_REGISTRY.get(spec.transform_type)
  if implementation is None:
    raise TransformError(
      "unknown_transform_type",
      f"unknown transform type: {spec.transform_type!r}. "
      f"Supported: {sorted(_TRANSFORM_REGISTRY.keys())}",
    )
  return implementation


def validate_transform(spec: TransformSpec) -> None:
  """Validate a transform definition without applying it to event data."""
  _implementation_for(spec).validate_settings(spec.settings)


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

  implementation = _implementation_for(spec)
  settings = implementation.validate_settings(spec.settings)
  return implementation.forward(values, settings)


def inverse_transform(
  spec: TransformSpec,
  values: NDArray[np.float64],
) -> NDArray[np.float64]:
  """Apply the inverse of a validated transform definition."""
  implementation = _implementation_for(spec)
  settings = implementation.validate_settings(spec.settings)
  return implementation.inverse(values, settings)


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
      "unknown_transform_parameter",
      f"parameter {spec.parameter!r} not found in channel names: "
      f"{channel_names}"
    )

  result = data.copy()
  col_idx = channel_names.index(spec.parameter)
  result[:, col_idx] = apply_transform(spec, result[:, col_idx])
  return result
