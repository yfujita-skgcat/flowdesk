"""Cross-platform native package build and smoke-test entry point."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from flowdesk_qt._version import __version__

ROOT = Path(__file__).resolve().parents[1]
GUI_SPEC = ROOT / "packaging" / "flowdesk.spec"
CLI_SPEC = ROOT / "packaging" / "flowdesk-cli.spec"
SMOKE_SCRIPT = ROOT / "packaging" / "smoke_test.py"


def _flowdesk_version() -> str:
  """Return the same source version used by setuptools and the GUI."""
  return __version__


def _run(command: list[str]) -> None:
  subprocess.run(command, cwd=ROOT, check=True)


def _executable(directory: str) -> Path:
  name = directory + (".exe" if sys.platform == "win32" else "")
  return ROOT / "dist" / directory / name


def build() -> None:
  """Build GUI and console onedir artifacts for the current native OS."""
  _flowdesk_version()
  pyinstaller = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm"]
  _run([*pyinstaller, str(GUI_SPEC)])
  _run([*pyinstaller, str(CLI_SPEC)])


def smoke(
  project: Path | None = None,
  fcs_file: Path | None = None,
  qt_platform: str | None = None,
  output_dir: Path | None = None,
) -> None:
  """Run package smoke checks without rebuilding artifacts."""
  gui = _executable("flowdesk")
  cli = _executable("flowdesk-cli")
  if not gui.exists():
    raise RuntimeError(f"GUI package not found: {gui}; run 'python tools/package.py build'")
  command = [sys.executable, str(SMOKE_SCRIPT), "--gui", str(gui)]
  if project is not None:
    if not cli.exists():
      raise RuntimeError(f"CLI package not found: {cli}")
    command.extend(["--cli", str(cli), "--project", str(project)])
    if fcs_file is not None:
      command.extend(["--fcs", str(fcs_file)])
  if qt_platform is not None:
    command.extend(["--qt-platform", qt_platform])
  command.extend(["--output-dir", str(output_dir or ROOT / "artifacts" / "package-smoke")])
  _run(command)


def manifest(output: Path) -> None:
  """Write build provenance without requiring a VCS or packaging service."""
  data = {
    "flowdesk_version": _flowdesk_version(),
    "build_os": platform.system(),
    "architecture": platform.machine(),
    "python_version": platform.python_version(),
    "pyinstaller_version": _package_version("PyInstaller"),
    "pyside6_version": _package_version("PySide6"),
    "numpy_version": _package_version("numpy"),
    "flowio_version": _package_version("flowio"),
    "build_timestamp_utc": datetime.now(UTC).isoformat(),
  }
  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _package_version(name: str) -> str | None:
  try:
    return version(name)
  except PackageNotFoundError:
    return None


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  subparsers = parser.add_subparsers(dest="command", required=True)
  subparsers.add_parser("build")
  smoke_parser = subparsers.add_parser("smoke")
  smoke_parser.add_argument("--project", type=Path)
  smoke_parser.add_argument("--fcs", type=Path)
  smoke_parser.add_argument("--qt-platform")
  smoke_parser.add_argument("--output-dir", type=Path)
  manifest_parser = subparsers.add_parser("manifest")
  manifest_parser.add_argument("--output", type=Path, required=True)
  subparsers.add_parser("check")
  args = parser.parse_args()

  if args.command == "build":
    build()
  elif args.command == "smoke":
    smoke(args.project, args.fcs, args.qt_platform, args.output_dir)
  elif args.command == "manifest":
    manifest(args.output)
  else:
    build()
    smoke()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
