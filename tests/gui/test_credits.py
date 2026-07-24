"""GUI exposure of the shared credit information."""

import pytest

from flowdesk_qt.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_help_menu_exposes_credits_action(qapp) -> None:
  window = MainWindow()
  try:
    action = window.findChild(type(window.action_save_project), "actionCredits")
    assert action is not None
    assert action.text() == "&Credits..."
  finally:
    window.close()
    window.deleteLater()
