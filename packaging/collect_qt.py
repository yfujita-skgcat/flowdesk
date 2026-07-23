"""Small PyInstaller collection helpers for the Flowdesk desktop build.

The helper is intentionally build-time only.  Flowdesk's runtime modules do
not import PyInstaller, which keeps the core and source-tree execution paths
unchanged.
"""

from __future__ import annotations

from typing import Any

PACKAGE_NAMES = (
  "flowdesk_core",
  "flowdesk_storage",
  "flowdesk_cli",
  "flowdesk_qt",
  "numpy",
  "flowio",
  "PySide6",
  "pyqtgraph",
)


def collect_packages() -> tuple[list[Any], list[Any], list[str]]:
  """Collect Python modules, data, and native libraries for the build.

  ``collect_all`` is used for each package because the native dependencies
  differ by platform.  In particular, PySide6's platform and image format
  plugins are data files on some platforms and binaries on others.
  """
  from PyInstaller.utils.hooks import collect_all

  datas: list[Any] = []
  binaries: list[Any] = []
  hiddenimports: list[str] = []
  for package_name in PACKAGE_NAMES:
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
  return datas, binaries, hiddenimports
