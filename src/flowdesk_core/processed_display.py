"""Immutable GUI-independent request/result contracts for processed plot data."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.execution_report import ExecutionDiagnostic
from flowdesk_core.models import ChannelSpec
from flowdesk_core.preview import PreviewReport
from flowdesk_core.sample import SampleData


@dataclass(frozen=True)
class ProcessedDisplayRequest:
  """Request one processed sample view from the canonical pipeline stages."""

  revision: int
  sample: SampleData
  population_id: str
  x_parameter_id: str
  y_parameter_id: str | None = None
  x_transform_id: str | None = None
  y_transform_id: str | None = None
  execution_profile_id: str = "default"
  plot_type: str = "scatter"
  display_max_points: int = 20_000

  def __post_init__(self) -> None:
    if self.revision < 0:
      raise ValueError("display revision must be non-negative")
    if not self.population_id or not self.x_parameter_id:
      raise ValueError("display population and X parameter IDs must be non-empty")
    if not self.execution_profile_id:
      raise ValueError("display execution profile ID must be non-empty")
    if self.display_max_points < 0:
      raise ValueError("display max points must be non-negative")

  @property
  def sample_id(self) -> str:
    """Stable sample identity carried by the immutable typed input."""
    return self.sample.sample_id


@dataclass(frozen=True)
class ProcessedDisplayResult:
  """Immutable processed event view plus matching full-resolution membership."""

  revision: int
  sample_id: str
  population_id: str
  x_parameter_id: str
  y_parameter_id: str | None
  x_transform_id: str | None
  y_transform_id: str | None
  plot_type: str
  display_max_points: int
  events: NDArray[np.float64]
  channels: tuple[ChannelSpec, ...]
  display_mask: NDArray[np.bool_]
  preview_report: PreviewReport
  diagnostics: tuple[ExecutionDiagnostic, ...] = ()

  def __post_init__(self) -> None:
    if not self.x_parameter_id:
      raise ValueError("processed display X parameter ID must be non-empty")
    if self.display_max_points < 0:
      raise ValueError("processed display max points must be non-negative")
    events = np.array(self.events, dtype=np.float64, copy=True, order="C")
    if events.ndim != 2 or events.shape[1] != len(self.channels):
      raise ValueError("processed display events must align with channels")
    mask = np.array(self.display_mask, dtype=np.bool_, copy=True)
    if mask.ndim != 1 or len(mask) != len(events):
      raise ValueError("processed display mask must align with events")
    events.setflags(write=False)
    mask.setflags(write=False)
    object.__setattr__(self, "events", events)
    object.__setattr__(self, "display_mask", mask)

  def channel_index(self, parameter_id: str) -> int:
    for index, channel in enumerate(self.channels):
      if channel.id == parameter_id:
        return index
    raise KeyError(parameter_id)
