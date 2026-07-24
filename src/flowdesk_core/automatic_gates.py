"""Deterministic full-data fitting for the Flowdesk automatic gate template."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.models import AutoGateFitResult, AutoGateTemplateSpec, GateSpec

AUTO_GATE_ALGORITHM_VERSION = "quantile_rectangle.v1"


class AutoGateFitError(ValueError):
  """Raised for invalid template configuration before fitting begins."""


def auto_gate_template_from_mapping(value: Mapping[str, Any]) -> AutoGateTemplateSpec:
  """Parse a persisted automatic gate template through the typed contract."""
  try:
    return AutoGateTemplateSpec(
      id=str(value["id"]),
      name=str(value.get("name", value["id"])),
      algorithm=value["algorithm"],
      x_parameter=str(value["x_parameter"]),
      y_parameter=str(value["y_parameter"]),
      parent_population_id=str(value.get("parent_population_id", "all_events")),
      parameters=dict(value.get("parameters", {})),
      algorithm_version=str(value.get("algorithm_version", AUTO_GATE_ALGORITHM_VERSION)),
      manual_override_policy=value.get("manual_override_policy", "preserve_until_reset"),
      notes=str(value.get("notes", "")),
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise AutoGateFitError(f"invalid automatic gate template: {exc}") from exc


def auto_gate_fit_to_mapping(result: AutoGateFitResult) -> dict[str, Any]:
  """Serialize a fitted result including its optional gate geometry."""
  return asdict(result)


def auto_gate_fit_from_mapping(value: Mapping[str, Any]) -> AutoGateFitResult:
  """Parse a persisted fitted result without evaluating it."""
  gate_value = value.get("gate")
  gate = None
  if isinstance(gate_value, Mapping):
    gate = GateSpec(
      id=str(gate_value["id"]),
      name=str(gate_value.get("name", gate_value["id"])),
      gate_type=gate_value["gate_type"],
      parent_population_id=gate_value.get("parent_population_id"),
      x_parameter=gate_value.get("x_parameter"),
      y_parameter=gate_value.get("y_parameter"),
      x_transform_id=gate_value.get("x_transform_id"),
      y_transform_id=gate_value.get("y_transform_id"),
      compensation_id=gate_value.get("compensation_id"),
      coordinates=tuple(tuple(point) for point in gate_value.get("coordinates", ())),
      thresholds=dict(gate_value.get("thresholds", {})),
      notes=str(gate_value.get("notes", "")),
    )
  return AutoGateFitResult(
    template_id=str(value["template_id"]),
    sample_id=str(value["sample_id"]),
    input_hash=str(value["input_hash"]),
    algorithm_version=str(value["algorithm_version"]),
    status=value["status"],
    gate=gate,
    diagnostics=tuple(dict(item) for item in value.get("diagnostics", ())),
    failure_reason=value.get("failure_reason"),
    manual_override=bool(value.get("manual_override", False)),
  )


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
