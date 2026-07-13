"""Manifest validation for .flowdesk project bundles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import TransformSpec
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
  defaults_by_parameter = {
    parameter: transform_id
    for transform_id, (_transform_type, parameter) in transforms.items()
  }
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
      for axis in ("x", "y"):
        parameter = gate.get(f"{axis}_parameter")
        if parameter is None:
          continue
        transform_id = gate.get(f"{axis}_transform_id")
        if axis == "x" and transform_id is None:
          transform_id = gate.get("transform_id")
        default_id = defaults_by_parameter.get(parameter)
        if transform_id is None and default_id is not None:
          raise ManifestValidationError(
            f"gate {gate_id!r} {axis}-axis must reference transform "
            f"{default_id!r} for parameter {parameter!r}"
          )
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
        if gate.get(f"{axis}_scale", "linear") != "linear":
          raise ManifestValidationError(
            f"gate {gate_id!r} {axis}-axis defines a double transform"
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
