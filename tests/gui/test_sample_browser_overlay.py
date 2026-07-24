from __future__ import annotations

import pytest

from flowdesk_qt.sample_browser import SampleBrowser

pytestmark = pytest.mark.gui


def test_clear_overlay_color_removes_only_manual_color(qapp) -> None:
  browser = SampleBrowser()
  states: list[dict[str, object]] = []
  browser.on_overlay_changed(states.append)
  browser._manual_overlay_sample_ids = {"sample-a"}
  browser._manual_overlay_colors = {"sample-a": "#123456"}
  browser._overlay_roles = {"sample-a": "positive_control"}

  browser._clear_overlay_color("sample-a")

  state = browser.overlay_state()
  assert state["manual_overlay_sample_ids"] == ["sample-a"]
  assert state["manual_overlay_colors"] == {}
  assert state["overlay_roles"] == {"sample-a": "positive_control"}
  assert states[-1] == state
  browser.close()
  browser.deleteLater()
  qapp.processEvents()


def test_default_overlay_color_is_available_for_sample_row(qapp) -> None:
  browser = SampleBrowser()
  try:
    assert browser.overlay_color("unknown") == "#4c78a8"
  finally:
    browser.close()
    browser.deleteLater()
    qapp.processEvents()
