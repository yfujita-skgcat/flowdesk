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
  from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
  )

  datas: list[Any] = []
  binaries: list[Any] = []
  hiddenimports: list[str] = []
  for package_name in PACKAGE_NAMES:
    if package_name == "pyqtgraph":
      # pyqtgraph.examples imports a QApplication while being inspected and
      # is not part of Flowdesk's runtime. Avoid collecting optional OpenGL
      # examples and their unrelated PyOpenGL dependency as well.
      package_datas = collect_data_files(package_name)
      package_binaries = collect_dynamic_libs(package_name)
      package_hiddenimports = collect_submodules(
        package_name,
        filter=lambda name: not name.startswith("pyqtgraph.examples"),
      )
      datas.extend(package_datas)
      binaries.extend(package_binaries)
      hiddenimports.extend(package_hiddenimports)
      continue
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
  return datas, binaries, hiddenimports
