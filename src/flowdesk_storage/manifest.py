"""Manifest validation for .flowdesk project bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION, migrate_manifest

REQUIRED_FIELDS = ["project_id", "project_version", "pipeline_version", "samples"]


class ManifestValidationError(FlowdeskError):
  """Raised when a project manifest fails validation."""


def validate_manifest(data: dict[str, Any]) -> None:
  """Validate that a manifest dictionary contains all required fields.

  Raises ManifestValidationError if required fields are missing or have
  incorrect types. Unknown fields are preserved (not rejected).
  """

  if not isinstance(data, dict):
    raise ManifestValidationError("manifest must be a JSON object")

  missing = [f for f in REQUIRED_FIELDS if f not in data]
  if missing:
    raise ManifestValidationError(f"missing required fields: {', '.join(missing)}")

  if not isinstance(data["project_id"], str):
    raise ManifestValidationError("project_id must be a string")

  if not isinstance(data["project_version"], str):
    raise ManifestValidationError("project_version must be a string")

  if not isinstance(data["pipeline_version"], str):
    raise ManifestValidationError("pipeline_version must be a string")

  if not isinstance(data["samples"], list):
    raise ManifestValidationError("samples must be an array")

  if data["project_version"] == CURRENT_PROJECT_VERSION:
    _validate_current_samples(data["samples"])


def _validate_current_samples(samples: list[Any]) -> None:
  """Validate sample/channel identity fields required by the current version."""
  for sample_index, sample in enumerate(samples):
    if not isinstance(sample, dict):
      raise ManifestValidationError(
        f"samples[{sample_index}] must be an object"
      )
    sample_id = sample.get("id")
    if not isinstance(sample_id, str) or not sample_id:
      raise ManifestValidationError(
        f"samples[{sample_index}].id must be a non-empty string"
      )
    fingerprint = sample.get("fingerprint")
    if fingerprint is not None:
      _validate_file_fingerprint(sample_id, fingerprint)
    channels = sample.get("channels")
    if not isinstance(channels, list):
      raise ManifestValidationError(
        f"sample {sample_id!r} channels must be an array"
      )
    channel_ids: set[str] = set()
    for channel_index, channel in enumerate(channels):
      if not isinstance(channel, dict):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_index} must be an object"
        )
      channel_id = channel.get("id")
      name = channel.get("name")
      if not isinstance(channel_id, str) or not channel_id:
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_index} id must be non-empty"
        )
      if channel_id in channel_ids:
        raise ManifestValidationError(
          f"sample {sample_id!r} has duplicate channel ID {channel_id!r}"
        )
      channel_ids.add(channel_id)
      if not isinstance(name, str) or not name:
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} name must be non-empty"
        )
      metadata = channel.get("metadata", {})
      if not isinstance(metadata, dict):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} metadata must be an object"
        )
      fcs_index = channel.get("fcs_parameter_index")
      if fcs_index is not None and (
        not isinstance(fcs_index, int) or isinstance(fcs_index, bool) or fcs_index < 1
      ):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} "
          "fcs_parameter_index must be a positive integer or null"
        )


def _validate_file_fingerprint(sample_id: str, value: Any) -> None:
  """Validate the persisted fingerprint fields without reading the input file."""
  if not isinstance(value, dict):
    raise ManifestValidationError(
      f"sample {sample_id!r} fingerprint must be an object"
    )
  for field in ("size", "mtime_ns"):
    number = value.get(field)
    if not isinstance(number, int) or isinstance(number, bool) or number < 0:
      raise ManifestValidationError(
        f"sample {sample_id!r} fingerprint {field} must be a non-negative integer"
      )
  for field in ("hash_algorithm", "hash_value"):
    text = value.get(field)
    if not isinstance(text, str) or not text:
      raise ManifestValidationError(
        f"sample {sample_id!r} fingerprint {field} must be a non-empty string"
      )


def load_manifest(path: str | Path) -> dict[str, Any]:
  """Load and validate a manifest.json from a .flowdesk directory."""

  manifest_path = Path(path) / "manifest.json"
  if not manifest_path.exists():
    raise ManifestValidationError(f"manifest.json not found: {manifest_path}")

  try:
    with manifest_path.open(encoding="utf-8") as handle:
      data: dict[str, Any] = json.load(handle)
  except json.JSONDecodeError as exc:
    raise ManifestValidationError(f"invalid JSON in manifest.json: {exc}") from exc

  validate_manifest(data)
  migrated = migrate_manifest(data)
  validate_manifest(migrated)
  return migrated
