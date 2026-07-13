"""GUI-independent pipeline runner.

Executes the canonical analysis pipeline:
  raw events -> compensation -> derived parameters -> transforms
  -> gates -> population statistics -> export.

Used by GUI, CLI, and Python API. Must never import PySide6, Qt, or flowdesk_qt.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.compensation import apply_compensation, validate_compensation_matrix
from flowdesk_core.derived_parameters import (
  DerivedParameterPlan,
  DerivedParameterPlanningError,
  ExpressionError,
  evaluate_expression,
  plan_derived_parameters,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_report import ExecutionDiagnostic, ExecutionReport
from flowdesk_core.gating_strategy import (
  GatingStrategyError,
  evaluate_gating_strategy_with_membership,
)
from flowdesk_core.models import (
  ChannelSpec,
  CompensationMatrixSpec,
  DerivedFailurePolicy,
  DerivedParameterSpec,
  GateSpec,
  GatingStrategySpec,
  PopulationMembership,
  PopulationResult,
  TransformSpec,
)
from flowdesk_core.sample import SampleData
from flowdesk_core.transforms import TransformError, apply_transform_to_column


class PipelineError(FlowdeskError):
  """Raised when the pipeline cannot execute."""


class _DerivedParameterStepError(PipelineError):
  """Carries a policy and diagnostic from the derived stage to the runner."""

  def __init__(
    self,
    policy: DerivedFailurePolicy,
    diagnostic: ExecutionDiagnostic,
  ) -> None:
    self.policy = policy
    self.diagnostic = diagnostic
    super().__init__(diagnostic.message)


@dataclass(frozen=True)
class _AnalysisData:
  """Events paired with ordered channel identity at one pipeline stage."""

  events: NDArray[np.float64]
  channels: tuple[ChannelSpec, ...]

  def __post_init__(self) -> None:
    if self.events.ndim != 2 or self.events.shape[1] != len(self.channels):
      raise PipelineError(
        "pipeline stage event columns must match ordered channel definitions"
      )

  @property
  def channel_ids(self) -> list[str]:
    """Stable IDs aligned with event columns."""
    return [channel.id for channel in self.channels]


def run_project_pipeline(
  project: Mapping[str, Any],
  output_dir: str | None = None,
  execution_profile_id: str = "default",
  event_data: dict[str, NDArray[np.float64]] | None = None,
  channel_names: list[str] | None = None,
  samples: Sequence[SampleData] | None = None,
) -> ExecutionReport:
  """Run a project pipeline and return an execution report.

  Args:
    project: Project manifest dictionary (from ``load_project``).
    output_dir: Directory for export outputs.
    execution_profile_id: Id of the execution profile to use.
    event_data: Optional per-sample event arrays keyed by sample id.
        If omitted, the runner uses pre-baked ``population_results`` from the
        project manifest (backward compatibility).
    channel_names: Column names aligned with ``event_data`` arrays.
    samples: Preferred typed inputs with per-sample channel identity.

  Returns:
    ``ExecutionReport`` with population results and reproducibility metadata.
  """

  context = ExecutionContext(
    output_dir=None if output_dir is None else Path(output_dir),
    execution_profile_id=execution_profile_id,
  )
  runner = PipelineRunner(project)
  if samples is not None:
    return runner.run_samples(context, samples)
  return runner.run(context, event_data, channel_names)


class PipelineRunner:
  """Headless runner used by GUI, CLI, and Python API."""

  def __init__(self, project: Mapping[str, Any]) -> None:
    self._project = dict(project)

  # ------------------------------------------------------------------
  # Public API
  # ------------------------------------------------------------------

  def run(
    self,
    context: ExecutionContext,
    event_data: dict[str, NDArray[np.float64]] | None = None,
    channel_names: list[str] | None = None,
  ) -> ExecutionReport:
    """Run the configured profile.

    When ``event_data`` is provided, the full canonical pipeline is executed.
    Otherwise, pre-baked ``population_results`` from the project manifest are
    returned (backward-compatible placeholder mode).
    """
    # ---------- Full pipeline execution when event data is supplied ----------
    if event_data is not None and channel_names is not None:
      legacy_channels = tuple(
        ChannelSpec(id=name, name=name) for name in channel_names
      )
      try:
        samples = tuple(
          SampleData(
            sample_id=sample_id,
            events=events,
            channels=legacy_channels,
          )
          for sample_id, events in event_data.items()
        )
      except FlowdeskError as exc:
        raise PipelineError(f"invalid legacy event input: {exc}") from exc
      return self.run_samples(context, samples)

    profile = self._resolve_execution_profile(context.execution_profile_id)
    messages = [f"execution_profile={context.execution_profile_id}"]

    # ---------- Placeholder mode (backward compat) ----------
    return self._run_placeholder(profile, context, messages)

  def run_samples(
    self,
    context: ExecutionContext,
    samples: Sequence[SampleData],
  ) -> ExecutionReport:
    """Run the canonical pipeline with sample-specific channel identities."""
    profile = self._resolve_execution_profile(context.execution_profile_id)
    sample_by_id: dict[str, SampleData] = {}
    for sample in samples:
      if sample.sample_id in sample_by_id:
        raise PipelineError(f"duplicate input sample ID: {sample.sample_id!r}")
      sample_by_id[sample.sample_id] = sample
    messages = [f"execution_profile={context.execution_profile_id}"]
    return self._run_full_pipeline(
      profile,
      context,
      sample_by_id,
      messages,
    )

  # ------------------------------------------------------------------
  # Profile resolution
  # ------------------------------------------------------------------

  def _resolve_execution_profile(
    self, profile_id: str
  ) -> dict[str, Any]:
    """Locate and return the execution profile by id."""
    profiles: list[dict[str, Any]] = self._project.get(
      "execution_profiles", []
    )
    for p in profiles:
      if p.get("id") == profile_id:
        return p

    known_ids = [p.get("id") for p in profiles if p.get("id")]
    raise PipelineError(
      f"unknown execution profile: {profile_id!r}. "
      f"Available: {known_ids or '(none)'}"
    )

  # ------------------------------------------------------------------
  # Full pipeline
  # ------------------------------------------------------------------

  def _run_full_pipeline(
    self,
    profile: dict[str, Any],
    context: ExecutionContext,
    sample_data: Mapping[str, SampleData],
    messages: list[str],
  ) -> ExecutionReport:
    """Execute the canonical pipeline on event data."""

    gating_strategy_id = profile.get("gating_strategy_id")
    samples = self._project.get("samples", [])

    # Resolve which samples to process.
    sample_selector = profile.get("sample_selector", "all")
    selected_samples = self._resolve_samples(samples, sample_selector)
    available_input_ids: set[str] = set()
    for sample_meta in selected_samples:
      sample_id = str(sample_meta.get("id", "unknown"))
      typed_sample = sample_data.get(sample_id)
      if typed_sample is not None:
        available_input_ids.update(channel.id for channel in typed_sample.channels)
      for channel in sample_meta.get("channels", []):
        if isinstance(channel, Mapping) and isinstance(channel.get("id"), str):
          available_input_ids.add(channel["id"])
    try:
      derived_plan = plan_derived_parameters(
        self._derived_parameter_specs(), available_input_ids
      )
    except DerivedParameterPlanningError as exc:
      raise PipelineError(f"{exc.code}: {exc}") from exc

    all_population_results: list[PopulationResult] = []
    all_population_membership: list[PopulationMembership] = []
    input_files: list[dict[str, Any]] = []
    diagnostics: list[ExecutionDiagnostic] = []
    failed_sample_count = 0

    for sample_meta in selected_samples:
      sid = sample_meta.get("id", "unknown")
      sample = sample_data.get(sid)
      if sample is None:
        messages.append(f"warning: no event data for sample {sid!r}, skipping")
        continue
      analysis_data = _AnalysisData(sample.events, sample.channels)

      # Record input file metadata.
      input_info = self._record_input_file(sample_meta, analysis_data.events)
      input_files.append(input_info)

      # --- Step 1: Compensation ---
      compensated = self._step_compensation(analysis_data)
      messages.append(f"sample={sid} compensation=done")

      # --- Step 2: Derived parameters ---
      try:
        enriched, derived_diagnostics = self._step_derived_parameters(
          compensated, sid, derived_plan
        )
      except _DerivedParameterStepError as exc:
        diagnostics.append(exc.diagnostic)
        if exc.policy is DerivedFailurePolicy.FAIL_RUN:
          raise PipelineError(
            f"{exc.diagnostic.code}: {exc.diagnostic.message}"
          ) from exc
        failed_sample_count += 1
        messages.append(
          f"sample={sid} derived_params=failed policy={exc.policy.value}"
        )
        continue
      diagnostics.extend(derived_diagnostics)
      messages.append(f"sample={sid} derived_params=done")

      # --- Step 3: Transforms ---
      transformed = self._step_transforms(enriched)
      messages.append(f"sample={sid} transforms=done")

      # --- Step 4: Gating ---
      if gating_strategy_id is not None:
        try:
          pop_results, pop_membership = self._step_gating(
            gating_strategy_id, transformed, sid
          )
        except GatingStrategyError as exc:
          raise PipelineError(
            f"invalid gating strategy {gating_strategy_id!r}: {exc}"
          ) from exc
      else:
        pop_results = self._fallback_root_population(
          sid, int(transformed.events.shape[0])
        )
        pop_membership = self._fallback_root_membership(
          sid, int(transformed.events.shape[0])
        )

      all_population_results.extend(pop_results)
      all_population_membership.extend(pop_membership)

    population_tuple = tuple(all_population_results)
    membership_tuple = tuple(all_population_membership)
    if failed_sample_count and population_tuple:
      status = "partial_success"
    elif failed_sample_count:
      status = "failed_samples"
    else:
      status = "success" if population_tuple else "no_data_processed"

    return ExecutionReport(
      project_id=str(self._project.get("project_id", "unknown")),
      execution_profile_id=context.execution_profile_id,
      pipeline_version=str(self._project.get("pipeline_version", "0.1")),
      status=status,
      population_results=population_tuple,
      population_membership=membership_tuple,
      input_files=tuple(input_files),
      messages=tuple(messages),
      diagnostics=tuple(diagnostics),
    )

  # ------------------------------------------------------------------
  # Pipeline steps
  # ------------------------------------------------------------------

  def _step_compensation(
    self,
    data: _AnalysisData,
  ) -> _AnalysisData:
    """Apply compensation if configured."""
    comp_id = self._project.get("default_compensation_matrix_id")
    if comp_id is None:
      return data

    matrices = self._project.get("compensation_matrices", [])
    matrix_spec = self._find_by_id(matrices, comp_id)
    if matrix_spec is None:
      return data

    channels = tuple(matrix_spec.get("channels", []))
    matrix_data = tuple(
      tuple(row) for row in matrix_spec.get("matrix", [])
    )

    comp_spec = CompensationMatrixSpec(
      id=comp_id,
      name=matrix_spec.get("name", comp_id),
      source=matrix_spec.get("source", "user_defined"),
      channels=channels,
      matrix=matrix_data,
    )
    validate_compensation_matrix(comp_spec)
    return _AnalysisData(
      apply_compensation(comp_spec, data.events, data.channel_ids),
      data.channels,
    )

  def _step_derived_parameters(
    self,
    data: _AnalysisData,
    sample_id: str,
    plan: DerivedParameterPlan,
  ) -> tuple[_AnalysisData, tuple[ExecutionDiagnostic, ...]]:
    """Evaluate derived parameter expressions and append as new columns."""
    if not plan.execution_order:
      return data, ()

    current_channels = list(data.channels)
    current_data = data.events
    diagnostics: list[ExecutionDiagnostic] = []

    for spec in plan.execution_order:
      label = spec.output_label or spec.name

      # Build variable dict from current columns.
      variables: dict[str, NDArray[np.float64]] = {}
      for i, channel in enumerate(current_channels):
        variables[channel.id] = current_data[:, i]

      try:
        result_any = evaluate_expression(spec.expression, variables,  # type: ignore[arg-type]
                                         allow_functions=True)
        result = np.asarray(result_any, dtype=np.float64)
        if result.ndim == 0:
          result = np.full(current_data.shape[0], float(result), dtype=np.float64)
        elif result.shape != (current_data.shape[0],):
          raise ValueError(
            f"expression returned shape {result.shape}, expected "
            f"({current_data.shape[0]},)"
          )
      except (ExpressionError, ArithmeticError, TypeError, ValueError) as exc:
        diagnostic = ExecutionDiagnostic(
          code="derived_parameter_evaluation_failed",
          message=(
            f"derived parameter {spec.id!r} failed for sample {sample_id!r}: "
            f"{exc}"
          ),
          severity=(
            "warning"
            if spec.invalid_value_policy
            is DerivedFailurePolicy.EMIT_NAN_WITH_WARNING
            else "error"
          ),
          stage="derived_parameters",
          sample_id=sample_id,
          parameter_id=spec.id,
          exception_type=type(exc).__name__,
          affected_event_count=int(current_data.shape[0]),
          details={
            "expression": spec.expression,
            "policy": spec.invalid_value_policy.value,
          },
        )
        if (
          spec.invalid_value_policy
          is not DerivedFailurePolicy.EMIT_NAN_WITH_WARNING
        ):
          raise _DerivedParameterStepError(
            spec.invalid_value_policy, diagnostic
          ) from exc
        diagnostics.append(diagnostic)
        result = np.full(current_data.shape[0], np.nan, dtype=np.float64)

      new_col = result.reshape(-1, 1)
      current_data = np.hstack([current_data, new_col])
      current_channels.append(
        ChannelSpec(
          id=spec.id,
          name=label,
          metadata={
            "kind": "derived_parameter",
            "source_stage": spec.source_stage,
          },
        )
      )

    return _AnalysisData(current_data, tuple(current_channels)), tuple(diagnostics)

  def _derived_parameter_specs(self) -> tuple[DerivedParameterSpec, ...]:
    """Parse project definitions once before any sample is processed."""
    definitions = self._project.get("derived_parameters", [])
    parsed: list[DerivedParameterSpec] = []
    for definition in definitions:
      if not isinstance(definition, Mapping):
        raise PipelineError(
          "invalid_derived_parameter_definition: definition must be an object"
        )
      try:
        parameter_id = definition["id"]
        parsed.append(
          DerivedParameterSpec(
            id=parameter_id,
            name=definition.get("name", parameter_id),
            expression=definition["expression"],
            source_stage=definition.get("source_stage", "compensated"),
            input_parameters=tuple(definition.get("input_parameters", ())),
            output_label=definition.get("output_label"),
            invalid_value_policy=definition.get(
              "invalid_value_policy", "emit_nan_with_warning"
            ),
            notes=definition.get("notes", ""),
          )
        )
      except (KeyError, TypeError, ValueError) as exc:
        parameter_id = definition.get("id", "unknown")
        raise PipelineError(
          f"invalid_derived_parameter_definition: {parameter_id!r}: {exc}"
        ) from exc
    return tuple(parsed)

  def _step_transforms(
    self,
    data: _AnalysisData,
  ) -> _AnalysisData:
    """Apply transforms to specified parameters."""
    specs = self._project.get("transforms", [])
    if not specs:
      return data

    current_data = data.events.copy()

    for spec_dict in specs:
      spec = TransformSpec(
        id=spec_dict["id"],
        name=spec_dict.get("name", spec_dict["id"]),
        transform_type=spec_dict["transform_type"],
        parameter=spec_dict["parameter"],
        settings=spec_dict.get("settings", {}),
      )

      try:
        current_data = apply_transform_to_column(
          spec, current_data, data.channel_ids
        )
      except TransformError:
        pass  # Skip invalid transforms silently.

    return _AnalysisData(current_data, data.channels)

  def _step_gating(
    self,
    strategy_id: str,
    data: _AnalysisData,
    sample_id: str,
  ) -> tuple[list[PopulationResult], list[PopulationMembership]]:
    """Evaluate the gating strategy on transformed data.

    Returns:
      A tuple of (population_results, population_membership) where membership
      carries read-only boolean masks aligned with the input event data.
    """
    strategy_dict = self._project.get("gating_strategies_data", {})
    strat = strategy_dict.get(strategy_id)
    if strat is None:
      # Try to build a minimal strategy from manifest.
      strat = self._build_strategy_from_manifest(strategy_id)
      if strat is None:
        return (
          self._fallback_root_population(sample_id, int(data.events.shape[0])),
          self._fallback_root_membership(sample_id, int(data.events.shape[0])),
        )

    if isinstance(strat, Mapping):
      strat = self._strategy_from_mapping(strat)

    results, masks = evaluate_gating_strategy_with_membership(
      strat, data.events, data.channel_ids
    )

    # Attach sample_id to results (frozen dataclass, so rebuild).
    tagged_results: list[PopulationResult] = []
    for r in results:
      tagged_results.append(
        PopulationResult(
          sample_id=sample_id,
          population_id=r.population_id,
          event_count=r.event_count,
          frequency_of_parent=r.frequency_of_parent,
          frequency_of_total=r.frequency_of_total,
        )
      )

    # Build PopulationMembership entries from read-only masks.
    tagged_membership: list[PopulationMembership] = []
    for pop_id, mask in masks.items():
      tagged_membership.append(
        PopulationMembership(
          sample_id=sample_id,
          population_id=pop_id,
          mask=mask,
        )
      )

    return tagged_results, tagged_membership

  # ------------------------------------------------------------------
  # Placeholder mode (backward compatibility)
  # ------------------------------------------------------------------

  def _run_placeholder(
    self,
    profile: dict[str, Any],
    context: ExecutionContext,
    messages: list[str],
  ) -> ExecutionReport:
    """Return pre-baked population results from the project manifest."""

    results = tuple(
      PopulationResult(**result)
      for result in self._project.get("population_results", [])
    )
    messages.append("mode=placeholder (no event data supplied)")
    return ExecutionReport(
      project_id=str(self._project.get("project_id", "unknown")),
      execution_profile_id=context.execution_profile_id,
      pipeline_version=str(self._project.get("pipeline_version", "0.1")),
      status="placeholder_complete",
      population_results=results,
      messages=tuple(messages),
    )

  # ------------------------------------------------------------------
  # Helpers
  # ------------------------------------------------------------------

  @staticmethod
  def _find_by_id(
    items: list[dict[str, Any]], item_id: str
  ) -> dict[str, Any] | None:
    for item in items:
      if item.get("id") == item_id:
        return item
    return None

  @staticmethod
  def _resolve_samples(
    samples: list[dict[str, Any]], selector: str
  ) -> list[dict[str, Any]]:
    """Select samples based on the profile's sample_selector."""
    if selector == "all" or not selector:
      return samples
    # selector can be a specific sample id.
    return [s for s in samples if s.get("id") == selector]

  @staticmethod
  def _record_input_file(
    sample_meta: dict[str, Any], data: NDArray[np.float64]
  ) -> dict[str, Any]:
    """Record sample metadata for the execution report."""
    info: dict[str, Any] = {
      "sample_id": sample_meta.get("id", "unknown"),
      "n_events": int(data.shape[0]),
      "n_channels": int(data.shape[1]),
    }
    path = sample_meta.get("path")
    if path:
      info["path"] = path
      p = Path(path)
      if p.exists():
        stat = p.stat()
        info["mtime"] = stat.st_mtime
        # Compute a lightweight hash of first 8KB.
        with p.open("rb") as f:
          head = f.read(8192)
        info["head_hash"] = hashlib.md5(head).hexdigest()
    return info

  @staticmethod
  def _fallback_root_population(
    sample_id: str, n_events: int
  ) -> list[PopulationResult]:
    return [
      PopulationResult(
        sample_id=sample_id,
        population_id="all_events",
        event_count=n_events,
        frequency_of_parent=None,
        frequency_of_total=1.0,
      )
    ]

  @staticmethod
  def _fallback_root_membership(
    sample_id: str, n_events: int
  ) -> list[PopulationMembership]:
    mask = np.ones(n_events, dtype=np.bool_)
    mask.setflags(write=False)
    return [
      PopulationMembership(
        sample_id=sample_id,
        population_id="all_events",
        mask=mask,
      )
    ]

  @staticmethod
  def _build_strategy_from_manifest(
    strategy_id: str,
  ) -> GatingStrategySpec | None:
    """Attempt to construct a GatingStrategySpec from manifest data."""
    # This is intentionally minimal; full strategy loading is handled
    # by the storage layer.
    return None

  @staticmethod
  def _strategy_from_mapping(data: Mapping[str, Any]) -> GatingStrategySpec:
    """Build the core strategy model from JSON-compatible project data."""
    gates = tuple(
      GateSpec(
        id=str(gate["id"]),
        name=str(gate.get("name", gate["id"])),
        gate_type=gate["gate_type"],
        parent_population_id=gate.get("parent_population_id"),
        x_parameter=gate.get("x_parameter"),
        y_parameter=gate.get("y_parameter"),
        x_scale=gate.get("x_scale", "linear"),
        y_scale=gate.get("y_scale", "linear"),
        transform_id=gate.get("transform_id"),
        compensation_id=gate.get("compensation_id"),
        coordinates=tuple(tuple(point) for point in gate.get("coordinates", ())),
        thresholds=dict(gate.get("thresholds", {})),
        notes=str(gate.get("notes", "")),
      )
      for gate in data.get("gates", ())
    )
    return GatingStrategySpec(
      id=str(data["id"]),
      name=str(data.get("name", data["id"])),
      gates=gates,
      root_population_id=str(data.get("root_population_id", "all_events")),
      notes=str(data.get("notes", "")),
    )
