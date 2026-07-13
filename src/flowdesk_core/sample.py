"""Sample-specific immutable event and channel data."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.channels import (
  channel_index_by_id,
  resolve_channel_index,
  validate_unique_channel_ids,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ChannelSpec


class InvalidSampleDataError(FlowdeskError):
  """Raised when an event matrix and its sample metadata are inconsistent."""


@dataclass(frozen=True)
class SampleData:
  """Raw events paired with the ordered channel identity for one sample."""

  sample_id: str
  events: NDArray[np.float64]
  channels: tuple[ChannelSpec, ...]

  def __post_init__(self) -> None:
    events = np.array(self.events, copy=True)
    channels = tuple(self.channels)
    if events.ndim != 2:
      raise InvalidSampleDataError(
        f"sample {self.sample_id!r} events must be a 2-D array, got {events.ndim}-D"
      )
    if events.shape[1] != len(channels):
      raise InvalidSampleDataError(
        f"sample {self.sample_id!r} has {events.shape[1]} event columns but "
        f"{len(channels)} channels"
      )
    validate_unique_channel_ids(channels, sample_id=self.sample_id)
    events.setflags(write=False)
    object.__setattr__(self, "events", events)
    object.__setattr__(self, "channels", channels)

  @property
  def event_count(self) -> int:
    """Number of raw events in this sample."""
    return int(self.events.shape[0])

  @property
  def channel_count(self) -> int:
    """Number of ordered event columns in this sample."""
    return len(self.channels)

  def channel_index(self, channel_id: str) -> int:
    """Return an event-column index using only an exact stable channel ID."""
    return channel_index_by_id(
      self.channels,
      channel_id,
      sample_id=self.sample_id,
    )

  def channel_by_id(self, channel_id: str) -> ChannelSpec:
    """Return channel metadata using only an exact stable channel ID."""
    return self.channels[self.channel_index(channel_id)]

  def resolve_channel_index(self, reference: str) -> int:
    """Resolve a stable ID or an unambiguous original FCS label."""
    return resolve_channel_index(
      self.channels,
      reference,
      sample_id=self.sample_id,
    )
