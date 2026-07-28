"""Renderer-neutral contract for lightweight vector scatter export.

This module deliberately contains no Qt, SVG, PDF, or raster writer code.  It
defines the immutable event/style plan that all format adapters will consume.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
  from flowdesk_core.plot_export import ExportCanvasSpec

VectorScatterMode = Literal["full_vector", "compact_vector", "hybrid_raster"]
Point = tuple[float, float]
COMPACT_VECTOR_CHUNK_POINTS = 4096


@dataclass(frozen=True)
class VectorScatterLayer:
  """One ordered source layer with immutable display points and style."""

  source_id: str
  points: tuple[Point, ...]
  color: str = "#000000"
  alpha: float = 1.0
  marker_shape: str = "circle"
  marker_size: float = 1.5
  z_index: int = 0

  def __post_init__(self) -> None:
    if not self.source_id:
      raise ValueError("vector scatter source_id is required")
    if not self.color:
      raise ValueError("vector scatter color is required")
    if not 0.0 <= self.alpha <= 1.0 or not math.isfinite(self.alpha):
      raise ValueError("vector scatter alpha must be finite and between 0 and 1")
    if self.marker_size <= 0 or not math.isfinite(self.marker_size):
      raise ValueError("vector scatter marker_size must be positive and finite")
    for point in self.points:
      if len(point) != 2 or not all(math.isfinite(value) for value in point):
        raise ValueError("vector scatter points must contain finite x/y pairs")

  def to_mapping(self) -> dict[str, Any]:
    return {
      "source_id": self.source_id,
      "points": [[x, y] for x, y in self.points],
      "style": {
        "color": self.color,
        "alpha": self.alpha,
        "marker_shape": self.marker_shape,
        "marker_size": self.marker_size,
        "z_index": self.z_index,
      },
    }


@dataclass(frozen=True)
class VectorScatterPlan:
  """Deterministic scatter representation shared by SVG, PDF, and hybrid writers."""

  mode: VectorScatterMode
  logical_canvas: "ExportCanvasSpec"
  clip_rect: tuple[float, float, float, float]
  source_order: tuple[str, ...]
  layers: tuple[VectorScatterLayer, ...]
  sampling_identity: str
  algorithm_version: str = "vector_scatter_plan.v1"
  input_event_count: int | None = None
  hybrid_scatter_dpi: int | None = None

  def __post_init__(self) -> None:
    if self.mode not in {"full_vector", "compact_vector", "hybrid_raster"}:
      raise ValueError(f"invalid vector scatter mode {self.mode!r}")
    if len(self.clip_rect) != 4 or not all(
      math.isfinite(value) for value in self.clip_rect
    ):
      raise ValueError("vector scatter clip_rect must contain four finite values")
    if self.clip_rect[2] <= 0 or self.clip_rect[3] <= 0:
      raise ValueError("vector scatter clip_rect width and height must be positive")
    if not self.sampling_identity or not self.algorithm_version:
      raise ValueError("vector scatter identity and algorithm version are required")
    if self.source_order != tuple(layer.source_id for layer in self.layers):
      raise ValueError("source_order must exactly match layer order")
    if len(set(self.source_order)) != len(self.source_order):
      raise ValueError("vector scatter source IDs must be unique")
    rendered_count = sum(len(layer.points) for layer in self.layers)
    if self.input_event_count is not None and self.input_event_count < rendered_count:
      raise ValueError("input_event_count cannot be less than rendered point count")
    if self.mode == "hybrid_raster":
      if self.hybrid_scatter_dpi is None or not 72 <= self.hybrid_scatter_dpi <= 2400:
        raise ValueError("hybrid_raster requires hybrid_scatter_dpi between 72 and 2400")
    elif self.hybrid_scatter_dpi is not None:
      raise ValueError("hybrid_scatter_dpi is only valid for hybrid_raster")

  @property
  def rendered_event_count(self) -> int:
    return sum(len(layer.points) for layer in self.layers)

  def to_mapping(self) -> dict[str, Any]:
    return {
      "mode": self.mode,
      "logical_canvas": self.logical_canvas.to_mapping(),
      "clip_rect": list(self.clip_rect),
      "source_order": list(self.source_order),
      "layers": [layer.to_mapping() for layer in self.layers],
      "input_event_count": self.input_event_count,
      "rendered_event_count": self.rendered_event_count,
      "sampling_identity": self.sampling_identity,
      "algorithm_version": self.algorithm_version,
      "hybrid_scatter_dpi": self.hybrid_scatter_dpi,
    }

  def plan_hash(self) -> str:
    canonical = json.dumps(
      self.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

  def provenance_mapping(self) -> dict[str, Any]:
    return {
      "requested_mode": self.mode,
      "resolved_mode": self.mode,
      "algorithm_version": self.algorithm_version,
      "input_event_count": self.input_event_count,
      "rendered_event_count": self.rendered_event_count,
      "sampling_identity": self.sampling_identity,
      "point_plan_hash": self.plan_hash(),
      "scatter_image_dpi": self.hybrid_scatter_dpi,
      "source_order": list(self.source_order),
    }


@dataclass(frozen=True)
class CompactScatterBatch:
  """A non-overlapping compound-path batch for one source/style."""

  source_id: str
  points: tuple[Point, ...]
  color: str
  alpha: float
  marker_shape: str
  marker_size: float
  z_index: int
  batch_key: tuple[int, int, int]


@dataclass(frozen=True)
class VectorScatterPreflight:
  """Structured resource estimate; it never changes the requested mode."""

  mode: VectorScatterMode
  rendered_event_count: int | None
  estimated_placements: int | None
  estimated_paths: int | None
  raster_width: int | None
  raster_height: int | None
  estimated_memory_bytes: int
  status: Literal["ok", "warning", "failed"]
  diagnostics: tuple[dict[str, Any], ...] = ()

  def to_mapping(self) -> dict[str, Any]:
    return {
      "mode": self.mode,
      "rendered_event_count": self.rendered_event_count,
      "estimated_placements": self.estimated_placements,
      "estimated_paths": self.estimated_paths,
      "raster_width": self.raster_width,
      "raster_height": self.raster_height,
      "estimated_memory_bytes": self.estimated_memory_bytes,
      "status": self.status,
      "diagnostics": [dict(item) for item in self.diagnostics],
    }


def preflight_vector_scatter_export(
  spec: Any,
  *,
  rendered_event_count: int | None,
  logical_plot_width: float,
  logical_plot_height: float,
  estimated_compact_paths: int | None = None,
  max_events: int = 2_000_000,
  max_paths: int = 1_000_000,
  max_raster_pixels: int = 100_000_000,
  max_memory_bytes: int = 512 * 1024 * 1024,
) -> VectorScatterPreflight:
  """Estimate output resources and return explicit structured diagnostics."""
  mode = spec.vector_scatter_mode
  count = rendered_event_count
  placements = count
  paths = count if mode == "full_vector" else (
    estimated_compact_paths if estimated_compact_paths is not None else count
  )
  raster_width = raster_height = None
  memory = 0
  diagnostics: list[dict[str, Any]] = []
  if mode == "hybrid_raster":
    raster_scale = spec.hybrid_scatter_dpi / 96.0
    raster_width = max(1, round(logical_plot_width * raster_scale))
    raster_height = max(1, round(logical_plot_height * raster_scale))
    pixels = raster_width * raster_height
    memory = pixels * 4 + max(pixels // 2, 1024)
    if pixels > max_raster_pixels:
      diagnostics.append({
        "code": "hybrid_raster_pixels_exceeded", "severity": "error",
        "message": "hybrid scatter raster exceeds the configured pixel limit",
        "value": pixels, "limit": max_raster_pixels,
      })
  elif count is not None:
    # Conservative estimates are used until the renderer has built its exact
    # compact batches; this never authorizes an automatic mode change.
    memory = count * (64 if mode == "full_vector" else 32)
  if count is not None and count > max_events:
    diagnostics.append({
      "code": "scatter_events_exceeded", "severity": "error",
      "message": "rendered event count exceeds the configured preflight limit",
      "value": count, "limit": max_events,
    })
  if paths is not None and paths > max_paths:
    diagnostics.append({
      "code": "vector_paths_exceeded", "severity": "error",
      "message": "estimated vector path/placement count exceeds the configured limit",
      "value": paths, "limit": max_paths,
    })
  if memory > max_memory_bytes:
    diagnostics.append({
      "code": "scatter_memory_exceeded", "severity": "error",
      "message": "estimated scatter memory exceeds the configured limit",
      "value": memory, "limit": max_memory_bytes,
    })
  status: Literal["ok", "warning", "failed"] = "failed" if diagnostics else "ok"
  return VectorScatterPreflight(
    mode, count, placements, paths, raster_width, raster_height, memory, status,
    tuple(diagnostics),
  )


def compact_scatter_batches(
  layers: tuple[VectorScatterLayer, ...],
  *,
  plot_width: float,
  plot_height: float,
) -> tuple[CompactScatterBatch, ...]:
  """Partition markers into deterministic, non-overlapping compound batches.

  A 3x3 residue class separates neighboring spatial cells by at least two
  marker diameters. Points sharing a cell receive distinct slots, preserving
  repeated source-over alpha instead of unioning their geometry.
  """
  if plot_width <= 0 or plot_height <= 0:
    raise ValueError("compact scatter plot dimensions must be positive")
  result: list[CompactScatterBatch] = []
  for layer in layers:
    cell_size = max(layer.marker_size, 1e-9)
    grouped: dict[tuple[int, int, int], list[Point]] = {}
    cell_counts: dict[tuple[int, int], int] = {}
    for point in layer.points:
      cell = (
        math.floor(point[0] * plot_width / cell_size),
        math.floor(point[1] * plot_height / cell_size),
      )
      slot = cell_counts.get(cell, 0)
      cell_counts[cell] = slot + 1
      key = (cell[0] % 3, cell[1] % 3, slot)
      grouped.setdefault(key, []).append(point)
    for key in sorted(grouped):
      points = grouped[key]
      for chunk_index in range(0, len(points), COMPACT_VECTOR_CHUNK_POINTS):
        chunk = tuple(points[chunk_index:chunk_index + COMPACT_VECTOR_CHUNK_POINTS])
        result.append(CompactScatterBatch(
          source_id=layer.source_id,
          points=chunk,
          color=layer.color,
          alpha=layer.alpha,
          marker_shape=layer.marker_shape,
          marker_size=layer.marker_size,
          z_index=layer.z_index,
          batch_key=(key[0], key[1], key[2] * COMPACT_VECTOR_CHUNK_POINTS + chunk_index // COMPACT_VECTOR_CHUNK_POINTS),
        ))
  return tuple(result)


def build_vector_scatter_plan(
  *,
  mode: VectorScatterMode,
  logical_canvas: "ExportCanvasSpec",
  clip_rect: tuple[float, float, float, float],
  layers: tuple[VectorScatterLayer, ...],
  sampling_identity: str,
  input_event_count: int | None = None,
  hybrid_scatter_dpi: int = 600,
  algorithm_version: str = "vector_scatter_plan.v1",
) -> VectorScatterPlan:
  """Build a validated plan while preserving source and point ordering."""
  return VectorScatterPlan(
    mode=mode,
    logical_canvas=logical_canvas,
    clip_rect=clip_rect,
    source_order=tuple(layer.source_id for layer in layers),
    layers=layers,
    sampling_identity=sampling_identity,
    algorithm_version=algorithm_version,
    input_event_count=input_event_count,
    hybrid_scatter_dpi=hybrid_scatter_dpi if mode == "hybrid_raster" else None,
  )
