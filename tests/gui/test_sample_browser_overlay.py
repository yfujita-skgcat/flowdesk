from __future__ import annotations

import pytest

from flowdesk_qt.sample_browser import SampleBrowser, _SampleInfo

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


def test_overlay_state_follows_sample_list_order(qapp) -> None:
  browser = SampleBrowser()
  try:
    browser._samples = [
      _SampleInfo("top", "Top", "top.fcs", None),
      _SampleInfo("bottom", "Bottom", "bottom.fcs", None),
    ]
    browser._manual_overlay_sample_ids = {"top", "bottom"}
    assert browser.overlay_state()["manual_overlay_sample_ids"] == ["top", "bottom"]
  finally:
    browser.close()
    browser.deleteLater()
    qapp.processEvents()
