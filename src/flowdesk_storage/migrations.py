"""Pure project manifest migrations for persisted scientific identity."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from flowdesk_core.errors import FlowdeskError

CURRENT_PROJECT_VERSION = "1.5.0"


@dataclass
class MigrationReport:
  """Typed result from a project manifest migration."""

  from_version: str
  to_version: str
  was_migrated: bool
  diagnostics: list[dict[str, Any]] = field(default_factory=list)
  migrated: dict[str, Any] | None = None

  def to_mapping(self) -> dict[str, Any]:
    """Return the stable diagnostic representation for adapters."""
    return {
      "from_version": self.from_version,
      "to_version": self.to_version,
      "was_migrated": self.was_migrated,
      "diagnostics": list(self.diagnostics),
    }
LEGACY_PROJECT_VERSIONS = frozenset({
  "0.1",
  "1.0.0",
  "1.1.0",
  "1.2.0",
  "1.3.0",
  "1.4.0",
})

# Ordered list of all known versions from oldest to newest.
ALL_KNOWN_VERSIONS = [
  "0.1",
  "1.0.0",
  "1.1.0",
  "1.2.0",
  "1.3.0",
  "1.4.0",
  CURRENT_PROJECT_VERSION,
]


def _get_migration_path(from_version: str) -> list[str]:
  """Return the ordered list of versions to migrate through.

  Returns an empty list if ``from_version`` is already current.
  """

  if from_version == CURRENT_PROJECT_VERSION:
    return []
  if from_version not in ALL_KNOWN_VERSIONS:
    return []
  start_idx = ALL_KNOWN_VERSIONS.index(from_version)
  return ALL_KNOWN_VERSIONS[start_idx + 1:]


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
  """Return a migrated deep copy while preserving all unknown fields.

  DEPRECATED: Use ``migrate_manifest_with_report()`` for typed diagnostics.
  This wrapper remains for backward compatibility.
  """

  result = migrate_manifest_with_report(data)
  return result.migrated


def migrate_manifest_with_report(data: dict[str, Any]) -> MigrationReport:
  """Migrate a manifest and return a typed ``MigrationReport``.

  Returns a report with ``from_version``, ``to_version``, ``was_migrated``,
  and any diagnostics emitted during migration.
  """

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
    copied = deepcopy(data)
    return MigrationReport(
      from_version=version,
      to_version=version,
      was_migrated=False,
      migrated=copied,
    )
  if version not in LEGACY_PROJECT_VERSIONS:
    raise ProjectMigrationError(
      "unsupported_project_version",
      f"unsupported project version: {version!r}",
    )

  migrated = deepcopy(data)
  diagnostics: list[dict[str, Any]] = migrated.get("migration_diagnostics", [])
  if not isinstance(diagnostics, list):
    raise ProjectMigrationError(
      "invalid_legacy_migration_diagnostics",
      "legacy migration_diagnostics must be an array",
    )

  _migrate_samples(migrated, diagnostics)
  _migrate_derived_parameters(migrated, diagnostics)
  _migrate_transforms(migrated, diagnostics)
  _migrate_gate_transforms(migrated, diagnostics)
  _migrate_compensation_matrices(migrated, diagnostics)
  _ensure_compensation_bindings(migrated, diagnostics)

  if diagnostics:
    migrated["migration_diagnostics"] = diagnostics

  migrated["project_version"] = CURRENT_PROJECT_VERSION
  return MigrationReport(
    from_version=version,
    to_version=CURRENT_PROJECT_VERSION,
    was_migrated=True,
    diagnostics=list(diagnostics),
    migrated=migrated,
  )


def _migrate_samples(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Migrate legacy channel_names to structured channel objects."""

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


