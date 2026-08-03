"""CSV and TSV export helpers.

Consumes core ``PopulationResult`` or ``ExportRecord`` values and writes
them to delimited text files.  Never imports Qt or GUI modules.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Literal, TextIO

from flowdesk_core.annotations import resolve_sample_title
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.groups import annotation_specs_from_mapping
from flowdesk_core.models import (
  ExportRecord,
  GateSpec,
  PopulationResult,
  StatisticResult,
)
from flowdesk_core.pipeline_runner import PipelineRunner
from flowdesk_core.populations import build_population_paths
from flowdesk_core.statistics import population_results_to_export_records

NaNPolicy = Literal["string_nan", "empty", "zero"]


class ExportError(FlowdeskError):
  """Raised when export cannot complete."""


@dataclass(frozen=True)
class UnifiedResultsRow:
  """One sample/population row for the integrated wide export."""

  sample_id: str
  population_id: str
  population_name: str
  population_path: str
  parent_population_id: str | None
  depth: int
  event_count: int | None
  frequency_of_parent: float | None
  frequency_of_total: float | None
  statistics: Mapping[str, StatisticResult] = field(default_factory=dict)


@dataclass(frozen=True)
class PopulationPathInfo:
  """Resolved display metadata for one population."""

  population_id: str
  population_name: str
  population_path: str
  parent_population_id: str | None
  depth: int


def _sample_order(project: Mapping[str, Any], sample_ids: set[str]) -> list[str]:
  ordered = [
    str(sample.get("id"))
    for sample in project.get("samples", [])
    if isinstance(sample, Mapping) and str(sample.get("id", "")) in sample_ids
  ]
  ordered.extend(sorted(sample_ids - set(ordered)))
  return ordered


def _strategy_path_info(
  project: Mapping[str, Any],
  sample_ids: set[str],
  execution_profile_id: str,
) -> dict[str, dict[str, PopulationPathInfo]]:
  """Resolve each sample's applied strategy without executing analysis."""
  try:
    assignments = PipelineRunner(project).resolve_group_assignments(
      execution_profile_id
    )
  except Exception as exc:
    raise ExportError(f"failed to resolve sample strategy for export: {exc}") from exc
  strategies = project.get("gating_strategies_data", {})
  result: dict[str, dict[str, PopulationPathInfo]] = {}
  for sample_id in _sample_order(project, sample_ids):
    strategy_id = assignments.get(sample_id, {}).get("strategy_id")
    if not strategy_id:
      if not strategies or all(
        isinstance(value, Mapping) and not value.get("gates", [])
        for value in strategies.values()
      ):
        result[sample_id] = {
          "all_events": PopulationPathInfo(
            "all_events", "All Events", "All Events", None, 0
          )
        }
        continue
      raise ExportError(f"no gating strategy is applied to sample {sample_id!r}")
    strategy = strategies.get(strategy_id) if isinstance(strategies, Mapping) else None
    if not isinstance(strategy, Mapping):
      raise ExportError(
        f"sample {sample_id!r} references unknown gating strategy {strategy_id!r}"
      )
    try:
      gates = tuple(GateSpec(**gate) for gate in strategy.get("gates", []))
      paths = build_population_paths(
        gates,
        root_population_id=str(strategy.get("root_population_id", "all_events")),
      )
    except Exception as exc:
      raise ExportError(
        f"cannot resolve population hierarchy for sample {sample_id!r}: {exc}"
      ) from exc
    parent_ids = {
      gate.id: (gate.parent_population_id or str(strategy.get("root_population_id", "all_events")))
      for gate in gates
    }
    names = {gate.id: gate.name for gate in gates}
    info: dict[str, PopulationPathInfo] = {}
    for population_id, path in paths.items():
      depth = path.count("/")
      info[population_id] = PopulationPathInfo(
        population_id=population_id,
        population_name=names.get(population_id, "All Events"),
        population_path=path,
        parent_population_id=parent_ids.get(population_id),
        depth=depth,
      )
    result[sample_id] = info
  return result


