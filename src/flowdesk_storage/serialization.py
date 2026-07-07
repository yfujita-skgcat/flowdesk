"""Serialization helpers for Flowdesk project data."""

from __future__ import annotations

import json
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