def _migrate_derived_parameters(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Migrate legacy derived parameter fields to current schema."""

  definitions = migrated.get("derived_parameters", [])
  if not isinstance(definitions, list):
    raise ProjectMigrationError(
      "invalid_legacy_derived_parameters",
      "legacy derived_parameters must be an array",
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


def _migrate_transforms(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Migrate legacy transform types and add role field."""

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
    transform.setdefault("role", "analysis")
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


def _migrate_gate_transforms(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Bind legacy gate axes to project transforms."""

  transforms = migrated.get("transforms", [])
  if not isinstance(transforms, list):
    return

  transform_ids_by_parameter: dict[str, str] = {}
  duplicate_transform_parameters: set[str] = set()
  for transform in transforms:
    parameter = transform.get("parameter")
    transform_id = transform.get("id")
    if not isinstance(parameter, str) or not parameter:
      continue
    if parameter in transform_ids_by_parameter:
      duplicate_transform_parameters.add(parameter)
      continue
    transform_ids_by_parameter[parameter] = transform_id
  for parameter in duplicate_transform_parameters:
    transform_ids_by_parameter.pop(parameter, None)

  strategy_data = migrated.get("gating_strategies_data", {})
  if not isinstance(strategy_data, dict):
    return
  for strategy in strategy_data.values():
    if not isinstance(strategy, dict):
      continue
    gates = strategy.get("gates", [])
    if not isinstance(gates, list):
      continue
    for gate in gates:
      if not isinstance(gate, dict):
        continue
      legacy_transform_id = gate.get("transform_id")
      if legacy_transform_id is not None:
        gate.setdefault("x_transform_id", legacy_transform_id)
      for axis in ("x", "y"):
        parameter = gate.get(f"{axis}_parameter")
        if not isinstance(parameter, str) or not parameter:
          continue
        transform_id = transform_ids_by_parameter.get(parameter)
        if transform_id is None or gate.get(f"{axis}_transform_id") is not None:
          continue
        scale = gate.get(f"{axis}_scale", "linear")
        if scale == "linear":
          gate[f"{axis}_transform_id"] = transform_id
          continue
        diagnostic = {
          "code": "legacy_double_transform",
          "severity": "error",
          "stage": "migration",
          "message": (
            f"Gate {gate.get('id', 'unknown')!r} {axis}-axis combines "
            f"project transform {transform_id!r} with legacy scale {scale!r}"
          ),
          "transform_id": transform_id,
          "details": {
            "gate_id": gate.get("id"),
            "axis": axis,
            "legacy_scale": scale,
            "compatibility_policy": "reject_double_application",
          },
        }
        if diagnostic not in diagnostics:
          diagnostics.append(diagnostic)


def _migrate_compensation_matrices(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Ensure each compensation matrix has a provenance block."""

  matrices = migrated.get("compensation_matrices", [])
  if not isinstance(matrices, list):
    return
  for matrix in matrices:
    if not isinstance(matrix, dict):
      continue
    matrix_id = matrix.get("id", "unknown")
    if "provenance" not in matrix:
      matrix["provenance"] = {}
      diagnostic = {
        "code": "legacy_compensation_matrix_provenance",
        "severity": "info",
        "stage": "migration",
        "message": (
          f"Compensation matrix {matrix_id!r} had no provenance; "
          "empty provenance was added"
        ),
        "details": {"matrix_id": matrix_id},
      }
      if diagnostic not in diagnostics:
        diagnostics.append(diagnostic)


def _ensure_compensation_bindings(
  migrated: dict[str, Any],
  diagnostics: list[dict[str, Any]],
) -> None:
  """Initialize compensation_bindings and emit diagnostics for legacy fields.

  If the legacy ``default_compensation_matrix_id`` field is present and
  ``compensation_bindings`` is empty, emit an info diagnostic noting that
  the legacy default matrix ID is still the authoritative fallback.
  The field is preserved as-is and remains usable by the pipeline runner.
  """

  if "compensation_bindings" not in migrated:
    migrated["compensation_bindings"] = []

  default_matrix_id = migrated.get("default_compensation_matrix_id")
  if not default_matrix_id:
    return
  bindings = migrated.get("compensation_bindings", [])
  if not bindings:
    diagnostic = {
      "code": "legacy_default_compensation_preserved",
      "severity": "info",
      "stage": "migration",
      "message": (
        f"Legacy default_compensation_matrix_id {default_matrix_id!r} "
        "preserved as project default fallback"
      ),
      "details": {"default_matrix_id": default_matrix_id},
    }
    if diagnostic not in diagnostics:
      diagnostics.append(diagnostic)
