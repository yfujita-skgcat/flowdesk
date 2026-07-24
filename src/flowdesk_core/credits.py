"""Project credit and license information shared by CLI and GUI."""

from __future__ import annotations

COPYRIGHT_YEAR = "2026"
COPYRIGHT_HOLDER = "Yoshihiko Fujita"
CONTACT_EMAIL = "yfujita.skgcat@gmail.com"
LICENSE_NAME = "BSD 3-Clause License"


def credits_text() -> str:
  """Return the user-facing credit and license summary."""
  return (
    "Flowdesk\n"
    f"Copyright (c) {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}\n"
    f"Contact: {CONTACT_EMAIL}\n"
    f"License: {LICENSE_NAME}\n"
    "See the LICENSE file for the complete license text."
  )
