"""Serialization helpers for Flowdesk project data."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_json(path: str | Path, data: dict[str, Any], indent: int = 2) -> None:
  """Write a dictionary to a JSON file with consistent formatting."""

  path_obj = Path(path)
  path_obj.parent.mkdir(parents=True, exist_ok=True)
  with path_obj.open("w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=indent, ensure_ascii=False)
    handle.write("\n")


def atomic_write_json(
  path: str | Path,
  data: dict[str, Any],
  indent: int = 2,
) -> None:
  """Write a JSON file atomically using temp file + fsync + rename.

  Writes to a sibling temporary file, flushes required data, then
  atomically replaces the target. If the write fails, the previous
  file is left intact.
  """

  path_obj = Path(path)
  path_obj.parent.mkdir(parents=True, exist_ok=True)

  content = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
  content_bytes = content.encode("utf-8")

  # Write to a temporary file in the same directory to ensure same filesystem.
  fd, tmp_path = tempfile.mkstemp(
    suffix=".tmp",
    prefix=".atomic_",
    dir=str(path_obj.parent),
  )
  try:
    with os.fdopen(fd, "wb") as handle:
      handle.write(content_bytes)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(tmp_path, str(path_obj))
    _fsync_directory(path_obj.parent)
  except BaseException:
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise


def _fsync_directory(directory: Path) -> None:
  """Persist a completed atomic rename where the filesystem supports it."""
  # Windows does not support opening a directory with os.open(..., O_RDONLY)
  # for fsync. The file itself has already been flushed before os.replace;
  # directory fsync is an additional durability step available on POSIX.
  if os.name == "nt":
    return
  directory_fd = os.open(directory, os.O_RDONLY)
  try:
    os.fsync(directory_fd)
  finally:
    os.close(directory_fd)


def read_json(path: str | Path) -> dict[str, Any]:
  """Read and parse a JSON file."""

  path_obj = Path(path)
  with path_obj.open(encoding="utf-8") as handle:
    data: dict[str, Any] = json.load(handle)
    return data


def now_iso() -> str:
  """Return the current UTC time as an ISO 8601 string."""

  return datetime.now(UTC).isoformat()


def merge_with_existing(
  base: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
  """Return a new dict with ``updates`` applied on top of ``base``.

  Unknown fields in ``base`` are preserved. Lists are replaced, not merged.
  """

  result = dict(base)
  result.update(updates)
  return result
