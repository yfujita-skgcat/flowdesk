"""GUI-independent pipeline runner.

Executes the canonical analysis pipeline:
  raw events -> compensation -> derived parameters -> transforms
  -> gates -> population statistics -> export.

Used by GUI, CLI, and Python API. Must never import PySide6, Qt, or flowdesk_qt.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.automatic_gates import (
  AutoGateFitError,
  auto_gate_fit_to_mapping,
  auto_gate_template_from_mapping,
  fit_auto_gate,
)
from flowdesk_core.compensation import (
  CompensationBindingResolution,
  CompensationError,
  CompensationValidationResult,
  apply_compensation,
  calculate_spillover_matrix,
  inspect_compensation_matrix,
  resolve_compensation_binding,
)
from flowdesk_core.derived_parameters import (
  DerivedParameterPlan,
  DerivedParameterPlanningError,
  DerivedParameterPreview,
  DerivedParameterStageError,
  DerivedParameterStageResult,
  ExpressionError,
  evaluate_array_expression,
  plan_derived_parameters,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.execution_context import ExecutionContext
from flowdesk_core.execution_report import ExecutionDiagnostic, ExecutionReport
from flowdesk_core.gating_strategy import (
  GatingStrategyError,
  evaluate_gating_strategy_with_membership,
)
from flowdesk_core.groups import (
  GroupResolutionError,
  annotation_specs_from_mapping,
  group_strategy_binding_specs_from_mapping,
  resolve_group_assignments_from_mappings,
  resolve_group_strategy_bindings,
  sample_group_specs_from_mapping,
)
from flowdesk_core.magnetic_gates import (
  MagneticGateFitError,
  fit_magnetic_gate,
  magnetic_gate_fit_to_mapping,
  magnetic_gate_template_from_mapping,
)
from flowdesk_core.models import (
  ChannelSpec,
  CompensationBindingSpec,
  CompensationCalculationControlSpec,
  CompensationCalculationSpec,
  CompensationMatrixSpec,
  DerivedFailurePolicy,
  DerivedParameterSpec,
  GateSpec,
  GatingStrategySpec,
  PopulationMembership,
  PopulationResult,
  SampleSpec,
  StatisticResult,
  StatisticSpec,
  TransformSpec,
)
from flowdesk_core.overrides import (
  GateOverrideError,
  override_spec_from_mapping,
  resolve_gate_overrides,
)
from flowdesk_core.preview import PreviewReport, PreviewRequest
from flowdesk_core.sample import SampleData
from flowdesk_core.statistics import compute_statistic
from flowdesk_core.tethered_gates import (
  TetheredGateFitError,
  fit_tethered_gate,
  tethered_gate_fit_to_mapping,
  tethered_gate_template_from_mapping,
)
from flowdesk_core.transforms import TransformError, apply_transform, validate_transform


class PipelineError(FlowdeskError):
  """Raised when the pipeline cannot execute."""

  def __init__(
    self,
    message: str,
    *,
    code: str = "pipeline_error",
    details: Mapping[str, Any] | None = None,
  ) -> None:
    self.code = code
    self.details = dict(details or {})
    super().__init__(message)


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
  transforms: tuple[TransformSpec, ...] = ()
  default_transform_ids: dict[str, str] = field(default_factory=dict)

  def __post_init__(self) -> None:
    if self.events.ndim != 2 or self.events.shape[1] != len(self.channels):
      raise PipelineError(
        "pipeline stage event columns must match ordered channel definitions"
      )

  @property
  def channel_ids(self) -> list[str]:
    """Stable IDs aligned with event columns."""
    return [channel.id for channel in self.channels]


@dataclass(frozen=True)
class _CompensationStepResult:
  """Canonical compensated view plus report-ready diagnostics."""

  data: _AnalysisData
  diagnostics: tuple[ExecutionDiagnostic, ...] = ()


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
    # A runner is an execution snapshot. Nested GUI/project mutations after
    # construction must not alter a running batch or preview calculation.
    self._project = deepcopy(dict(project))

  # ------------------------------------------------------------------
  # Public API
  # ------------------------------------------------------------------

  def resolve_group_assignments(
    self,
    execution_profile_id: str = "default",
  ) -> dict[str, dict[str, Any]]:
    """Return persisted Group IDs and strategy IDs for GUI/CLI inspection."""
    profile = self._resolve_execution_profile(execution_profile_id)
    selected = self._resolve_samples(
      self._project.get("samples", []), profile.get("sample_selector", "all")
    )
    groups = self._project.get("sample_groups", [])
    bindings = self._project.get("group_strategy_bindings", [])
    if not groups and not bindings:
      return {
        str(sample.get("id", "")): {
          "group_ids": [],
          "strategy_id": profile.get("gating_strategy_id"),
        }
        for sample in selected
      }
    try:
      resolved = resolve_group_assignments_from_mappings(
        groups,
        bindings,
        selected,
        self._project.get("annotations", []),
      )
    except GroupResolutionError as exc:
      raise PipelineError(
        f"{exc.code}: {exc}", code=exc.code, details=exc.details
      ) from exc
    fallback = profile.get("gating_strategy_id")
    return {
      str(sample.get("id", "")): resolved.get(
        str(sample.get("id", "")),
        {"group_ids": [], "strategy_id": fallback},
      )
      for sample in selected
    }

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

  def preview_sample(self, request: PreviewRequest) -> PreviewReport:
    """Run the canonical pipeline for one full-resolution sample.

    The returned values are non-authoritative preview data. The method is
    synchronous and GUI-independent so a later Qt scheduler can execute it on
    a worker without introducing a second scientific implementation.
    """
    assignments = self.resolve_group_assignments(request.execution_profile_id)
    assignment = assignments.get(request.sample_id)
    if assignment is None:
      raise PipelineError(
        f"preview sample is not selected by the execution profile: "
        f"{request.sample_id!r}"
      )
    strategy_id = assignment.get("strategy_id")
    if request.strategy_id is not None and request.strategy_id != strategy_id:
      raise PipelineError(
        "preview strategy does not match the project snapshot: "
        f"requested {request.strategy_id!r}, resolved {strategy_id!r}"
      )

    report = self.run_samples(
      ExecutionContext(execution_profile_id=request.execution_profile_id),
      (request.sample,),
    )
    population_results = tuple(
      result for result in report.population_results
      if result.sample_id == request.sample_id
    )
    population_membership = tuple(
      membership for membership in report.population_membership
      if membership.sample_id == request.sample_id
    )
    statistic_results = tuple(
      result for result in report.statistic_results
      if result.sample_id == request.sample_id
      and (
        not request.requested_statistic_ids
        or result.statistic_id in request.requested_statistic_ids
      )
    )
    population_ids = {
      result.population_id for result in population_results
    }
    if request.required_population_id not in population_ids:
      raise PipelineError(
        "preview required population was not produced: "
        f"{request.required_population_id!r}"
      )
    diagnostics = tuple(
      diagnostic for diagnostic in report.diagnostics
      if diagnostic.sample_id in {None, request.sample_id}
    )
    return PreviewReport(
      revision=request.revision,
      project_id=report.project_id,
      execution_profile_id=report.execution_profile_id,
      sample_id=request.sample_id,
      strategy_id=strategy_id,
      required_population_id=request.required_population_id,
      source_event_count=request.sample.event_count,
      status=report.status,
      population_results=population_results,
      population_membership=population_membership,
      statistic_results=statistic_results,
      diagnostics=diagnostics,
      messages=report.messages,
    )

  def preview_derived_parameter(
    self,
    sample: SampleData,
    output_channel_id: str,
    *,
    max_events: int = 200,
    execution_profile_id: str = "default",
  ) -> DerivedParameterPreview:
    """Preview one derived output through the canonical headless stages."""
    if max_events <= 0:
      raise PipelineError("derived preview max_events must be positive")
    specs = self._derived_parameter_specs()
    try:
      plan = plan_derived_parameters(
        specs, (channel.id for channel in sample.channels)
      )
    except DerivedParameterPlanningError as exc:
      raise PipelineError(f"{exc.code}: {exc}") from exc
    by_output_id = {spec.output_id: spec for spec in plan.execution_order}
    if output_channel_id not in by_output_id:
      raise PipelineError(
        f"unknown derived preview output channel: {output_channel_id!r}"
      )
    dependencies = dict(plan.dependencies)
    required = {output_channel_id}
    pending = [output_channel_id]
    while pending:
      current = pending.pop()
      for dependency in dependencies[current]:
        if dependency not in required:
          required.add(dependency)
          pending.append(dependency)
    preview_plan = DerivedParameterPlan(
      display_order=tuple(
        spec for spec in plan.display_order if spec.output_id in required
      ),
      execution_order=tuple(
        spec for spec in plan.execution_order if spec.output_id in required
      ),
      dependencies=tuple(
        item for item in plan.dependencies if item[0] in required
      ),
    )
    preview_event_count = min(sample.event_count, max_events)
    bounded = _AnalysisData(
      np.array(sample.events[:preview_event_count], dtype=np.float64, copy=True),
      sample.channels,
    )
    sample_meta = next(
      (
        value for value in self._project.get("samples", [])
        if value.get("id") == sample.sample_id
      ),
      {"id": sample.sample_id},
    )
    compensation = self._step_compensation(
      bounded,
      sample_id=sample.sample_id,
      execution_profile_id=execution_profile_id,
      group_ids=self._sample_group_ids(sample_meta),
    )
    try:
      stage_result, diagnostics = self._step_derived_parameters(
        compensation.data,
        bounded,
        sample.sample_id,
        preview_plan,
      )
    except _DerivedParameterStepError as exc:
      raise PipelineError(
        f"{exc.diagnostic.code}: {exc.diagnostic.message}"
      ) from exc
    output_index = stage_result.channel_ids.index(output_channel_id)
    return DerivedParameterPreview(
      values=stage_result.events[:, output_index],
      channel=stage_result.channels[output_index],
      source_event_count=sample.event_count,
      preview_event_count=preview_event_count,
      diagnostics=compensation.diagnostics + diagnostics,
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
    sample_assignments = self._resolve_group_assignments(
      selected_samples, gating_strategy_id
    )
    sample_strategy_ids = {
      sample_id: assignment[0]
      for sample_id, assignment in sample_assignments.items()
    }
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
    all_statistic_results: list[StatisticResult] = []
    all_auto_gate_fits: list[dict[str, Any]] = []
    all_magnetic_gate_fits: list[dict[str, Any]] = []
    all_tethered_gate_fits: list[dict[str, Any]] = []
    input_files: list[dict[str, Any]] = []
    diagnostics: list[ExecutionDiagnostic] = []
    failed_sample_count = 0

    # --- Pre-step: Execute compensation calculations ---
    # Control samples and populations are explicit in the persisted calculation
    # spec. They are gated from raw events before a calculated matrix is applied.
    extra_matrices: dict[str, Mapping[str, Any]] = {}
    calc_spec_list = self._compensation_calculation_specs()
    saved_calculation_matrix_ids = {
      matrix.get("id")
      for matrix in self._project.get("compensation_matrices", [])
      if isinstance(matrix, Mapping)
      and matrix.get("source") == "calculated"
      and isinstance(matrix.get("id"), str)
    }
    calculations_to_execute = tuple(
      spec for spec in calc_spec_list
      if f"calculated-{spec.id}" not in saved_calculation_matrix_ids
    )
    saved_count = len(calc_spec_list) - len(calculations_to_execute)
    if saved_count:
      messages.append(
        f"compensation_calculation=using_saved_result n_matrices={saved_count}"
      )
    if calculations_to_execute:
      try:
        extra_matrices, calc_diagnostics = (
          self._execute_compensation_calculations_with_gating(
            calculations_to_execute, sample_data, gating_strategy_id,
          )
        )
        diagnostics.extend(calc_diagnostics)
        messages.append(
          f"compensation_calculation=done n_matrices={len(extra_matrices)}"
        )
      except PipelineError as exc:
        messages.append(f"compensation_calculation=failed: {exc}")
        raise

    for sample_meta in selected_samples:
      sid = str(sample_meta.get("id", "unknown"))
      sample = sample_data.get(sid)
      if sample is None:
        messages.append(f"warning: no event data for sample {sid!r}, skipping")
        continue
      analysis_data = _AnalysisData(sample.events, sample.channels)

      # Record input file metadata.
      input_info = self._record_input_file(sample_meta, analysis_data.events)
      input_files.append(input_info)

      # --- Step 1: Compensation ---
      compensation = self._step_compensation(
        analysis_data,
        sample_id=sid,
        execution_profile_id=context.execution_profile_id,
        group_ids=self._sample_group_ids(sample_meta),
        extra_matrices=extra_matrices if extra_matrices else None,
      )
      compensated = compensation.data
      diagnostics.extend(compensation.diagnostics)
      messages.append(f"sample={sid} compensation=done")

      # --- Step 2: Derived parameters ---
      try:
        enriched, derived_diagnostics = self._step_derived_parameters(
          compensated, analysis_data, sid, derived_plan
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
      sample_gating_strategy_id = sample_strategy_ids.get(sid, gating_strategy_id)
      if sample_gating_strategy_id is not None:
        try:
          (
            pop_results,
            pop_membership,
            population_parent_ids,
            auto_gate_fits,
          ) = self._step_gating(
            sample_gating_strategy_id, transformed, sid
          )
          diagnostics.extend(
            diagnostic for fit in auto_gate_fits for diagnostic in fit["diagnostics"]
          )
          all_auto_gate_fits.extend(
            auto_gate_fit_to_mapping(fit["result"])
            for fit in auto_gate_fits if fit["kind"] == "auto"
          )
          all_magnetic_gate_fits.extend(
            magnetic_gate_fit_to_mapping(fit["result"])
            for fit in auto_gate_fits if fit["kind"] == "magnetic"
          )
          all_tethered_gate_fits.extend(
            tethered_gate_fit_to_mapping(fit["result"])
            for fit in auto_gate_fits if fit["kind"] == "tethered"
          )
        except GatingStrategyError as exc:
          raise PipelineError(
            f"invalid gating strategy {sample_gating_strategy_id!r}: {exc}"
          ) from exc
      else:
        pop_results = self._fallback_root_population(
          sid, int(transformed.events.shape[0])
        )
        pop_membership = self._fallback_root_membership(
          sid, int(transformed.events.shape[0])
        )
        population_parent_ids = {"all_events": None}

      all_population_results.extend(pop_results)
      all_population_membership.extend(pop_membership)

      # --- Step 5: Statistics ---
      statistic_data_by_stage = {
        "raw": analysis_data,
        "compensated": _AnalysisData(enriched.events, enriched.channels),
        "transformed": self._materialize_transformed_statistics_data(transformed),
      }
      stat_results = self._step_statistics(
        sample_id=sid,
        data_by_stage=statistic_data_by_stage,
        population_results=pop_results,
        membership=pop_membership,
        population_parent_ids=population_parent_ids,
        statistic_ids=(
          sample_assignments.get(sid, (None, ()))
          [1]
        ),
      )
      all_statistic_results.extend(stat_results)
      messages.append(
        f"sample={sid} statistics=done n={len(stat_results)}"
      )

    population_tuple = tuple(all_population_results)
    membership_tuple = tuple(all_population_membership)
    statistic_tuple = tuple(all_statistic_results)
    if failed_sample_count and population_tuple:
      status = "partial_success"
    elif failed_sample_count:
      status = "failed_samples"
    else:
      status = "success" if population_tuple else "no_data_processed"

    diagnostics.extend(self._group_override_qc_diagnostics(
      selected_samples=selected_samples,
      sample_data=sample_data,
      population_results=population_tuple,
    ))

    return ExecutionReport(
      project_id=str(self._project.get("project_id", "unknown")),
      execution_profile_id=context.execution_profile_id,
      pipeline_version=str(self._project.get("pipeline_version", "0.1")),
      status=status,
      population_results=population_tuple,
      population_membership=membership_tuple,
      statistic_results=statistic_tuple,
      input_files=tuple(input_files),
      messages=tuple(messages),
      diagnostics=tuple(diagnostics),
      auto_gate_fits=tuple(all_auto_gate_fits),
      magnetic_gate_fits=tuple(all_magnetic_gate_fits),
      tethered_gate_fits=tuple(all_tethered_gate_fits),
    )

  def _group_override_qc_diagnostics(
    self,
    *,
    selected_samples: Sequence[Mapping[str, Any]],
    sample_data: Mapping[str, SampleData],
    population_results: Sequence[PopulationResult],
  ) -> list[ExecutionDiagnostic]:
    """Emit reproducible QC diagnostics for group overrides after execution."""
    diagnostics: list[ExecutionDiagnostic] = []
    if not self._project.get("gate_overrides") and not self._project.get("sample_groups"):
      return diagnostics
    strategy_data = self._project.get("gating_strategies_data", {})
    profiles = self._project.get("execution_profiles", [])
    profile = next(
      (value for value in profiles if isinstance(value, Mapping) and value.get("id") == "default"),
      {},
    )
    assignments = self._resolve_group_assignments(
      selected_samples, profile.get("gating_strategy_id")
    )
    overrides = tuple(
      override_spec_from_mapping(value)
      for value in self._project.get("gate_overrides", [])
      if isinstance(value, Mapping)
    )
    by_sample: dict[str, set[str]] = {}
    for result in population_results:
      by_sample.setdefault(result.sample_id, set()).add(result.population_id)
      if result.population_id != "all_events" and result.frequency_of_total is not None and (
        result.frequency_of_total < 0.01 or result.frequency_of_total > 0.99
      ):
        diagnostics.append(ExecutionDiagnostic(
          code="frequency_outlier", severity="warning", stage="qc",
          sample_id=result.sample_id,
          message=f"Population {result.population_id!r} has an outlier total frequency",
          details={"frequency_of_total": result.frequency_of_total},
        ))

    for sample_meta in selected_samples:
      sample_id = str(sample_meta.get("id", ""))
      strategy_id = assignments.get(sample_id, (None, ()))[0]
      strategy = strategy_data.get(strategy_id) if strategy_id else None
      if isinstance(strategy, GatingStrategySpec):
        strategy = asdict(strategy)
      if not isinstance(strategy, Mapping):
        continue
      expected = {
        str(gate.get("id"))
        for gate in strategy.get("gates", [])
        if isinstance(gate, Mapping)
      }
      missing = sorted(expected - by_sample.get(sample_id, set()))
      for population_id in missing:
        diagnostics.append(ExecutionDiagnostic(
          code="missing_population", severity="warning", stage="qc",
          sample_id=sample_id, parameter_id=population_id,
          message=f"Population {population_id!r} is missing from the execution result",
        ))
      for override in overrides:
        if override.sample_id != sample_id or not override.enabled:
          continue
        diagnostics.append(ExecutionDiagnostic(
          code="override_applied", severity="info", stage="qc", sample_id=sample_id,
          parameter_id=override.base_gate_id,
          message=f"Override {override.id!r} applied ({override.gate_purpose})",
        ))
        if override.gate_purpose == "comparison_critical":
          diagnostics.append(ExecutionDiagnostic(
            code="comparison_critical_override", severity="warning", stage="qc",
            sample_id=sample_id, parameter_id=override.base_gate_id,
            message="Comparison-critical override requires review before comparison",
          ))
      sample = sample_data.get(sample_id)
      if sample is None:
        continue
      values = {
        channel.id: sample.events[:, index]
        for index, channel in enumerate(sample.channels)
      }
      for gate in strategy.get("gates", []):
        if not isinstance(gate, Mapping):
          continue
        thresholds = gate.get("thresholds", {})
        if gate.get("gate_type") == "range":
          axis_thresholds = ((gate.get("x_parameter"), "min", "max"),)
        else:
          axis_thresholds = (
            (gate.get("x_parameter"), "x_min", "x_max"),
            (gate.get("y_parameter"), "y_min", "y_max"),
          )
        for parameter, low_key, high_key in axis_thresholds:
          if parameter not in values or not isinstance(thresholds, Mapping):
            continue
          finite = values[parameter][np.isfinite(values[parameter])]
          if finite.size == 0:
            continue
          if (
            thresholds.get(low_key) == float(np.min(finite))
            or thresholds.get(high_key) == float(np.max(finite))
          ):
            diagnostics.append(ExecutionDiagnostic(
              code="gate_boundary_clipping", severity="warning", stage="qc",
              sample_id=sample_id, parameter_id=str(gate.get("id")),
              message=f"Gate boundary for {parameter!r} touches the sample data boundary",
            ))
    return diagnostics

  # ------------------------------------------------------------------
  # Pipeline steps
  # ------------------------------------------------------------------

  def _step_compensation(
    self,
    data: _AnalysisData,
    *,
    sample_id: str,
    execution_profile_id: str,
    group_ids: Sequence[str] = (),
    extra_matrices: dict[str, Mapping[str, Any]] | None = None,
  ) -> _CompensationStepResult:
    """Resolve and apply one matrix before derived parameter evaluation.

    Args:
      data: Analysis data with events and channel identity.
      sample_id: Target sample identifier.
      execution_profile_id: Active execution profile ID.
      group_ids: Group membership of the sample.
      extra_matrices: Dynamically computed matrices (e.g., from
          compensation calculations) to merge with static definitions.
    """
    matrices = self._compensation_matrix_mappings()
    if extra_matrices:
      matrices = {**matrices, **extra_matrices}
    bindings = self._compensation_bindings()
    try:
      resolution = resolve_compensation_binding(
        bindings,
        sample_id=sample_id,
        execution_profile_id=execution_profile_id,
        group_ids=group_ids,
        default_matrix_id=self._project.get("default_compensation_matrix_id"),
        known_matrix_ids=set(matrices),
      )
    except CompensationError as exc:
      raise PipelineError(f"{exc.code}: {exc}") from exc
    if resolution.matrix_id is None:
      return _CompensationStepResult(data)

    mapping = matrices[resolution.matrix_id]
    try:
      spec = CompensationMatrixSpec(
        id=resolution.matrix_id,
        name=str(mapping.get("name", resolution.matrix_id)),
        source=mapping.get("source", "user_defined"),
        channels=tuple(mapping.get("channels", ())),
        matrix=tuple(tuple(row) for row in mapping.get("matrix", ())),
        created_by=mapping.get("created_by"),
        created_at=mapping.get("created_at"),
        notes=str(mapping.get("notes", "")),
      )
    except (TypeError, ValueError) as exc:
      raise PipelineError(
        f"invalid_compensation_matrix: {resolution.matrix_id!r}: {exc}"
      ) from exc
    validation = inspect_compensation_matrix(spec, data.channel_ids)
    error = next(
      (
        diagnostic for diagnostic in validation.diagnostics
        if diagnostic.severity == "error"
      ),
      None,
    )
    if error is not None:
      raise PipelineError(f"{error.code}: {error.message}")

    details = self._compensation_diagnostic_details(
      spec, validation, resolution
    )
    diagnostics = [ExecutionDiagnostic(
      code="compensation_matrix_applied",
      message=f"applied compensation matrix {spec.id!r}",
      severity="info",
      stage="compensation",
      sample_id=sample_id,
      affected_event_count=int(data.events.shape[0]),
      details=details,
    )]
    diagnostics.extend(
      ExecutionDiagnostic(
        code=diagnostic.code,
        message=diagnostic.message,
        severity=diagnostic.severity,
        stage="compensation",
        sample_id=sample_id,
        affected_event_count=int(data.events.shape[0]),
        details={**details, **diagnostic.details},
      )
      for diagnostic in validation.diagnostics
      if diagnostic.severity == "warning"
    )
    return _CompensationStepResult(
      _AnalysisData(
        apply_compensation(spec, data.events, data.channel_ids),
        data.channels,
      ),
      tuple(diagnostics),
    )

  def _compensation_matrix_mappings(self) -> dict[str, Mapping[str, Any]]:
    matrices: dict[str, Mapping[str, Any]] = {}
    for value in self._project.get("compensation_matrices", []):
      if not isinstance(value, Mapping):
        raise PipelineError("invalid_compensation_matrix: definition must be an object")
      matrix_id = value.get("id")
      if not isinstance(matrix_id, str) or not matrix_id:
        raise PipelineError("invalid_compensation_matrix: matrix ID must be non-empty")
      if matrix_id in matrices:
        raise PipelineError(f"duplicate_compensation_matrix_id: {matrix_id!r}")
      matrices[matrix_id] = value
    return matrices

  def _compensation_bindings(self) -> tuple[CompensationBindingSpec, ...]:
    result: list[CompensationBindingSpec] = []
    for value in self._project.get("compensation_bindings", []):
      if not isinstance(value, Mapping):
        raise PipelineError("invalid_compensation_binding: binding must be an object")
      try:
        result.append(CompensationBindingSpec(
          id=value["id"],
          matrix_id=value["matrix_id"],
          scope=value["scope"],
          target_id=value["target_id"],
          created_at=value.get("created_at"),
          created_by=value.get("created_by"),
          notes=str(value.get("notes", "")),
        ))
      except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError(f"invalid_compensation_binding: {exc}") from exc
    return tuple(result)

  def _compensation_calculation_specs(
    self,
  ) -> tuple[CompensationCalculationSpec, ...]:
    """Parse compensation calculation definitions from the project manifest."""
    definitions = self._project.get("compensation_calculations", [])
    parsed: list[CompensationCalculationSpec] = []
    for definition in definitions:
      if not isinstance(definition, Mapping):
        raise PipelineError(
          "invalid_compensation_calculation: definition must be an object"
        )
      try:
        calc_id = definition["id"]
        controls_raw = definition.get("controls", [])
        controls = tuple(
          CompensationCalculationControlSpec(
            sample_id=c["sample_id"],
            detector_channel_id=c["detector_channel_id"],
            positive_population_id=c["positive_population_id"],
            negative_population_id=c["negative_population_id"],
          )
          for c in controls_raw
        )
        parsed.append(
          CompensationCalculationSpec(
            id=calc_id,
            name=definition.get("name", calc_id),
            controls=controls,
            regression_method=definition.get("regression_method", "linear"),
            outlier_policy=definition.get("outlier_policy", "iqr"),
            minimum_positive_events=definition.get(
              "minimum_positive_events", 100
            ),
            minimum_negative_events=definition.get(
              "minimum_negative_events", 50
            ),
            created_by=definition.get("created_by"),
            created_at=definition.get("created_at"),
            notes=str(definition.get("notes", "")),
          )
        )
      except (KeyError, TypeError, ValueError) as exc:
        calc_id = definition.get("id", "unknown")
        raise PipelineError(
          f"invalid_compensation_calculation: {calc_id!r}: {exc}"
        ) from exc
    return tuple(parsed)

  def _execute_compensation_calculations(
    self,
    specs: Sequence[CompensationCalculationSpec],
    events_by_sample: Mapping[str, NDArray[np.float64]],
    channel_ids_by_sample: Mapping[str, Sequence[str]],
    population_masks_by_sample: Mapping[str, Mapping[str, NDArray[np.bool_]]],
  ) -> tuple[dict[str, Mapping[str, Any]], list[ExecutionDiagnostic]]:
    """Execute compensation calculations and return resulting matrix mappings.

    For each calculation spec, call ``calculate_spillover_matrix`` and collect
    the resulting ``CompensationMatrixSpec`` as a dynamic matrix mapping.
    Returns a dict of ``{matrix_id: mapping_dict}`` and a list of diagnostics.

    Args:
      events: Raw event array aligned with ``channel_ids``.
      channel_ids: Ordered channel IDs.
      population_masks: Mapping from population ID to boolean mask.

    Returns:
      Tuple of (matrix_mappings, diagnostics).
    """
    matrix_mappings: dict[str, Mapping[str, Any]] = {}
    diagnostics: list[ExecutionDiagnostic] = []
    affected_event_count = sum(
      int(events.shape[0]) for events in events_by_sample.values()
    )

    for spec in specs:
      try:
        result = calculate_spillover_matrix(
          spec,
          events_by_sample,
          channel_ids_by_sample,
          population_masks_by_sample,
        )
      except CompensationError as exc:
        diagnostics.append(ExecutionDiagnostic(
          code=exc.code if hasattr(exc, "code") else "compensation_calculation_error",
          message=f"compensation calculation {spec.id!r} failed: {exc}",
          severity="error",
          stage="compensation_calculation",
          details={"calculation_id": spec.id},
        ))
        raise PipelineError(f"{exc.code}: {exc}") from exc

      # Register the calculated matrix as a dynamic mapping.
      mapping: dict[str, Any] = {
        "id": result.matrix_spec.id,
        "name": result.matrix_spec.name,
        "source": result.matrix_spec.source,
        "channels": list(result.matrix_spec.channels),
        "matrix": result.matrix_spec.matrix,
        "created_by": result.matrix_spec.created_by,
        "created_at": result.matrix_spec.created_at,
        "notes": result.matrix_spec.notes,
        "provenance": {
          "control_sample_ids": list(
            result.matrix_spec.provenance.control_sample_ids
          ),
          "control_population_ids": list(
            result.matrix_spec.provenance.control_population_ids
          ),
          "algorithm": result.matrix_spec.provenance.algorithm,
          "algorithm_version": result.matrix_spec.provenance.algorithm_version,
          "software_version": result.matrix_spec.provenance.software_version,
        },
      }
      matrix_mappings[result.matrix_spec.id] = mapping

      details = {
        "calculation_id": spec.id,
        "matrix_id": result.matrix_spec.id,
        "condition_number": result.condition_number,
        "n_detectors": len(spec.controls),
        "matrix": [list(row) for row in result.matrix_spec.matrix],
        "provenance": mapping["provenance"],
      }
      diagnostics.append(ExecutionDiagnostic(
        code="compensation_calculated",
        message=f"calculated compensation matrix {result.matrix_spec.id!r} from {spec.id!r}",
        severity="info",
        stage="compensation_calculation",
        affected_event_count=affected_event_count,
        details=details,
      ))

      # Emit warnings from the calculation result.
      for warning in result.overall_warnings:
        diagnostics.append(ExecutionDiagnostic(
          code="compensation_calculation_warning",
          message=warning,
          severity="warning",
          stage="compensation_calculation",
          affected_event_count=affected_event_count,
          details={**details, "warning": warning},
        ))

    return matrix_mappings, diagnostics

  def _execute_compensation_calculations_with_gating(
    self,
    specs: Sequence[CompensationCalculationSpec],
    sample_data: Mapping[str, SampleData],
    gating_strategy_id: str | None,
  ) -> tuple[dict[str, Mapping[str, Any]], list[ExecutionDiagnostic]]:
    """Gate a control sample to obtain population masks, then calculate.

    Args:
      sample_id: ID of the control sample containing populations.
      sample: Typed sample data for the control.
      gating_strategy_id: Strategy ID to gate the control sample.

    Returns:
      Tuple of (matrix_mappings, diagnostics).
    """
    sample_ids = {control.sample_id for spec in specs for control in spec.controls}
    events_by_sample: dict[str, NDArray[np.float64]] = {}
    channel_ids_by_sample: dict[str, Sequence[str]] = {}
    masks_by_sample: dict[str, Mapping[str, NDArray[np.bool_]]] = {}
    for sample_id in sample_ids:
      sample = sample_data.get(sample_id)
      if sample is None:
        raise PipelineError(
          f"calculation_control_sample_missing: control sample {sample_id!r} "
          "was not supplied"
        )
      events_by_sample[sample_id] = sample.events
      channel_ids_by_sample[sample_id] = tuple(channel.id for channel in sample.channels)
      if gating_strategy_id is None:
        all_mask = np.ones(int(sample.events.shape[0]), dtype=np.bool_)
        all_mask.setflags(write=False)
        masks_by_sample[sample_id] = {"all_events": all_mask}
        continue
      try:
        transformed = self._step_transforms(_AnalysisData(sample.events, sample.channels))
        _, membership, _, _ = self._step_gating(
          gating_strategy_id, transformed, sample_id
        )
      except GatingStrategyError as exc:
        raise PipelineError(
          f"gating strategy {gating_strategy_id!r} failed on control "
          f"sample {sample_id!r}"
        ) from exc
      masks_by_sample[sample_id] = {
        item.population_id: item.mask for item in membership
      }
    return self._execute_compensation_calculations(
      specs,
      events_by_sample,
      channel_ids_by_sample,
      masks_by_sample,
    )

  @staticmethod
  def _sample_group_ids(sample_meta: Mapping[str, Any]) -> tuple[str, ...]:
    group_ids: list[str] = []
    group_id = sample_meta.get("group_id")
    if isinstance(group_id, str) and group_id:
      group_ids.append(group_id)
    multiple = sample_meta.get("group_ids", ())
    if not isinstance(multiple, (list, tuple)):
      raise PipelineError("invalid sample group_ids: expected an array")
    for value in multiple:
      if not isinstance(value, str) or not value:
        raise PipelineError("invalid sample group_ids: IDs must be non-empty strings")
      if value not in group_ids:
        group_ids.append(value)
    return tuple(group_ids)

  @staticmethod
  def _compensation_diagnostic_details(
    spec: CompensationMatrixSpec,
    validation: CompensationValidationResult,
    resolution: CompensationBindingResolution,
  ) -> dict[str, Any]:
    return {
      "matrix_id": spec.id,
      "matrix_source": spec.source,
      "channel_order": list(validation.channel_order),
      "channel_indices": (
        None if validation.channel_indices is None
        else list(validation.channel_indices)
      ),
      "condition_number": validation.condition_number,
      "binding_id": resolution.binding_id,
      "binding_ids": list(resolution.binding_ids),
      "binding_scope": resolution.priority,
      "binding_target_id": (
        resolution.target_ids[0] if len(resolution.target_ids) == 1 else None
      ),
      "binding_target_ids": list(resolution.target_ids),
      "resolution_priority": resolution.priority,
    }

  def _step_derived_parameters(
    self,
    compensated_data: _AnalysisData,
    raw_data: _AnalysisData,
    sample_id: str,
    plan: DerivedParameterPlan,
  ) -> tuple[DerivedParameterStageResult, tuple[ExecutionDiagnostic, ...]]:
    """Evaluate derived parameter expressions and append as new columns."""
    if raw_data.channel_ids != compensated_data.channel_ids:
      raise PipelineError(
        "raw and compensated stage channel identities must remain aligned"
      )
    stage_result = DerivedParameterStageResult(
      compensated_data.events, compensated_data.channels
    )
    if not plan.execution_order:
      return stage_result, ()

    diagnostics: list[ExecutionDiagnostic] = []

    for spec in plan.execution_order:
      label = spec.output_label or spec.name
      output_channel = ChannelSpec(
        id=spec.output_id,
        name=label,
        unit=spec.unit,
        metadata={
          "kind": "derived_parameter",
          "definition_id": spec.id,
          "source_stage": spec.source_stage,
        },
      )

      source_data = raw_data if spec.source_stage == "raw" else compensated_data
      variables = {
        channel.id: source_data.events[:, index]
        for index, channel in enumerate(source_data.channels)
      }
      base_channel_ids = set(source_data.channel_ids)
      for index, channel in enumerate(stage_result.channels):
        if channel.id not in base_channel_ids:
          variables[channel.id] = stage_result.events[:, index]

      try:
        result = evaluate_array_expression(
          spec.expression,
          variables,
          row_count=stage_result.events.shape[0],
          allow_functions=True,
        )
        next_stage_result = stage_result.append_channel(result, output_channel)
      except (
        DerivedParameterStageError,
        ExpressionError,
        ArithmeticError,
        TypeError,
        ValueError,
      ) as exc:
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
          affected_event_count=int(stage_result.events.shape[0]),
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
        next_stage_result = stage_result.append_channel(
          np.full(stage_result.events.shape[0], np.nan, dtype=np.float64),
          output_channel,
        )
      stage_result = next_stage_result

    return stage_result, tuple(diagnostics)

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
            output_channel_id=definition.get("output_channel_id"),
            output_label=definition.get("output_label"),
            unit=definition.get("unit"),
            invalid_value_policy=definition.get(
              "invalid_value_policy", "emit_nan_with_warning"
            ),
            legacy_source_stage_policy=definition.get(
              "legacy_source_stage_policy"
            ),
            notes=definition.get("notes", ""),
          )
        )
      except (KeyError, TypeError, ValueError) as exc:
        parameter_id = definition.get("id", "unknown")
        raise PipelineError(
          f"invalid_derived_parameter_definition: {parameter_id!r}: {exc}"
        ) from exc
    for spec in parsed:
      if spec.source_stage == "transformed":
        raise PipelineError(
          "legacy_transformed_source_rejected: derived parameter "
          f"{spec.id!r} requires transformed input, which would violate "
          "the canonical pipeline order"
        )
    return tuple(parsed)

  def _step_transforms(
    self,
    data: _AnalysisData | DerivedParameterStageResult,
  ) -> _AnalysisData:
    """Validate and bind immutable transform views for downstream gates."""
    specs = self._project.get("transforms", [])
    if not specs:
      return _AnalysisData(data.events, data.channels)

    parsed: list[TransformSpec] = []
    transform_ids: set[str] = set()
    default_ids: dict[str, str] = {}
    for spec_dict in specs:
      try:
        spec = TransformSpec(
          id=spec_dict["id"],
          name=spec_dict.get("name", spec_dict["id"]),
          transform_type=spec_dict["transform_type"],
          parameter=spec_dict["parameter"],
          settings=spec_dict.get("settings", {}),
          role=spec_dict.get("role", "analysis"),
          notes=spec_dict.get("notes", ""),
        )
        validate_transform(spec)
      except (KeyError, TypeError, ValueError, TransformError) as exc:
        transform_id = spec_dict.get("id", "unknown")
        raise PipelineError(
          f"invalid_transform_definition: {transform_id!r}: {exc}"
        ) from exc
      if spec.role != "analysis":
        raise PipelineError(
          f"invalid_transform_role: transform {spec.id!r} must be analysis"
        )
      if spec.id in transform_ids:
        raise PipelineError(f"duplicate_transform_id: {spec.id!r}")
      if spec.parameter in default_ids:
        raise PipelineError(
          "duplicate_analysis_transform_parameter: "
          f"{spec.parameter!r} uses {default_ids[spec.parameter]!r} "
          f"and {spec.id!r}"
        )
      if spec.parameter not in data.channel_ids:
        raise PipelineError(
          f"unknown_transform_parameter: {spec.parameter!r}"
        )
      transform_ids.add(spec.id)
      default_ids[spec.parameter] = spec.id
      parsed.append(spec)

    return _AnalysisData(
      data.events,
      data.channels,
      transforms=tuple(parsed),
      default_transform_ids=default_ids,
    )

  def _step_gating(
    self,
    strategy_id: str,
    data: _AnalysisData,
    sample_id: str,
  ) -> tuple[
    list[PopulationResult],
    list[PopulationMembership],
    dict[str, str | None],
    tuple[dict[str, Any], ...],
  ]:
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
          {"all_events": None},
          (),
        )

    if isinstance(strat, Mapping):
      strat = self._strategy_from_mapping(strat)

    auto_fit_records: list[dict[str, Any]] = []
    auto_gates = list(strat.gates)
    existing_gate_ids = {gate.id for gate in auto_gates}
    for value in self._project.get("auto_gate_templates", []):
      if not isinstance(value, Mapping):
        continue
      try:
        template = auto_gate_template_from_mapping(value)
        fit = fit_auto_gate(
          template,
          data.events,
          data.channel_ids,
          sample_id,
        )
      except AutoGateFitError as exc:
        raise PipelineError(
          f"auto_gate_fit_invalid: {exc}",
          code="auto_gate_fit_invalid",
          details={"template_id": value.get("id"), "sample_id": sample_id},
        ) from exc
      fit_diagnostics = tuple(
        ExecutionDiagnostic(
          code=str(item.get("code", "auto_gate_diagnostic")),
          message=str(item.get("reason", item.get("code", "automatic gate fit"))),
          severity=str(item.get("severity", "info")),
          stage="auto_gate_fit",
          sample_id=sample_id,
          parameter_id=template.id,
          details=dict(item),
        )
        for item in fit.diagnostics
      )
      if fit.status == "failed" or fit.gate is None:
        raise PipelineError(
          f"auto_gate_fit_failed: {fit.failure_reason}",
          code="auto_gate_fit_failed",
          details={
            "template_id": template.id,
            "sample_id": sample_id,
            "input_hash": fit.input_hash,
            "diagnostics": list(fit.diagnostics),
          },
        )
      if fit.gate.id in existing_gate_ids:
        raise PipelineError(
          f"auto_gate_id_conflict: {fit.gate.id!r}",
          code="auto_gate_id_conflict",
          details={"template_id": template.id, "sample_id": sample_id},
        )
      auto_gates.append(fit.gate)
      existing_gate_ids.add(fit.gate.id)
      auto_fit_records.append({"kind": "auto", "result": fit, "diagnostics": fit_diagnostics})
    for value in self._project.get("magnetic_gate_templates", []):
      if not isinstance(value, Mapping):
        continue
      try:
        template = magnetic_gate_template_from_mapping(value)
        fit = fit_magnetic_gate(template, data.events, data.channel_ids, sample_id)
      except MagneticGateFitError as exc:
        raise PipelineError(
          f"magnetic_gate_fit_invalid: {exc}", code="magnetic_gate_fit_invalid",
          details={"template_id": value.get("id"), "sample_id": sample_id},
        ) from exc
      fit_diagnostics = tuple(
        ExecutionDiagnostic(
          code=str(item.get("code", "magnetic_gate_diagnostic")),
          message=str(item.get("reason", item.get("code", "magnetic gate fit"))),
          severity=str(item.get("severity", "info")), stage="magnetic_gate_fit",
          sample_id=sample_id, parameter_id=template.id, details=dict(item),
        ) for item in fit.diagnostics
      )
      if fit.status == "failed" or fit.gate is None:
        raise PipelineError(
          f"magnetic_gate_fit_failed: {fit.failure_reason}",
          code="magnetic_gate_fit_failed",
          details={"template_id": template.id, "sample_id": sample_id,
                   "input_hash": fit.input_hash, "diagnostics": list(fit.diagnostics)},
        )
      if fit.gate.id in existing_gate_ids:
        raise PipelineError(
          f"magnetic_gate_id_conflict: {fit.gate.id!r}",
          code="magnetic_gate_id_conflict",
          details={"template_id": template.id, "sample_id": sample_id},
        )
      auto_gates.append(fit.gate)
      existing_gate_ids.add(fit.gate.id)
      auto_fit_records.append({"kind": "magnetic", "result": fit, "diagnostics": fit_diagnostics})
    for value in self._project.get("tethered_gate_templates", []):
      if not isinstance(value, Mapping):
        continue
      try:
        template = tethered_gate_template_from_mapping(value)
        anchor = next((gate for gate in auto_gates if gate.id == template.anchor_gate_id), None)
        fit = fit_tethered_gate(template, anchor, sample_id)
      except TetheredGateFitError as exc:
        raise PipelineError(
          f"tethered_gate_fit_invalid: {exc}", code="tethered_gate_fit_invalid",
          details={"template_id": value.get("id"), "sample_id": sample_id},
        ) from exc
      fit_diagnostics = tuple(
        ExecutionDiagnostic(
          code=str(item.get("code", "tethered_gate_diagnostic")),
          message=str(item.get("reason", item.get("code", "tethered gate fit"))),
          severity=str(item.get("severity", "info")), stage="tethered_gate_fit",
          sample_id=sample_id, parameter_id=template.id, details=dict(item),
        ) for item in fit.diagnostics
      )
      if fit.status == "failed" or fit.gate is None:
        raise PipelineError(
          f"tethered_gate_fit_failed: {fit.failure_reason}", code="tethered_gate_fit_failed",
          details={"template_id": template.id, "sample_id": sample_id},
        )
      if fit.gate.id in existing_gate_ids:
        raise PipelineError(
          f"tethered_gate_id_conflict: {fit.gate.id!r}", code="tethered_gate_id_conflict",
          details={"template_id": template.id, "sample_id": sample_id},
        )
      auto_gates.append(fit.gate)
      existing_gate_ids.add(fit.gate.id)
      auto_fit_records.append({"kind": "tethered", "result": fit, "diagnostics": fit_diagnostics})
    if auto_gates != list(strat.gates):
      strat = GatingStrategySpec(**{
        **asdict(strat),
        "gates": tuple(auto_gates),
      })

    try:
      overrides = tuple(
        override_spec_from_mapping(value)
        for value in self._project.get("gate_overrides", [])
        if isinstance(value, Mapping)
      )
      strat = resolve_gate_overrides(strat, sample_id, overrides)
    except GateOverrideError as exc:
      raise PipelineError(
        f"{exc.code}: {exc}", code=exc.code, details=exc.details
      ) from exc

    results, masks = evaluate_gating_strategy_with_membership(
      strat,
      data.events,
      data.channel_ids,
      transforms=data.transforms,
      default_transform_ids=data.default_transform_ids,
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

    population_parent_ids = {strat.root_population_id: None}
    population_parent_ids.update({
      gate.id: gate.parent_population_id or strat.root_population_id
      for gate in strat.gates
    })
    return tagged_results, tagged_membership, population_parent_ids, tuple(auto_fit_records)

  def _step_statistics(
    self,
    *,
    sample_id: str,
    data_by_stage: Mapping[str, _AnalysisData],
    population_results: list[PopulationResult],
    membership: list[PopulationMembership],
    population_parent_ids: Mapping[str, str | None],
    statistic_ids: tuple[str, ...] = (),
  ) -> list[StatisticResult]:
    """Evaluate statistic definitions for a single sample.

    Each definition chooses raw, compensated, or materialized transformed
    values.  Gate membership always remains the full-event mask produced by
    the canonical transformed gating stage.
    """
    specs = self._statistic_specs()
    if statistic_ids:
      allowed = set(statistic_ids)
      specs = tuple(spec for spec in specs if spec.id in allowed)
    if not specs:
      return []

    # Build lookup tables.
    parent_by_population: dict[str, PopulationResult] = {
      r.population_id: r for r in population_results
    }
    total_count = 0
    for r in population_results:
      if r.frequency_of_parent is None and r.event_count > total_count:
        total_count = r.event_count
    if total_count == 0:
      total_count = int(data_by_stage["transformed"].events.shape[0])

    membership_by_population: dict[str, NDArray[np.bool_]] = {
      m.population_id: m.mask for m in membership
    }

    results: list[StatisticResult] = []

    for spec in specs:
      pop_result = parent_by_population.get(spec.population_id)
      if pop_result is None:
        continue

      event_count = pop_result.event_count
      parent_population_id = population_parent_ids.get(spec.population_id)
      parent_mask = (
        None if parent_population_id is None
        else membership_by_population.get(parent_population_id)
      )
      parent_count = (
        None if parent_mask is None else int(parent_mask.sum())
      )

      mask = membership_by_population.get(spec.population_id)

      # count / frequency metrics don't need per-parameter values.
      if spec.metric in ("count", "frequency_of_parent", "frequency_of_total"):
        result = compute_statistic(
          spec=spec,
          sample_id=sample_id,
          event_count=event_count,
          parent_count=parent_count,
          total_count=total_count,
          values=None,
        )
        results.append(replace(result, statistic_name=spec.name))
        continue

      # Value-based metrics need a parameter column.
      if spec.parameter_id is None:
        continue
      source_data = data_by_stage[spec.source_stage]
      column_index = {
        channel_id: index
        for index, channel_id in enumerate(source_data.channel_ids)
      }
      col_idx = column_index.get(spec.parameter_id)
      if col_idx is None:
        continue

      values: NDArray[np.float64] | None = None
      if mask is not None:
        values = source_data.events[mask, col_idx].copy()
      elif event_count > 0:
        values = source_data.events[:, col_idx].copy()
      else:
        values = None

      result = compute_statistic(
        spec=spec,
        sample_id=sample_id,
        event_count=event_count,
        parent_count=parent_count,
        total_count=total_count,
        values=values,
      )
      results.append(
        replace(
          result,
          statistic_name=spec.name,
          unit=source_data.channels[col_idx].unit,
        )
      )

    return results

  @staticmethod
  def _materialize_transformed_statistics_data(
    data: _AnalysisData,
  ) -> _AnalysisData:
    """Return the configured analysis-transform value space for statistics.

    Gating applies transforms lazily to preserve gate-coordinate semantics;
    numeric transformed statistics instead require a concrete full-event
    array.  This creates that derived view without mutating prior stages.
    """
    events = np.array(data.events, dtype=np.float64, copy=True)
    for transform in data.transforms:
      column_index = data.channel_ids.index(transform.parameter)
      try:
        events[:, column_index] = apply_transform(
          transform, events[:, column_index]
        )
      except TransformError as exc:
        raise PipelineError(
          f"statistics_transform_failed: {transform.id!r}: {exc}"
        ) from exc
    return _AnalysisData(events, data.channels)

  def _statistic_specs(self) -> tuple[StatisticSpec, ...]:
    """Parse statistic definitions from the project manifest."""
    definitions = self._project.get("statistics", [])
    parsed: list[StatisticSpec] = []
    for definition in definitions:
      if not isinstance(definition, Mapping):
        raise PipelineError(
          "invalid_statistic_definition: definition must be an object"
        )
      try:
        stat_id = definition["id"]
        parsed.append(
          StatisticSpec(
            id=stat_id,
            name=definition.get("name", stat_id),
            population_id=definition["population_id"],
            parameter_id=definition.get("parameter_id"),
            metric=definition.get("metric", "count"),
            source_stage=definition.get("source_stage", "compensated"),
            value_policy=definition.get("value_policy", "full_events"),
            settings=dict(definition.get("settings", {})),
            format=definition.get("format"),
            notes=str(definition.get("notes", "")),
          )
        )
      except (KeyError, TypeError, ValueError) as exc:
        stat_id = definition.get("id", "unknown")
        raise PipelineError(
          f"invalid_statistic_definition: {stat_id!r}: {exc}"
        ) from exc
    return tuple(parsed)

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

  def _resolve_group_strategy_ids(
    self,
    selected_samples: Sequence[Mapping[str, Any]],
    fallback_strategy_id: str | None,
  ) -> dict[str, str]:
    """Resolve persisted Group bindings for selected samples.

    Projects without Group fields retain the execution profile's historical
    strategy behavior. Group binding errors are raised before any sample is
    processed, so a partial run cannot silently mix strategies.
    """
    return {
      sample_id: strategy_id
      for sample_id, (strategy_id, _statistic_ids) in self._resolve_group_assignments(
        selected_samples, fallback_strategy_id
      ).items()
      if strategy_id is not None
    }

  def _resolve_group_assignments(
    self,
    selected_samples: Sequence[Mapping[str, Any]],
    fallback_strategy_id: str | None,
  ) -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """Resolve strategy and optional statistics binding per selected sample."""
    groups_data = self._project.get("sample_groups", [])
    bindings_data = self._project.get("group_strategy_bindings", [])
    if not groups_data and not bindings_data:
      return {
        str(sample.get("id", "")): (fallback_strategy_id, ())
        for sample in selected_samples
      }
    if not isinstance(groups_data, list) or not isinstance(bindings_data, list):
      raise PipelineError(
        "sample Groups and strategy bindings must be arrays",
        code="invalid_group_configuration",
      )
    try:
      groups = sample_group_specs_from_mapping(groups_data)
      bindings = group_strategy_binding_specs_from_mapping(bindings_data)
      annotations = annotation_specs_from_mapping(
        self._project.get("annotations", [])
      )
      typed_samples = tuple(
        SampleSpec(
          id=str(sample.get("id", "")),
          name=str(sample.get("name", sample.get("id", ""))),
          path=str(sample.get("path", "")),
          metadata=dict(sample.get("metadata", {})),
        )
        for sample in selected_samples
      )
      resolved = resolve_group_strategy_bindings(
        groups, bindings, typed_samples, annotations
      )
    except GroupResolutionError as exc:
      raise PipelineError(
        f"{exc.code}: {exc}", code=exc.code, details=exc.details
      ) from exc
    resolved_group_ids = {
      group_id
      for _sample_id, (_strategy, group_ids) in resolved.items()
      for group_id in group_ids
    }
    bindings_by_group = {
      group_id: [
        binding for binding in bindings if binding.group_id == group_id
      ]
      for group_id in resolved_group_ids
    }
    assignments: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for sample in selected_samples:
      sample_id = str(sample.get("id", ""))
      resolved_strategy = resolved.get(sample_id)
      if resolved_strategy is None:
        assignments[sample_id] = (fallback_strategy_id, ())
        continue
      strategy_id, group_ids = resolved_strategy
      statistic_ids = tuple(sorted({
        statistic_id
        for group_id in group_ids
        for binding in bindings_by_group.get(group_id, [])
        for statistic_id in binding.statistic_ids
      }))
      assignments[sample_id] = (strategy_id, statistic_ids)
    return assignments

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
        x_transform_id=gate.get("x_transform_id"),
        y_transform_id=gate.get("y_transform_id"),
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
