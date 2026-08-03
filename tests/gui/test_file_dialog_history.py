"""Tests for operation-specific File dialog directory history."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from flowdesk_qt.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_file_dialog_history_is_separate_per_operation(qapp, tmp_path: Path) -> None:
  window = MainWindow()
  keys = window._FILE_DIALOG_DIRECTORY_KEYS
  settings = QSettings()
  previous = {key: settings.value(key, None) for key in keys.values()}
  try:
    for key in keys.values():
      settings.remove(key)

    fcs_dir = tmp_path / "fcs"
    project_dir = tmp_path / "projects"
    fcs_dir.mkdir()
    project_dir.mkdir()
    window._remember_file_dialog_directory("add_fcs_files", fcs_dir)
    window._remember_file_dialog_directory("open_project", project_dir)

    assert window._file_dialog_directory("add_fcs_files") == str(fcs_dir.resolve())
    assert window._file_dialog_directory("open_project") == str(project_dir.resolve())
    assert window._file_dialog_directory("add_fcs_directory") == str(Path.cwd())
  finally:
    for key, value in previous.items():
      if value is None:
        settings.remove(key)
      else:
        settings.setValue(key, value)
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_file_dialog_history_uses_existing_fallback_and_parent_for_file(
  qapp, tmp_path: Path,
) -> None:
  window = MainWindow()
  key = window._FILE_DIALOG_DIRECTORY_KEYS["save_project"]
  settings = QSettings()
  previous = settings.value(key, None)
  try:
    settings.remove(key)
    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    selected_path = project_dir / "analysis.flowdesk"
    window._remember_file_dialog_directory("save_project", selected_path)

    assert window._file_dialog_directory("save_project") == str(project_dir.resolve())

    settings.setValue(key, str(tmp_path / "missing"))
    assert window._file_dialog_directory("save_project", project_dir) == str(
      project_dir.resolve()
    )
  finally:
    if previous is None:
      settings.remove(key)
    else:
      settings.setValue(key, previous)
    window.close()
    window.deleteLater()
    qapp.processEvents()
