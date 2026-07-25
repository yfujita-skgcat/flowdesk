"""Immutable, renderer-neutral plot scene contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from math import isfinite
from typing import Any, Mapping


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
  def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "PlotScene":
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
