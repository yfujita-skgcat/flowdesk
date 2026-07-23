"""Small PyInstaller collection helpers for the Flowdesk desktop build.

The helper is intentionally build-time only.  Flowdesk's runtime modules do
not import PyInstaller, which keeps the core and source-tree execution paths
unchanged.
"""

from __future__ import annotations

from typing import Any


def collect_packages() -> tuple[list[Any], list[Any], list[str]]:
  """Collect only non-code data not covered by PyInstaller's standard hooks.

  Application modules, NumPy, FlowIO, and PySide6 are reached through normal
  imports and their standard PyInstaller hooks.  Qt platform/image plugins
  are also handled by the PySide6 hook.  Keeping this list narrow avoids
  bundling unused Qt modules, examples, and optional OpenGL dependencies.
  """
  from PyInstaller.utils.hooks import collect_data_files

  return collect_data_files("pyqtgraph"), [], []
