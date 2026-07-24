# -*- mode: python ; coding: utf-8 -*-
"""Native-platform PyInstaller onedir build for Flowdesk.

Build from the repository root with::

  pyinstaller --clean --noconfirm packaging/flowdesk.spec

PyInstaller must run on the target OS; this spec is not a cross-compiler.
"""

from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import copy_metadata

project_root = Path(SPECPATH).parent
src_dir = project_root / "src"

# The helper lives beside this spec and is imported only while building.
import sys

sys.path.insert(0, str(Path(SPECPATH)))
from collect_qt import collect_packages


datas, binaries, hiddenimports = collect_packages()
# importlib.metadata needs the installed distribution metadata in a frozen
# build.  The fallback in app_info remains useful for source-tree execution.
datas.extend(copy_metadata("flowdesk"))

# Flowdesk uses Qt Widgets, Qt SVG, and pyqtgraph's 2-D plotting APIs.  Keep
# PyInstaller's normal import analysis for the runtime dependencies, while
# preventing optional Qt tooling, 3-D/OpenGL support, and test packages from
# being pulled into the onedir artifact by broad package hooks.
excluded_modules = [
  "PySide6.Qt3DAnimation",
  "PySide6.Qt3DCore",
  "PySide6.Qt3DExtras",
  "PySide6.Qt3DInput",
  "PySide6.Qt3DLogic",
  "PySide6.Qt3DRender",
  "PySide6.QtBluetooth",
  "PySide6.QtCharts",
  "PySide6.QtDataVisualization",
  "PySide6.QtDesigner",
  "PySide6.QtGraphs",
  "PySide6.QtLocation",
  "PySide6.QtMultimedia",
  "PySide6.QtNfc",
  "PySide6.QtPdf",
  "PySide6.QtPdfWidgets",
  "PySide6.QtQml",
  "PySide6.QtQuick",
  "PySide6.QtQuick3D",
  "PySide6.QtSql",
  "PySide6.QtWebChannel",
  "PySide6.QtWebEngineCore",
  "PySide6.QtWebEngineWidgets",
  "PySide6.scripts",
  "pyqtgraph.opengl",
  "OpenGL",
  "numpy.tests",
  "numpy.f2py.tests",
  "numpy.lib.tests",
  "numpy.linalg.tests",
  "numpy.random.tests",
  "numpy.typing.tests",
  "pytest",
]

analysis = Analysis(
  [str(src_dir / "flowdesk_qt" / "__main__.py")],
  pathex=[str(src_dir)],
  binaries=binaries,
  datas=datas,
  hiddenimports=hiddenimports,
  hookspath=[str(Path(SPECPATH) / "hooks")],
  hooksconfig={},
  runtime_hooks=[],
  excludes=excluded_modules,
  noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
  pyz,
  analysis.scripts,
  [],
  exclude_binaries=True,
  name="flowdesk",
  debug=False,
  bootloader_ignore_signals=False,
  strip=False,
  upx=False,
  console=False,
)

coll = COLLECT(
  exe,
  analysis.binaries,
  analysis.datas,
  strip=False,
  upx=False,
  name="flowdesk",
)
