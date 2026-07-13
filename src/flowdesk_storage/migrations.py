"""Pure project manifest migrations for persisted scientific identity."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from flowdesk_core.errors import FlowdeskError

CURRENT_PROJECT_VERSION = "1.1.0"
LEGACY_PROJECT_VERSIONS = frozenset({"0.1", "1.0.0"})


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

  migrated["project_version"] = CURRENT_PROJECT_VERSION
  return migrated
