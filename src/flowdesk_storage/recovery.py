"""Autosave and crash-recovery storage with explicit copy semantics."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowdesk_storage.project import load_project, save_project


@dataclass(frozen=True)
class AutosaveSettings:
  """Global autosave policy; project manifests never contain this preference."""

  enabled: bool = True
  interval_seconds: int = 300
  retention: int = 5

  def __post_init__(self) -> None:
    if isinstance(self.interval_seconds, bool) or self.interval_seconds < 10:
      raise ValueError("autosave interval_seconds must be at least 10")
    if isinstance(self.retention, bool) or self.retention < 1:
      raise ValueError("autosave retention must be positive")


class RecoveryManager:
  """Write dirty project copies to a separate recovery location atomically."""

  def __init__(self, root: str | Path) -> None:
    self.root = Path(root)

  def autosave(
    self,
    project_id: str,
    manifest: dict[str, Any],
    *,
    dirty: bool,
    read_only: bool = False,
    retention: int = 5,
  ) -> Path | None:
    if not dirty or read_only:
      return None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = self.root / project_id / f"{timestamp}.flowdesk"
    save_project(destination, manifest)
    self.cleanup(project_id, retention)
    return destination

  def candidates(self, project_id: str) -> tuple[Path, ...]:
    directory = self.root / project_id
    if not directory.exists():
      return ()
    return tuple(sorted(
      directory.glob("*.flowdesk"), key=lambda item: item.stat().st_mtime, reverse=True
    ))

  def newer_than(self, project_path: str | Path, project_id: str) -> tuple[Path, ...]:
    source = Path(project_path) / "manifest.json"
    if not source.exists():
      return self.candidates(project_id)
    source_mtime = source.stat().st_mtime_ns
    return tuple(path for path in self.candidates(project_id)
                 if (path / "manifest.json").exists()
                 and (path / "manifest.json").stat().st_mtime_ns > source_mtime)

  def recover_copy(self, recovery_path: str | Path, destination: str | Path) -> Path:
    """Open recovery as a new bundle; never overwrite the original project."""
    source = Path(recovery_path)
    target = Path(destination)
    if source.resolve() == target.resolve():
      raise ValueError("recovery destination must differ from recovery source")
    manifest = load_project(source)
    save_project(target, manifest, source_project_path=source)
    return target

  def cleanup(self, project_id: str, retention: int) -> None:
    paths = self.candidates(project_id)
    for path in paths[retention:]:
      shutil.rmtree(path, ignore_errors=False)