def _statistic_headers(
  results: list[StatisticResult],
  project: Mapping[str, Any],
) -> dict[str, str]:
  configured: list[tuple[str, str | None]] = [
    (str(value.get("id")), str(value.get("name")) if value.get("name") else None)
    for value in project.get("statistics", [])
    if isinstance(value, Mapping) and value.get("id")
  ]
  configured.extend(
    (result.statistic_id, result.statistic_name)
    for result in results
    if result.statistic_id not in {statistic_id for statistic_id, _name in configured}
  )
  by_id = {result.statistic_id: result for result in results}
  names: dict[str, str] = {}
  used: set[str] = set()
  for statistic_id, configured_name in configured:
    result = by_id.get(statistic_id)
    name = (
      (result.statistic_name if result else None)
      or configured_name
      or statistic_id
    )
    header = str(name).strip() or statistic_id
    if header in used:
      header = f"{header} [{statistic_id}]"
    while header in used:
      header += "_"
    used.add(header)
    names[statistic_id] = header
  return names


def build_results_wide_rows(
  report: ExecutionReport,
  project: Mapping[str, Any],
  *,
  execution_profile_id: str = "default",
) -> tuple[UnifiedResultsRow, ...]:
  """Build unified rows from one authoritative execution report."""
  population_results = list(report.population_results)
  statistic_results = list(report.statistic_results)
  sample_ids = {result.sample_id for result in population_results}
  sample_ids.update(result.sample_id for result in statistic_results)
  path_info = _strategy_path_info(project, sample_ids, execution_profile_id)
  pop_by_key = {
    (result.sample_id, result.population_id): result
    for result in population_results
  }
  stats_by_key: dict[tuple[str, str], dict[str, StatisticResult]] = {}
  for result in statistic_results:
    stats_by_key.setdefault((result.sample_id, result.population_id), {})[
      result.statistic_id
    ] = result
  rows: list[UnifiedResultsRow] = []
  for sample_id in _sample_order(project, sample_ids):
    info_for_sample = path_info.get(sample_id, {})
    population_ids: set[str] = set()
    population_ids.update(
      population_id for sid, population_id in pop_by_key if sid == sample_id
    )
    population_ids.update(
      population_id for sid, population_id in stats_by_key if sid == sample_id
    )
    ordered_ids = [
      population_id for population_id in info_for_sample
      if population_id in population_ids
    ]
    ordered_ids.extend(
      sorted(population_ids - set(ordered_ids))
    )
    for population_id in ordered_ids:
      info = info_for_sample.get(
        population_id,
        PopulationPathInfo(population_id, population_id, population_id, None, 0),
      )
      population = pop_by_key.get((sample_id, population_id))
      rows.append(UnifiedResultsRow(
        sample_id=sample_id,
        population_id=population_id,
        population_name=info.population_name,
        population_path=info.population_path,
        parent_population_id=info.parent_population_id,
        depth=info.depth,
        event_count=population.event_count if population else None,
        frequency_of_parent=(population.frequency_of_parent if population else None),
        frequency_of_total=(population.frequency_of_total if population else None),
        statistics=stats_by_key.get((sample_id, population_id), {}),
      ))
  return tuple(rows)


def _project_sample_title(project: Mapping[str, Any], sample_id: str) -> str:
  sample = next(
    (value for value in project.get("samples", [])
     if isinstance(value, Mapping) and value.get("id") == sample_id),
    {},
  )
  annotations = annotation_specs_from_mapping(project.get("annotations", []))
  return resolve_sample_title(
    sample_id,
    str(sample.get("name", "")) or None,
    str(sample.get("path", "")) or None,
    annotations,
  )


def _format_export_number(value: int | float | None, nan_policy: NaNPolicy) -> str:
  if value is None:
    return ""
  if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
    return _nan_placeholder(nan_policy)
  return str(value)


def _export_target(path: str | Path | TextIO):
  """Return a text target for a file path or an existing text stream."""
  if hasattr(path, "write"):
    return nullcontext(path)
  return Path(path).open("w", encoding="utf-8", newline="")


