"""B7.4 menu ownership and unfinished-feature guard tests."""

from __future__ import annotations

import pytest

from flowdesk_qt.main_window import MainWindow

pytestmark = pytest.mark.gui


def _menu_action_texts(window: MainWindow, title: str) -> list[str]:
  for action in window.menuBar().actions():
    menu = action.menu()
    if menu is not None and menu.title() == title:
      return [item.text() for item in menu.actions() if not item.isSeparator()]
  raise AssertionError(f"menu not found: {title}")


def test_analysis_workflow_actions_have_one_menu_owner(qapp) -> None:
  window = MainWindow()
  try:
    analysis = _menu_action_texts(window, "&Analysis")
    results = _menu_action_texts(window, "&Results")
    data = _menu_action_texts(window, "&Data")
    plot = _menu_action_texts(window, "&Plot")

    assert "Manage Parameter &Transforms..." in analysis
    assert "Population &Statistics..." not in analysis
    assert "Sample &Annotations..." not in analysis
    assert "Sample &Sheet..." not in analysis
    assert "Overlay &Sources..." not in analysis
    assert "&Add Statistic..." in results
    assert "Manage &Statistics..." in results
    assert "Batch Plot E&xport..." in results
    assert "Sample &Sheet..." in data
    assert "Channel / Parameter &Information" in data
    assert "Overlay &Samples" in plot
    assert "Advanced Overlay Sources... (Not implemented)" in plot
    assert "Plot &Presentation..." in plot
  finally:
    window.close()
    window.deleteLater()


def test_advanced_overlay_is_disabled_and_does_not_mutate_project(qapp) -> None:
  window = MainWindow()
  try:
    before = window._build_project_manifest()
    revision = window.analysis_revision

    assert window.action_overlay_sources.objectName() == "actionOverlaySources"
    assert window.action_overlay_sources.isVisible()
    assert not window.action_overlay_sources.isEnabled()
    assert "not implemented" in window.action_overlay_sources.toolTip().lower()

    window.action_overlay_samples.trigger()

    assert window._build_project_manifest() == before
    assert window.analysis_revision == revision
    assert "Samples pane Ov column" in window.statusBar().currentMessage()
  finally:
    window.close()
    window.deleteLater()


def test_release_build_hides_unfinished_advanced_overlay(qapp, monkeypatch) -> None:
  monkeypatch.setenv("FLOWDESK_BUILD_CHANNEL", "release")
  window = MainWindow()
  try:
    assert not window.action_overlay_sources.isVisible()
    assert not window.action_overlay_sources.isEnabled()
  finally:
    window.close()
    window.deleteLater()
