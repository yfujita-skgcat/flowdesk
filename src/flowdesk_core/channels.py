"""Stable channel identity validation and lookup helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ChannelSpec


class ChannelIdentityError(FlowdeskError):
  """Base error for invalid or unresolved channel identity."""

  code = "channel_identity_error"

  def __init__(self, message: str, **context: Any) -> None:
    self.context = context
    super().__init__(message)

  def to_mapping(self) -> dict[str, Any]:
    """Return a stable machine-readable representation."""
    return {"code": self.code, "message": str(self), **self.context}


class DuplicateChannelIdError(ChannelIdentityError):
  """Raised when a sample contains the same stable channel ID more than once."""

  code = "duplicate_channel_id"

  def __init__(self, sample_id: str, channel_id: str) -> None:
    self.sample_id = sample_id
    self.channel_id = channel_id
    super().__init__(
      f"sample {sample_id!r} contains duplicate channel ID {channel_id!r}",
      sample_id=sample_id,
      channel_id=channel_id,
    )


class ChannelNotFoundError(ChannelIdentityError):
  """Raised when no stable ID or visible channel label matches a reference."""

  code = "channel_not_found"

  def __init__(self, sample_id: str, reference: str) -> None:
    self.sample_id = sample_id
    self.reference = reference
    super().__init__(
      f"sample {sample_id!r} has no channel matching {reference!r}",
      sample_id=sample_id,
      reference=reference,
    )


class AmbiguousChannelReferenceError(ChannelIdentityError):
  """Raised instead of silently choosing among duplicate visible labels."""

  code = "ambiguous_channel_reference"

  def __init__(
    self,
    sample_id: str,
    reference: str,
    candidate_ids: tuple[str, ...],
    matching_fields: tuple[tuple[str, tuple[str, ...]], ...] = (),
  ) -> None:
    self.sample_id = sample_id
    self.reference = reference
    self.candidate_ids = candidate_ids
    self.matching_fields = matching_fields
    candidates = ", ".join(repr(candidate) for candidate in candidate_ids)
    super().__init__(
      f"channel reference {reference!r} is ambiguous in sample {sample_id!r}; "
      f"candidate IDs: {candidates}",
      sample_id=sample_id,
      reference=reference,
      candidate_ids=candidate_ids,
      matching_fields=matching_fields,
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

  candidates = []
  for index, channel in enumerate(channels):
    fields = tuple(
      field
      for field, value in (("name", channel.name), ("short_name", channel.short_name))
      if reference == value
    )
    if fields:
      candidates.append((index, channel.id, fields))
  if not candidates:
    raise ChannelNotFoundError(sample_id, reference)
  if len(candidates) > 1:
    raise AmbiguousChannelReferenceError(
      sample_id,
      reference,
      tuple(channel_id for _, channel_id, _ in candidates),
      tuple((channel_id, fields) for _, channel_id, fields in candidates),
    )
  return candidates[0][0]
