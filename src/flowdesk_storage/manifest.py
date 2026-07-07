"""Manifest validation for .flowdesk project bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flowdesk_core.errors import FlowdeskError

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
  return data
