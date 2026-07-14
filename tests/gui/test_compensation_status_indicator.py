"""Tests for the compensation status indicator in the main window.

Verifies that the status bar displays the correct compensation badge and
stale status based on the current project state.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from flowdesk_qt.main_window import _CompensationStatusIndicator


@pytest.fixture
def indicator(qapp: QApplication) -> _CompensationStatusIndicator:
    return _CompensationStatusIndicator()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_indicator_starts_with_none(indicator: _CompensationStatusIndicator) -> None:
    text = indicator._label.text()
    assert "none" in text.lower()
    assert "(stale)" not in text


# ---------------------------------------------------------------------------
# Valid matrix state
# ---------------------------------------------------------------------------


def test_indicator_shows_valid_matrix(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("My Matrix")
    text = indicator._label.text()
    assert "My Matrix" in text
    assert "🟢" in text
    assert "(stale)" not in text


def test_indicator_shows_valid_matrix_stale(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("My Matrix", stale=True)
    text = indicator._label.text()
    assert "My Matrix" in text
    assert "🟢" in text
    assert "(stale)" in text


# ---------------------------------------------------------------------------
# Warning (ill-conditioned) state
# ---------------------------------------------------------------------------


def test_indicator_shows_warning(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_warning("Ill Matrix", condition_number=1e10)
    text = indicator._label.text()
    assert "Ill Matrix" in text
    assert "🟡" in text
    assert "cond=" in text


def test_indicator_shows_warning_stale(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_warning("Ill Matrix", condition_number=1e10, stale=True)
    text = indicator._label.text()
    assert "(stale)" in text


# ---------------------------------------------------------------------------
# None state
# ---------------------------------------------------------------------------


def test_indicator_shows_none(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_none()
    text = indicator._label.text()
    assert "none" in text.lower()
    assert "🔴" in text


def test_indicator_shows_none_stale(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_none(stale=True)
    text = indicator._label.text()
    assert "(stale)" in text


# ---------------------------------------------------------------------------
# Error state
# ---------------------------------------------------------------------------


def test_indicator_shows_error(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_error("Singular matrix")
    text = indicator._label.text()
    assert "Singular matrix" in text
    assert "⚠️" in text


def test_indicator_shows_error_stale(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_error("Singular matrix", stale=True)
    text = indicator._label.text()
    assert "(stale)" in text


# ---------------------------------------------------------------------------
# Stale marker operations
# ---------------------------------------------------------------------------


def test_mark_stale_adds_marker(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("Good Matrix")
    assert "(stale)" not in indicator._label.text()
    indicator.mark_stale()
    assert "(stale)" in indicator._label.text()


def test_clear_stale_removes_marker(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("Good Matrix")
    indicator.mark_stale()
    assert "(stale)" in indicator._label.text()
    indicator.clear_stale()
    assert "(stale)" not in indicator._label.text()


def test_mark_stale_is_idempotent(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("Good Matrix")
    indicator.mark_stale()
    indicator.mark_stale()
    text = indicator._label.text()
    # Should have exactly one stale marker
    assert text.count("(stale)") == 1


def test_clear_stale_when_not_stale_is_noop(indicator: _CompensationStatusIndicator) -> None:
    indicator.set_valid("Good Matrix")
    original = indicator._label.text()
    indicator.clear_stale()
    assert indicator._label.text() == original