def write_results_wide(
  report: ExecutionReport,
  project: Mapping[str, Any],
  path: str | Path | TextIO,
  *,
  delimiter: str = "\t",
  execution_profile_id: str = "default",
  include_population_metrics: bool = True,
  include_custom_statistics: bool = True,
  include_internal_ids: bool = False,
  include_qc: bool = False,
  population_ids: Sequence[str] | None = None,
  nan_policy: NaNPolicy = "empty",
) -> None:
  """Write the integrated sample-by-population wide table."""
  rows = build_results_wide_rows(
    report, project, execution_profile_id=execution_profile_id
  )
  if population_ids is not None:
    selected_ids = set(population_ids)
    rows = tuple(row for row in rows if row.population_id in selected_ids)
  stat_results = list(report.statistic_results)
  stat_headers = _statistic_headers(stat_results, project) if include_custom_statistics else {}
  header: list[str] = ["Sample", "Population"]
  if include_internal_ids:
    header.extend([
      "Sample ID", "Population ID", "Population Name",
      "Parent Population ID", "Population Depth",
    ])
  if include_population_metrics:
    header.extend(["Events", "% Parent", "% Total"])
  header.extend(stat_headers.values())
  if include_qc:
    if include_population_metrics:
      header.append("Population Status")
    for statistic_header in stat_headers.values():
      header.extend([
        f"{statistic_header} Status",
        f"{statistic_header} Undefined Reason",
        f"{statistic_header} n valid",
        f"{statistic_header} n total",
        f"{statistic_header} n invalid",
        f"{statistic_header} invalid fraction",
        f"{statistic_header} non-finite policy",
      ])
  try:
    with _export_target(path) as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for row in rows:
        values: list[object] = [_project_sample_title(project, row.sample_id), row.population_path]
        if include_internal_ids:
          values.extend([
            row.sample_id, row.population_id, row.population_name,
            row.parent_population_id or "", row.depth,
          ])
        if include_population_metrics:
          values.extend([
            _format_export_number(row.event_count, nan_policy),
            _format_export_number(
              None if row.frequency_of_parent is None else row.frequency_of_parent * 100,
              nan_policy,
            ),
            _format_export_number(
              100.0 if row.population_id == "all_events"
              else (None if row.frequency_of_total is None
                    else row.frequency_of_total * 100),
              nan_policy,
            ),
          ])
        for statistic_id in stat_headers:
          result = row.statistics.get(statistic_id)
          values.append(_format_export_number(result.value if result else None, nan_policy))
        if include_qc:
          if include_population_metrics:
            values.append("current")
          for statistic_id in stat_headers:
            result = row.statistics.get(statistic_id)
            values.extend([
              result.status if result else "",
              result.undefined_reason if result and result.undefined_reason else "",
              result.n_valid if result and result.n_valid is not None else "",
              result.n_total if result and result.n_total is not None else "",
              result.n_invalid if result and result.n_invalid is not None else "",
              result.invalid_fraction if result and result.invalid_fraction is not None else "",
              result.non_finite_policy if result else "",
            ])
        writer.writerow(values)
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc


def write_results_long(
  report: ExecutionReport,
  project: Mapping[str, Any],
  path: str | Path | TextIO,
  *,
  delimiter: str = "\t",
  execution_profile_id: str = "default",
  include_population_metrics: bool = True,
  include_custom_statistics: bool = True,
  include_internal_ids: bool = False,
  include_qc: bool = True,
  population_ids: Sequence[str] | None = None,
  nan_policy: NaNPolicy = "empty",
) -> None:
  """Write population metrics and custom statistics as one long table."""
  rows = build_results_wide_rows(
    report, project, execution_profile_id=execution_profile_id
  )
  if population_ids is not None:
    selected_ids = set(population_ids)
    rows = tuple(row for row in rows if row.population_id in selected_ids)
  statistic_ids = (
    _statistic_headers(list(report.statistic_results), project)
    if include_custom_statistics else {}
  )
  header = [
    "Sample", "Population", "Result Type", "Statistic ID", "Statistic",
    "Metric", "Value", "Unit", "Status", "Undefined Reason",
  ]
  if include_internal_ids:
    header.extend([
      "Sample ID", "Population ID", "Parent Population ID", "Population Depth",
    ])
  if include_qc:
    header.extend(["n valid", "n total", "n invalid", "invalid fraction", "non-finite policy"])
  try:
    with _export_target(path) as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for row in rows:
        prefix = [_project_sample_title(project, row.sample_id), row.population_path]
        if include_population_metrics:
          metrics = (
            ("Events", "event_count", row.event_count, "", "current", ""),
            (
              "% Parent", "frequency_of_parent",
              None if row.frequency_of_parent is None else row.frequency_of_parent * 100,
              "%", "current", "",
            ),
            (
              "% Total", "frequency_of_total",
              100.0 if row.population_id == "all_events"
              else (None if row.frequency_of_total is None
                    else row.frequency_of_total * 100),
              "%", "current", "",
            ),
          )
          for name, metric, value, unit, status, reason in metrics:
            values: list[object] = [
              *prefix, "population", "", name, metric,
              _format_export_number(value, nan_policy), unit, status, reason,
            ]
            if include_internal_ids:
              values.extend([
                row.sample_id, row.population_id,
                row.parent_population_id or "", row.depth,
              ])
            if include_qc:
              values.extend(["", "", "", "", ""])
            writer.writerow(values)
        for statistic_id in statistic_ids:
          result = row.statistics.get(statistic_id)
          if result is None:
            continue
          values = [
            *prefix, "statistic", result.statistic_id,
            result.statistic_name or statistic_id, result.metric,
            _format_export_number(result.value, nan_policy), result.unit or "",
            result.status, result.undefined_reason or "",
          ]
          if include_internal_ids:
            values.extend([
              row.sample_id, row.population_id,
              row.parent_population_id or "", row.depth,
            ])
          if include_qc:
            values.extend([
              result.n_valid if result.n_valid is not None else "",
              result.n_total if result.n_total is not None else "",
              result.n_invalid if result.n_invalid is not None else "",
              result.invalid_fraction if result.invalid_fraction is not None else "",
              result.non_finite_policy,
            ])
          writer.writerow(values)
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc


