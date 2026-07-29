from __future__ import annotations

import numpy as np

from flowdesk_core.density_colors import density_event_colors


def test_density_colors_are_deterministic_and_reward_local_occupancy() -> None:
  x = np.array([0.1, 0.1, 0.1, 0.9])
  y = np.array([0.1, 0.1, 0.1, 0.9])

  colors = density_event_colors(x, y, bins=8)

  assert colors.tolist()[:3] == ["#ed1c24"] * 3
  assert colors.tolist()[3] == "#1f3cff"
  assert np.array_equal(colors, density_event_colors(x, y, bins=8))


def test_density_colors_handle_nonfinite_and_degenerate_coordinates() -> None:
  assert density_event_colors(
    np.array([np.nan, np.inf]), np.array([1.0, 2.0])
  ).tolist() == ["#1f3cff", "#1f3cff"]
  assert density_event_colors(
    np.array([1.0, 1.0]), np.array([2.0, 2.0])
  ).tolist() == ["#ed1c24", "#ed1c24"]
