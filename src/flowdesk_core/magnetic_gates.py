"""Deterministic full-data fitting for magnetic-bead range gates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.models import GateSpec, MagneticGateFitResult, MagneticGateTemplateSpec

MAGNETIC_GATE_ALGORITHM_VERSION = "largest_gap_range.v1"


class MagneticGateFitError(ValueError):
  """Raised for invalid magnetic-gate configuration."""


def magnetic_gate_template_from_mapping(
  value: Mapping[str, Any],
) -> MagneticGateTemplateSpec:
  try:
    return MagneticGateTemplateSpec(
      id=str(value["id"]), name=str(value.get("name", value["id"])),
      algorithm=value["algorithm"], parameter=str(value["parameter"]),
      parent_population_id=str(value.get("parent_population_id", "all_events")),
      parameters=dict(value.get("parameters", {})),
      algorithm_version=str(value.get("algorithm_version", MAGNETIC_GATE_ALGORITHM_VERSION)),
      manual_override_policy=value.get("manual_override_policy", "preserve_until_reset"),
      notes=str(value.get("notes", "")),
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise MagneticGateFitError(f"invalid magnetic gate template: {exc}") from exc


def magnetic_gate_fit_to_mapping(result: MagneticGateFitResult) -> dict[str, Any]:
  return asdict(result)


def fit_magnetic_gate(
  template: MagneticGateTemplateSpec,
  data: NDArray[np.float64],
  channel_names: list[str] | tuple[str, ...],
  sample_id: str,
  *,
  population_mask: NDArray[np.bool_] | None = None,
) -> MagneticGateFitResult:
  """Fit the upper cluster after the largest adjacent finite-value gap.

  This is a Flowdesk-defined magnetic-bead heuristic, not a claim of vendor
  compatibility. The complete selected Population is used; display sampling is
  not accepted as an input.
  """
  if template.algorithm_version != MAGNETIC_GATE_ALGORITHM_VERSION:
    raise MagneticGateFitError(
      f"unsupported magnetic gate algorithm version: {template.algorithm_version!r}"
    )
  if data.ndim != 2 or data.shape[1] != len(channel_names):
    raise MagneticGateFitError("magnetic gate data columns must match channel names")
  try:
    index = tuple(channel_names).index(template.parameter)
  except ValueError as exc:
    raise MagneticGateFitError(f"magnetic gate parameter is missing: {exc}") from exc
  selected = data
  if population_mask is not None:
    mask = np.asarray(population_mask, dtype=np.bool_)
    if mask.ndim != 1 or len(mask) != len(data):
      raise MagneticGateFitError("magnetic gate population mask must match event count")
    selected = data[mask]
  values = selected[:, index]
  finite = values[np.isfinite(values)]
  input_hash = hashlib.sha256(np.ascontiguousarray(finite, dtype=np.float64).tobytes()).hexdigest()
  minimum_events = int(template.parameters.get("minimum_events", 20))
  if minimum_events < 2:
    raise MagneticGateFitError("minimum_events must be at least 2")
  diagnostics: list[dict[str, Any]] = [{
    "code": "magnetic_input_summary", "severity": "info",
    "event_count": int(len(selected)), "finite_event_count": int(len(finite)),
    "excluded_nonfinite_count": int(len(values) - len(finite)),
  }]
  if len(finite) < minimum_events:
    reason = f"insufficient finite events: {len(finite)} < minimum_events {minimum_events}"
    return _failed(template, sample_id, input_hash, reason, diagnostics)
  ordered = np.sort(finite)
  gaps = np.diff(ordered)
  gap_index = int(np.argmax(gaps))
  threshold = float((ordered[gap_index] + ordered[gap_index + 1]) / 2.0)
  diagnostics.append({
    "code": "magnetic_fit_complete", "severity": "info",
    "algorithm": template.algorithm, "algorithm_version": template.algorithm_version,
    "largest_gap": float(gaps[gap_index]), "threshold": threshold,
    "positive_event_count": int(np.count_nonzero(finite >= threshold)),
  })
  gate = GateSpec(
    id=f"{template.id}:{sample_id}", name=f"{template.name} [{sample_id}]",
    gate_type="range", parent_population_id=template.parent_population_id,
    x_parameter=template.parameter, thresholds={"min": threshold},
  )
  return MagneticGateFitResult(
    template_id=template.id, sample_id=sample_id, input_hash=input_hash,
    algorithm_version=template.algorithm_version, status="success", gate=gate,
    diagnostics=tuple(diagnostics),
  )


def _failed(
  template: MagneticGateTemplateSpec, sample_id: str, input_hash: str,
  reason: str, diagnostics: list[dict[str, Any]],
) -> MagneticGateFitResult:
  diagnostics.append({"code": "magnetic_fit_failed", "severity": "error", "reason": reason})
  return MagneticGateFitResult(
    template_id=template.id, sample_id=sample_id, input_hash=input_hash,
    algorithm_version=template.algorithm_version, status="failed",
    diagnostics=tuple(diagnostics), failure_reason=reason,
  )
