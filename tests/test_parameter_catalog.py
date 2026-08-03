"""Core contracts for acquired-plus-derived parameter catalog resolution."""

from __future__ import annotations

from flowdesk_core.models import ChannelSpec
from flowdesk_core.parameter_catalog import build_parameter_catalog
from flowdesk_core.statistic_values import (
  build_statistic_value_choices,
  resolve_statistic_value_choice,
)


def test_catalog_keeps_acquired_then_derived_display_order_and_provenance() -> None:
  catalog = build_parameter_catalog(
    (
      ChannelSpec(id="FL1-A", name="FL1-A", unit="a.u."),
      ChannelSpec(id="FL2-A", name="FL2-A"),
    ),
    ({
      "id": "ratio-definition",
      "name": "FL1 / FL2",
      "output_channel_id": "ratio",
      "output_label": "Marker ratio",
      "expression": "FL1-A / FL2-A",
      "input_parameters": ["FL1-A", "FL2-A"],
      "source_stage": "compensated",
      "unit": "ratio",
    },),
    sample_id="sample-1",
  )

  assert [entry.parameter_id for entry in catalog] == ["FL1-A", "FL2-A", "ratio"]
  ratio = catalog[-1]
  assert ratio.kind == "derived"
  assert ratio.display_name == "Marker ratio"
  assert ratio.source_stage == "compensated"
  assert ratio.unit == "ratio"
  assert ratio.input_parameter_ids == ("FL1-A", "FL2-A")
  assert ratio.availability == "not_run"
  assert ratio.is_definition_valid
  assert "Derived" in ratio.selector_label


def test_catalog_keeps_invalid_derived_entry_visible_with_diagnostic() -> None:
  catalog = build_parameter_catalog(
    (ChannelSpec(id="FL1-A", name="Same label"),),
    ({
      "id": "broken",
      "name": "Same label",
      "output_channel_id": "broken-output",
      "expression": "FL1-A / unknown",
      "input_parameters": ["FL1-A"],
    },),
  )

  acquired, broken = catalog
  assert acquired.display_name == broken.display_name
  assert acquired.parameter_id != broken.parameter_id
  assert broken.availability == "missing_input"
  assert not broken.is_definition_valid
  assert broken.diagnostics[0].code == "unknown_derived_input"


def test_catalog_marks_dependency_cycle_entries_as_errors() -> None:
  catalog = build_parameter_catalog(
    (ChannelSpec(id="FL1-A", name="FL1-A"),),
    (
      {
        "id": "first", "name": "First", "output_channel_id": "first-output",
        "expression": "second-output + FL1-A", "input_parameters": (),
      },
      {
        "id": "second", "name": "Second", "output_channel_id": "second-output",
        "expression": "first-output + FL1-A", "input_parameters": (),
      },
    ),
  )

  assert [entry.availability for entry in catalog[1:]] == ["error", "error"]
  assert {entry.diagnostics[0].code for entry in catalog[1:]} == {
    "derived_dependency_cycle"
  }


def test_statistic_value_choices_keep_raw_input_derived_output_in_analysis_stage() -> None:
  catalog = build_parameter_catalog(
    (ChannelSpec(id="FL1-A", name="FITC-A"),),
    ({
      "id": "ratio-definition",
      "name": "GFPvsRFP",
      "output_channel_id": "ratio-output",
      "expression": "FL1-A / FL1-A",
      "input_parameters": ["FL1-A"],
      "source_stage": "raw",
    },),
  )
  choices = build_statistic_value_choices(catalog, ({
    "id": "ratio-log",
    "name": "Ratio log",
    "parameter": "ratio-output",
    "transform_type": "log",
  },))

  keys = [choice.key for choice in choices]
  assert ("FL1-A", "raw", None) in keys
  assert ("FL1-A", "compensated", None) in keys
  assert ("ratio-output", "compensated", None) in keys
  assert ("ratio-output", "raw", None) not in keys
  assert ("ratio-output", "transformed", "ratio-log") in keys
  ratio = next(choice for choice in choices if choice.parameter_id == "ratio-output")
  assert "raw inputs" in ratio.provenance_label


def test_statistic_value_resolver_rejects_raw_domain_for_derived_output() -> None:
  catalog = build_parameter_catalog(
    (ChannelSpec(id="FL1-A", name="FL1-A"),),
    ({
      "id": "ratio-definition",
      "name": "Ratio",
      "output_channel_id": "ratio-output",
      "expression": "FL1-A / FL1-A",
      "input_parameters": ["FL1-A"],
      "source_stage": "raw",
    },),
  )
  resolution = resolve_statistic_value_choice(
    catalog, (), "ratio-output", "raw", None
  )
  assert not resolution.is_valid
  assert resolution.code == "derived_output_not_available_in_raw_stage"


def test_statistic_value_resolver_distinguishes_transform_ids() -> None:
  catalog = build_parameter_catalog(
    (ChannelSpec(id="FL1-A", name="FL1-A"),), (),
  )
  transforms = ({
    "id": "fl1-log",
    "name": "FL1 Log10",
    "parameter": "FL1-A",
    "role": "analysis",
  },)
  valid = resolve_statistic_value_choice(
    catalog, transforms, "FL1-A", "transformed", "fl1-log"
  )
  invalid = resolve_statistic_value_choice(
    catalog, transforms, "FL1-A", "transformed", "other-transform"
  )
  assert valid.is_valid
  assert valid.choice is not None and valid.choice.transform_id == "fl1-log"
  assert not invalid.is_valid
  assert invalid.code == "unknown_or_mismatched_transform"
