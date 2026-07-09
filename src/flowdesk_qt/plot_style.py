"""Plot display style settings.

These settings control only the visual appearance of the scatter plot.
Changing them must NEVER affect gate membership, population counts, or
any other analytical result.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlotStyleSettings:
    """GUI-local display settings for the scatter plot.

    All fields are display-only.  They do not affect analytical results.
    """

    # Background
    background_color: str = "#000000"

    # Dot appearance
    dot_color: str = "#b8c7ff"
    selected_dot_color: str = "#ffffff"
    dot_size: float = 3.0
    dot_opacity: float = 0.75

    # Gate overlay appearance
    gate_outline_color: str = "#ffff00"
    gate_fill_color: str = "#ffff00"
    gate_fill_opacity: float = 0.0

    # Optional features
    show_grid: bool = False

    # Viewport behaviour
    use_robust_range: bool = True

    def __hash__(self) -> int:
        """Allow storage in sets / dicts if needed."""
        return hash(
            (
                self.background_color,
                self.dot_color,
                self.selected_dot_color,
                self.dot_size,
                self.dot_opacity,
                self.gate_outline_color,
                self.gate_fill_color,
                self.gate_fill_opacity,
                self.show_grid,
                self.use_robust_range,
            )
        )
