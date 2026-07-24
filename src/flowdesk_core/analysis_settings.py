"""Portable, sample-independent analysis settings definitions."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from flowdesk_core.gating_strategy import ordered_gates
from flowdesk_core.models import GateSpec, GatingStrategySpec

ANALYSIS_SETTINGS_DOCUMENT_KIND = "analysis_settings"
ANALYSIS_SETTINGS_VERSION = "1.0.0"

ANALYSIS_DEFINITION_KEYS = (
  "gating_strategies_data",
  "derived_parameters",
  "transforms",
  "compensation_matrices",
  "statistics",
  "auto_gate_templates",
  "magnetic_gate_templates",
  "tethered_gate_templates",
  "plot_views",
)


def migrate_analysis_settings(data: Mapping[str, Any]) -> dict[str, Any]:
  """Migrate a settings document through the versioned settings registry."""
  candidate = deepcopy(dict(data))
  version = candidate.get("settings_version")
  if version != ANALYSIS_SETTINGS_VERSION:
    raise AnalysisSettingsError(
      f"unsupported analysis settings version: {version!r}"
    )
  validate_analysis_settings(candidate)
  return candidate


class AnalysisSettingsError(ValueError):
  """Raised when portable analysis settings are invalid."""


def extract_analysis_settings(
  project: Mapping[str, Any],
  *,
  source_project_id: str | None = None,
) -> dict[str, Any]:
  """Extract reusable definitions without sample or result state."""
  if not isinstance(project, Mapping):
    raise AnalysisSettingsError("project must be an object")
  definition: dict[str, Any] = {}
  for key in ANALYSIS_DEFINITION_KEYS:
    value = project.get(key, {} if key == "gating_strategies_data" else [])
    if key == "gating_strategies_data" and not value:
      value = {
        "default_strategy": {
          "id": "default_strategy",
          "name": "Default Strategy",
          "root_population_id": "all_events",
          "gates": [],
        }
      }
    definition[key] = _portable_definition(key, value)
  result: dict[str, Any] = {
    "document_kind": ANALYSIS_SETTINGS_DOCUMENT_KIND,
    "settings_version": ANALYSIS_SETTINGS_VERSION,
    "analysis_definition": definition,
  }
  if source_project_id:
    result["source_project_id"] = source_project_id
  validate_analysis_settings(result)
  return result


def validate_analysis_settings(settings: Mapping[str, Any]) -> None:
  """Validate document shape and references internal to the definition."""
  if not isinstance(settings, Mapping):
    raise AnalysisSettingsError("analysis settings must be an object")
  if settings.get("document_kind") != ANALYSIS_SETTINGS_DOCUMENT_KIND:
    raise AnalysisSettingsError("document_kind must be 'analysis_settings'")
  if settings.get("settings_version") != ANALYSIS_SETTINGS_VERSION:
    raise AnalysisSettingsError(
      f"unsupported analysis settings version: {settings.get('settings_version')!r}"
    )
  definition = settings.get("analysis_definition")
  if not isinstance(definition, Mapping):
    raise AnalysisSettingsError("analysis_definition must be an object")
  strategies = definition.get("gating_strategies_data")
  if not isinstance(strategies, Mapping) or not strategies:
    raise AnalysisSettingsError("at least one gating strategy is required")
  gate_ids: set[str] = set()
  for strategy_id, raw_strategy in strategies.items():
    if not isinstance(strategy_id, str) or not strategy_id:
      raise AnalysisSettingsError("strategy IDs must be non-empty strings")
    if not isinstance(raw_strategy, Mapping):
      raise AnalysisSettingsError(f"strategy {strategy_id!r} must be an object")
    gates = raw_strategy.get("gates")
    if not isinstance(gates, list):
      raise AnalysisSettingsError(f"strategy {strategy_id!r}.gates must be an array")
    parsed: list[GateSpec] = []
    for raw_gate in gates:
      if not isinstance(raw_gate, Mapping):
        raise AnalysisSettingsError("gate definitions must be objects")
      try:
        gate = GateSpec(**dict(raw_gate))
      except (TypeError, ValueError) as exc:
        raise AnalysisSettingsError(f"invalid gate definition: {exc}") from exc
      if gate.id in gate_ids:
        raise AnalysisSettingsError(f"duplicate gate ID: {gate.id!r}")
      gate_ids.add(gate.id)
      parsed.append(gate)
    try:
      ordered_gates(
        GatingStrategySpec(
          id=strategy_id,
          name=str(raw_strategy.get("name", strategy_id)),
          gates=tuple(parsed),
          root_population_id=str(raw_strategy.get("root_population_id", "all_events")),
        )
      )
    except Exception as exc:
      raise AnalysisSettingsError(
        f"invalid strategy {strategy_id!r}: {exc}"
      ) from exc

  _validate_collection(definition, "derived_parameters")
  _validate_collection(definition, "transforms")
  _validate_collection(definition, "compensation_matrices")
  _validate_collection(definition, "statistics")
  for key in ("auto_gate_templates", "magnetic_gate_templates", "tethered_gate_templates"):
    _validate_collection(definition, key)
  _validate_collection(definition, "plot_views")
  transform_ids = {
    item.get("id") for item in definition["transforms"]
    if isinstance(item, Mapping)
  }
  parameter_ids = _definition_parameter_ids(definition)
  for strategy in strategies.values():
    for raw_gate in strategy.get("gates", []):
      for key in ("x_transform_id", "y_transform_id"):
        transform_id = raw_gate.get(key)
        if transform_id is not None and transform_id not in transform_ids:
          raise AnalysisSettingsError(
            f"gate {raw_gate.get('id')!r} references unknown transform {transform_id!r}"
          )
      for key in ("x_parameter", "y_parameter"):
        parameter_id = raw_gate.get(key)
        if parameter_id is not None and parameter_ids and parameter_id not in parameter_ids:
          raise AnalysisSettingsError(
            f"gate {raw_gate.get('id')!r} references unknown parameter {parameter_id!r}"
          )
  for transform in definition["transforms"]:
    transform_id = transform.get("id") if isinstance(transform, Mapping) else None
    if not isinstance(transform_id, str) or not transform_id:
      raise AnalysisSettingsError("transform IDs must be non-empty strings")
    parameter = transform.get("parameter")
    if parameter_ids and parameter not in parameter_ids:
      raise AnalysisSettingsError(
        f"transform {transform_id!r} references unknown parameter {parameter!r}"
      )
  transform_by_id = {
    item["id"]: item for item in definition["transforms"]
    if isinstance(item, Mapping) and isinstance(item.get("id"), str)
  }
  for strategy in strategies.values():
    for gate in strategy.get("gates", []):
      for parameter_key, transform_key in (
        ("x_parameter", "x_transform_id"),
        ("y_parameter", "y_transform_id"),
      ):
        transform_id = gate.get(transform_key)
        transform = transform_by_id.get(transform_id)
        if transform is not None and transform.get("parameter") != gate.get(parameter_key):
          raise AnalysisSettingsError(
            f"gate {gate.get('id')!r} {transform_key} does not match its parameter"
          )
  for statistic in definition["statistics"]:
    if not isinstance(statistic, Mapping):
      continue
    transform_id = statistic.get("transform_id")
    if transform_id is not None and transform_id not in transform_ids:
      raise AnalysisSettingsError(
        f"statistic {statistic.get('id')!r} references unknown transform {transform_id!r}"
      )
    population_ids = statistic.get("population_ids")
    if population_ids is None and statistic.get("population_id") is not None:
      population_ids = [statistic.get("population_id")]
    if population_ids is not None:
      known_population_ids = gate_ids | {"all_events"}
      if any(population_id not in known_population_ids for population_id in population_ids):
        raise AnalysisSettingsError(
          f"statistic {statistic.get('id')!r} references an unknown population"
        )


def replace_analysis_settings(
  project: Mapping[str, Any],
  settings: Mapping[str, Any],
) -> dict[str, Any]:
  """Return a target project with only reusable analysis definitions replaced."""
  validate_analysis_settings(settings)
  candidate = deepcopy(dict(project))
  definition = settings["analysis_definition"]
  for key in ANALYSIS_DEFINITION_KEYS:
    candidate[key] = deepcopy(definition[key])
  strategies = candidate["gating_strategies_data"]
  strategy_ids = set(strategies)
  default_strategy_id = (
    "default_strategy"
    if "default_strategy" in strategy_ids
    else next(iter(strategy_ids))
  )
  for profile in candidate.get("execution_profiles", []):
    if isinstance(profile, dict) and profile.get("gating_strategy_id") not in strategy_ids:
      profile["gating_strategy_id"] = default_strategy_id
  for binding in candidate.get("group_strategy_bindings", []):
    if isinstance(binding, dict) and binding.get("gating_strategy_id") not in strategy_ids:
      binding["gating_strategy_id"] = default_strategy_id
  matrix_ids = {
    item.get("id") for item in candidate["compensation_matrices"]
    if isinstance(item, Mapping)
  }
  if candidate.get("default_compensation_matrix_id") not in matrix_ids:
    candidate["default_compensation_matrix_id"] = None
  return candidate


def preflight_analysis_settings(
  project: Mapping[str, Any],
  settings: Mapping[str, Any],
) -> list[str]:
  """Return blocking channel diagnostics before applying settings."""
  validate_analysis_settings(settings)
  definition = settings["analysis_definition"]
  parameter_ids = _definition_parameter_ids(definition)
  derived_ids = {
    item.get("id") for item in definition["derived_parameters"]
    if isinstance(item, Mapping)
  }
  sample_parameters: dict[str, set[str]] = {}
  for sample in project.get("samples", []):
    if not isinstance(sample, Mapping):
      continue
    sample_id = str(sample.get("id", "unknown"))
    sample_parameters[sample_id] = {
      str(channel.get("id"))
      for channel in sample.get("channels", [])
      if isinstance(channel, Mapping) and channel.get("id")
    }
  referenced = _referenced_parameters(definition)
  diagnostics: list[str] = []
  for sample_id, available in sample_parameters.items():
    for parameter in sorted(referenced):
      if (
        parameter not in available
        and parameter not in derived_ids
        and parameter in parameter_ids
      ):
        diagnostics.append(
          f"sample {sample_id!r} is missing analysis parameter {parameter!r}"
        )
  return diagnostics


def _portable_definition(key: str, value: Any) -> Any:
  if key == "gating_strategies_data":
    if not isinstance(value, Mapping):
      raise AnalysisSettingsError("gating_strategies_data must be an object")
    return deepcopy(dict(value))
  if not isinstance(value, list):
    raise AnalysisSettingsError(f"{key} must be an array")
  if key == "plot_views":
    portable_views = []
    for item in value:
      if not isinstance(item, Mapping):
        raise AnalysisSettingsError("plot view definitions must be objects")
      portable_views.append({
        key: deepcopy(item[key])
        for key in ("id", "presentation", "rendering_downsample")
        if key in item
      })
    return portable_views
  return deepcopy(value)


def _validate_collection(definition: Mapping[str, Any], key: str) -> None:
  if not isinstance(definition.get(key), list):
    raise AnalysisSettingsError(f"{key} must be an array")


def _definition_parameter_ids(definition: Mapping[str, Any]) -> set[str]:
  parameters = {
    str(item.get("id")) for item in definition["derived_parameters"]
    if isinstance(item, Mapping) and item.get("id")
  }
  parameters.update(
    str(item.get("parameter")) for item in definition["transforms"]
    if isinstance(item, Mapping) and item.get("parameter")
  )
  for strategy in definition["gating_strategies_data"].values():
    parameters.update(
      str(raw_gate[key])
      for raw_gate in strategy.get("gates", [])
      for key in ("x_parameter", "y_parameter")
      if raw_gate.get(key)
    )
  return parameters


def _referenced_parameters(definition: Mapping[str, Any]) -> set[str]:
  result: set[str] = set()
  for strategy in definition["gating_strategies_data"].values():
    for gate in strategy.get("gates", []):
      for key in ("x_parameter", "y_parameter"):
        if gate.get(key):
          result.add(str(gate[key]))
  result.update(
    str(item["parameter"])
    for item in definition["transforms"]
    if isinstance(item, Mapping) and item.get("parameter")
  )
  result.update(
    str(item["parameter_id"])
    for item in definition["statistics"]
    if isinstance(item, Mapping) and item.get("parameter_id")
  )
  result.update(
    str(parameter)
    for item in definition["derived_parameters"]
    if isinstance(item, Mapping)
    for parameter in item.get("input_parameters", [])
    if parameter
  )
  return result
