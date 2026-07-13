from flowdesk_core.models import ChannelSpec, DerivedParameterSpec, SampleSpec


def test_channel_and_sample_models() -> None:
  channel = ChannelSpec(
    id="fl1_a",
    name="FL1-A",
    short_name="CD3",
    detector="B530-A",
    stain="CD3 FITC",
    fcs_parameter_index=4,
    unit="a.u.",
  )
  sample = SampleSpec(id="s1", name="sample 1", path="data/sample.fcs")

  assert channel.name == "FL1-A"
  assert channel.short_name == "CD3"
  assert channel.detector == "B530-A"
  assert channel.stain == "CD3 FITC"
  assert channel.fcs_parameter_index == 4
  assert sample.path == "data/sample.fcs"


def test_channel_identity_fields_have_compatible_defaults() -> None:
  channel = ChannelSpec(id="fsc_a", name="FSC-A")

  assert channel.short_name is None
  assert channel.detector is None
  assert channel.stain is None
  assert channel.fcs_parameter_index is None


def test_derived_parameter_persists_output_channel_identity_and_unit() -> None:
  spec = DerivedParameterSpec(
    id="ratio_definition",
    name="Ratio",
    expression="signal / reference",
    output_channel_id="signal_ratio",
    unit="ratio",
  )

  assert spec.output_id == "signal_ratio"
  assert spec.unit == "ratio"
