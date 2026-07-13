"""Pure project manifest migrations for persisted scientific identity."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from flowdesk_core.errors import FlowdeskError

CURRENT_PROJECT_VERSION = "1.4.0"
LEGACY_PROJECT_VERSIONS = frozenset({
  "0.1",
  "1.0.0",
  "1.1.0",
  "1.2.0",
  "1.3.0",
})


class ProjectMigrationError(FlowdeskError):
  """Raised when a project cannot be migrated without guessing its meaning."""

  def __init__(
    self,
    code: str,
    message: str,
    *,
    sample_id: str | None = None,
    candidate_labels: tuple[str, ...] = (),
  ) -> None:
    self.code = code
    self.sample_id = sample_id
    self.candidate_labels = candidate_labels
    super().__init__(message)


def migrate_manifest(data: dict[str, Any]) -> dict[str, Any]:
  """Return a migrated deep copy while preserving all unknown fields."""
  if not isinstance(data, dict):
    raise ProjectMigrationError(
      "invalid_manifest_type",
      "project manifest must be a JSON object",
    )
  version = data.get("project_version")
  if not isinstance(version, str):
    raise ProjectMigrationError(
      "missing_project_version",
      "project manifest has no string project_version",
    )
  if version == CURRENT_PROJECT_VERSION:
    return deepcopy(data)
  if version not in LEGACY_PROJECT_VERSIONS:
    raise ProjectMigrationError(
      "unsupported_project_version",
      f"unsupported project version: {version!r}",
    )

  migrated = deepcopy(data)
  samples = migrated.get("samples", [])
  if not isinstance(samples, list):
    raise ProjectMigrationError(
      "invalid_legacy_samples",
      "legacy project samples must be an array",
    )
  for sample in samples:
    if not isinstance(sample, dict):
      raise ProjectMigrationError(
        "invalid_legacy_sample",
        "legacy project sample must be an object",
      )
    if "channels" in sample:
      continue
    sample_id = str(sample.get("id", "unknown"))
    legacy_names = sample.get("channel_names")
    if legacy_names is None:
      sample["channels"] = []
      continue
    if not isinstance(legacy_names, list) or not all(
      isinstance(name, str) and name for name in legacy_names
    ):
      raise ProjectMigrationError(
        "invalid_legacy_channel_names",
        f"sample {sample_id!r} has invalid legacy channel_names",
        sample_id=sample_id,
      )
    counts = Counter(legacy_names)
    duplicates = tuple(name for name, count in counts.items() if count > 1)
    if duplicates:
      raise ProjectMigrationError(
        "ambiguous_legacy_channel_label",
        f"sample {sample_id!r} has duplicate legacy channel labels: "
        f"{', '.join(repr(label) for label in duplicates)}",
        sample_id=sample_id,
        candidate_labels=duplicates,
      )
    sample["channels"] = [
      {
        "id": name,
        "name": name,
        "metadata": {"identity_source": "legacy_name"},
      }
      for name in legacy_names
    ]

  definitions = migrated.get("derived_parameters", [])
  if not isinstance(definitions, list):
    raise ProjectMigrationError(
      "invalid_legacy_derived_parameters",
      "legacy derived_parameters must be an array",
    )
  diagnostics = migrated.get("migration_diagnostics", [])
  if not isinstance(diagnostics, list):
    raise ProjectMigrationError(
      "invalid_legacy_migration_diagnostics",
      "legacy migration_diagnostics must be an array",
    )
  for definition in definitions:
    if not isinstance(definition, dict):
      raise ProjectMigrationError(
        "invalid_legacy_derived_parameter",
        "legacy derived parameter must be an object",
      )
    parameter_id = definition.get("id")
    if not isinstance(parameter_id, str) or not parameter_id:
      raise ProjectMigrationError(
        "invalid_legacy_derived_parameter_id",
        "legacy derived parameter ID must be a non-empty string",
      )
    definition.setdefault("output_channel_id", parameter_id)
    definition.setdefault("unit", None)
    definition.setdefault("source_stage", "compensated")
    definition.setdefault("input_parameters", [])
    policy = definition.setdefault(
      "invalid_value_policy", "emit_nan_with_warning"
    )
    if policy == "division_by_zero_to_nan":
      definition["invalid_value_policy"] = "emit_nan_with_warning"
    if definition["source_stage"] == "transformed":
      definition["legacy_source_stage_policy"] = "reject"
      diagnostic = {
        "code": "legacy_transformed_derived_source",
        "severity": "error",
        "stage": "migration",
        "message": (
          f"Derived parameter {parameter_id!r} uses legacy transformed source "
          "and cannot run in the canonical pipeline"
        ),
        "parameter_id": parameter_id,
        "details": {"compatibility_policy": "reject"},
      }
      if diagnostic not in diagnostics:
        diagnostics.append(diagnostic)

  transforms = migrated.get("transforms", [])
  if not isinstance(transforms, list):
    raise ProjectMigrationError(
      "invalid_legacy_transforms",
      "legacy project transforms must be an array",
    )
  for transform in transforms:
    if not isinstance(transform, dict):
      raise ProjectMigrationError(
        "invalid_legacy_transform",
        "legacy project transform must be an object",
      )
    transform_id = transform.get("id")
    if not isinstance(transform_id, str) or not transform_id:
      raise ProjectMigrationError(
        "invalid_legacy_transform_id",
        "legacy transform ID must be a non-empty string",
      )
    if transform.get("transform_type") != "logicle_like":
      continue
    transform["transform_type"] = "legacy_logicle_approximation"
    diagnostic = {
      "code": "legacy_logicle_approximation",
      "severity": "warning",
      "stage": "migration",
      "message": (
        f"Transform {transform_id!r} used the historical logicle_like "
        "approximation; it was renamed without changing numeric behavior"
      ),
      "transform_id": transform_id,
      "details": {
        "old_type": "logicle_like",
        "new_type": "legacy_logicle_approximation",
        "numeric_behavior_preserved": True,
      },
    }
    if diagnostic not in diagnostics:
      diagnostics.append(diagnostic)
  if diagnostics:
    migrated["migration_diagnostics"] = diagnostics

  migrated["project_version"] = CURRENT_PROJECT_VERSION
  return migrated
