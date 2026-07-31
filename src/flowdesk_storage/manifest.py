"""Manifest validation for .flowdesk project bundles."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import TransformSpec, validate_gate_name
from flowdesk_core.tables import table_definition_from_mapping
from flowdesk_core.transforms import TransformError, validate_transform
from flowdesk_storage.migrations import CURRENT_PROJECT_VERSION, migrate_manifest

REQUIRED_FIELDS = ["project_id", "project_version", "pipeline_version", "samples"]


class ManifestValidationError(FlowdeskError):
  """Raised when a project manifest fails validation."""


def validate_manifest(data: dict[str, Any]) -> None:
  """Validate that a manifest dictionary contains all required fields.

  Raises ManifestValidationError if required fields are missing or have
  incorrect types. Unknown fields are preserved (not rejected).
  """

  if not isinstance(data, dict):
    raise ManifestValidationError("manifest must be a JSON object")

  missing = [f for f in REQUIRED_FIELDS if f not in data]
  if missing:
    raise ManifestValidationError(f"missing required fields: {', '.join(missing)}")

  if not isinstance(data["project_id"], str):
    raise ManifestValidationError("project_id must be a string")

  if not isinstance(data["project_version"], str):
    raise ManifestValidationError("project_version must be a string")

  if not isinstance(data["pipeline_version"], str):
    raise ManifestValidationError("pipeline_version must be a string")

  if not isinstance(data["samples"], list):
    raise ManifestValidationError("samples must be an array")

  _validate_gate_names(data.get("gating_strategies_data", {}))

  # Statistic definitions use the same stable contract across the legacy
  # 1.5 manifest and the current format.  Validate them whenever present so
  # malformed definitions cannot bypass validation solely because the rest of
  # of the manifest still requires migration.
  if "statistics" in data:
    _validate_current_statistics(data.get("statistics"), None)
  if "table_definitions" in data:
    _validate_current_table_definitions(data.get("table_definitions"))

  if "advanced_groups_enabled" in data and not isinstance(
    data["advanced_groups_enabled"], bool
  ):
    raise ManifestValidationError("advanced_groups_enabled must be a boolean")

  if data["project_version"] == CURRENT_PROJECT_VERSION:
    _validate_current_samples(data["samples"])
    _validate_current_derived_parameters(data.get("derived_parameters", []))
    transform_parameters = _validate_current_transforms(
      data.get("transforms", [])
    )
    _validate_current_gate_transforms(
      data.get("gating_strategies_data", {}),
      transform_parameters,
    )
    _validate_current_compensation_matrices(data.get("compensation_matrices", []))
    calculated_matrix_ids = _validate_current_compensation_calculations(
      data.get("compensation_calculations", []),
      {sample["id"] for sample in data["samples"] if isinstance(sample, dict)},
    )
    _validate_current_compensation_bindings(
      data.get("compensation_bindings", []),
      {
        m["id"] for m in data.get("compensation_matrices", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str)
      } | calculated_matrix_ids,
    )
    gate_ids = _collect_gate_ids(data.get("gating_strategies_data", {}))
    _validate_current_statistics(
      data.get("statistics", []), gate_ids, transform_parameters
    )
    _validate_current_gate_parent_references(
      data.get("gating_strategies_data", {}),
      gate_ids,
    )
    _validate_current_groups_and_annotations(data, gate_ids)
    _validate_current_gate_overrides(data, gate_ids)
    _validate_current_plot_definitions(data)
    _validate_current_integrated_overlay(data)


def _validate_current_table_definitions(value: Any) -> None:
  """Validate persisted table definitions without executing their sources."""
  if not isinstance(value, list):
    raise ManifestValidationError("table_definitions must be an array")
  definition_ids: set[str] = set()
  for index, definition in enumerate(value):
    if not isinstance(definition, dict):
      raise ManifestValidationError(f"table_definitions[{index}] must be an object")
    try:
      parsed = table_definition_from_mapping(definition)
    except (TypeError, ValueError) as exc:
      raise ManifestValidationError(
        f"invalid table_definitions[{index}]: {exc}"
      ) from exc
    if parsed.id in definition_ids:
      raise ManifestValidationError(f"duplicate table definition ID {parsed.id!r}")
    definition_ids.add(parsed.id)


def _validate_current_plot_definitions(data: Mapping[str, Any]) -> None:
  """Validate typed overlay source identity without resolving runtime data."""
  for collection_name, source_key in (("plot_views", "overlay_sources"), ("overlays", "sources")):
    definitions = data.get(collection_name, [])
    if not isinstance(definitions, list):
      raise ManifestValidationError(f"{collection_name} must be an array")
    definition_ids: set[str] = set()
    for index, definition in enumerate(definitions):
      if not isinstance(definition, dict):
        raise ManifestValidationError(f"{collection_name}[{index}] must be an object")
      definition_id = definition.get("id")
      if not isinstance(definition_id, str) or not definition_id:
        raise ManifestValidationError(f"{collection_name}[{index}].id must be non-empty")
      if definition_id in definition_ids:
        raise ManifestValidationError(f"duplicate {collection_name[:-1]} ID {definition_id!r}")
      definition_ids.add(definition_id)
      sources = definition.get(source_key, [])
      if not isinstance(sources, list):
        raise ManifestValidationError(f"{collection_name}[{index}].{source_key} must be an array")
      source_ids: set[str] = set()
      orders: set[int] = set()
      for source_index, source in enumerate(sources):
        if not isinstance(source, dict):
          raise ManifestValidationError(f"{source_key}[{source_index}] must be an object")
        required = ("source_id", "display_name", "x_parameter_id")
        if any(not isinstance(source.get(key), str) or not source[key] for key in required):
          raise ManifestValidationError(f"{source_key}[{source_index}] has missing identity fields")
        source_id = source["source_id"]
        if source_id in source_ids:
          raise ManifestValidationError(f"duplicate overlay source ID {source_id!r}")
        source_ids.add(source_id)
        if source.get("sample_id") is None and not source.get("template_source_role"):
          raise ManifestValidationError(
            f"overlay source {source_id!r} needs sample_id or template_source_role"
          )
        if source.get("population_id") is None and not source.get("template_population_path"):
          raise ManifestValidationError(
            f"overlay source {source_id!r} needs population_id or template_population_path"
          )
        order = source.get("order", 0)
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
          raise ManifestValidationError(f"overlay source {source_id!r} has invalid order")
        if order in orders:
          raise ManifestValidationError(f"overlay source {source_id!r} has duplicate order")
        orders.add(order)


def _validate_current_integrated_overlay(data: Mapping[str, Any]) -> None:
  """Validate display-only comparison metadata without binding scientific groups."""
  sample_ids = {
    sample.get("id") for sample in data.get("samples", [])
    if isinstance(sample, dict) and isinstance(sample.get("id"), str)
  }
  comparisons = data.get("comparison_set_definitions", [])
  if not isinstance(comparisons, list):
    raise ManifestValidationError("comparison_set_definitions must be an array")
  comparison_ids: set[str] = set()
  valid_roles = {"reference", "target", "positive_control", "negative_control", "control"}
  for index, comparison in enumerate(comparisons):
    if not isinstance(comparison, dict):
      raise ManifestValidationError(f"comparison_set_definitions[{index}] must be an object")
    comparison_id = comparison.get("id")
    if not isinstance(comparison_id, str) or not comparison_id:
      raise ManifestValidationError(f"comparison_set_definitions[{index}].id must be non-empty")
    if comparison_id in comparison_ids:
      raise ManifestValidationError(f"duplicate comparison set ID {comparison_id!r}")
    comparison_ids.add(comparison_id)
    members = comparison.get("members")
    if not isinstance(members, list) or len(members) < 2:
      raise ManifestValidationError(f"comparison set {comparison_id!r} needs at least two members")
    member_ids: set[str] = set()
    for member in members:
      if not isinstance(member, dict):
        raise ManifestValidationError(f"comparison set {comparison_id!r} member must be an object")
      sample_id = member.get("sample_id")
      if not isinstance(sample_id, str) or sample_id not in sample_ids:
        raise ManifestValidationError(
          f"comparison set {comparison_id!r} references an unknown sample"
        )
      if sample_id in member_ids:
        raise ManifestValidationError(
          f"comparison set {comparison_id!r} has duplicate sample {sample_id!r}"
        )
      member_ids.add(sample_id)
      if member.get("role", "target") not in valid_roles:
        raise ManifestValidationError(f"comparison set {comparison_id!r} has invalid role")
    role_colors = comparison.get("role_colors", {})
    if not isinstance(role_colors, dict):
      raise ManifestValidationError(
        f"comparison set {comparison_id!r}.role_colors must be an object"
      )
    for role, color in role_colors.items():
      if role not in valid_roles or not isinstance(color, str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}", color
      ):
        raise ManifestValidationError(f"comparison set {comparison_id!r} has invalid role color")
  role_colors = data.get("comparison_role_colors", {})
  if not isinstance(role_colors, dict):
    raise ManifestValidationError("comparison_role_colors must be an object")
  for role, color in role_colors.items():
    if role not in valid_roles or not isinstance(color, str) or not re.fullmatch(
      r"#[0-9a-fA-F]{6}", color
    ):
      raise ManifestValidationError("invalid comparison role default color")


def _validate_current_groups_and_annotations(
  data: Mapping[str, Any],
  gate_ids: set[str],
) -> None:
  """Validate persisted group/annotation identities without altering metadata."""
  groups = data.get("sample_groups", [])
  annotations = data.get("annotations", [])
  bindings = data.get("group_strategy_bindings", [])
  if not isinstance(groups, list):
    raise ManifestValidationError("sample_groups must be an array")
  if not isinstance(annotations, list):
    raise ManifestValidationError("annotations must be an array")
  if not isinstance(bindings, list):
    raise ManifestValidationError("group_strategy_bindings must be an array")

  sample_ids = {
    sample["id"] for sample in data["samples"] if isinstance(sample, dict)
  }
  group_ids: set[str] = set()
  valid_roles = {
    "all_samples", "compensation_controls", "panel", "acquisition", "qc", "user"
  }
  for index, group in enumerate(groups):
    if not isinstance(group, dict):
      raise ManifestValidationError(f"sample_groups[{index}] must be an object")
    group_id = group.get("id")
    if not isinstance(group_id, str) or not group_id:
      raise ManifestValidationError(f"sample_groups[{index}].id must be non-empty")
    if group_id in group_ids:
      raise ManifestValidationError(f"duplicate sample group ID {group_id!r}")
    group_ids.add(group_id)
    if group.get("role") not in valid_roles:
      raise ManifestValidationError(f"sample group {group_id!r} has invalid role")
    members = group.get("sample_ids")
    if not isinstance(members, list) or not all(
      isinstance(sample_id, str) and sample_id for sample_id in members
    ):
      raise ManifestValidationError(f"sample group {group_id!r} sample_ids must be strings")
    if len(set(members)) != len(members):
      raise ManifestValidationError(f"sample group {group_id!r} has duplicate sample IDs")
    unknown_members = set(members) - sample_ids
    if unknown_members:
      raise ManifestValidationError(
        f"sample group {group_id!r} references unknown samples {sorted(unknown_members)!r}"
      )
    rule = group.get("membership_rule")
    if rule is not None and not isinstance(rule, dict):
      raise ManifestValidationError(
        f"sample group {group_id!r} membership_rule must be an object or null"
      )

  valid_sources = {"fcs", "workspace", "imported"}
  for index, annotation in enumerate(annotations):
    if not isinstance(annotation, dict):
      raise ManifestValidationError(f"annotations[{index}] must be an object")
    sample_id = annotation.get("sample_id")
    keyword = annotation.get("keyword")
    if not isinstance(sample_id, str) or sample_id not in sample_ids:
      raise ManifestValidationError(f"annotations[{index}] references an unknown sample")
    if not isinstance(keyword, str) or not keyword:
      raise ManifestValidationError(f"annotations[{index}].keyword must be non-empty")
    if annotation.get("source") not in valid_sources:
      raise ManifestValidationError(f"annotations[{index}] has invalid source")
    if isinstance(annotation.get("value"), (list, dict)):
      raise ManifestValidationError(f"annotations[{index}].value must be scalar or null")

  strategy_ids = set(data.get("gating_strategies_data", {}))
  statistic_ids = {
    statistic.get("id") for statistic in data.get("statistics", [])
    if isinstance(statistic, dict) and isinstance(statistic.get("id"), str)
  }
  binding_ids: set[str] = set()
  for index, binding in enumerate(bindings):
    if not isinstance(binding, dict):
      raise ManifestValidationError(f"group_strategy_bindings[{index}] must be an object")
    binding_id = binding.get("id")
    if not isinstance(binding_id, str) or not binding_id:
      raise ManifestValidationError(f"group_strategy_bindings[{index}].id must be non-empty")
    if binding_id in binding_ids:
      raise ManifestValidationError(f"duplicate group strategy binding ID {binding_id!r}")
    binding_ids.add(binding_id)
    if binding.get("group_id") not in group_ids:
      raise ManifestValidationError(f"binding {binding_id!r} references an unknown group")
    strategy_id = binding.get("gating_strategy_id")
    if strategy_id not in strategy_ids:
      raise ManifestValidationError(f"binding {binding_id!r} references an unknown strategy")
    statistic_ids_for_binding = binding.get("statistic_ids")
    if not isinstance(statistic_ids_for_binding, list) or not all(
      isinstance(statistic_id, str) and statistic_id for statistic_id in statistic_ids_for_binding
    ):
      raise ManifestValidationError(f"binding {binding_id!r} statistic_ids must be strings")
    if len(set(statistic_ids_for_binding)) != len(statistic_ids_for_binding):
      raise ManifestValidationError(f"binding {binding_id!r} has duplicate statistic IDs")
    unknown_statistics = set(statistic_ids_for_binding) - statistic_ids
    if unknown_statistics:
      raise ManifestValidationError(
        f"binding {binding_id!r} references unknown statistics {sorted(unknown_statistics)!r}"
      )


def _validate_current_gate_overrides(
  data: Mapping[str, Any], gate_ids: set[str]
) -> None:
  """Validate explicit sample geometry overrides without resolving them."""
  overrides = data.get("gate_overrides", [])
  if not isinstance(overrides, list):
    raise ManifestValidationError("gate_overrides must be an array")
  sample_ids = {
    sample["id"] for sample in data["samples"]
    if isinstance(sample, dict) and isinstance(sample.get("id"), str)
  }
  override_ids: set[str] = set()
  targets: set[tuple[str, str]] = set()
  for index, override in enumerate(overrides):
    if not isinstance(override, dict):
      raise ManifestValidationError(f"gate_overrides[{index}] must be an object")
    required = (
      "id", "sample_id", "base_gate_id", "base_version_hash", "geometry_mode",
      "author", "created_at", "reason",
    )
    if any(not isinstance(override.get(key), str) or not override[key] for key in required):
      raise ManifestValidationError(f"gate_overrides[{index}] has missing required fields")
    override_id = override["id"]
    if override_id in override_ids:
      raise ManifestValidationError(f"duplicate gate override ID {override_id!r}")
    override_ids.add(override_id)
    sample_id = override["sample_id"]
    gate_id = override["base_gate_id"]
    if sample_id not in sample_ids:
      raise ManifestValidationError(f"override {override_id!r} references an unknown sample")
    if gate_id not in gate_ids:
      raise ManifestValidationError(f"override {override_id!r} references an unknown gate")
    if (sample_id, gate_id) in targets:
      raise ManifestValidationError(
        f"duplicate override for sample {sample_id!r} and gate {gate_id!r}"
      )
    targets.add((sample_id, gate_id))
    if override["geometry_mode"] not in {"delta", "full"}:
      raise ManifestValidationError(f"override {override_id!r} has invalid geometry_mode")
    if override.get("gate_purpose", "technical_cleanup") not in {
      "technical_cleanup", "comparison_critical"
    }:
      raise ManifestValidationError(f"override {override_id!r} has invalid gate_purpose")
    if not isinstance(override.get("coordinates", []), list):
      raise ManifestValidationError(f"override {override_id!r} coordinates must be an array")
    if not isinstance(override.get("thresholds", {}), dict):
      raise ManifestValidationError(f"override {override_id!r} thresholds must be an object")


def _validate_current_transforms(transforms: Any) -> dict[str, tuple[str, str]]:
  """Validate unambiguous transform types in the current project format."""
  if not isinstance(transforms, list):
    raise ManifestValidationError("transforms must be an array")
  valid_types = {
    "linear",
    "log",
    "asinh",
    "logicle",
    "legacy_logicle_approximation",
  }
  transform_ids: set[str] = set()
  transform_parameters: dict[str, tuple[str, str]] = {}
  for index, transform in enumerate(transforms):
    if not isinstance(transform, dict):
      raise ManifestValidationError(f"transforms[{index}] must be an object")
    transform_id = transform.get("id")
    if not isinstance(transform_id, str) or not transform_id:
      raise ManifestValidationError(
        f"transforms[{index}].id must be a non-empty string"
      )
    if transform_id in transform_ids:
      raise ManifestValidationError(f"duplicate transform ID {transform_id!r}")
    transform_ids.add(transform_id)
    transform_type = transform.get("transform_type")
    if transform_type not in valid_types:
      raise ManifestValidationError(
        f"transform {transform_id!r} has invalid transform_type "
        f"{transform_type!r}"
      )
    parameter = transform.get("parameter")
    if not isinstance(parameter, str) or not parameter:
      raise ManifestValidationError(
        f"transform {transform_id!r} parameter must be a non-empty string"
      )
    if transform.get("role") != "analysis":
      raise ManifestValidationError(
        f"transform {transform_id!r} role must be 'analysis'"
      )
    if parameter in (item[1] for item in transform_parameters.values()):
      raise ManifestValidationError(
        f"parameter {parameter!r} has more than one analysis transform"
      )
    transform_parameters[transform_id] = (transform_type, parameter)
    settings = transform.get("settings", {})
    if not isinstance(settings, dict):
      raise ManifestValidationError(
        f"transform {transform_id!r} settings must be an object"
      )
    if transform_type == "logicle":
      try:
        validate_transform(TransformSpec(
          id=transform_id,
          name=str(transform.get("name", transform_id)),
          transform_type="logicle",
          parameter=parameter,
          settings=settings,
        ))
      except TransformError as exc:
        raise ManifestValidationError(
          f"transform {transform_id!r} has invalid Logicle settings: {exc}"
        ) from exc
  return transform_parameters


def _validate_current_gate_transforms(
  strategies: Any,
  transforms: Mapping[str, tuple[str, str]],
) -> None:
  if not isinstance(strategies, dict):
    raise ManifestValidationError("gating_strategies_data must be an object")
  for strategy_id, strategy in strategies.items():
    if not isinstance(strategy, dict):
      raise ManifestValidationError(
        f"gating strategy {strategy_id!r} must be an object"
      )
    gates = strategy.get("gates", [])
    if not isinstance(gates, list):
      raise ManifestValidationError(
        f"gating strategy {strategy_id!r} gates must be an array"
      )
    for gate in gates:
      if not isinstance(gate, dict):
        raise ManifestValidationError(
          f"gating strategy {strategy_id!r} gate must be an object"
        )
      gate_id = str(gate.get("id", "unknown"))
      legacy_fields = {"transform_id", "x_scale", "y_scale"}.intersection(gate)
      if legacy_fields:
        raise ManifestValidationError(
          f"gate {gate_id!r} uses removed legacy fields: "
          f"{', '.join(sorted(legacy_fields))}"
        )
      for axis in ("x", "y"):
        parameter = gate.get(f"{axis}_parameter")
        if parameter is None:
          continue
        transform_id = gate.get(f"{axis}_transform_id")
        if transform_id is None:
          continue
        if transform_id not in transforms:
          raise ManifestValidationError(
            f"gate {gate_id!r} references unknown transform {transform_id!r}"
          )
        if transforms[transform_id][1] != parameter:
          raise ManifestValidationError(
            f"gate {gate_id!r} {axis}-parameter does not match transform "
            f"{transform_id!r}"
          )


def _validate_current_derived_parameters(definitions: Any) -> None:
  """Validate persisted derived identity and source-stage compatibility."""
  if not isinstance(definitions, list):
    raise ManifestValidationError("derived_parameters must be an array")
  definition_ids: set[str] = set()
  output_ids: set[str] = set()
  valid_policies = {"fail_run", "fail_sample", "emit_nan_with_warning"}
  for index, definition in enumerate(definitions):
    if not isinstance(definition, dict):
      raise ManifestValidationError(
        f"derived_parameters[{index}] must be an object"
      )
    for field in ("id", "name", "expression", "output_channel_id"):
      value = definition.get(field)
      if not isinstance(value, str) or not value:
        raise ManifestValidationError(
          f"derived_parameters[{index}].{field} must be a non-empty string"
        )
    parameter_id = definition["id"]
    output_id = definition["output_channel_id"]
    if parameter_id in definition_ids:
      raise ManifestValidationError(
        f"duplicate derived parameter ID {parameter_id!r}"
      )
    if output_id in output_ids:
      raise ManifestValidationError(
        f"duplicate derived output channel ID {output_id!r}"
      )
    definition_ids.add(parameter_id)
    output_ids.add(output_id)
    unit = definition.get("unit")
    if unit is not None and not isinstance(unit, str):
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} unit must be a string or null"
      )
    inputs = definition.get("input_parameters")
    if not isinstance(inputs, list) or not all(
      isinstance(value, str) and value for value in inputs
    ):
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} input_parameters must be strings"
      )
    policy = definition.get("invalid_value_policy")
    if policy not in valid_policies:
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} has invalid failure policy"
      )
    non_finite_policy = definition.get("non_finite_policy", "strict")
    if non_finite_policy not in {"strict", "exclude_invalid"}:
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} has invalid non_finite_policy"
      )
    source_stage = definition.get("source_stage")
    if source_stage not in {"raw", "compensated", "transformed"}:
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} has invalid source_stage"
      )
    legacy_policy = definition.get("legacy_source_stage_policy")
    if source_stage == "transformed" and legacy_policy != "reject":
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} transformed source requires "
        "legacy_source_stage_policy='reject'"
      )
    if source_stage != "transformed" and legacy_policy is not None:
      raise ManifestValidationError(
        f"derived parameter {parameter_id!r} legacy_source_stage_policy is "
        "only valid for transformed source"
      )


def _validate_current_samples(samples: list[Any]) -> None:
  """Validate sample/channel identity fields required by the current version."""
  for sample_index, sample in enumerate(samples):
    if not isinstance(sample, dict):
      raise ManifestValidationError(
        f"samples[{sample_index}] must be an object"
      )
    sample_id = sample.get("id")
    if not isinstance(sample_id, str) or not sample_id:
      raise ManifestValidationError(
        f"samples[{sample_index}].id must be a non-empty string"
      )
    fingerprint = sample.get("fingerprint")
    if fingerprint is not None:
      _validate_file_fingerprint(sample_id, fingerprint)
    channels = sample.get("channels")
    if not isinstance(channels, list):
      raise ManifestValidationError(
        f"sample {sample_id!r} channels must be an array"
      )
    channel_ids: set[str] = set()
    for channel_index, channel in enumerate(channels):
      if not isinstance(channel, dict):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_index} must be an object"
        )
      channel_id = channel.get("id")
      name = channel.get("name")
      if not isinstance(channel_id, str) or not channel_id:
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_index} id must be non-empty"
        )
      if channel_id in channel_ids:
        raise ManifestValidationError(
          f"sample {sample_id!r} has duplicate channel ID {channel_id!r}"
        )
      channel_ids.add(channel_id)
      if not isinstance(name, str) or not name:
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} name must be non-empty"
        )
      metadata = channel.get("metadata", {})
      if not isinstance(metadata, dict):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} metadata must be an object"
        )
      fcs_index = channel.get("fcs_parameter_index")
      if fcs_index is not None and (
        not isinstance(fcs_index, int) or isinstance(fcs_index, bool) or fcs_index < 1
      ):
        raise ManifestValidationError(
          f"sample {sample_id!r} channel {channel_id!r} "
          "fcs_parameter_index must be a positive integer or null"
        )


def _validate_current_compensation_matrices(matrices: Any) -> None:
  """Validate compensation matrix definitions in the current project format."""

  if not isinstance(matrices, list):
    raise ManifestValidationError("compensation_matrices must be an array")
  matrix_ids: set[str] = set()
  valid_sources = {"fcs_metadata_spillover", "user_defined", "imported", "calculated"}
  for index, matrix in enumerate(matrices):
    if not isinstance(matrix, dict):
      raise ManifestValidationError(
        f"compensation_matrices[{index}] must be an object"
      )
    matrix_id = matrix.get("id")
    if not isinstance(matrix_id, str) or not matrix_id:
      raise ManifestValidationError(
        f"compensation_matrices[{index}].id must be a non-empty string"
      )
    if matrix_id in matrix_ids:
      raise ManifestValidationError(
        f"duplicate compensation matrix ID {matrix_id!r}"
      )
    matrix_ids.add(matrix_id)
    name = matrix.get("name")
    if not isinstance(name, str) or not name:
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} name must be a non-empty string"
      )
    source = matrix.get("source")
    if source not in valid_sources:
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} has invalid source {source!r}"
      )
    channels = matrix.get("channels")
    if not isinstance(channels, list) or len(channels) == 0 or not all(
      isinstance(c, str) and c for c in channels
    ):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} channels must be non-empty strings"
      )
    if len(set(channels)) != len(channels):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} has duplicate channel IDs"
      )
    mat = matrix.get("matrix")
    if not isinstance(mat, list):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} matrix must be an array"
      )
    n = len(channels)
    if len(mat) != n:
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} row count ({len(mat)}) "
        f"must match channel count ({n})"
      )
    for row_idx, row in enumerate(mat):
      if not isinstance(row, list) or len(row) != n:
        raise ManifestValidationError(
          f"compensation matrix {matrix_id!r} row {row_idx} "
          f"must have {n} elements"
        )
      for val_idx, val in enumerate(row):
        if (
          not isinstance(val, (int, float)) or isinstance(val, bool)
          or not math.isfinite(val)
        ):
          raise ManifestValidationError(
            f"compensation matrix {matrix_id!r} row {row_idx} "
            f"col {val_idx} must be a number"
          )
    provenance = matrix.get("provenance", {})
    if not isinstance(provenance, dict):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} provenance must be an object"
      )
    edits = provenance.get("manual_edits", [])
    if not isinstance(edits, list):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} provenance.manual_edits "
        "must be an array"
      )
    for edit_idx, edit in enumerate(edits):
      if not isinstance(edit, dict):
        raise ManifestValidationError(
          f"compensation matrix {matrix_id!r} manual edit {edit_idx} "
          "must be an object"
        )
      for field in ("row_channel_id", "column_channel_id"):
        val = edit.get(field)
        if not isinstance(val, str) or not val:
          raise ManifestValidationError(
            f"compensation matrix {matrix_id!r} manual edit {edit_idx} "
            f"{field} must be a non-empty string"
          )
      for field in ("old_value", "new_value"):
        val = edit.get(field)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
          raise ManifestValidationError(
            f"compensation matrix {matrix_id!r} manual edit {edit_idx} "
            f"{field} must be a number"
          )
    has_edits = len(edits) > 0
    derived_from = provenance.get("derived_from_matrix_id")
    if has_edits and (
      not isinstance(derived_from, str) or not derived_from
    ):
      raise ManifestValidationError(
        f"compensation matrix {matrix_id!r} has manual edits but "
        "missing derived_from_matrix_id"
      )


def _validate_current_compensation_bindings(
  bindings: Any,
  known_matrix_ids: set[str],
) -> None:
  """Validate compensation binding definitions in the current project format."""

  if not isinstance(bindings, list):
    raise ManifestValidationError("compensation_bindings must be an array")
  valid_scopes = {"sample", "group", "execution_profile"}
  binding_ids: set[str] = set()
  binding_keys: set[tuple[str, str]] = set()
  for index, binding in enumerate(bindings):
    if not isinstance(binding, dict):
      raise ManifestValidationError(
        f"compensation_bindings[{index}] must be an object"
      )
    binding_id = binding.get("id")
    if not isinstance(binding_id, str) or not binding_id:
      raise ManifestValidationError(
        f"compensation_bindings[{index}].id must be a non-empty string"
      )
    if binding_id in binding_ids:
      raise ManifestValidationError(
        f"duplicate compensation binding ID {binding_id!r}"
      )
    binding_ids.add(binding_id)
    matrix_id = binding.get("matrix_id")
    if not isinstance(matrix_id, str) or not matrix_id:
      raise ManifestValidationError(
        f"compensation binding {binding_id!r} matrix_id must be "
        "a non-empty string"
      )
    if matrix_id not in known_matrix_ids:
      raise ManifestValidationError(
        f"compensation binding {binding_id!r} references unknown "
        f"matrix {matrix_id!r}"
      )
    scope = binding.get("scope")
    if scope not in valid_scopes:
      raise ManifestValidationError(
        f"compensation binding {binding_id!r} has invalid scope {scope!r}"
      )
    target_id = binding.get("target_id")
    if not isinstance(target_id, str) or not target_id:
      raise ManifestValidationError(
        f"compensation binding {binding_id!r} target_id must be "
        "a non-empty string"
      )
    key = (scope, target_id)
    if key in binding_keys:
      raise ManifestValidationError(
        f"duplicate compensation binding target ({scope}, {target_id!r})"
      )
    binding_keys.add(key)


def _validate_current_compensation_calculations(
  calculations: Any,
  known_sample_ids: set[str],
) -> set[str]:
  """Validate compensation calculation definitions in the current project format."""

  if not isinstance(calculations, list):
    raise ManifestValidationError("compensation_calculations must be an array")
  calc_ids: set[str] = set()
  valid_methods = {"linear", "median"}
  valid_policies = {"iqr", "zscore", "none"}
  for index, calc in enumerate(calculations):
    if not isinstance(calc, dict):
      raise ManifestValidationError(
        f"compensation_calculations[{index}] must be an object"
      )

    # --- id ---
    calc_id = calc.get("id")
    if not isinstance(calc_id, str) or not calc_id:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] id must be a non-empty string"
      )
    if calc_id in calc_ids:
      raise ManifestValidationError(
        f"duplicate calculation id {calc_id!r}"
      )
    calc_ids.add(calc_id)

    # --- name ---
    calc_name = calc.get("name")
    if not isinstance(calc_name, str) or not calc_name:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] name must be a non-empty string"
      )

    # --- controls ---
    controls = calc.get("controls")
    if not isinstance(controls, list) or len(controls) == 0:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] controls must be a non-empty array"
      )
    detector_ids: set[str] = set()
    for ci, ctrl in enumerate(controls):
      if not isinstance(ctrl, dict):
        raise ManifestValidationError(
          f"compensation_calculations[{index}].controls[{ci}] must be an object"
        )
      for field in ("sample_id", "detector_channel_id", "positive_population_id",
                    "negative_population_id"):
        val = ctrl.get(field)
        if not isinstance(val, str) or not val:
          raise ManifestValidationError(
            f"compensation_calculations[{index}].controls[{ci}] "
            f"{field} must be a non-empty string"
          )
      if ctrl["sample_id"] not in known_sample_ids:
        raise ManifestValidationError(
          f"compensation_calculations[{index}].controls[{ci}] references "
          f"unknown sample {ctrl['sample_id']!r}"
        )
      det = ctrl["detector_channel_id"]
      if det in detector_ids:
        raise ManifestValidationError(
          f"duplicate detector_channel_id {det!r} in calculation {calc_id!r}"
        )
      detector_ids.add(det)

    # --- regression_method ---
    method = calc.get("regression_method", "linear")
    if method not in valid_methods:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] invalid regression_method "
        f"{method!r}"
      )

    # --- outlier_policy ---
    policy = calc.get("outlier_policy", "iqr")
    if policy not in valid_policies:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] invalid outlier_policy "
        f"{policy!r}"
      )

    # --- minimum_positive_events ---
    mpe = calc.get("minimum_positive_events", 100)
    if not isinstance(mpe, int) or isinstance(mpe, bool) or mpe < 1:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] minimum_positive_events "
        f"must be a positive integer"
      )

    # --- minimum_negative_events ---
    mne = calc.get("minimum_negative_events", 50)
    if not isinstance(mne, int) or isinstance(mne, bool) or mne < 1:
      raise ManifestValidationError(
        f"compensation_calculations[{index}] minimum_negative_events "
        f"must be a positive integer"
      )
  return {f"calculated-{calc_id}" for calc_id in calc_ids}


def _collect_gate_ids(strategy_data: Any) -> set[str]:
  """Collect all gate IDs from all gating strategies."""

  gate_ids: set[str] = set()
  if not isinstance(strategy_data, dict):
    return gate_ids
  for strategy in strategy_data.values():
    if not isinstance(strategy, dict):
      continue
    gates = strategy.get("gates", [])
    if not isinstance(gates, list):
      continue
    for gate in gates:
      if not isinstance(gate, dict):
        continue
      gate_id = gate.get("id")
      if isinstance(gate_id, str) and gate_id:
        gate_ids.add(gate_id)
  return gate_ids


def _validate_gate_names(strategy_data: Any) -> None:
  """Validate gate names before version-specific migration handling."""
  if not isinstance(strategy_data, Mapping):
    return
  for strategy_id, strategy in strategy_data.items():
    if not isinstance(strategy, Mapping):
      continue
    for gate in strategy.get("gates", []):
      if not isinstance(gate, Mapping):
        continue
      gate_id = gate.get("id", "unknown")
      try:
        validate_gate_name(gate.get("name", ""))
      except ValueError as exc:
        raise ManifestValidationError(
          f"gating strategy {strategy_id!r} gate {gate_id!r} has invalid name "
          f"{gate.get('name')!r}; {exc}"
        ) from exc


def _validate_current_statistics(
  statistics: Any,
  gate_ids: set[str] | None = None,
  transforms: Mapping[str, tuple[str, str]] | None = None,
) -> None:
  """Validate persisted statistic definitions in the current project format."""

  if not isinstance(statistics, list):
    raise ManifestValidationError("statistics must be an array")
  valid_metrics = {
    "count",
    "frequency_of_parent",
    "frequency_of_total",
    "mean",
    "median",
    "geometric_mean",
    "stddev",
    "cv",
    "mad",
    "percentile",
  }
  valid_stages = {"raw", "compensated", "transformed"}
  valid_value_policies = {"full_events"}
  valid_non_finite_policies = {"strict", "exclude_invalid"}
  value_metrics = valid_metrics - {
    "count",
    "frequency_of_parent",
    "frequency_of_total",
  }
  stat_ids: set[str] = set()
  for index, stat in enumerate(statistics):
    if not isinstance(stat, dict):
      raise ManifestValidationError(
        f"statistics[{index}] must be an object"
      )
    stat_id = stat.get("id")
    if not isinstance(stat_id, str) or not stat_id:
      raise ManifestValidationError(
        f"statistics[{index}].id must be a non-empty string"
      )
    if stat_id in stat_ids:
      raise ManifestValidationError(
        f"duplicate statistic ID {stat_id!r}"
      )
    stat_ids.add(stat_id)
    name = stat.get("name")
    if not isinstance(name, str) or not name:
      raise ManifestValidationError(
        f"statistic {stat_id!r} name must be a non-empty string"
      )
    legacy_population_id = stat.get("population_id")
    if legacy_population_id is not None and (
      not isinstance(legacy_population_id, str) or not legacy_population_id
    ):
      raise ManifestValidationError(
        f"statistic {stat_id!r} population_id must be a non-empty string"
      )
    population_ids = stat.get("population_ids")
    if population_ids is None:
      if legacy_population_id is None:
        raise ManifestValidationError(
          f"statistic {stat_id!r} requires population_id or population_ids"
        )
      population_ids = [legacy_population_id]
    if (
      not isinstance(population_ids, list)
      or not population_ids
      or any(not isinstance(value, str) or not value for value in population_ids)
    ):
      raise ManifestValidationError(
        f"statistic {stat_id!r} population_ids must be a non-empty string array"
      )
    if len(set(population_ids)) != len(population_ids):
      raise ManifestValidationError(
        f"statistic {stat_id!r} population_ids must not contain duplicates"
      )
    if legacy_population_id is not None and legacy_population_id != population_ids[0]:
      raise ManifestValidationError(
        f"statistic {stat_id!r} population_id must match first population_ids entry"
      )
    compute_enabled = stat.get("compute_enabled", True)
    if not isinstance(compute_enabled, bool):
      raise ManifestValidationError(
        f"statistic {stat_id!r} compute_enabled must be a boolean"
      )
    if gate_ids is not None:
      unknown_populations = set(population_ids) - (set(gate_ids) | {"all_events"})
      if unknown_populations:
        raise ManifestValidationError(
          f"statistic {stat_id!r} references unknown populations "
          f"{sorted(unknown_populations)!r}"
        )
    metric = stat.get("metric")
    if metric not in valid_metrics:
      raise ManifestValidationError(
        f"statistic {stat_id!r} has invalid metric {metric!r}"
      )
    source_stage = stat.get("source_stage")
    if source_stage not in valid_stages:
      raise ManifestValidationError(
        f"statistic {stat_id!r} has invalid source_stage {source_stage!r}"
      )
    transform_id = stat.get("transform_id")
    if source_stage == "transformed" and (
      not isinstance(transform_id, str) or not transform_id
    ):
      raise ManifestValidationError(
        f"statistic {stat_id!r} transformed source_stage requires transform_id"
      )
    if transform_id is not None and (
      not isinstance(transform_id, str) or not transform_id
    ):
      raise ManifestValidationError(
        f"statistic {stat_id!r} transform_id must be a non-empty string or null"
      )
    value_policy = stat.get("value_policy", "full_events")
    if value_policy not in valid_value_policies:
      raise ManifestValidationError(
        f"statistic {stat_id!r} has invalid value_policy {value_policy!r}"
      )
    non_finite_policy = stat.get("non_finite_policy", "strict")
    if non_finite_policy not in valid_non_finite_policies:
      raise ManifestValidationError(
        f"statistic {stat_id!r} has invalid non_finite_policy "
        f"{non_finite_policy!r}"
      )
    parameter_id = stat.get("parameter_id")
    if parameter_id is not None and (
      not isinstance(parameter_id, str) or not parameter_id
    ):
      raise ManifestValidationError(
        f"statistic {stat_id!r} parameter_id must be a non-empty string or null"
      )
    if metric in value_metrics and parameter_id is None:
      raise ManifestValidationError(
        f"statistic {stat_id!r} metric {metric!r} requires parameter_id"
      )
    if transform_id is not None and transforms is not None:
      if transform_id not in transforms:
        raise ManifestValidationError(
          f"statistic {stat_id!r} references unknown transform {transform_id!r}"
        )
      if parameter_id != transforms[transform_id][1]:
        raise ManifestValidationError(
          f"statistic {stat_id!r} parameter_id does not match transform "
          f"{transform_id!r}"
        )
    settings = stat.get("settings", {})
    if not isinstance(settings, dict):
      raise ManifestValidationError(
        f"statistic {stat_id!r} settings must be an object"
      )
    if metric == "percentile":
      q = settings.get("q")
      if q is None:
        raise ManifestValidationError(
          f"statistic {stat_id!r} percentile metric requires 'q' in settings"
        )
      if not isinstance(q, (int, float)) or isinstance(q, bool):
        raise ManifestValidationError(
          f"statistic {stat_id!r} percentile 'q' must be a number"
        )
      if not math.isfinite(q):
        raise ManifestValidationError(
          f"statistic {stat_id!r} percentile 'q' must be finite"
        )
      if q < 0 or q > 100:
        raise ManifestValidationError(
          f"statistic {stat_id!r} percentile 'q' must be in [0, 100]"
        )
    display_format = stat.get("format")
    if display_format is not None and not isinstance(display_format, str):
      raise ManifestValidationError(
        f"statistic {stat_id!r} format must be a string or null"
      )


def _validate_current_gate_parent_references(
  strategy_data: Any,
  gate_ids: set[str],
) -> None:
  """Validate that gate parent_population_id references are resolvable.

  A gate's parent_population_id is either:
    - null (root gate, parent is All Events)
    - "all_events" (built-in root population)
    - Another gate ID within the same strategy
  """

  # Built-in population IDs that don't need to be defined as gates.
  BUILTIN_POPULATIONS = frozenset({"all_events", "allEvents"})

  if not isinstance(strategy_data, dict):
    return
  for strategy_id, strategy in strategy_data.items():
    if not isinstance(strategy, dict):
      continue
    gates = strategy.get("gates", [])
    if not isinstance(gates, list):
      continue
    # Collect gate IDs within this specific strategy.
    local_gate_ids = {
      g.get("id") for g in gates
      if isinstance(g, dict) and isinstance(g.get("id"), str) and g.get("id")
    }
    for gate in gates:
      if not isinstance(gate, dict):
        continue
      gate_id = gate.get("id", "unknown")
      try:
        validate_gate_name(gate.get("name", ""))
      except ValueError as exc:
        raise ManifestValidationError(
          f"gating strategy {strategy_id!r} gate {gate_id!r} has invalid name "
          f"{gate.get('name')!r}; {exc}"
        ) from exc
      parent = gate.get("parent_population_id")
      if parent is None:
        continue  # Root gate.
      if not isinstance(parent, str) or not parent:
        raise ManifestValidationError(
          f"gate {gate_id!r} parent_population_id must be a non-empty string or null"
        )
      if parent in BUILTIN_POPULATIONS:
        continue  # Built-in root population.
      if parent not in local_gate_ids:
        raise ManifestValidationError(
          f"gate {gate_id!r} references unknown parent_population_id "
          f"{parent!r} in strategy {strategy_id!r}"
        )


def _validate_file_fingerprint(sample_id: str, value: Any) -> None:
  """Validate the persisted fingerprint fields without reading the input file."""
  if not isinstance(value, dict):
    raise ManifestValidationError(
      f"sample {sample_id!r} fingerprint must be an object"
    )
  for field in ("size", "mtime_ns"):
    number = value.get(field)
    if not isinstance(number, int) or isinstance(number, bool) or number < 0:
      raise ManifestValidationError(
        f"sample {sample_id!r} fingerprint {field} must be a non-negative integer"
      )
  for field in ("hash_algorithm", "hash_value"):
    text = value.get(field)
    if not isinstance(text, str) or not text:
      raise ManifestValidationError(
        f"sample {sample_id!r} fingerprint {field} must be a non-empty string"
      )


def load_manifest(path: str | Path) -> dict[str, Any]:
  """Load and validate a manifest.json from a .flowdesk directory."""

  manifest_path = Path(path) / "manifest.json"
  if not manifest_path.exists():
    raise ManifestValidationError(f"manifest.json not found: {manifest_path}")

  try:
    with manifest_path.open(encoding="utf-8") as handle:
      data: dict[str, Any] = json.load(handle)
  except json.JSONDecodeError as exc:
    raise ManifestValidationError(f"invalid JSON in manifest.json: {exc}") from exc

  validate_manifest(data)
  migrated = migrate_manifest(data)
  validate_manifest(migrated)
  return migrated
