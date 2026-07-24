"""Application identity shared by the GUI and packaged builds."""

from __future__ import annotations

from flowdesk_qt._version import __version__

APP_NAME = "Flowdesk"
ORGANIZATION_NAME = "Flowdesk"


def application_version() -> str:
  """Return the version used by packaging and the running application."""
  return __version__
