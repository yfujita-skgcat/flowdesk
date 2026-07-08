"""CSV and TSV export helpers.

Consumes core ``PopulationResult`` or ``ExportRecord`` values and writes
them to delimited text files.  Never imports Qt or GUI modules.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Literal

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ExportRecord, PopulationResult
from flowdesk_core.statistics import population_results_to_export_records

NaNPolicy = Literal["string_nan", "empty", "zero"]


class ExportError(FlowdeskError):
  """Raised when export cannot complete."""


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