def results_wide_to_text(
  report: ExecutionReport,
  project: Mapping[str, Any],
  *,
  delimiter: str = "\t",
  execution_profile_id: str = "default",
  include_population_metrics: bool = True,
  include_custom_statistics: bool = True,
  include_internal_ids: bool = False,
  include_qc: bool = False,
  population_ids: Sequence[str] | None = None,
  nan_policy: NaNPolicy = "empty",
) -> str:
  """Return the wide Results table as delimited text without touching disk."""
  buffer = StringIO()
  write_results_wide(
    report,
    project,
    buffer,
    delimiter=delimiter,
    execution_profile_id=execution_profile_id,
    include_population_metrics=include_population_metrics,
    include_custom_statistics=include_custom_statistics,
    include_internal_ids=include_internal_ids,
    include_qc=include_qc,
    population_ids=population_ids,
    nan_policy=nan_policy,
  )
  return buffer.getvalue()


def results_long_to_text(
  report: ExecutionReport,
  project: Mapping[str, Any],
  *,
  delimiter: str = "\t",
  execution_profile_id: str = "default",
  include_population_metrics: bool = True,
  include_custom_statistics: bool = True,
  include_internal_ids: bool = False,
  include_qc: bool = True,
  population_ids: Sequence[str] | None = None,
  nan_policy: NaNPolicy = "empty",
) -> str:
  """Return the long Results table as delimited text without touching disk."""
  buffer = StringIO()
  write_results_long(
    report,
    project,
    buffer,
    delimiter=delimiter,
    execution_profile_id=execution_profile_id,
    include_population_metrics=include_population_metrics,
    include_custom_statistics=include_custom_statistics,
    include_internal_ids=include_internal_ids,
    include_qc=include_qc,
    population_ids=population_ids,
    nan_policy=nan_policy,
  )
  return buffer.getvalue()


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------


def _format_value(
  value: int | float | str | None,
  nan_policy: NaNPolicy,
) -> str:
  """Format a single export value according to the NaN policy.

  Args:
    value: The raw value (may be ``None`` or ``float('nan')``).
    nan_policy: How to represent missing / NaN values.

  Returns:
    A string suitable for delimited output.
  """
  if value is None:
    return _nan_placeholder(nan_policy)

  if isinstance(value, float) and math.isnan(value):
    return _nan_placeholder(nan_policy)

  return str(value)


def _nan_placeholder(policy: NaNPolicy) -> str:
  """Return the placeholder string for a missing value.

  Args:
    policy: The NaN representation policy.

  Returns:
    "NaN" for ``string_nan``, ``""`` for ``empty``, ``"0"`` for ``zero``.
  """
  if policy == "string_nan":
    return "NaN"
  if policy == "empty":
    return ""
  return "0"


