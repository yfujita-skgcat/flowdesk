from __future__ import annotations

from pathlib import Path

import pytest

from flowdesk_storage.recovery import AutosaveSettings, RecoveryManager

MANIFEST = {"project_id": "p", "project_version": "0.1", "pipeline_version": "1", "samples": []}


def test_dirty_autosave_retention_and_recover_copy(tmp_path: Path) -> None:
  manager = RecoveryManager(tmp_path / "recovery")
  assert manager.autosave("p", MANIFEST, dirty=False) is None
  first = manager.autosave("p", MANIFEST, dirty=True, retention=1)
  assert first is not None
  second = manager.autosave("p", MANIFEST, dirty=True, retention=1)
  assert second is not None
  assert len(manager.candidates("p")) == 1
  restored = manager.recover_copy(second, tmp_path / "restored.flowdesk")
  assert restored.exists()
  assert (restored / "manifest.json").exists()


def test_read_only_and_invalid_settings_are_safe(tmp_path: Path) -> None:
  manager = RecoveryManager(tmp_path / "recovery")
  assert manager.autosave("p", MANIFEST, dirty=True, read_only=True) is None
  with pytest.raises(ValueError):
    AutosaveSettings(interval_seconds=1)
  with pytest.raises(ValueError):
    AutosaveSettings(retention=0)
