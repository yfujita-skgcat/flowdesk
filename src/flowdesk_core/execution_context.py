"""Execution context for headless pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionContext:
  """Runtime options selected for one pipeline execution."""

  project_path: Path | None = None
  output_dir: Path | None = None
  execution_profile_id: str = "default"
  recompute_cache: bool = False
  metadata: dict[str, Any] = field(default_factory=dict)