# ---------------------------------------------------------------------------
# ExportRecord -> delimited file
# ---------------------------------------------------------------------------


def write_export_records(
  records: list[ExportRecord],
  path: str | Path,
  delimiter: str = "\t",
  nan_policy: NaNPolicy = "string_nan",
) -> None:
  """Write ``ExportRecord`` objects to a delimited text file.

  Each record becomes one row with columns:
  ``sample_id``, ``population_id``, ``metric``, ``value``.

  Args:
    records: List of export records to write.
    path: Destination file path.
    delimiter: Field delimiter (``\\t`` for TSV, ``','`` for CSV).
    nan_policy: How to represent NaN / None values.

  Raises:
    ExportError: If the file cannot be written.
  """
  header = ["sample_id", "population_id", "metric", "value"]

  try:
    out_path = Path(path)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for rec in records:
        writer.writerow(
          [
            rec.sample_id,
            rec.population_id,
            rec.metric,
            _format_value(rec.value, nan_policy),
          ]
        )
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc
  except Exception as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc


# ---------------------------------------------------------------------------
# PopulationResult -> delimited file (long format)
# ---------------------------------------------------------------------------


def write_population_results(
  results: list[PopulationResult],
  path: str | Path,
  delimiter: str = "\t",
  nan_policy: NaNPolicy = "string_nan",
) -> None:
  """Write ``PopulationResult`` objects to a delimited text file.

  This is a convenience wrapper that first converts results to
  ``ExportRecord`` rows and then calls :func:`write_export_records`.

  Each ``PopulationResult`` becomes three rows (one per metric):
  ``event_count``, ``frequency_of_parent``, ``frequency_of_total``.

  Args:
    results: Population results to export.
    path: Destination file path.
    delimiter: Field delimiter.
    nan_policy: How to represent NaN / None values.

  Raises:
    ExportError: If the file cannot be written.
  """
  records = population_results_to_export_records(results)
  write_export_records(records, path, delimiter=delimiter, nan_policy=nan_policy)


# ---------------------------------------------------------------------------
# Wide-format export (one row per population, not per metric)
# ---------------------------------------------------------------------------


def write_population_results_wide(
  results: list[PopulationResult],
  path: str | Path,
  delimiter: str = "\t",
  nan_policy: NaNPolicy = "string_nan",
) -> None:
  """Write population results in wide format (one row per population).

  Columns:
    sample_id, population_id, event_count, frequency_of_parent,
    frequency_of_total.

  Args:
    results: Population results to export.
    path: Destination file path.
    delimiter: Field delimiter.
    nan_policy: How to represent NaN / None values.

  Raises:
    ExportError: If the file cannot be written.
  """
  header = [
    "sample_id",
    "population_id",
    "event_count",
    "frequency_of_parent",
    "frequency_of_total",
  ]

  try:
    out_path = Path(path)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for pop in results:
        writer.writerow(
          [
            pop.sample_id,
            pop.population_id,
            _format_value(pop.event_count, nan_policy),
            _format_value(pop.frequency_of_parent, nan_policy),
            _format_value(pop.frequency_of_total, nan_policy),
          ]
        )
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc
  except Exception as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc


# ---------------------------------------------------------------------------
# CSV convenience wrapper
# ---------------------------------------------------------------------------


def write_population_results_csv(
  results: list[PopulationResult],
  path: str | Path,
  nan_policy: NaNPolicy = "string_nan",
) -> None:
  """Write population results to a CSV file (comma-delimited).

  Args:
    results: Population results to export.
    path: Destination file path.
    nan_policy: How to represent NaN / None values.

  Raises:
    ExportError: If the file cannot be written.
  """
  write_population_results_wide(
    results, path, delimiter=",", nan_policy=nan_policy
  )


# ---------------------------------------------------------------------------
# StatisticResult -> delimited file
# ---------------------------------------------------------------------------


