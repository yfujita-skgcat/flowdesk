"""Immutable, renderer-neutral plot scene contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class PlotScene:
  """Validated display scene shared by GUI and headless renderers.

  This is presentation data only. It contains no raw event arrays, gate
  membership, population counts, or analytical results.
  """

  x_parameter: str = ""
  y_parameter: str | None = None
  x_transform_id: str | None = None
  y_transform_id: str | None = None
  view_range: tuple[tuple[float, float], tuple[float, float]] | None = None
  plot_area: tuple[float, float, float, float] = (60.0, 50.0, 20.0, 60.0)
  x_ticks: tuple[dict[str, Any], ...] = ()
  y_ticks: tuple[dict[str, Any], ...] = ()
  title_lines: tuple[str, ...] = ()
  layout_title_line_count: int | None = None
  title_baseline_y: float | None = None
  title_colors: tuple[str, ...] = ()
  x_axis_label: str = ""
  y_axis_label: str = ""
  source_order: tuple[str, ...] = ()
  gates: tuple[dict[str, Any], ...] = ()
  clip_to_plot_area: bool = True
  z_order: tuple[str, ...] = ("grid", "points", "gates", "text")
  font_requests: dict[str, Any] = field(default_factory=dict)

  def __post_init__(self) -> None:
    if any(not isinstance(value, str) or not value for value in self.source_order):
      raise ValueError("plot scene source IDs must be non-empty strings")
    if len(set(self.source_order)) != len(self.source_order):
      raise ValueError("plot scene source IDs must be unique")
    if len(self.plot_area) != 4 or any(float(value) < 0 for value in self.plot_area):
      raise ValueError("plot scene plot area must contain four non-negative margins")
    if self.view_range is not None:
      if len(self.view_range) != 2 or any(len(axis) != 2 for axis in self.view_range):
        raise ValueError("plot scene view range must contain X and Y pairs")
      if any(not isfinite(float(value)) for axis in self.view_range for value in axis):
        raise ValueError("plot scene view range must be finite")
      if any(axis[0] >= axis[1] for axis in self.view_range):
        raise ValueError("plot scene view range must be increasing")
    for axis in (self.x_ticks, self.y_ticks):
      for tick in axis:
        position = tick.get("position")
        if not isinstance(position, (int, float)) or not 0 <= float(position) <= 1:
          raise ValueError("plot scene tick positions must be in [0, 1]")

  @classmethod
  def from_mapping(cls, value: Mapping[str, Any] | None = None) -> PlotScene:
    """Build a scene from JSON-compatible display metadata."""
    raw = dict(value or {})
    raw_range = raw.get("view_range")
    view_range = None
    if raw_range is not None:
      view_range = (
        (float(raw_range[0][0]), float(raw_range[0][1])),
        (float(raw_range[1][0]), float(raw_range[1][1])),
      )
    area = raw.get("plot_area", (60.0, 50.0, 20.0, 60.0))
    return cls(
      x_parameter=str(raw.get("x_parameter", "")),
      y_parameter=None if raw.get("y_parameter") is None else str(raw["y_parameter"]),
      x_transform_id=None if raw.get("x_transform_id") is None else str(raw["x_transform_id"]),
      y_transform_id=None if raw.get("y_transform_id") is None else str(raw["y_transform_id"]),
      view_range=view_range,
      plot_area=tuple(float(item) for item in area),
      x_ticks=tuple(dict(tick) for tick in raw.get("x_ticks", ()) if isinstance(tick, Mapping)),
      y_ticks=tuple(dict(tick) for tick in raw.get("y_ticks", ()) if isinstance(tick, Mapping)),
      title_lines=tuple(str(item) for item in raw.get("title_lines", ()) if str(item)),
      layout_title_line_count=(
        None if raw.get("layout_title_line_count") is None
        else max(1, int(raw["layout_title_line_count"]))
      ),
      title_baseline_y=(
        None if raw.get("title_baseline_y") is None
        else float(raw["title_baseline_y"])
      ),
      title_colors=tuple(str(item) for item in raw.get("title_colors", ())),
      x_axis_label=str(raw.get("x_axis_label", "")),
      y_axis_label=str(raw.get("y_axis_label", "")),
      source_order=tuple(str(item) for item in raw.get("source_order", ())),
      gates=tuple(dict(gate) for gate in raw.get("gates", ()) if isinstance(gate, Mapping)),
      clip_to_plot_area=bool(raw.get("clip_to_plot_area", True)),
      z_order=tuple(str(item) for item in raw.get("z_order", ("grid", "points", "gates", "text"))),
      font_requests=dict(raw.get("font_requests", {})),
    )

  def to_mapping(self) -> dict[str, Any]:
    """Return a stable JSON-compatible representation."""
    return {
      "x_parameter": self.x_parameter,
      "y_parameter": self.y_parameter,
      "x_transform_id": self.x_transform_id,
      "y_transform_id": self.y_transform_id,
      "view_range": None if self.view_range is None else [list(axis) for axis in self.view_range],
      "plot_area": list(self.plot_area),
      "x_ticks": [dict(tick) for tick in self.x_ticks],
      "y_ticks": [dict(tick) for tick in self.y_ticks],
      "title_lines": list(self.title_lines),
      "layout_title_line_count": self.layout_title_line_count,
      "title_baseline_y": self.title_baseline_y,
      "title_colors": list(self.title_colors),
      "x_axis_label": self.x_axis_label,
      "y_axis_label": self.y_axis_label,
      "source_order": list(self.source_order),
      "gates": [dict(gate) for gate in self.gates],
      "clip_to_plot_area": self.clip_to_plot_area,
      "z_order": list(self.z_order),
      "font_requests": dict(self.font_requests),
    }

  def scene_hash(self) -> str:
    """Return a deterministic audit hash for the serialized scene."""
    payload = json.dumps(
      self.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PlotLayoutSpec:
  """Logical layout shared by GUI and format-specific renderers.

  Coordinates use a top-left origin and logical canvas units.  The layout is
  presentation-only: it contains no event coordinates or analytical values.
  ``plot_area`` remains a margin tuple for backwards-compatible scene files;
  this object is the resolved rectangle for one concrete canvas and visibility
  selection.
  """

  canvas_width: int
  canvas_height: int
  margins: tuple[float, float, float, float]
  plot_rect: tuple[float, float, float, float]
  title_block: tuple[float, float, float, float]
  title_baselines: tuple[float, ...]
  title_line_height: float
  x_tick_label_y: float
  y_tick_label_x: float
  x_axis_label_anchor: tuple[float, float]
  y_axis_label_anchor: tuple[float, float]

  def __post_init__(self) -> None:
    if self.canvas_width < 1 or self.canvas_height < 1:
      raise ValueError("plot layout canvas must be positive")
    if (
      len(self.margins) != 4 or len(self.plot_rect) != 4
      or len(self.title_block) != 4
      or len(self.x_axis_label_anchor) != 2
      or len(self.y_axis_label_anchor) != 2
    ):
      raise ValueError("plot layout rectangles must contain four values")
    if self.title_line_height <= 0:
      raise ValueError("plot layout title line height must be positive")
    plot_x, plot_y, plot_width, plot_height = self.plot_rect
    if plot_x < 0 or plot_y < 0 or plot_width <= 0 or plot_height <= 0:
      raise ValueError("plot layout plot rectangle must be positive and in canvas")
    if plot_x + plot_width > self.canvas_width + 1e-6:
      raise ValueError("plot layout plot rectangle exceeds canvas width")
    if plot_y + plot_height > self.canvas_height + 1e-6:
      raise ValueError("plot layout plot rectangle exceeds canvas height")

  def to_mapping(self) -> dict[str, Any]:
    return {
      "canvas_width": self.canvas_width,
      "canvas_height": self.canvas_height,
      "margins": list(self.margins),
      "plot_rect": list(self.plot_rect),
      "title_block": list(self.title_block),
      "title_baselines": list(self.title_baselines),
      "title_line_height": self.title_line_height,
      "x_tick_label_y": self.x_tick_label_y,
      "y_tick_label_x": self.y_tick_label_x,
      "x_axis_label_anchor": list(self.x_axis_label_anchor),
      "y_axis_label_anchor": list(self.y_axis_label_anchor),
    }


def _font_size(presentation: Mapping[str, Any] | None) -> float:
  value = (presentation or {}).get("title_font", {})
  if isinstance(value, Mapping):
    value = value.get("size", 14.0)
  else:
    value = getattr(value, "size", 14.0)
  try:
    return max(1.0, float(value))
  except (TypeError, ValueError):
    return 14.0


def resolve_plot_layout(
  scene: PlotScene,
  presentation: Mapping[str, Any] | None,
  *,
  width: int,
  height: int,
  include_title: bool = True,
  include_axis_labels: bool = True,
  include_ticks: bool = True,
) -> PlotLayoutSpec:
  """Resolve deterministic logical geometry for one rendered plot.

  The title band is derived from the number of non-empty scene title lines,
  not from a fixed y-coordinate.  A minimum top margin captured from the live
  GUI is retained, while an insufficient margin is enlarged so title glyphs
  cannot enter the data rectangle.  Font rasterisation remains backend
  specific; line height and baselines are deliberately backend independent.
  """
  if width < 1 or height < 1:
    raise ValueError("plot layout canvas must be positive")
  raw_left, raw_top, raw_right, raw_bottom = scene.plot_area
  left = max(0.0, float(raw_left))
  right = max(0.0, float(raw_right))
  bottom = max(0.0, float(raw_bottom))
  lines = tuple(line for line in scene.title_lines if str(line))
  layout_line_count = max(
    len(lines), int(scene.layout_title_line_count or 0)
  )
  font_size = _font_size(presentation)
  line_height = max(18.0, font_size * 1.45)
  tick_size = _font_size({"title_font": (presentation or {}).get("tick_font", {})})
  axis_size = _font_size({"title_font": (presentation or {}).get("axis_label_font", {})})
  # Leave enough room for the actual Qt/Pillow glyph descent.  The previous
  # four-pixel band padding was sufficient for the old unscaled export fonts
  # but allowed the final bold title line to touch the plot frame after the
  # Qt point-to-pixel conversion.
  title_height = (
    line_height * layout_line_count + 14.0
    if include_title and layout_line_count else 0.0
  )
  title_top_padding = 10.0 if title_height else 0.0
  top = max(0.0, float(raw_top))
  if title_height:
    top = max(top, title_height + title_top_padding)
  if include_ticks:
    left = max(left, 1.0)
    bottom = max(bottom, 1.0)
  plot_width = max(1.0, float(width) - left - right)
  plot_height = max(1.0, float(height) - top - bottom)
  title_block_height = max(0.0, top - title_top_padding)
  title_block = (0.0, 0.0, float(width), title_block_height)
  title_baselines = tuple(
    title_block_height - line_height * (layout_line_count - index - 0.35)
    for index in range(layout_line_count)
  )
  if scene.title_baseline_y is not None and title_baselines:
    baseline_shift = float(scene.title_baseline_y) - title_baselines[0]
    title_baselines = tuple(value + baseline_shift for value in title_baselines)
  # Keep tick labels close to the frame; the previous full tick-font-size
  # plus nine-pixel offset was tuned for the old smaller export glyphs.
  x_tick_label_y = top + plot_height + tick_size * 0.6 + 4.0
  y_tick_label_x = left - 9.0
  x_axis_label_anchor = (
    left + plot_width / 2.0,
    x_tick_label_y + axis_size * 1.5 + 4.0,
  )
  y_axis_label_anchor = (
    # Major tick labels can be several characters wide (e.g. ``10⁷``).
    # Reserve a separate column so the rotated axis label cannot overlap them.
    left - tick_size * 5.5,
    top + plot_height / 2.0,
  )
  return PlotLayoutSpec(
    canvas_width=int(width), canvas_height=int(height),
    margins=(left, top, right, bottom),
    plot_rect=(left, top, plot_width, plot_height),
    title_block=title_block,
    title_baselines=title_baselines,
    title_line_height=line_height,
    x_tick_label_y=x_tick_label_y,
    y_tick_label_x=y_tick_label_x,
    x_axis_label_anchor=x_axis_label_anchor,
    y_axis_label_anchor=y_axis_label_anchor,
  )
POINTS_TO_PX = 96.0 / 72.0
