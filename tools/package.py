"""Cross-platform native package build and smoke-test entry point."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, metadata, version
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
  batch_export_id: str | None = None,
  timeout: int = 60,
) -> None:
  """Run package smoke checks without rebuilding artifacts."""
  if timeout < 1:
    raise ValueError("timeout must be positive")
  if batch_export_id is not None and project is None:
    raise ValueError("--batch-export-id requires --project")
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
  if batch_export_id is not None:
    command.extend(["--batch-export-id", batch_export_id])
  command.extend(["--timeout", str(timeout)])
  if qt_platform is not None:
    command.extend(["--qt-platform", qt_platform])
  command.extend(["--output-dir", str(output_dir or ROOT / "artifacts" / "package-smoke")])
  _run(command)


def manifest(output: Path) -> None:
  """Write build provenance without requiring a VCS or packaging service."""
  dependency_names = (
    "numpy",
    "flowio",
    "Pillow",
    "PySide6",
    "pyqtgraph",
    "PyInstaller",
  )
  data = {
    "flowdesk_version": _flowdesk_version(),
    "build_os": platform.system(),
    "architecture": platform.machine(),
    "python_version": platform.python_version(),
    "dependencies": {
      name: _package_license_metadata(name) for name in dependency_names
    },
    "build_timestamp_utc": datetime.now(UTC).isoformat(),
  }
  output.parent.mkdir(parents=True, exist_ok=True)
  output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _package_version(name: str) -> str | None:
  try:
    return version(name)
  except PackageNotFoundError:
    return None


def _package_license_metadata(name: str) -> dict[str, object] | None:
  """Return the installed package version and declared license metadata."""
  try:
    package_metadata = metadata(name)
  except PackageNotFoundError:
    return None
  license_files = package_metadata.get_all("License-File") or []
  expression = package_metadata.get("License-Expression")
  legacy_license = package_metadata.get("License")
  result: dict[str, object] = {"version": package_metadata.get("Version")}
  if expression:
    result["license_expression"] = expression
  if legacy_license:
    result["license"] = legacy_license
  if license_files:
    result["license_files"] = license_files
  return result


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  subparsers = parser.add_subparsers(dest="command", required=True)
  subparsers.add_parser("build")
  smoke_parser = subparsers.add_parser("smoke")
  smoke_parser.add_argument("--project", type=Path)
  smoke_parser.add_argument("--fcs", type=Path)
  smoke_parser.add_argument("--qt-platform")
  smoke_parser.add_argument("--output-dir", type=Path)
  smoke_parser.add_argument("--batch-export-id")
  smoke_parser.add_argument(
    "--timeout",
    type=int,
    default=60,
    help="Timeout in seconds for each packaged smoke command (default: 60).",
  )
  manifest_parser = subparsers.add_parser("manifest")
  manifest_parser.add_argument("--output", type=Path, required=True)
  subparsers.add_parser("check")
  args = parser.parse_args()

  if args.command == "build":
    build()
  elif args.command == "smoke":
    smoke(
      args.project, args.fcs, args.qt_platform, args.output_dir,
      args.batch_export_id, args.timeout,
    )
  elif args.command == "manifest":
    manifest(args.output)
  else:
    build()
    smoke()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