def write_statistic_results(
  results: list[StatisticResult],
  path: str | Path,
  delimiter: str = "\t",
  nan_policy: NaNPolicy = "string_nan",
) -> None:
  """Write ``StatisticResult`` objects to a delimited text file.

  Each statistic becomes one row with columns:
  ``sample_id``, ``statistic_id``, ``display_name``, ``population_id``, ``metric``,
  ``value``, ``unit``, ``status``, ``undefined_reason``, and non-finite QC counts.

  Args:
    results: Statistic results to write.
    path: Destination file path.
    delimiter: Field delimiter (``\\t`` for TSV, ``','`` for CSV).
    nan_policy: How to represent NaN / None values.

  Raises:
    ExportError: If the file cannot be written.
  """
  base_header = [
    "sample_id",
    "statistic_id",
    "display_name",
    "population_id",
    "metric",
    "value",
    "unit",
    "status",
    "undefined_reason",
  ]
  include_qc = any(
    result.n_total is not None or result.n_invalid is not None
    for result in results
  )
  qc_header = [
    "n_total", "n_valid", "n_invalid", "invalid_fraction",
    "non_finite_policy",
  ]
  header = base_header + (qc_header if include_qc else [])

  try:
    out_path = Path(path)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for rec in results:
        row: list[object] = [
          rec.sample_id,
          rec.statistic_id,
          rec.statistic_name if rec.statistic_name is not None else "",
          rec.population_id,
          rec.metric,
          _format_value(rec.value, nan_policy),
          rec.unit if rec.unit is not None else "",
          rec.status,
          rec.undefined_reason if rec.undefined_reason is not None else "",
        ]
        if include_qc:
          row.extend([
            "" if rec.n_total is None else rec.n_total,
            "" if rec.n_valid is None else rec.n_valid,
            "" if rec.n_invalid is None else rec.n_invalid,
            "" if rec.invalid_fraction is None else rec.invalid_fraction,
            rec.non_finite_policy,
          ])
        writer.writerow(row)
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc
  except Exception as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc


def write_statistic_results_wide(
  results: list[StatisticResult],
  path: str | Path,
  delimiter: str = "\t",
  nan_policy: NaNPolicy = "string_nan",
  revisions: Mapping[tuple[str, str, str], int | None] | None = None,
) -> None:
  """Write one row per sample/population with metadata columns per statistic.

  The long-form :func:`write_statistic_results` remains the lossless export for
  status and QC metadata.  This view is intended for spreadsheet-style matrix
  analysis; column names use stable statistic IDs and duplicate target rows do
  not overwrite one another. ``revisions`` can supply runtime revision values
  keyed by ``(sample_id, statistic_id, population_id)``; otherwise the revision
  cell is empty rather than fabricated.
  """
  statistic_ids = list(dict.fromkeys(result.statistic_id for result in results))
  rows: dict[tuple[str, str], dict[str, StatisticResult]] = {}
  for result in results:
    rows.setdefault((result.sample_id, result.population_id), {})[
      result.statistic_id
    ] = result
  metadata_suffixes = (
    "value", "unit", "status", "undefined_reason", "n_total", "n_valid",
    "n_invalid", "invalid_fraction", "non_finite_policy", "revision",
  )
  header = ["sample_id", "population_id"] + [
    f"{statistic_id}_{suffix}"
    for statistic_id in statistic_ids
    for suffix in metadata_suffixes
  ]
  try:
    out_path = Path(path)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
      writer = csv.writer(fh, delimiter=delimiter)
      writer.writerow(header)
      for sample_id, population_id in sorted(rows):
        values = rows[(sample_id, population_id)]
        row: list[object] = [sample_id, population_id]
        for statistic_id in statistic_ids:
          stat_result = values.get(statistic_id)
          if stat_result is None:
            row.extend([_nan_placeholder(nan_policy)] + [""] * 9)
            continue
          row.extend([
            _format_value(stat_result.value, nan_policy),
            stat_result.unit or "",
            stat_result.status,
            stat_result.undefined_reason or "",
            "" if stat_result.n_total is None else stat_result.n_total,
            "" if stat_result.n_valid is None else stat_result.n_valid,
            "" if stat_result.n_invalid is None else stat_result.n_invalid,
            "" if stat_result.invalid_fraction is None else stat_result.invalid_fraction,
            stat_result.non_finite_policy,
            "" if revisions is None else revisions.get(
              (sample_id, statistic_id, population_id), ""
            ),
          ])
        writer.writerow(row)
  except OSError as exc:
    raise ExportError(f"Failed to write export file: {path}") from exc
