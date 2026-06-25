"""Project bundle loading and saving."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeAlias

ProjectManifest: TypeAlias = dict[str, Any]


def load_project(path: str | Path) -> ProjectManifest:
  """Load a `.flowdesk` project bundle manifest."""

  project_path = Path(path)
  manifest_path = project_path / "manifest.json"
  with manifest_path.open(encoding="utf-8") as handle:
    data: ProjectManifest = json.load(handle)
  return data
