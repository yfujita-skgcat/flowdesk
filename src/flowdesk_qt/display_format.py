"""Presentation-only numeric formatting for Qt result views."""

from __future__ import annotations

import math


def format_display_number(value: float | int) -> str:
  """Format a number with all integer digits and at most ten total digits."""
  numeric = float(value)
  if not math.isfinite(numeric):
    return str(value)
  integer_digits = len(str(abs(int(numeric))))
  decimals = max(0, 10 - integer_digits)
  rendered = f"{numeric:.{decimals}f}"
  if "." in rendered:
    rendered = rendered.rstrip("0").rstrip(".")
  return rendered


def format_percentage(value: float | None) -> str:
  """Format a 0..1 fraction as percentage numbers with at most two decimals."""
  if value is None:
    return "-"
  rendered = f"{float(value) * 100:.2f}".rstrip("0").rstrip(".")
  return rendered
