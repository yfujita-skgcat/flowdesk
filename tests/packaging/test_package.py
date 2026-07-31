from __future__ import annotations

import importlib.util
from pathlib import Path

PACKAGE_SCRIPT = Path(__file__).parents[2] / "tools" / "package.py"
SPEC = importlib.util.spec_from_file_location("flowdesk_package", PACKAGE_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_package_smoke_forwards_timeout_to_smoke_runner(tmp_path, monkeypatch) -> None:
  commands: list[list[str]] = []
  monkeypatch.setattr(MODULE, "_executable", lambda name: tmp_path / name)
  (tmp_path / "flowdesk").write_text("gui", encoding="utf-8")
  (tmp_path / "flowdesk-cli").write_text("cli", encoding="utf-8")
  monkeypatch.setattr(MODULE, "_run", commands.append)

  MODULE.smoke(
    project=tmp_path / "project.flowdesk",
    fcs_file=tmp_path / "sample.fcs",
    output_dir=tmp_path / "output",
    batch_export_id="export",
    timeout=300,
  )

  assert len(commands) == 1
  command = commands[0]
  assert "--timeout" in command
  assert command[command.index("--timeout") + 1] == "300"
