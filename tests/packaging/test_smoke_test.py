import importlib.util
import os
import platform
from pathlib import Path

import pytest

SMOKE_TEST_PATH = Path(__file__).parents[2] / "packaging" / "smoke_test.py"
SMOKE_TEST_SPEC = importlib.util.spec_from_file_location(
  "flowdesk_package_smoke", SMOKE_TEST_PATH
)
assert SMOKE_TEST_SPEC is not None
assert SMOKE_TEST_SPEC.loader is not None
SMOKE_TEST_MODULE = importlib.util.module_from_spec(SMOKE_TEST_SPEC)
SMOKE_TEST_SPEC.loader.exec_module(SMOKE_TEST_MODULE)
run_smoke = SMOKE_TEST_MODULE.run_smoke


def _write_executable(path: Path, body: str) -> Path:
  if os.name == "nt":
    path = path.with_suffix(".cmd")
  path.write_text(body, encoding="utf-8")
  if os.name != "nt":
    path.chmod(0o755)
  return path


def test_smoke_runs_gui_and_cli_contracts(tmp_path: Path) -> None:
  if os.name == "nt":
    gui_body = (
      "@echo off\n"
      "set report=\n"
      ":args\n"
      "if \"%~1\"==\"\" goto done\n"
      "if \"%~1\"==\"--smoke-report\" (set \"report=%~2\" & shift & shift & goto args)\n"
      "shift\n"
      "goto args\n"
      ":done\n"
      "(echo {\"status\":\"ok\",\"platform\":\"windows\","
      "\"main_window_created\":true}) > \"%report%\"\n"
    )
    cli_body = (
      "@echo off\n"
      "if \"%~1\"==\"inspect\" exit /b 0\n"
      "(echo sample,count) > \"%~4\"\n"
    )
  else:
    gui_body = (
      "#!/bin/sh\n"
      "report=''\n"
      "while [ $# -gt 0 ]; do\n"
      "  if [ \"$1\" = \"--smoke-report\" ]; then report=\"$2\"; shift 2; continue; fi\n"
      "  shift\n"
      "done\n"
      f"printf '{{\"status\":\"ok\",\"platform\":\"{platform.system().lower()}\","
      "\"main_window_created\":true}' > \"$report\"\n"
    )
    cli_body = (
      "#!/bin/sh\n"
      "if [ \"$1\" = \"inspect\" ]; then exit 0; fi\n"
      "echo 'sample,count' > \"$4\"\n"
    )
  gui = _write_executable(
    tmp_path / "gui",
    gui_body,
  )
  cli = _write_executable(
    tmp_path / "cli",
    cli_body,
  )
  project = tmp_path / "project.flowdesk"
  project.mkdir()
  fcs = tmp_path / "sample.fcs"
  fcs.write_bytes(b"synthetic")

  run_smoke(gui, cli, project, fcs, tmp_path / "out")
  assert (tmp_path / "out" / "results.tsv").is_file()


def test_smoke_requires_project_for_cli(tmp_path: Path) -> None:
  body = "@echo off\nexit /b 0\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n"
  cli = _write_executable(tmp_path / "cli", body)

  with pytest.raises(ValueError, match="--project"):
    run_smoke(None, cli, None, None, tmp_path / "out")
