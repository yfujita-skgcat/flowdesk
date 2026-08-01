# -*- mode: python ; coding: utf-8 -*-
"""Native-platform PyInstaller console build for headless Flowdesk runs."""

from pathlib import Path

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import copy_metadata

project_root = Path(SPECPATH).parent
src_dir = project_root / "src"
release_documents = [
  (str(project_root / "LICENSE"), "."),
  (str(project_root / "THIRD_PARTY_NOTICES.md"), "."),
  (str(project_root / "src" / "flowdesk_core" / "assets" / "fonts" / "DejaVuSans.ttf"),
   "flowdesk_core/assets/fonts"),
  (str(project_root / "src" / "flowdesk_core" / "assets" / "fonts" / "DejaVuSans-Bold.ttf"),
   "flowdesk_core/assets/fonts"),
  (str(project_root / "src" / "flowdesk_core" / "assets" / "fonts" / "LICENSE-DejaVu.txt"),
   "flowdesk_core/assets/fonts"),
]

# The CLI has no GUI entry point.  These exclusions also keep optional test
# modules out when NumPy's package hook is evaluated for the headless build.
excluded_modules = [
  "numpy.tests",
  "numpy.f2py.tests",
  "numpy.lib.tests",
  "numpy.linalg.tests",
  "numpy.random.tests",
  "numpy.typing.tests",
  "pytest",
]

analysis = Analysis(
  [str(src_dir / "flowdesk_cli" / "main.py")],
  pathex=[str(src_dir)],
  binaries=[],
  datas=[*copy_metadata("flowdesk"), *release_documents],
  hiddenimports=[],
  hookspath=[],
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
