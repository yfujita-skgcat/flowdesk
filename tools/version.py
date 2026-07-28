#!/usr/bin/env python
"""Read or increment the Flowdesk application version."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "flowdesk_qt" / "_version.py"
VERSION_PATTERN = re.compile(
  r'(?m)^(?P<prefix>__version__\s*=\s*["\'])(?P<version>\d+\.\d+\.\d+)(?P<suffix>["\'])\s*$'
)


def read_version() -> tuple[str, str]:
  source = VERSION_FILE.read_text(encoding="utf-8")
  match = VERSION_PATTERN.search(source)
  if match is None:
    raise RuntimeError(f"Could not find a semantic version in {VERSION_FILE}")
  return source, match.group("version")


def increment_patch() -> str:
  source, current = read_version()
  major, minor, patch = (int(part) for part in current.split("."))
  updated = f"{major}.{minor}.{patch + 1}"
  replacement = (
    f"{match.group('prefix')}{updated}{match.group('suffix')}"
    if (match := VERSION_PATTERN.search(source)) is not None
    else None
  )
  if replacement is None:
    raise RuntimeError(f"Could not update the version in {VERSION_FILE}")
  VERSION_FILE.write_text(
    source[:match.start()] + replacement + source[match.end():],
    encoding="utf-8",
  )
  print(f"Flowdesk version: {current} -> {updated}")
  return updated


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--read", action="store_true")
  parser.add_argument("--increment-patch", action="store_true")
  args = parser.parse_args()
  if args.read == args.increment_patch:
    parser.error("choose exactly one of --read or --increment-patch")
  if args.read:
    print(read_version()[1])
  else:
    increment_patch()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
