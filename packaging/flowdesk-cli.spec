# -*- mode: python ; coding: utf-8 -*-
"""Native-platform PyInstaller console build for headless Flowdesk runs."""

from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import copy_metadata

project_root = Path(SPECPATH).parent
src_dir = project_root / "src"

analysis = Analysis(
  [str(src_dir / "flowdesk_cli" / "main.py")],
  pathex=[str(src_dir)],
  binaries=[],
  datas=copy_metadata("flowdesk"),
  hiddenimports=[],
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
  name="flowdesk-cli",
  debug=False,
  bootloader_ignore_signals=False,
  strip=False,
  upx=False,
  console=True,
)

coll = COLLECT(
  exe,
  analysis.binaries,
  analysis.datas,
  strip=False,
  upx=False,
  name="flowdesk-cli",
)
