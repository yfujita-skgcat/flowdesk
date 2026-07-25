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
    background_color: str = "#ffffff"

    # Dot appearance
    dot_color: str = "#000000"
    selected_dot_color: str = "#e00000"
    dot_size: float = 1.5
    dot_opacity: float = 0.60

    # Gate overlay appearance
    gate_outline_color: str = "#e00000"
    gate_fill_color: str = "#e00000"
    gate_fill_opacity: float = 0.0

    # Axis and tick readability
    axis_line_width: float = 2.0
    tick_font_family: str = "DejaVu Sans"
    tick_font_size: float = 10.0
    tick_font_weight: str = "bold"

    # Optional features
    show_grid: bool = True

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
                self.axis_line_width,
                self.tick_font_family,
                self.tick_font_size,
                self.tick_font_weight,
                self.show_grid,
                self.use_robust_range,
            )
        )
