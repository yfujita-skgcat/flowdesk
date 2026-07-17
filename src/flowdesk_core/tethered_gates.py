"""Deterministic geometry propagation for tethered gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from flowdesk_core.models import GateSpec, TetheredGateFitResult, TetheredGateTemplateSpec

TETHERED_GATE_ALGORITHM_VERSION = "translated_rectangle.v1"


class TetheredGateFitError(ValueError):
  """Raised for invalid anchor or tether configuration."""


def tethered_gate_template_from_mapping(value: Mapping[str, Any]) -> TetheredGateTemplateSpec:
  try:
    return TetheredGateTemplateSpec(
      id=str(value["id"]), name=str(value.get("name", value["id"])),
      algorithm=value["algorithm"], anchor_gate_id=str(value["anchor_gate_id"]),
      x_offset=float(value.get("x_offset", 0.0)), y_offset=float(value.get("y_offset", 0.0)),
      parent_population_id=value.get("parent_population_id"),
      algorithm_version=str(value.get("algorithm_version", TETHERED_GATE_ALGORITHM_VERSION)),
      manual_override_policy=value.get("manual_override_policy", "preserve_until_reset"),
      notes=str(value.get("notes", "")),
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise TetheredGateFitError(f"invalid tethered gate template: {exc}") from exc


def tethered_gate_fit_to_mapping(result: TetheredGateFitResult) -> dict[str, Any]:
  return asdict(result)


def fit_tethered_gate(
  template: TetheredGateTemplateSpec,
  anchor: GateSpec | None,
  sample_id: str,
) -> TetheredGateFitResult:
  if template.algorithm_version != TETHERED_GATE_ALGORITHM_VERSION:
    raise TetheredGateFitError(
      f"unsupported tethered algorithm version: {template.algorithm_version!r}"
    )
  anchor_mapping = asdict(anchor) if anchor is not None else None
  input_hash = hashlib.sha256(
    json.dumps(anchor_mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")
  ).hexdigest()
  diagnostics: list[dict[str, Any]] = [{
    "code": "tethered_input_summary", "severity": "info",
    "anchor_gate_id": template.anchor_gate_id,
  }]
  if anchor is None:
    reason = f"anchor gate not found: {template.anchor_gate_id}"
    diagnostics.append({"code": "tethered_fit_failed", "severity": "error", "reason": reason})
    return TetheredGateFitResult(
      template_id=template.id, sample_id=sample_id, input_hash=input_hash,
      algorithm_version=template.algorithm_version, status="failed",
      diagnostics=tuple(diagnostics), failure_reason=reason,
    )
  if anchor.gate_type != "rectangle":
    raise TetheredGateFitError("translated_rectangle requires a rectangle anchor")
  thresholds = dict(anchor.thresholds)
  for low, high, offset in (
    ("x_min", "x_max", template.x_offset), ("y_min", "y_max", template.y_offset)
  ):
    if low not in thresholds or high not in thresholds:
      raise TetheredGateFitError("rectangle anchor requires x_min/x_max/y_min/y_max")
    thresholds[low] = float(thresholds[low]) + offset
    thresholds[high] = float(thresholds[high]) + offset
  gate = GateSpec(
    id=f"{template.id}:{sample_id}", name=f"{template.name} [{sample_id}]",
    gate_type="rectangle",
    parent_population_id=template.parent_population_id or anchor.parent_population_id,
    x_parameter=anchor.x_parameter, y_parameter=anchor.y_parameter, thresholds=thresholds,
    notes=f"tethered to {template.anchor_gate_id}",
  )
  diagnostics.append({
    "code": "tethered_fit_complete", "severity": "info", "algorithm": template.algorithm,
  })
  return TetheredGateFitResult(
    template_id=template.id, sample_id=sample_id, input_hash=input_hash,
    algorithm_version=template.algorithm_version, status="success", gate=gate,
    diagnostics=tuple(diagnostics),
  )
