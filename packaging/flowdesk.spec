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

analysis = Analysis(
  [str(src_dir / "flowdesk_qt" / "__main__.py")],
  pathex=[str(src_dir)],
  binaries=binaries,
  datas=datas,
  hiddenimports=hiddenimports,
  hookspath=[],
  hooksconfig={},
  runtime_hooks=[],
  excludes=[],
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
