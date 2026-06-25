from flowdesk_core.models import ChannelSpec, SampleSpec


def test_channel_and_sample_models() -> None:
  channel = ChannelSpec(id="fl1_a", name="FL1-A", unit="a.u.")
  sample = SampleSpec(id="s1", name="sample 1", path="data/sample.fcs")

  assert channel.name == "FL1-A"
  assert sample.path == "data/sample.fcs"
