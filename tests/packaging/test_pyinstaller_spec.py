from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "packaging" / "flowdesk.spec"
CLI_SPEC = ROOT / "packaging" / "flowdesk-cli.spec"
COLLECTOR = ROOT / "packaging" / "collect_qt.py"


def test_onedir_spec_has_native_build_entrypoint_and_collection() -> None:
  text = SPEC.read_text(encoding="utf-8")

  assert "Analysis(" in text
  assert "COLLECT(" in text
  assert 'name="flowdesk"' in text
  assert "exclude_binaries=True" in text
  assert "console=False" in text
  assert "copy_metadata(\"flowdesk\")" in text
  assert "collect_packages()" in text


def test_collection_covers_runtime_and_native_dependencies() -> None:
  text = COLLECTOR.read_text(encoding="utf-8")

  assert 'collect_data_files("pyqtgraph")' in text
  assert "collect_all" not in text
  assert "collect_submodules" not in text


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
