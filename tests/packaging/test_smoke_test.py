import importlib.util
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
  path.write_text(body, encoding="utf-8")
  path.chmod(0o755)
  return path


def test_smoke_runs_gui_and_cli_contracts(tmp_path: Path) -> None:
  gui = _write_executable(
    tmp_path / "gui",
    "#!/bin/sh\n"
    "if [ \"$1\" = \"--version\" ]; then exit 0; fi\n"
    "mkdir -p \"$3\"\n",
  )
  cli = _write_executable(
    tmp_path / "cli",
    "#!/bin/sh\n"
    "if [ \"$1\" = \"inspect\" ]; then exit 0; fi\n"
    "echo 'sample,count' > \"$4\"\n",
  )
  project = tmp_path / "project.flowdesk"
  project.mkdir()
  fcs = tmp_path / "sample.fcs"
  fcs.write_bytes(b"synthetic")

  run_smoke(gui, cli, project, fcs, tmp_path / "out")
  assert (tmp_path / "out" / "results.tsv").is_file()


def test_smoke_requires_project_for_cli(tmp_path: Path) -> None:
  cli = _write_executable(tmp_path / "cli", "#!/bin/sh\nexit 0\n")

  with pytest.raises(ValueError, match="--project"):
    run_smoke(None, cli, None, None, tmp_path / "out")
