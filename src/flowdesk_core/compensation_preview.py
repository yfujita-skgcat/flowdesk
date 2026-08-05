"""GUI-independent compensation candidate preview and pair diagnostics.

This module intentionally contains no Qt or plotting code.  It applies a candidate
matrix through the canonical compensation implementation, then returns a deterministic
display subset plus full-resolution diagnostics for an explicitly selected control pair.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from flowdesk_core.compensation import (
  CompensationError,
  _outlier_mask,
  apply_compensation,
  inspect_compensation_matrix,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import CompensationMatrixSpec, TransformSpec
from flowdesk_core.transforms import TransformError, apply_transform


class CompensationPreviewError(FlowdeskError):
  """Raised when a candidate preview request cannot be evaluated."""

  def __init__(
    self,
    message: str,
    *,
    code: str = "compensation_preview_invalid_request",
    details: dict[str, Any] | None = None,
  ) -> None:
    self.code = code
    self.details = details or {}
    super().__init__(message)


@dataclass(frozen=True)
class CompensationPairDiagnostic:
  """Full-resolution diagnostic for one source-to-receiving detector pair."""

  source_channel_id: str
  receiving_channel_id: str
  automatic_coefficient: float | None
  candidate_coefficient: float
  coefficient_difference: float | None
  positive_event_count: int
  negative_event_count: int
  included_event_count: int
  excluded_event_count: int
  residual_slope: float | None
  correlation: float | None
  receiving_median_difference: float | None
  residual_rms: float | None
  condition_number: float | None
  undefined_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompensationPreviewRequest:
  """Immutable candidate preview input.

  Masks are full-event masks.  The population mask limits both display and control
  diagnostics; positive/negative masks are intersected with it and are never inferred
  from sample names or channel values.
  """

  revision: int
  sample_id: str
  events: NDArray[np.float64]
  channel_ids: tuple[str, ...]
  population_mask: NDArray[np.bool_]
  candidate_matrix: CompensationMatrixSpec
  source_channel_id: str
  receiving_channel_id: str
  source_matrix: CompensationMatrixSpec | None = None
  positive_mask: NDArray[np.bool_] | None = None
  negative_mask: NDArray[np.bool_] | None = None
  outlier_policy: str = "none"
  display_max_points: int = 20_000
  x_transform: TransformSpec | None = None
  y_transform: TransformSpec | None = None

  def __post_init__(self) -> None:
    if self.revision < 0:
      raise ValueError("preview revision must be non-negative")
    if not self.sample_id:
      raise ValueError("preview sample_id must be non-empty")
    if not self.source_channel_id or not self.receiving_channel_id:
      raise ValueError("preview pair channel IDs must be non-empty")
    if self.display_max_points < 0:
      raise ValueError("preview display_max_points must be non-negative")
    if self.outlier_policy not in {"none", "iqr", "zscore"}:
      raise ValueError(f"invalid preview outlier policy: {self.outlier_policy!r}")

    events = np.array(self.events, dtype=np.float64, copy=True, order="C")
    if events.ndim != 2 or events.shape[1] != len(self.channel_ids):
      raise ValueError("preview events must align with channel_ids")
    if len(set(self.channel_ids)) != len(self.channel_ids):
      raise ValueError("preview channel_ids must be unique")
    if any(not channel_id for channel_id in self.channel_ids):
      raise ValueError("preview channel_ids must be non-empty")
    mask = _readonly_mask(self.population_mask, len(events), "population_mask")
    positive = _optional_readonly_mask(
      self.positive_mask, len(events), "positive_mask"
    )
    negative = _optional_readonly_mask(
      self.negative_mask, len(events), "negative_mask"
    )
    events.setflags(write=False)
    object.__setattr__(self, "events", events)
    object.__setattr__(self, "channel_ids", tuple(self.channel_ids))
    object.__setattr__(self, "population_mask", mask)
    object.__setattr__(self, "positive_mask", positive)
    object.__setattr__(self, "negative_mask", negative)


@dataclass(frozen=True)
class CompensationPreviewResult:
  """Candidate display arrays and full-resolution diagnostic metadata."""

  revision: int
  sample_id: str
  source_matrix_id: str | None
  candidate_matrix_id: str
  source_channel_id: str
  receiving_channel_id: str
  display_event_indices: NDArray[np.int64]
  uncompensated_x: NDArray[np.float64]
  uncompensated_y: NDArray[np.float64]
  compensated_x: NDArray[np.float64]
  compensated_y: NDArray[np.float64]
  x_transform_id: str | None
  y_transform_id: str | None
  axis_limits: tuple[float, float, float, float] | None
  full_event_count: int
  population_event_count: int
  diagnostics: tuple[CompensationPairDiagnostic, ...] = ()
  nonfinite_display_count: int = 0
  matrix_condition_number: float | None = None

  def __post_init__(self) -> None:
    indices = np.array(self.display_event_indices, dtype=np.int64, copy=True)
    arrays = tuple(
      np.array(value, dtype=np.float64, copy=True)
      for value in (
        self.uncompensated_x,
        self.uncompensated_y,
        self.compensated_x,
        self.compensated_y,
      )
    )
    if indices.ndim != 1 or any(value.ndim != 1 for value in arrays):
      raise ValueError("preview display arrays must be one-dimensional")
    if any(len(value) != len(indices) for value in arrays):
      raise ValueError("preview display arrays must have equal length")
    for value in (indices, *arrays):
      value.setflags(write=False)
    object.__setattr__(self, "display_event_indices", indices)
    object.__setattr__(self, "uncompensated_x", arrays[0])
    object.__setattr__(self, "uncompensated_y", arrays[1])
    object.__setattr__(self, "compensated_x", arrays[2])
    object.__setattr__(self, "compensated_y", arrays[3])


def _readonly_mask(
  value: NDArray[np.bool_], length: int, name: str
) -> NDArray[np.bool_]:
  mask = np.array(value, dtype=np.bool_, copy=True)
  if mask.ndim != 1 or len(mask) != length:
    raise ValueError(f"preview {name} must align with events")
  mask.setflags(write=False)
  return mask


def _optional_readonly_mask(
  value: NDArray[np.bool_] | None, length: int, name: str
) -> NDArray[np.bool_] | None:
  if value is None:
    return None
  return _readonly_mask(value, length, name)


def _display_indices(
  population_indices: NDArray[np.int64], max_points: int
) -> NDArray[np.int64]:
  if max_points == 0 or len(population_indices) <= max_points:
    return np.array(population_indices, dtype=np.int64, copy=True)
  # Evenly spaced selection is deterministic and preserves the full index identity.
  positions = np.linspace(0, len(population_indices) - 1, max_points, dtype=np.int64)
  return np.asarray(population_indices[positions], dtype=np.int64)


def _apply_display_transform(
  values: NDArray[np.float64],
  spec: TransformSpec | None,
  channel_id: str,
) -> NDArray[np.float64]:
  if spec is None:
    return np.array(values, dtype=np.float64, copy=True)
  if spec.parameter not in ("", channel_id):
    raise CompensationPreviewError(
      f"transform {spec.id!r} targets {spec.parameter!r}, not {channel_id!r}",
      code="compensation_preview_transform_parameter_mismatch",
    )
  try:
    return np.asarray(apply_transform(spec, values), dtype=np.float64)
  except TransformError as exc:
    raise CompensationPreviewError(
      str(exc), code="compensation_preview_transform_unsupported"
    ) from exc


def _pair_indices(
  channel_ids: Sequence[str], source: str, receiving: str
) -> tuple[int, int]:
  try:
    source_index = tuple(channel_ids).index(source)
    receiving_index = tuple(channel_ids).index(receiving)
  except ValueError as exc:
    raise CompensationPreviewError(
      "selected compensation pair is missing from event channels",
      code="compensation_preview_pair_invalid",
      details={"source": source, "receiving": receiving},
    ) from exc
  return source_index, receiving_index


def _safe_correlation(x: NDArray[np.float64], y: NDArray[np.float64]) -> float | None:
  if len(x) < 2 or len(y) < 2:
    return None
  x_std = float(np.std(x, ddof=1))
  y_std = float(np.std(y, ddof=1))
  if x_std <= 0 or y_std <= 0:
    return None
  value = float(np.corrcoef(x, y)[0, 1])
  return value if np.isfinite(value) else None


def _pair_diagnostic(
  request: CompensationPreviewRequest,
  compensated: NDArray[np.float64],
  source_index: int,
  receiving_index: int,
  condition_number: float | None,
) -> CompensationPairDiagnostic:
  source = request.source_channel_id
  receiving = request.receiving_channel_id
  candidate_coefficient = float(
    request.candidate_matrix.matrix[
      request.candidate_matrix.channels.index(receiving)
    ][request.candidate_matrix.channels.index(source)]
  )
  automatic_coefficient: float | None = None
  if request.source_matrix is not None:
    if source in request.source_matrix.channels and receiving in request.source_matrix.channels:
      automatic_coefficient = float(
        request.source_matrix.matrix[
          request.source_matrix.channels.index(receiving)
        ][request.source_matrix.channels.index(source)]
      )

  undefined: list[str] = []
  positive_count = 0
  negative_count = 0
  included_count = 0
  excluded_count = 0
  residual_slope: float | None = None
  correlation: float | None = None
  median_difference: float | None = None
  residual_rms: float | None = None

  if request.positive_mask is None or request.negative_mask is None:
    undefined.append("control_populations_not_provided")
  else:
    positive = request.population_mask & request.positive_mask
    negative = request.population_mask & request.negative_mask
    positive_count = int(positive.sum())
    negative_count = int(negative.sum())
    if positive_count == 0 or negative_count == 0:
      undefined.append("control_population_empty")
    else:
      negative_source = compensated[negative, source_index]
      negative_receiving = compensated[negative, receiving_index]
      positive_source = compensated[positive, source_index]
      positive_receiving = compensated[positive, receiving_index]
      finite_negative = np.isfinite(negative_source) & np.isfinite(negative_receiving)
      finite_positive = np.isfinite(positive_source) & np.isfinite(positive_receiving)
      if not np.any(finite_negative) or not np.any(finite_positive):
        undefined.append("control_values_nonfinite")
      else:
        negative_source_median = float(np.median(negative_source[finite_negative]))
        negative_receiving_median = float(np.median(negative_receiving[finite_negative]))
        positive_source = positive_source[finite_positive] - negative_source_median
        positive_receiving = positive_receiving[finite_positive] - negative_receiving_median
        finite = np.isfinite(positive_source) & np.isfinite(positive_receiving)
        positive_source = positive_source[finite]
        positive_receiving = positive_receiving[finite]
        if len(positive_source) == 0:
          undefined.append("control_values_nonfinite")
        else:
          keep = _outlier_mask(positive_source, request.outlier_policy)
          excluded_count = int((~keep).sum())
          positive_source = positive_source[keep]
          positive_receiving = positive_receiving[keep]
          included_count = len(positive_source)
          if included_count == 0:
            undefined.append("no_events_after_outlier_filter")
          else:
            denominator = float(np.dot(positive_source, positive_source))
            if denominator > 0 and np.isfinite(denominator):
              residual_slope = float(
                np.dot(positive_source, positive_receiving) / denominator
              )
              prediction = positive_source * residual_slope
              residual_rms = float(
                np.sqrt(np.mean((positive_receiving - prediction) ** 2))
              )
            else:
              undefined.append("source_signal_degenerate")
            correlation = _safe_correlation(positive_source, positive_receiving)
            finite_positive_receiving = compensated[positive, receiving_index]
            finite_negative_receiving = compensated[negative, receiving_index]
            finite_positive_receiving = finite_positive_receiving[
              np.isfinite(finite_positive_receiving)
            ]
            finite_negative_receiving = finite_negative_receiving[
              np.isfinite(finite_negative_receiving)
            ]
            if len(finite_positive_receiving) and len(finite_negative_receiving):
              median_difference = float(
                np.median(finite_positive_receiving)
                - np.median(finite_negative_receiving)
              )

  return CompensationPairDiagnostic(
    source_channel_id=source,
    receiving_channel_id=receiving,
    automatic_coefficient=automatic_coefficient,
    candidate_coefficient=candidate_coefficient,
    coefficient_difference=(
      candidate_coefficient - automatic_coefficient
      if automatic_coefficient is not None else None
    ),
    positive_event_count=positive_count,
    negative_event_count=negative_count,
    included_event_count=included_count,
    excluded_event_count=excluded_count,
    residual_slope=residual_slope,
    correlation=correlation,
    receiving_median_difference=median_difference,
    residual_rms=residual_rms,
    condition_number=condition_number,
    undefined_reasons=tuple(undefined),
  )


def prepare_compensation_preview(
  request: CompensationPreviewRequest,
) -> CompensationPreviewResult:
  """Evaluate a candidate matrix without changing project state or raw events."""
  candidate_validation = inspect_compensation_matrix(
    request.candidate_matrix, request.channel_ids
  )
  if not candidate_validation.is_valid:
    first_error = next(
      diagnostic for diagnostic in candidate_validation.diagnostics
      if diagnostic.severity == "error"
    )
    raise CompensationPreviewError(
      first_error.message,
      code=first_error.code,
      details=first_error.details,
    )
  if (
    request.source_channel_id not in request.candidate_matrix.channels
    or request.receiving_channel_id not in request.candidate_matrix.channels
  ):
    raise CompensationPreviewError(
      "selected compensation pair is not represented by the candidate matrix",
      code="compensation_preview_pair_invalid",
      details={
        "source": request.source_channel_id,
        "receiving": request.receiving_channel_id,
      },
    )
  try:
    compensated = apply_compensation(
      request.candidate_matrix,
      request.events,
      list(request.channel_ids),
    )
  except CompensationError as exc:
    raise CompensationPreviewError(
      str(exc), code=exc.code, details=exc.details
    ) from exc

  source_index, receiving_index = _pair_indices(
    request.channel_ids,
    request.source_channel_id,
    request.receiving_channel_id,
  )
  population_indices = np.flatnonzero(request.population_mask).astype(np.int64)
  display_indices = _display_indices(
    population_indices, request.display_max_points
  )
  raw_x = request.events[display_indices, source_index]
  raw_y = request.events[display_indices, receiving_index]
  compensated_x = compensated[display_indices, source_index]
  compensated_y = compensated[display_indices, receiving_index]
  display_raw_x = _apply_display_transform(
    raw_x, request.x_transform, request.source_channel_id
  )
  display_raw_y = _apply_display_transform(
    raw_y, request.y_transform, request.receiving_channel_id
  )
  display_comp_x = _apply_display_transform(
    compensated_x, request.x_transform, request.source_channel_id
  )
  display_comp_y = _apply_display_transform(
    compensated_y, request.y_transform, request.receiving_channel_id
  )
  finite = (
    np.isfinite(display_raw_x)
    & np.isfinite(display_raw_y)
    & np.isfinite(display_comp_x)
    & np.isfinite(display_comp_y)
  )
  finite_values = np.concatenate((
    display_raw_x[finite], display_raw_y[finite],
    display_comp_x[finite], display_comp_y[finite],
  ))
  axis_limits: tuple[float, float, float, float] | None = None
  if len(finite_values):
    finite_x = np.concatenate((display_raw_x[finite], display_comp_x[finite]))
    finite_y = np.concatenate((display_raw_y[finite], display_comp_y[finite]))
    axis_limits = (
      float(np.min(finite_x)), float(np.max(finite_x)),
      float(np.min(finite_y)), float(np.max(finite_y)),
    )
  diagnostic = _pair_diagnostic(
    request, compensated, source_index, receiving_index,
    candidate_validation.condition_number,
  )
  return CompensationPreviewResult(
    revision=request.revision,
    sample_id=request.sample_id,
    source_matrix_id=(
      request.source_matrix.id if request.source_matrix is not None else None
    ),
    candidate_matrix_id=request.candidate_matrix.id,
    source_channel_id=request.source_channel_id,
    receiving_channel_id=request.receiving_channel_id,
    display_event_indices=display_indices,
    uncompensated_x=display_raw_x,
    uncompensated_y=display_raw_y,
    compensated_x=display_comp_x,
    compensated_y=display_comp_y,
    x_transform_id=request.x_transform.id if request.x_transform else None,
    y_transform_id=request.y_transform.id if request.y_transform else None,
    axis_limits=axis_limits,
    full_event_count=len(request.events),
    population_event_count=len(population_indices),
    diagnostics=(diagnostic,),
    nonfinite_display_count=int((~finite).sum()),
    matrix_condition_number=candidate_validation.condition_number,
  )


__all__ = [
  "CompensationPairDiagnostic",
  "CompensationPreviewError",
  "CompensationPreviewRequest",
  "CompensationPreviewResult",
  "prepare_compensation_preview",
]
