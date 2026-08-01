"""Write a small non-sensitive native runtime report for package CI."""

from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version(name: str) -> str | None:
  try:
    return version(name)
  except PackageNotFoundError:
    return None


def collect_report() -> dict[str, object]:
  report: dict[str, object] = {
    "os": platform.system(),
    "os_release": platform.release(),
    "architecture": platform.machine(),
    "python": platform.python_version(),
    "implementation": platform.python_implementation(),
    "filesystem_encoding": sys.getfilesystemencoding(),
    "preferred_encoding": locale.getpreferredencoding(False),
    "locale": locale.setlocale(locale.LC_ALL, None),
    "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
    "packages": {
      name: _version(name)
      for name in ("numpy", "flowio", "Pillow", "PySide6", "pyqtgraph", "PyInstaller")
    },
  }
  try:
    import numpy as np

    report["numpy_config"] = np.show_config(mode="dicts")
  except (ImportError, TypeError, ValueError):
    report["numpy_config"] = None
  return report


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(
    json.dumps(collect_report(), indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
