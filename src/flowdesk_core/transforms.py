"""Transform functions for linear, log, asinh, and Logicle views.

Transforms are analysis definitions, not merely GUI display settings.
All parameters needed to reproduce a transform are stored in the spec.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import TransformSpec


class TransformError(FlowdeskError):
  """Raised when a transform definition or application is invalid."""

  def __init__(self, code: str, message: str) -> None:
    self.code = code
    super().__init__(message)


@dataclass(frozen=True)
class TransformTick:
  """One axis tick derived from a versioned transform definition."""

  coordinate: float
  event_value: float
  label: str
  level: Literal["major", "minor"] = "major"


LOGICLE_IMPLEMENTATION_VERSION = "logicle-gml2-moore-parks-2012-v1"
_LOGICLE_MAX_ITERATIONS = 20
_LOGICLE_TAYLOR_LENGTH = 16


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


@dataclass(frozen=True)
class _LogicleParameters:
  """Precomputed Moore-Parks Logicle coefficients."""

  a: float
  b: float
  c: float
  d: float
  f: float
  w: float
  x1: float
  x_taylor: float
  taylor: tuple[float, ...]


def _required_finite_setting(
  settings: Mapping[str, Any],
  name: str,
) -> float:
  if name not in settings:
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle setting {name!r} is required",
    )
  try:
    value = float(settings[name])
  except (TypeError, ValueError) as exc:
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle setting {name!r} must be numeric",
    ) from exc
  if not math.isfinite(value):
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle setting {name!r} must be finite, got {value}",
    )
  return value


def _validate_logicle(
  settings: Mapping[str, Any],
) -> dict[str, Any]:
  normalized = {
    name: _required_finite_setting(settings, name)
    for name in ("T", "W", "M", "A")
  }
  version = settings.get("implementation_version")
  if version != LOGICLE_IMPLEMENTATION_VERSION:
    raise TransformError(
      "invalid_transform_settings",
      "Logicle implementation_version must be "
      f"{LOGICLE_IMPLEMENTATION_VERSION!r}, got {version!r}",
    )

  top = normalized["T"]
  width = normalized["W"]
  decades = normalized["M"]
  additional = normalized["A"]
  if top <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle T must be positive, got {top}",
    )
  if decades <= 0:
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle M must be positive, got {decades}",
    )
  if width < 0 or 2 * width > decades:
    raise TransformError(
      "invalid_transform_settings",
      f"Logicle W must satisfy 0 <= W <= M/2, got W={width}, M={decades}",
    )
  if additional < -width or additional > decades - 2 * width:
    raise TransformError(
      "invalid_transform_settings",
      "Logicle A must satisfy -W <= A <= M - 2W, got "
      f"A={additional}, W={width}, M={decades}",
    )
  normalized["implementation_version"] = version
  return normalized


def _solve_logicle_d(b: float, w: float) -> float:
  """Solve the Moore-Parks coefficient equation by bounded bisection."""
  if w == 0:
    return b
  lower = 0.0
  upper = b
  for _ in range(128):
    midpoint = (lower + upper) / 2
    if midpoint == lower or midpoint == upper:
      return midpoint
    value = 2 * (math.log(midpoint) - math.log(b)) + w * (b + midpoint)
    if value > 0:
      upper = midpoint
    else:
      lower = midpoint
  return (lower + upper) / 2


def _make_logicle_parameters(
  settings: Mapping[str, Any],
) -> _LogicleParameters:
  top = float(settings["T"])
  width = float(settings["W"])
  decades = float(settings["M"])
  additional = float(settings["A"])

  denominator = decades + additional
  w = width / denominator
  x2 = additional / denominator
  x1 = x2 + w
  x0 = x2 + 2 * w
  b = denominator * math.log(10)
  d = _solve_logicle_d(b, w)

  c_over_a = math.exp(x0 * (b + d))
  f_over_a = math.exp(b * x1) - c_over_a / math.exp(d * x1)
  a = top / (
    math.exp(b) - f_over_a - c_over_a / math.exp(d)
  )
  c = c_over_a * a
  f = -f_over_a * a

  positive = a * math.exp(b * x1)
  negative = -c / math.exp(d * x1)
  taylor: list[float] = []
  for index in range(_LOGICLE_TAYLOR_LENGTH):
    positive *= b / (index + 1)
    negative *= -d / (index + 1)
    taylor.append(positive + negative)
  taylor[1] = 0.0

  return _LogicleParameters(
    a=a,
    b=b,
    c=c,
    d=d,
    f=f,
    w=w,
    x1=x1,
    x_taylor=x1 + w / 4,
    taylor=tuple(taylor),
  )


def _logicle_series(scale: float, params: _LogicleParameters) -> float:
  delta = scale - params.x1
  total = params.taylor[-1] * delta
  for coefficient in reversed(params.taylor[2:-1]):
    total = (total + coefficient) * delta
  return (total * delta + params.taylor[0]) * delta


def _logicle_forward_value(value: float, params: _LogicleParameters) -> float:
  if value == 0:
    return params.x1
  if value < 0:
    return 2 * params.x1 - _logicle_forward_value(-value, params)

  if value < params.f:
    scale = params.x1 + value / params.taylor[0]
  else:
    scale = math.log(value / params.a) / params.b
  tolerance = 3 * np.finfo(np.float64).eps
  if scale > 1:
    tolerance *= scale

  for _ in range(_LOGICLE_MAX_ITERATIONS):
    try:
      positive = params.a * math.exp(params.b * scale)
      negative = params.c / math.exp(params.d * scale)
    except OverflowError as exc:
      raise TransformError(
        "transform_non_convergence",
        f"Logicle solver overflowed for event value {value}",
      ) from exc
    if scale < params.x_taylor:
      residual = _logicle_series(scale, params) - value
    else:
      residual = (positive + params.f) - (negative + value)
    derivative = params.b * positive + params.d * negative
    second_derivative = (
      params.b * params.b * positive
      - params.d * params.d * negative
    )
    if derivative == 0:
      break
    correction = 1 - residual * second_derivative / (
      2 * derivative * derivative
    )
    if correction == 0 or not math.isfinite(correction):
      break
    delta = residual / (derivative * correction)
    scale -= delta
    if abs(delta) < tolerance:
      return scale

  raise TransformError(
    "transform_non_convergence",
    f"Logicle solver did not converge for event value {value}",
  )


def _apply_logicle(
  values: NDArray[np.float64],
  settings: Mapping[str, Any],
) -> NDArray[np.float64]:
  if not np.all(np.isfinite(values)):
    raise TransformError(
      "transform_domain_error",
      "Logicle forward input must contain only finite event values",
    )
  params = _make_logicle_parameters(settings)
  result = np.empty_like(values, dtype=np.float64)
  for index in np.ndindex(values.shape):
    result[index] = _logicle_forward_value(float(values[index]), params)
  return result


def _inverse_logicle(
  values: NDArray[np.float64],
  settings: Mapping[str, Any],
) -> NDArray[np.float64]:
  if not np.all(np.isfinite(values)):
    raise TransformError(
      "transform_domain_error",
      "Logicle inverse input must contain only finite coordinates",
    )
  params = _make_logicle_parameters(settings)
  result = np.empty_like(values, dtype=np.float64)
  for index in np.ndindex(values.shape):
    scale = float(values[index])
    negative = scale < params.x1
    if negative:
      scale = 2 * params.x1 - scale
    try:
      if scale < params.x_taylor:
        value = _logicle_series(scale, params)
      else:
        value = (
          params.a * math.exp(params.b * scale)
          + params.f
          - params.c / math.exp(params.d * scale)
        )
    except OverflowError as exc:
      raise TransformError(
        "transform_domain_error",
        f"Logicle inverse coordinate is outside the finite numeric range: {scale}",
      ) from exc
    result[index] = -value if negative else value
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
  "logicle": _RegisteredTransform(
    _validate_logicle, _apply_logicle, _inverse_logicle
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


def generate_transform_ticks(
  spec: TransformSpec,
  minimum_coordinate: float,
  maximum_coordinate: float,
  policy: Literal["decades", "one_two_five", "auto"] = "decades",
) -> tuple[TransformTick, ...]:
  """Generate signed-decade ticks using the same forward/inverse transform.

  Coordinate limits are inverse-mapped to event space. Candidate event values
  are then forward-mapped with ``spec``; no independent display approximation
  is used.
  """
  if not math.isfinite(minimum_coordinate) or not math.isfinite(maximum_coordinate):
    raise TransformError(
      "transform_domain_error",
      "transform tick coordinate limits must be finite",
    )
  low_coordinate = min(minimum_coordinate, maximum_coordinate)
  high_coordinate = max(minimum_coordinate, maximum_coordinate)
  event_bounds = inverse_transform(
    spec,
    np.array([low_coordinate, high_coordinate], dtype=np.float64),
  )
  low_event = float(min(event_bounds))
  high_event = float(max(event_bounds))
  if policy not in {"decades", "one_two_five", "auto"}:
    raise ValueError(f"unsupported transform tick policy: {policy!r}")
  candidates: dict[float, Literal["major", "minor"]] = {}
  if low_event <= 0 <= high_event:
    candidates[0.0] = "major"

  maximum_magnitude = max(abs(low_event), abs(high_event))
  if maximum_magnitude > 0 and math.isfinite(maximum_magnitude):
    maximum_exponent = min(308, math.ceil(math.log10(maximum_magnitude)))
    minimum_nonzero = min(
      (abs(value) for value in (low_event, high_event) if value != 0),
      default=1.0,
    )
    minimum_exponent = max(-15, math.floor(math.log10(minimum_nonzero)))
    minimum_exponent = min(minimum_exponent, 0)
    use_one_two_five = policy == "one_two_five"
    if policy == "auto":
      positive_low = max(low_event, 1e-300)
      positive_high = max(high_event, positive_low)
      use_one_two_five = math.log10(positive_high / positive_low) < 2.0
    for exponent in range(minimum_exponent, maximum_exponent + 1):
      for multiplier in ((1.0, 2.0, 5.0) if use_one_two_five else (1.0,)):
        magnitude = multiplier * (10.0 ** exponent)
        level: Literal["major", "minor"] = (
          "major" if multiplier == 1.0 or use_one_two_five else "minor"
        )
        if low_event <= magnitude <= high_event:
          candidates[magnitude] = level
        if low_event <= -magnitude <= high_event:
          candidates[-magnitude] = level
      if policy == "auto":
        for multiplier in range(2, 10):
          magnitude = multiplier * (10.0 ** exponent)
          if low_event <= magnitude <= high_event:
            candidates.setdefault(magnitude, "minor")
          if low_event <= -magnitude <= high_event:
            candidates.setdefault(-magnitude, "minor")

  if spec.transform_type == "logicle":
    top = float(spec.settings["T"])
    if low_event <= top <= high_event:
      candidates[top] = "major"

  if not candidates:
    return ()
  event_values = np.array(sorted(candidates), dtype=np.float64)
  coordinates = apply_transform(spec, event_values)
  ticks: list[TransformTick] = []
  for event_value, coordinate in zip(event_values, coordinates, strict=True):
    coordinate_value = float(coordinate)
    event_value_float = float(event_value)
    if not math.isfinite(coordinate_value):
      continue
    if coordinate_value < low_coordinate or coordinate_value > high_coordinate:
      continue
    if ticks and math.isclose(
      coordinate_value,
      ticks[-1].coordinate,
      rel_tol=0.0,
      abs_tol=8 * np.finfo(np.float64).eps,
    ):
      continue
    ticks.append(TransformTick(
      coordinate=coordinate_value,
      event_value=event_value_float,
      label=_format_tick_label(event_value_float),
      level=candidates[event_value_float],
    ))
  ticks.sort(key=lambda tick: tick.coordinate)
  return tuple(ticks)


def _format_tick_label(value: float) -> str:
  if value == 0:
    return "0"
  magnitude = abs(value)
  exponent = round(math.log10(magnitude))
  if math.isclose(magnitude, 10.0 ** exponent, rel_tol=1e-12):
    sign = "-" if value < 0 else ""
    return f"{sign}1e{exponent}"
  return f"{value:g}"


def generate_log_ticks(
  minimum_event: float,
  maximum_event: float,
  policy: Literal["decades", "one_two_five", "auto"] = "auto",
) -> tuple[TransformTick, ...]:
  """Generate display ticks for a native base-10 log axis.

  ``coordinate`` is log10(event value), matching pyqtgraph's native log mode.
  Major labels use decade values by default; short ranges use a 1-2-5 set and
  retain 2-9 multiples as unlabeled minor ticks.
  """
  low = min(float(minimum_event), float(maximum_event))
  high = max(float(minimum_event), float(maximum_event))
  if not math.isfinite(low) or not math.isfinite(high) or high <= 0:
    return ()
  low = max(low, np.finfo(np.float64).tiny)
  return tuple(
    tick for tick in _generate_positive_log_ticks(low, high, policy)
    if math.isfinite(tick.coordinate)
  )


def _generate_positive_log_ticks(
  low: float,
  high: float,
  policy: Literal["decades", "one_two_five", "auto"],
) -> tuple[TransformTick, ...]:
  if policy not in {"decades", "one_two_five", "auto"}:
    raise ValueError(f"unsupported log tick policy: {policy!r}")
  use_one_two_five = policy == "one_two_five"
  if policy == "auto":
    use_one_two_five = math.log10(high / low) < 2.0
  first = max(-308, math.floor(math.log10(low)))
  last = min(308, math.ceil(math.log10(high)))
  ticks: list[TransformTick] = []
  for exponent in range(first, last + 1):
    for multiplier in ((1.0, 2.0, 5.0) if use_one_two_five else (1.0,)):
      value = multiplier * (10.0 ** exponent)
      if low <= value <= high:
        ticks.append(TransformTick(
          coordinate=math.log10(value),
          event_value=value,
          label=_format_tick_label(value),
          level="major",
        ))
    if policy == "auto":
      for multiplier in range(2, 10):
        if use_one_two_five and multiplier in {2, 5}:
          continue
        value = multiplier * (10.0 ** exponent)
        if low <= value <= high:
          ticks.append(TransformTick(
            coordinate=math.log10(value),
            event_value=value,
            label=_format_tick_label(value),
            level="minor",
          ))
  return tuple(sorted(ticks, key=lambda tick: tick.coordinate))


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
