"""Stable channel identity validation and lookup helpers."""

from __future__ import annotations

from collections.abc import Sequence

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ChannelSpec


class ChannelIdentityError(FlowdeskError):
  """Base error for invalid or unresolved channel identity."""


class DuplicateChannelIdError(ChannelIdentityError):
  """Raised when a sample contains the same stable channel ID more than once."""

  def __init__(self, sample_id: str, channel_id: str) -> None:
    self.sample_id = sample_id
    self.channel_id = channel_id
    super().__init__(
      f"sample {sample_id!r} contains duplicate channel ID {channel_id!r}"
    )


class ChannelNotFoundError(ChannelIdentityError):
  """Raised when no stable ID or visible channel label matches a reference."""

  def __init__(self, sample_id: str, reference: str) -> None:
    self.sample_id = sample_id
    self.reference = reference
    super().__init__(
      f"sample {sample_id!r} has no channel matching {reference!r}"
    )


class AmbiguousChannelReferenceError(ChannelIdentityError):
  """Raised instead of silently choosing among duplicate visible labels."""

  def __init__(
    self,
    sample_id: str,
    reference: str,
    candidate_ids: tuple[str, ...],
  ) -> None:
    self.sample_id = sample_id
    self.reference = reference
    self.candidate_ids = candidate_ids
    candidates = ", ".join(repr(candidate) for candidate in candidate_ids)
    super().__init__(
      f"channel reference {reference!r} is ambiguous in sample {sample_id!r}; "
      f"candidate IDs: {candidates}"
    )


def validate_unique_channel_ids(
  channels: Sequence[ChannelSpec],
  *,
  sample_id: str,
) -> None:
  """Validate that stable channel IDs are unique within one sample."""
  seen: set[str] = set()
  for channel in channels:
    if channel.id in seen:
      raise DuplicateChannelIdError(sample_id, channel.id)
    seen.add(channel.id)


def channel_index_by_id(
  channels: Sequence[ChannelSpec],
  channel_id: str,
  *,
  sample_id: str,
) -> int:
  """Return the event-column index for an exact stable channel ID."""
  for index, channel in enumerate(channels):
    if channel.id == channel_id:
      return index
  raise ChannelNotFoundError(sample_id, channel_id)


def resolve_channel_index(
  channels: Sequence[ChannelSpec],
  reference: str,
  *,
  sample_id: str,
) -> int:
  """Resolve an ID, ``$PnN`` name, or ``$PnS`` short name without guessing."""
  for index, channel in enumerate(channels):
    if channel.id == reference:
      return index

  candidates = tuple(
    (index, channel.id)
    for index, channel in enumerate(channels)
    if reference == channel.name or reference == channel.short_name
  )
  if not candidates:
    raise ChannelNotFoundError(sample_id, reference)
  if len(candidates) > 1:
    raise AmbiguousChannelReferenceError(
      sample_id,
      reference,
      tuple(channel_id for _, channel_id in candidates),
    )
  return candidates[0][0]
