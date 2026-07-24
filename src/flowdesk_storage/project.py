"""Project bundle loading, validation, and saving."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, TypeAlias

from flowdesk_storage.manifest import (
  ManifestValidationError,
  load_manifest,
  validate_manifest,
)
from flowdesk_storage.migrations import migrate_manifest_with_report
from flowdesk_storage.serialization import atomic_write_json, now_iso

ProjectManifest: TypeAlias = dict[str, Any]

DEFAULT_RESOLUTION_POLICY = "relative_to_project_or_absolute"


def load_project(path: str | Path) -> ProjectManifest:
  """Load a ``.flowdesk`` project bundle manifest.

  Returns the validated manifest dictionary.
  """

  return load_manifest(path)


def save_project(
  path: str | Path,
  manifest: ProjectManifest,
) -> None:
  """Save a project manifest to a ``.flowdesk`` bundle directory.

  Preserves unknown fields. Updates ``updated_at`` timestamp.
  """

  project_path = Path(path)
  manifest_path = project_path / "manifest.json"

  # Migrate and validate BEFORE creating any files.
  original_manifest = deepcopy(manifest)
  migration_report = migrate_manifest_with_report(manifest)
  migrated_manifest = migration_report.migrated
  if migrated_manifest is None:
    raise RuntimeError("migration did not produce a manifest")
  manifest = migrated_manifest
  validate_manifest(manifest)

  # Ensure the bundle directory structure exists.
  (project_path / "cache").mkdir(parents=True, exist_ok=True)
  (project_path / "exports").mkdir(parents=True, exist_ok=True)
  (project_path / "gates").mkdir(parents=True, exist_ok=True)
  if migration_report.was_migrated:
    backup_path = (
      project_path
      / "backups"
      / f"manifest.pre-migration-{migration_report.from_version}.json"
    )
    if not backup_path.exists():
      atomic_write_json(backup_path, original_manifest)
  manifest["updated_at"] = now_iso()
  atomic_write_json(manifest_path, manifest)

  strategies = manifest.get("gating_strategies_data", {})
  if len(strategies) == 1:
    strategy = next(iter(strategies.values()))
    atomic_write_json(project_path / "gates" / "gating_strategy.json", strategy)


def load_gating_strategy(
  project_path: str | Path,
  strategy_id: str,
) -> dict[str, Any]:
  """Load a gating strategy JSON file from the project bundle."""

  strategy_path = Path(project_path) / "gates" / "gating_strategy.json"
  if not strategy_path.exists():
    raise FileNotFoundError(
      f"gating strategy file not found: {strategy_path}"
    )

  import json

  with strategy_path.open(encoding="utf-8") as handle:
    data: dict[str, Any] = json.load(handle)

  if data.get("id") != strategy_id:
    raise ValueError(
      f"gating strategy id mismatch: expected {strategy_id}, got {data.get('id')}"
    )

  return data


def resolve_sample_paths(
  manifest: ProjectManifest,
  project_path: str | Path,
) -> list[dict[str, Any]]:
  """Resolve sample paths according to the configured resolution policy.

  Supported policies:
    - ``absolute``: paths must be absolute; relative paths are rejected.
    - ``relative_to_project``: relative paths are resolved against the
      project bundle directory.
    - ``relative_to_project_or_absolute`` (default): absolute paths are kept
      as-is; relative paths are resolved against the project bundle directory.
  """

  policy = manifest.get(
    "sample_path_resolution_policy", DEFAULT_RESOLUTION_POLICY
  )
  base = Path(project_path).resolve()
  samples = manifest.get("samples", [])

  resolved = []
  for sample in samples:
    s = dict(sample)
    raw_path = s.get("path", "")
    sample_path = Path(raw_path)

    # A POSIX absolute path is still absolute metadata when a project is
    # inspected on Windows, even though pathlib treats /path as drive-rooted
    # and not fully absolute there.
    posix_absolute = (
      isinstance(raw_path, str)
      and raw_path.startswith(("/", "\\"))
    )
    if sample_path.is_absolute() or posix_absolute:
      pass  # Keep absolute path as-is.
    elif policy == "absolute":
      raise ManifestValidationError(
        f"sample path is relative but policy is 'absolute': {raw_path}"
      )
    else:
      s["path"] = str(base / sample_path)

    resolved.append(s)

  return resolved
