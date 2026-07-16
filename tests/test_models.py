import pytest

from flowdesk_core.groups import GroupResolutionError, resolve_group_member_ids
from flowdesk_core.models import (
  AnnotationSpec,
  ChannelSpec,
  DerivedParameterSpec,
  GroupStrategyBindingSpec,
  SampleGroupSpec,
  SampleSpec,
)


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


def test_groups_resolve_explicit_and_safe_keyword_membership() -> None:
  samples = (
    SampleSpec(id="s1", name="one", path="one.fcs", metadata={"Panel": "A", "Dose": 1}),
    SampleSpec(id="s2", name="two", path="two.fcs", metadata={"Panel": "B", "Dose": 2}),
  )
  groups = (
    SampleGroupSpec(
      id="all-samples",
      name="All Samples",
      role="all_samples",
      membership_rule={"all": []},
    ),
    SampleGroupSpec(
      id="panel-a-high-dose",
      name="Panel A high dose",
      membership_rule={
        "all": [
          {"keyword": "Panel", "comparison": "equals", "value": "A"},
          {"keyword": "Dose", "comparison": "gte", "value": 2},
        ]
      },
      sample_ids=("s2",),
    ),
  )
  annotations = (AnnotationSpec("s1", "Dose", 2, "workspace"),)

  assert resolve_group_member_ids(groups, samples, annotations) == {
    "all-samples": ("s1", "s2"),
    "panel-a-high-dose": ("s2", "s1"),
  }


def test_group_rules_reject_arbitrary_or_invalid_expressions() -> None:
  sample = SampleSpec(id="s1", name="one", path="one.fcs")
  group = SampleGroupSpec(
    id="unsafe",
    name="Unsafe",
    membership_rule={"python": "__import__('os').system('false')"},
  )

  with pytest.raises(GroupResolutionError, match="one operator") as exc_info:
    resolve_group_member_ids((group,), (sample,))
  assert exc_info.value.code == "invalid_group_rule"


def test_group_strategy_binding_requires_stable_references() -> None:
  binding = GroupStrategyBindingSpec(
    id="all-default",
    group_id="all-samples",
    gating_strategy_id="default-strategy",
  )
  assert binding.statistic_ids == ()
