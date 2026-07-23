"""User-writable application directories for all supported desktop systems."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths

from flowdesk_qt.app_info import APP_NAME, ORGANIZATION_NAME


def _writable_location(
  location: QStandardPaths.StandardLocation,
  fallback: Path,
) -> Path:
  """Resolve and create a Qt user directory, with a safe source fallback."""
  app = QCoreApplication.instance()
  if app is not None:
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
  resolved = QStandardPaths.writableLocation(location)
  path = Path(resolved) if resolved else fallback
  try:
    path.mkdir(parents=True, exist_ok=True)
    return path
  except OSError:
    # A read-only home directory can occur in CI, sandboxed launches, and
    # locked-down portable environments.  Keep the GUI usable while retaining
    # the standard location whenever it is writable.
    temp_root = QStandardPaths.writableLocation(
      QStandardPaths.StandardLocation.TempLocation
    )
    temporary = Path(temp_root or "/tmp") / "flowdesk" / fallback.name
    temporary.mkdir(parents=True, exist_ok=True)
    return temporary


def cache_directory() -> Path:
  """Return the per-user cache directory used for recoverable data."""
  return _writable_location(
    QStandardPaths.StandardLocation.CacheLocation,
    Path.home() / ".cache" / "flowdesk",
  )


def app_data_directory() -> Path:
  """Return the per-user persistent application-data directory."""
  return _writable_location(
    QStandardPaths.StandardLocation.AppLocalDataLocation,
    Path.home() / ".local" / "share" / "flowdesk",
  )


def debug_artifacts_directory() -> Path:
  """Return the root directory for GUI logs and debug artifacts."""
  path = app_data_directory() / "debug-artifacts"
  path.mkdir(parents=True, exist_ok=True)
  return path
