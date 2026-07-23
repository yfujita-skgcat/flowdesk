"""Application identity shared by the GUI and packaged builds."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "Flowdesk"
ORGANIZATION_NAME = "Flowdesk"


def application_version() -> str:
  """Return the installed Flowdesk version, or a source-tree fallback."""
  try:
    return version("flowdesk")
  except PackageNotFoundError:
    return "0.0.0.dev0"
