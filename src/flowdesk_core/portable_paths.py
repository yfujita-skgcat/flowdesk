"""Portable filesystem naming helpers for user-visible export paths."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_WINDOWS_DEVICE_NAMES = {
  "CON", "PRN", "AUX", "NUL",
  *(f"COM{index}" for index in range(1, 10)),
  *(f"LPT{index}" for index in range(1, 10)),
}


def portable_filename_key(path: str | Path) -> str:
  """Return a conservative collision key shared by common OS filesystems."""
  text = str(path).replace("\\", "/")
  return "/".join(
    unicodedata.normalize("NFC", component).rstrip(" .").casefold()
    for component in text.split("/")
  )


def portable_output_component(value: str) -> str:
  """Sanitize one generated filename component for Windows and macOS."""
  normalized = unicodedata.normalize("NFC", value).strip()
  normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized)
  normalized = normalized.strip("._ ")
  if not normalized:
    return "output"
  stem = normalized.split(".", 1)[0].rstrip(" .").upper()
  return f"_{normalized}" if stem in _WINDOWS_DEVICE_NAMES else normalized
