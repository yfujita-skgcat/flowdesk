import numpy as np
import pytest

from flowdesk_core.channels import (
  AmbiguousChannelReferenceError,
  ChannelNotFoundError,
  DuplicateChannelIdError,
)
from flowdesk_core.models import ChannelSpec
from flowdesk_core.sample import InvalidSampleDataError, SampleData


def _channel(
  channel_id: str,
  name: str,
  *,
  short_name: str | None = None,
) -> ChannelSpec:
  return ChannelSpec(id=channel_id, name=name, short_name=short_name)


def test_sample_data_preserves_order_and_makes_an_immutable_copy() -> None:
  source = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
  original_bytes = source.tobytes()
  channels = (
    _channel("fsc_a", "FSC-A"),
    _channel("cd3_a", "B530-A", short_name="CD3"),
  )

  sample = SampleData(sample_id="sample-1", events=source, channels=channels)
  source[0, 0] = 99.0

  assert sample.channels == channels
  assert sample.event_count == 2
  assert sample.channel_count == 2
  assert sample.events.tobytes() == original_bytes
  assert not sample.events.flags.writeable
  with pytest.raises(ValueError, match="read-only"):
    sample.events[0, 0] = 7.0


def test_sample_data_rejects_event_channel_shape_mismatch() -> None:
  with pytest.raises(InvalidSampleDataError, match="2 event columns but 1 channels"):
    SampleData(
      sample_id="sample-1",
      events=np.zeros((3, 2), dtype=np.float64),
      channels=(_channel("fsc_a", "FSC-A"),),
    )


def test_sample_data_rejects_duplicate_stable_ids() -> None:
  with pytest.raises(DuplicateChannelIdError) as error:
    SampleData(
      sample_id="sample-1",
      events=np.zeros((3, 2), dtype=np.float64),
      channels=(
        _channel("cd3_a", "B530-A", short_name="CD3"),
        _channel("cd3_a", "R660-A", short_name="CD4"),
      ),
    )

  assert error.value.sample_id == "sample-1"
  assert error.value.channel_id == "cd3_a"


def test_stable_id_lookup_does_not_depend_on_visible_channel_order() -> None:
  sample = SampleData(
    sample_id="sample-1",
    events=np.zeros((3, 2), dtype=np.float64),
    channels=(
      _channel("cd4_a", "R660-A", short_name="CD4"),
      _channel("cd3_a", "B530-A", short_name="CD3"),
    ),
  )

  assert sample.channel_index("cd3_a") == 1
  assert sample.channel_by_id("cd3_a").short_name == "CD3"
  assert sample.resolve_channel_index("CD3") == 1


def test_duplicate_visible_label_is_allowed_but_ambiguous_to_resolve() -> None:
  sample = SampleData(
    sample_id="sample-1",
    events=np.zeros((3, 2), dtype=np.float64),
    channels=(
      _channel("cd3_area", "B530-A", short_name="CD3"),
      _channel("cd3_height", "B530-H", short_name="CD3"),
    ),
  )

  with pytest.raises(AmbiguousChannelReferenceError) as error:
    sample.resolve_channel_index("CD3")

  assert error.value.sample_id == "sample-1"
  assert error.value.reference == "CD3"
  assert error.value.candidate_ids == ("cd3_area", "cd3_height")


def test_missing_channel_reference_has_sample_context() -> None:
  sample = SampleData(
    sample_id="sample-1",
    events=np.zeros((3, 1), dtype=np.float64),
    channels=(_channel("fsc_a", "FSC-A"),),
  )

  with pytest.raises(ChannelNotFoundError) as error:
    sample.resolve_channel_index("CD3")

  assert error.value.sample_id == "sample-1"
  assert error.value.reference == "CD3"
