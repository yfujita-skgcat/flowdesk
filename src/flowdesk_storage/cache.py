"""Safe cache-key primitives for disposable pipeline-derived results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

CacheStage = Literal[
  "compensation", "derived_parameters", "transforms", "gating", "statistics",
]
_STAGES: tuple[CacheStage, ...] = (
  "compensation", "derived_parameters", "transforms", "gating", "statistics",
)


def definition_hash(value: object) -> str:
  """Return a deterministic hash for JSON-compatible definition data."""
  payload = json.dumps(
    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
  ).encode("utf-8")
  return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PipelineCacheKey:
  """Identity of one sample's disposable, stage-specific derived cache."""

  sample_id: str
  input_fingerprint: str
  software_version: str
  execution_profile_id: str
  stage_hashes: Mapping[CacheStage, str]

  def for_stage(self, stage: CacheStage) -> str:
    """Return a stable key that includes all definitions upstream of ``stage``."""
    if stage not in self.stage_hashes:
      raise ValueError(f"unknown cache stage: {stage!r}")
    return definition_hash({
      "algorithm_version": "pipeline-cache-key.v1",
      "sample_id": self.sample_id,
      "input_fingerprint": self.input_fingerprint,
      "software_version": self.software_version,
      "execution_profile_id": self.execution_profile_id,
      "stage": stage,
      "stage_hash": self.stage_hashes[stage],
    })

  def to_mapping(self) -> dict[str, Any]:
    """Return audit metadata without exposing event data."""
    return {
      "algorithm_version": "pipeline-cache-key.v1",
      "sample_id": self.sample_id,
      "input_fingerprint": self.input_fingerprint,
      "software_version": self.software_version,
      "execution_profile_id": self.execution_profile_id,
      "stage_hashes": dict(self.stage_hashes),
      "stage_keys": {stage: self.for_stage(stage) for stage in _STAGES},
    }


def build_pipeline_cache_key(
  project: Mapping[str, Any],
  *,
  sample_id: str,
  input_fingerprint: str,
  execution_profile_id: str = "default",
  software_version: str = "flowdesk-cache.v1",
) -> PipelineCacheKey:
  """Build cumulative stage keys from all scientific upstream definitions.

  Display settings, export paths, timestamps, and runtime worker controls are
  intentionally excluded.  The returned key is metadata only; callers must
  still validate cache payloads and may discard them at any time.
  """
  profile = next(
    (
      value for value in project.get("execution_profiles", ())
      if isinstance(value, Mapping) and value.get("id") == execution_profile_id
    ),
    {},
  )
  sample = next(
    (
      value for value in project.get("samples", ())
      if isinstance(value, Mapping) and value.get("id") == sample_id
    ),
    {},
  )
  base = {
    "sample_id": sample_id,
    "sample_context": {
      "group_ids": sample.get("group_ids", ()),
      "metadata": sample.get("metadata", {}),
    },
    "execution_profile": profile,
  }
  definitions: dict[CacheStage, object] = {
    "compensation": {
      **base,
      "matrices": project.get("compensation_matrices", ()),
      "bindings": project.get("compensation_bindings", ()),
      "calculations": project.get("compensation_calculations", ()),
      "default_matrix": project.get("default_compensation_matrix_id"),
    },
    "derived_parameters": project.get("derived_parameters", ()),
    "transforms": project.get("transforms", ()),
    "gating": {
      "strategies": project.get("gating_strategies_data", {}),
      "templates": project.get("automatic_gate_templates", ()),
      "overrides": project.get("gate_overrides", ()),
    },
    "statistics": project.get("statistics", ()),
  }
  cumulative: dict[CacheStage, str] = {}
  upstream = definition_hash({"base": base, "input_fingerprint": input_fingerprint})
  for stage in _STAGES:
    cumulative[stage] = definition_hash({
      "upstream": upstream,
      "stage": stage,
      "definition": definitions[stage],
    })
    upstream = cumulative[stage]
  return PipelineCacheKey(
    sample_id=sample_id,
    input_fingerprint=input_fingerprint,
    software_version=software_version,
    execution_profile_id=execution_profile_id,
    stage_hashes=cumulative,
  )
