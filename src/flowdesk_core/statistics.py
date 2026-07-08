"""Population statistics computation.

Provides moment statistics (mean, median, MAD, stddev, percentiles),
histogram binning, and population result construction.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ExportRecord, PopulationResult


class PopulationStatsError(FlowdeskError):
  """Raised when population statistics cannot be computed."""


def make_population_result(
  sample_id: str,
  population_id: str,
  event_count: int,
  parent_count: int | None,
  total_count: int | None,
) -> PopulationResult:
  """Create population frequency statistics from counts.

  Args:
    sample_id: Identifier of the sample.
    population_id: Identifier of the population.
    event_count: Number of events in this population.
    parent_count: Number of events in the parent population.
        ``None`` or zero yields ``None`` for ``frequency_of_parent``.
    total_count: Total number of events in the sample.
        ``None`` or zero yields ``None`` for ``frequency_of_total``.

  Returns:
    ``PopulationResult`` with computed frequencies.
  """
  frequency_of_parent: float | None = None
  if parent_count is not None and parent_count != 0:
    frequency_of_parent = event_count / parent_count

  frequency_of_total: float | None = None
  if total_count is not None and total_count != 0:
    frequency_of_total = event_count / total_count

  return PopulationResult(
    sample_id=sample_id,
    population_id=population_id,
    event_count=event_count,
    frequency_of_parent=frequency_of_parent,
    frequency_of_total=frequency_of_total,
  )


# ---------------------------------------------------------------------------
# Moment statistics
# ---------------------------------------------------------------------------

def compute_mean(
  values: NDArray[np.float64],
) -> float:
  """Compute the arithmetic mean of a 1-D array.

  Returns ``np.nan`` when the input is empty or all values are ``NaN``.
  """
  if values.size == 0:
    return float("nan")
  return float(np.nanmean(values))


def compute_median(
  values: NDArray[np.float64],
) -> float:
  """Compute the median of a 1-D array (NaN-aware).

  Returns ``np.nan`` when the input is empty.
  """
  if values.size == 0:
    return float("nan")
  return float(np.nanmedian(values))


def compute_mad(
  values: NDArray[np.float64],
) -> float:
  """Compute the median absolute deviation (MAD).

  Uses the standard definition: ``median(|x - median(x)|)``.

  Returns ``np.nan`` when the input is empty.
  """
  if values.size == 0:
    return float("nan")
  med = np.nanmedian(values)
  return float(np.nanmedian(np.abs(values - med)))


def compute_stddev(
  values: NDArray[np.float64],
  ddof: int = 0,
) -> float:
  """Compute the standard deviation (NaN-aware).

  Args:
    values: 1-D array of event values.
    ddof: Delta degrees of freedom. Default 0 (population stddev).

  Returns:
    Standard deviation as a float. ``np.nan`` for empty input.
  """
  if values.size == 0:
    return float("nan")
  return float(np.nanstd(values, ddof=ddof))


def compute_percentile(
  values: NDArray[np.float64],
  q: float,
) -> float:
  """Compute a percentile (NaN-aware).

  Args:
    values: 1-D array of event values.
    q: Percentile in [0, 100].

  Returns:
    Percentile value. ``np.nan`` for empty input.
  """
  if values.size == 0:
    return float("nan")
  return float(np.nanpercentile(values, q))


# ---------------------------------------------------------------------------
# Histogram binning
# ---------------------------------------------------------------------------

def compute_histogram(
  values: NDArray[np.float64],
  n_bins: int = 100,
) -> dict[str, object]:
  """Compute a histogram of values.

  Returns a dict with keys:
    - ``counts``: list of bin counts (int).
    - ``bin_edges``: list of bin edge values (float).
    - ``bin_centers``: list of bin center values (float).

  Args:
    values: 1-D array of event values.
    n_bins: Number of histogram bins.

  Raises:
    PopulationStatsError: If ``n_bins`` < 1.
  """
  if n_bins < 1:
    raise PopulationStatsError(f"n_bins must be >= 1, got {n_bins}")

  if values.size == 0:
    return {
      "counts": [0] * n_bins,
      "bin_edges": [0.0] * (n_bins + 1),
      "bin_centers": [0.0] * n_bins,
    }

  finite = values[~np.isnan(values) & ~np.isinf(values)]
  if finite.size == 0:
    return {
      "counts": [0] * n_bins,
      "bin_edges": [0.0] * (n_bins + 1),
      "bin_centers": [0.0] * n_bins,
    }

  counts, bin_edges = np.histogram(finite, bins=n_bins)
  bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0

  return {
    "counts": counts.tolist(),
    "bin_edges": bin_edges.tolist(),
    "bin_centers": bin_centers.tolist(),
  }


# ---------------------------------------------------------------------------
# Export record conversion
# ---------------------------------------------------------------------------

def population_result_to_export_records(
  result: PopulationResult,
) -> list[ExportRecord]:
  """Convert a ``PopulationResult`` to serializable export records.

  Each metric becomes a separate row:
    - ``event_count``
    - ``frequency_of_parent``
    - ``frequency_of_total``
  """
  records: list[ExportRecord] = []

  records.append(
    ExportRecord(
      sample_id=result.sample_id,
      population_id=result.population_id,
      metric="event_count",
      value=result.event_count,
    )
  )

  records.append(
    ExportRecord(
      sample_id=result.sample_id,
      population_id=result.population_id,
      metric="frequency_of_parent",
      value=result.frequency_of_parent,
    )
  )

  records.append(
    ExportRecord(
      sample_id=result.sample_id,
      population_id=result.population_id,
      metric="frequency_of_total",
      value=result.frequency_of_total,
    )
  )

  return records


def population_results_to_export_records(
  results: list[PopulationResult],
) -> list[ExportRecord]:
  """Convert a list of ``PopulationResult`` to export records.

  Flattens all population results into a single list of ``ExportRecord``.
  """
  records: list[ExportRecord] = []
  for result in results:
    records.extend(population_result_to_export_records(result))
  return records
