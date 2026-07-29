"""Execution context for headless pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flowdesk_core.execution_control import ExecutionControl


@dataclass(frozen=True)
class ExecutionContext:
  """Runtime options selected for one pipeline execution."""

  project_path: Path | None = None
  output_dir: Path | None = None
  execution_profile_id: str = "default"
  recompute_cache: bool = False
  metadata: dict[str, Any] = field(default_factory=dict)
  # Runtime-only callbacks/tokens are deliberately excluded from project
  # serialization.  Existing callers retain sequential behavior when absent.
  execution_control: ExecutionControl | None = field(
    default=None, compare=False, repr=False
  )
