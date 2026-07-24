"""Storage for sample-independent analysis settings bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flowdesk_core.analysis_settings import (
  ANALYSIS_SETTINGS_DOCUMENT_KIND,
  extract_analysis_settings,
  migrate_analysis_settings,
)
from flowdesk_storage.project import load_project
from flowdesk_storage.serialization import atomic_write_json, now_iso


def save_analysis_settings(
  path: str | Path,
  project: dict[str, Any],
) -> None:
  """Write an atomic `.flowdesk-settings` directory bundle."""
  bundle = Path(path)
  settings = extract_analysis_settings(
    project,
    source_project_id=str(project.get("project_id", "")) or None,
  )
  settings["created_at"] = now_iso()
  migrate_analysis_settings(settings)
  bundle.mkdir(parents=True, exist_ok=True)
  atomic_write_json(bundle / "manifest.json", settings)


def load_analysis_settings(path: str | Path) -> dict[str, Any]:
  """Load settings or extract settings from a normal `.flowdesk` project."""
  source = Path(path)
  manifest_path = source / "manifest.json"
  if not manifest_path.exists():
    raise ValueError(f"analysis settings manifest not found: {manifest_path}")
  with manifest_path.open(encoding="utf-8") as handle:
    data = json.load(handle)
  if data.get("document_kind") == ANALYSIS_SETTINGS_DOCUMENT_KIND:
    return migrate_analysis_settings(data)
  project = load_project(source)
  return extract_analysis_settings(
    project,
    source_project_id=str(project.get("project_id", "")) or None,
  )
