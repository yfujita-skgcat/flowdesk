from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "packaging" / "flowdesk.spec"
CLI_SPEC = ROOT / "packaging" / "flowdesk-cli.spec"
COLLECTOR = ROOT / "packaging" / "collect_qt.py"
PYQTGRAPH_HOOK = ROOT / "packaging" / "hooks" / "hook-pyqtgraph.py"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"


def test_onedir_spec_has_native_build_entrypoint_and_collection() -> None:
  text = SPEC.read_text(encoding="utf-8")

  assert "Analysis(" in text
  assert "COLLECT(" in text
  assert 'name="flowdesk"' in text
  assert "exclude_binaries=True" in text
  assert "console=False" in text
  assert "copy_metadata(\"flowdesk\")" in text
  assert "collect_packages()" in text
  assert 'project_root / "LICENSE"' in text
  assert 'project_root / "THIRD_PARTY_NOTICES.md"' in text
  assert 'DejaVuSans.ttf' in text
  assert 'DejaVuSans-Bold.ttf' in text
  assert 'LICENSE-DejaVu.txt' in text


def test_collection_covers_runtime_and_native_dependencies() -> None:
  text = COLLECTOR.read_text(encoding="utf-8")

  assert 'collect_data_files("pyqtgraph")' in text
  assert "collect_all" not in text
  assert "collect_submodules" not in text


def test_gui_spec_excludes_optional_qt_and_test_modules() -> None:
  text = SPEC.read_text(encoding="utf-8")

  assert "excluded_modules" in text
  for module in (
    "PySide6.Qt3DAnimation",
    "PySide6.QtBluetooth",
    "PySide6.QtDesigner",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtSql",
    "PySide6.QtWebEngineWidgets",
    "PySide6.scripts",
    "pyqtgraph.opengl",
    "numpy.tests",
    "pytest",
  ):
    assert f'"{module}"' in text

  assert '"PySide6.QtCore"' not in text
  assert '"PySide6.QtGui"' not in text
  assert '"PySide6.QtSvg"' not in text
  assert '"PySide6.QtWidgets"' not in text


def test_pyqtgraph_hook_does_not_discover_opengl_modules() -> None:
  text = PYQTGRAPH_HOOK.read_text(encoding="utf-8")

  assert "collect_submodules" in text
  assert "pyqtgraph.opengl" in text
  assert "not name.startswith(\"pyqtgraph.opengl\")" in text
  assert "not name.startswith(\"pyqtgraph.jupyter\")" in text


def test_spec_does_not_place_runtime_state_in_install_directory() -> None:
  text = SPEC.read_text(encoding="utf-8")

  assert "app_paths" not in text
  assert "Path.home()" not in text
  assert "debug-artifacts" not in text


def test_headless_cli_spec_is_a_console_artifact() -> None:
  text = CLI_SPEC.read_text(encoding="utf-8")

  assert "flowdesk_cli" in text
  assert 'name="flowdesk-cli"' in text
  assert "console=True" in text
  assert "copy_metadata(\"flowdesk\")" in text
  assert 'project_root / "LICENSE"' in text
  assert 'project_root / "THIRD_PARTY_NOTICES.md"' in text
  assert 'DejaVuSans.ttf' in text
  assert 'DejaVuSans-Bold.ttf' in text
  assert 'LICENSE-DejaVu.txt' in text
  assert "numpy.tests" in text


def test_bundled_font_assets_and_package_data_are_declared() -> None:
  assert (ROOT / "src" / "flowdesk_core" / "assets" / "fonts" / "DejaVuSans.ttf").is_file()
  assert (ROOT / "src" / "flowdesk_core" / "assets" / "fonts" / "DejaVuSans-Bold.ttf").is_file()
  assert (ROOT / "src" / "flowdesk_core" / "assets" / "fonts" / "LICENSE-DejaVu.txt").is_file()
  pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
  assert '"assets/fonts/*.ttf"' in pyproject


def test_third_party_notices_separates_dependency_licenses() -> None:
  text = NOTICES.read_text(encoding="utf-8")

  assert "BSD 3-Clause License" in text
  assert "Qt licensing" in text
  assert "GNU LGPL version 3" in text
  assert "GNU GPL version 3" in text
  assert "PyInstaller" in text
