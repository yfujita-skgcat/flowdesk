"""Core tests for visual compensation candidate previews."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.compensation import apply_compensation
from flowdesk_core.compensation_preview import (
  CompensationPreviewError,
  CompensationPreviewRequest,
  prepare_compensation_preview,
)
from flowdesk_core.models import CompensationMatrixSpec


def _matrix(
  matrix: tuple[tuple[float, ...], ...],
  *,
  matrix_id: str = "candidate",
) -> CompensationMatrixSpec:
  return CompensationMatrixSpec(
    id=matrix_id,
    name=matrix_id,
    source="user_defined",
    channels=("A", "B"),
    matrix=matrix,
  )


def _request(display_max_points: int = 0) -> CompensationPreviewRequest:
  events = np.array([
    [1.0, 10.0, 2.0],
    [2.0, 12.0, 2.0],
    [3.0, 100.0, 10.0],
    [4.0, 200.0, 20.0],
    [5.0, 300.0, 30.0],
  ], dtype=np.float64)
  return CompensationPreviewRequest(
    revision=7,
    sample_id="control-a",
    events=events,
    channel_ids=("FSC", "A", "B"),
    population_mask=np.ones(len(events), dtype=np.bool_),
    candidate_matrix=_matrix(((1.0, 0.0), (0.0, 1.0))),
    source_matrix=_matrix(((1.0, 0.0), (0.1, 1.0)), matrix_id="automatic"),
    source_channel_id="A",
    receiving_channel_id="B",
    positive_mask=np.array([False, False, True, True, True]),
    negative_mask=np.array([True, True, False, False, False]),
    display_max_points=display_max_points,
  )


def test_preview_applies_candidate_matrix_and_preserves_raw_input() -> None:
  request = _request(display_max_points=2)
  before = request.events.copy()
  result = prepare_compensation_preview(request)

  assert result.revision == 7
  assert result.sample_id == "control-a"
  assert result.display_event_indices.tolist() == [0, 4]
  expected = apply_compensation(
    request.candidate_matrix, request.events, list(request.channel_ids)
  )
  np.testing.assert_array_equal(
    result.uncompensated_x,
    request.events[result.display_event_indices, 1],
  )
  np.testing.assert_array_equal(
    result.compensated_y,
    expected[result.display_event_indices, 2],
  )
  np.testing.assert_array_equal(request.events, before)
  assert not request.events.flags.writeable
  assert not result.compensated_y.flags.writeable


def test_full_resolution_pair_diagnostic_is_independent_of_display_limit() -> None:
  limited = prepare_compensation_preview(_request(display_max_points=2))
  full = prepare_compensation_preview(_request(display_max_points=0))
  assert limited.population_event_count == full.population_event_count == 5
  assert limited.diagnostics == full.diagnostics
  diagnostic = full.diagnostics[0]
  assert diagnostic.automatic_coefficient == pytest.approx(0.1)
  assert diagnostic.candidate_coefficient == pytest.approx(0.0)
  assert diagnostic.coefficient_difference == pytest.approx(-0.1)
  assert diagnostic.positive_event_count == 3
  assert diagnostic.negative_event_count == 2
  assert diagnostic.included_event_count == 3
  assert diagnostic.residual_slope == pytest.approx(0.09598704025542021)
  assert diagnostic.correlation == pytest.approx(1.0)


def test_preview_uses_one_shared_axis_range_for_before_and_after() -> None:
  result = prepare_compensation_preview(_request())
  assert result.axis_limits is not None
  x_min, x_max, y_min, y_max = result.axis_limits
  assert x_min == pytest.approx(10.0)
  assert x_max == pytest.approx(300.0)
  assert y_min == pytest.approx(2.0)
  assert y_max == pytest.approx(30.0)


def test_preview_reports_missing_control_populations_without_inventing_zero() -> None:
  request = _request()
  request = CompensationPreviewRequest(
    revision=request.revision,
    sample_id=request.sample_id,
    events=request.events,
    channel_ids=request.channel_ids,
    population_mask=request.population_mask,
    candidate_matrix=request.candidate_matrix,
    source_channel_id=request.source_channel_id,
    receiving_channel_id=request.receiving_channel_id,
  )
  diagnostic = prepare_compensation_preview(request).diagnostics[0]
  assert diagnostic.residual_slope is None
  assert diagnostic.correlation is None
  assert "control_populations_not_provided" in diagnostic.undefined_reasons


def test_preview_rejects_pair_not_in_candidate_matrix() -> None:
  request = _request()
  invalid = CompensationPreviewRequest(
    revision=request.revision,
    sample_id=request.sample_id,
    events=request.events,
    channel_ids=request.channel_ids,
    population_mask=request.population_mask,
    candidate_matrix=CompensationMatrixSpec(
      id="only-a",
      name="only-a",
      source="user_defined",
      channels=("A",),
      matrix=((1.0,),),
    ),
    source_channel_id=request.source_channel_id,
    receiving_channel_id=request.receiving_channel_id,
  )
  with pytest.raises(CompensationPreviewError) as error:
    prepare_compensation_preview(invalid)
  assert error.value.code == "compensation_preview_pair_invalid"
