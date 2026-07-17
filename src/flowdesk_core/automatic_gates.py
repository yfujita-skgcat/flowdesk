"""Deterministic full-data fitting for the Flowdesk automatic gate template."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.models import AutoGateFitResult, AutoGateTemplateSpec, GateSpec

AUTO_GATE_ALGORITHM_VERSION = "quantile_rectangle.v1"


class AutoGateFitError(ValueError):
  """Raised for invalid template configuration before fitting begins."""


def _input_hash(
  values: NDArray[np.float64],
  channel_names: tuple[str, ...],
) -> str:
  digest = hashlib.sha256()
  digest.update(json.dumps(channel_names, separators=(",", ":")).encode("utf-8"))
  digest.update(np.ascontiguousarray(values, dtype=np.float64).tobytes())
  return digest.hexdigest()


def fit_auto_gate(
  template: AutoGateTemplateSpec,
  data: NDArray[np.float64],
  channel_names: list[str] | tuple[str, ...],
  sample_id: str,
  *,
  population_mask: NDArray[np.bool_] | None = None,
) -> AutoGateFitResult:
  """Fit a quantile rectangle from the complete selected Population.

  This is explicitly a Flowdesk ``quantile_rectangle`` algorithm, not a claim
  of FlowJo Auto Gate compatibility. Display downsampling is never accepted as
  an input; callers pass the full event matrix and optional full-length parent
  membership mask.
  """
  if template.algorithm_version != AUTO_GATE_ALGORITHM_VERSION:
    raise AutoGateFitError(
      f"unsupported automatic gate algorithm version: {template.algorithm_version!r}"
    )
  if data.ndim != 2 or data.shape[1] != len(channel_names):
    raise AutoGateFitError("automatic gate data columns must match channel names")
  names = tuple(channel_names)
  try:
    x_index = names.index(template.x_parameter)
    y_index = names.index(template.y_parameter)
  except ValueError as exc:
    raise AutoGateFitError(f"automatic gate parameter is missing: {exc}") from exc
  if population_mask is not None:
    mask = np.asarray(population_mask, dtype=np.bool_)
    if mask.ndim != 1 or len(mask) != len(data):
      raise AutoGateFitError("automatic gate population mask must match event count")
    selected = data[mask]
  else:
    selected = data
  input_hash = _input_hash(
    selected[:, (x_index, y_index)],
    (template.x_parameter, template.y_parameter),
  )
  params = template.parameters
  q_low = _finite_parameter(params, "q_low", 0.01)
  q_high = _finite_parameter(params, "q_high", 0.99)
  minimum_events = _integer_parameter(params, "minimum_events", 20)
  if not 0.0 <= q_low < q_high <= 1.0:
    raise AutoGateFitError(
      "quantiles must satisfy 0 <= q_low < q_high <= 1"
    )
  finite = np.isfinite(selected[:, x_index]) & np.isfinite(selected[:, y_index])
  usable = selected[finite]
  diagnostics: list[dict[str, Any]] = [{
    "code": "auto_input_summary",
    "severity": "info",
    "event_count": int(len(selected)),
    "finite_event_count": int(len(usable)),
    "excluded_nonfinite_count": int(len(selected) - len(usable)),
    "q_low": q_low,
    "q_high": q_high,
  }]
  if len(usable) < minimum_events:
    return _failed(
      template, sample_id, input_hash,
      f"insufficient finite events: {len(usable)} < minimum_events {minimum_events}",
      diagnostics,
    )
  x_min, x_max = np.quantile(usable[:, x_index], [q_low, q_high])
  y_min, y_max = np.quantile(usable[:, y_index], [q_low, q_high])
  gate = GateSpec(
    id=f"{template.id}:{sample_id}",
    name=f"{template.name} [{sample_id}]",
    gate_type="rectangle",
    parent_population_id=template.parent_population_id,
    x_parameter=template.x_parameter,
    y_parameter=template.y_parameter,
    thresholds={
      "x_min": float(x_min), "x_max": float(x_max),
      "y_min": float(y_min), "y_max": float(y_max),
    },
  )
  diagnostics.append({
    "code": "auto_fit_complete",
    "severity": "info",
    "algorithm": template.algorithm,
    "algorithm_version": template.algorithm_version,
  })
  return AutoGateFitResult(
    template_id=template.id,
    sample_id=sample_id,
    input_hash=input_hash,
    algorithm_version=template.algorithm_version,
    status="success",
    gate=gate,
    diagnostics=tuple(diagnostics),
  )


def _failed(
  template: AutoGateTemplateSpec,
  sample_id: str,
  input_hash: str,
  reason: str,
  diagnostics: list[dict[str, Any]] | None = None,
) -> AutoGateFitResult:
  values = list(diagnostics or [])
  values.append({"code": "auto_fit_failed", "severity": "error", "reason": reason})
  return AutoGateFitResult(
    template_id=template.id,
    sample_id=sample_id,
    input_hash=input_hash,
    algorithm_version=template.algorithm_version,
    status="failed",
    diagnostics=tuple(values),
    failure_reason=reason,
  )


def _finite_parameter(parameters: Mapping[str, Any], key: str, default: float) -> float:
  value = parameters.get(key, default)
  try:
    value = float(value)
  except (TypeError, ValueError) as exc:
    raise AutoGateFitError(f"automatic gate parameter {key!r} must be finite") from exc
  if not np.isfinite(value):
    raise AutoGateFitError(f"automatic gate parameter {key!r} must be finite")
  return value


def _integer_parameter(parameters: Mapping[str, Any], key: str, default: int) -> int:
  value = parameters.get(key, default)
  if isinstance(value, bool):
    raise AutoGateFitError(f"automatic gate parameter {key!r} must be an integer")
  try:
    integer = int(value)
  except (TypeError, ValueError) as exc:
    raise AutoGateFitError(f"automatic gate parameter {key!r} must be an integer") from exc
  if integer < 1:
    raise AutoGateFitError(f"automatic gate parameter {key!r} must be positive")
  return integer
