"""Deterministic resolution of explicit sample gate geometry overrides."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import GateOverrideSpec, GateSpec, GatingStrategySpec


class GateOverrideError(FlowdeskError):
  """Raised when an override is missing, stale, or malformed."""

  def __init__(self, code: str, message: str, **details: Any) -> None:
    self.code = code
    self.details = details
    super().__init__(message)


def inspect_gate_override_statuses(
  strategy: GatingStrategySpec,
  sample_ids: Sequence[str],
  overrides: Sequence[GateOverrideSpec],
  *,
  results_stale: bool = False,
) -> dict[str, dict[str, str | bool]]:
  """Return display/audit status without silently resolving stale overrides."""
  gates = {gate.id: gate for gate in strategy.gates}
  result: dict[str, dict[str, str | bool]] = {}
  for sample_id in sample_ids:
    selected = [
      override for override in overrides
      if override.enabled and override.sample_id == sample_id
    ]
    status = "shared"
    if selected:
      status = "override"
      for override in selected:
        gate = gates.get(override.base_gate_id)
        if gate is None:
          status = "missing"
          break
        if gate_version_hash(gate) != override.base_version_hash:
          status = "stale"
          break
    result[sample_id] = {
      "override_status": status,
      "results_stale": results_stale,
    }
  return result


def gate_version_hash(gate: GateSpec | Mapping[str, Any]) -> str:
  """Hash all shared gate definition fields in a stable JSON representation."""
  if isinstance(gate, GateSpec):
    value = asdict(gate)
  else:
    raw = dict(gate)
    value = asdict(GateSpec(
      id=str(raw["id"]), name=str(raw.get("name", raw["id"])),
      gate_type=raw["gate_type"], parent_population_id=raw.get("parent_population_id"),
      x_parameter=raw.get("x_parameter"), y_parameter=raw.get("y_parameter"),
      x_transform_id=raw.get("x_transform_id"), y_transform_id=raw.get("y_transform_id"),
      compensation_id=raw.get("compensation_id"),
      coordinates=tuple(tuple(point) for point in raw.get("coordinates", ())),
      thresholds=dict(raw.get("thresholds", {})), notes=str(raw.get("notes", "")),
    ))
  encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=list)
  return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def override_spec_from_mapping(value: Mapping[str, Any]) -> GateOverrideSpec:
  try:
    return GateOverrideSpec(
      id=str(value["id"]),
      sample_id=str(value["sample_id"]),
      base_gate_id=str(value["base_gate_id"]),
      base_version_hash=str(value["base_version_hash"]),
      geometry_mode=value["geometry_mode"],
      coordinates=tuple(tuple(point) for point in value.get("coordinates", ())),
      thresholds=dict(value.get("thresholds", {})),
      author=str(value["author"]),
      created_at=str(value["created_at"]),
      reason=str(value["reason"]),
      gate_purpose=value.get("gate_purpose", "technical_cleanup"),
      enabled=bool(value.get("enabled", True)),
    )
  except (KeyError, TypeError, ValueError) as exc:
    raise GateOverrideError("invalid_override", str(exc)) from exc


def resolve_gate_overrides(
  strategy: GatingStrategySpec,
  sample_id: str,
  overrides: Sequence[GateOverrideSpec],
) -> GatingStrategySpec:
  """Apply at most one explicit, current-base override per gate for a sample."""
  by_gate: dict[str, GateOverrideSpec] = {}
  for override in overrides:
    if not override.enabled or override.sample_id != sample_id:
      continue
    if override.base_gate_id in by_gate:
      raise GateOverrideError(
        "duplicate_override",
        "multiple overrides target one gate",
        gate_id=override.base_gate_id,
      )
    by_gate[override.base_gate_id] = override

  resolved: list[GateSpec] = []
  for gate in strategy.gates:
    gate_override = by_gate.get(gate.id)
    if gate_override is None:
      resolved.append(gate)
      continue
    actual_hash = gate_version_hash(gate)
    if actual_hash != gate_override.base_version_hash:
      raise GateOverrideError(
        "stale_override", f"override {gate_override.id!r} has a stale base gate",
        override_id=gate_override.id, gate_id=gate.id,
        expected_hash=gate_override.base_version_hash, actual_hash=actual_hash,
      )
    if gate_override.geometry_mode == "full":
      coordinates = gate_override.coordinates
      thresholds = dict(gate_override.thresholds)
    else:
      coordinates = override.coordinates or gate.coordinates
      thresholds = dict(gate.thresholds)
      thresholds.update(override.thresholds)
    resolved.append(GateSpec(**{
      **asdict(gate),
      "coordinates": coordinates,
      "thresholds": thresholds,
    }))
  unknown = set(by_gate) - {gate.id for gate in strategy.gates}
  if unknown:
    raise GateOverrideError(
      "missing_base_gate",
      "override references a missing gate",
      gate_ids=tuple(sorted(unknown)),
    )
  return GatingStrategySpec(**{**asdict(strategy), "gates": tuple(resolved)})
