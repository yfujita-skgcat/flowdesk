"""Tests for shared Flowdesk credit information."""

from flowdesk_core.credits import credits_text


def test_credits_include_owner_contact_year_and_license() -> None:
  text = credits_text()
  assert "Yoshihiko Fujita" in text
  assert "yfujita.skgcat@gmail.com" in text
  assert "2026" in text
  assert "BSD 3-Clause License" in text
