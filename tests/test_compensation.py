"""Tests for compensation matrix validation and application."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.compensation import (
  CompensationError,
  apply_compensation,
  validate_compensation_matrix,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import CompensationMatrixSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(
  channels: tuple[str, ...],
  matrix: tuple[tuple[float, ...], ...],
) -> CompensationMatrixSpec:
  return CompensationMatrixSpec(
    id="comp_test",
    name="test",
    source="user_defined",
    channels=channels,
    matrix=matrix,
  )


# ---------------------------------------------------------------------------
# Model creation
# ---------------------------------------------------------------------------


def test_compensation_matrix_model_can_be_created() -> None:
  spec = CompensationMatrixSpec(
    id="comp1",
    name="FCS spillover",
    source="fcs_metadata_spillover",
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )
  validate_compensation_matrix(spec)
  assert spec.channels == ("FL1-A", "FL2-A")


def test_compensation_error_is_flowdesk_error() -> None:
  assert issubclass(CompensationError, FlowdeskError)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_rejects_non_square_matrix() -> None:
  # The model's __post_init__ raises ValueError for shape mismatch.
  with pytest.raises(ValueError, match="square"):
    _make_spec(
      channels=("FL1-A",),
      matrix=((1.0, 0.1), (0.2, 1.0)),
    )


def test_validate_rejects_duplicate_channels() -> None:
  with pytest.raises(CompensationError, match="unique"):
    validate_compensation_matrix(
      _make_spec(
        channels=("FL1-A", "FL1-A"),
        matrix=((1.0, 0.1), (0.2, 1.0)),
      )
    )


def test_validate_rejects_nan_values() -> None:
  with pytest.raises(CompensationError, match="finite"):
    validate_compensation_matrix(
      _make_spec(
        channels=("FL1-A", "FL2-A"),
        matrix=((float("nan"), 0.1), (0.2, 1.0)),
      )
    )


def test_validate_rejects_inf_values() -> None:
  with pytest.raises(CompensationError, match="finite"):
    validate_compensation_matrix(
      _make_spec(
        channels=("FL1-A", "FL2-A"),
        matrix=((float("inf"), 0.1), (0.2, 1.0)),
      )
    )


def test_validate_rejects_singular_matrix() -> None:
  """A zero-row matrix is singular and must be rejected."""
  with pytest.raises(CompensationError, match="singular"):
    validate_compensation_matrix(
      _make_spec(
        channels=("FL1-A", "FL2-A"),
        matrix=((0.0, 0.0), (0.0, 0.0)),
      )
    )


# ---------------------------------------------------------------------------
# Identity compensation
# ---------------------------------------------------------------------------


def test_identity_compensation_unchanged() -> None:
  """Applying an identity matrix must leave values unchanged."""
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.0), (0.0, 1.0)),
  )
  events = np.array([
    [100.0, 200.0, 50.0],
    [300.0, 400.0, 75.0],
  ], dtype=np.float64)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  result = apply_compensation(spec, events, channels)

  np.testing.assert_array_almost_equal(result[:, 0], events[:, 0])
  np.testing.assert_array_almost_equal(result[:, 1], events[:, 1])
  # Non-comp channels unchanged.
  np.testing.assert_array_almost_equal(result[:, 2], events[:, 2])


# ---------------------------------------------------------------------------
# Non-identity compensation
# ---------------------------------------------------------------------------


def test_2x2_compensation_hand_computed() -> None:
  """Compensation with a known 2x2 spillover matrix.

  Spillover:  FL1 receives 10% of FL2, FL2 receives 20% of FL1.
  Matrix: [[1.0, 0.1], [0.2, 1.0]]
  Inverse: [[1.1111, -0.1111], [-0.2222, 1.1111]]

  For raw [100, 50]:
    comp_FL1 = 1.1111*100 + (-0.1111)*50 = 105.5556
    comp_FL2 = (-0.2222)*100 + 1.1111*50 = 27.7778
  """
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )
  events = np.array([
    [100.0, 50.0, 1000.0],
  ], dtype=np.float64)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  result = apply_compensation(spec, events, channels)

  # Expected values: inverse of [[1,0.1],[0.2,1]] = [[1.0204,-0.1020],[-0.2041,1.0204]]
  # comp_FL1 = 1.0204*100 + (-0.1020)*50 = 96.9388
  # comp_FL2 = (-0.2041)*100 + 1.0204*50 = 30.6122
  np.testing.assert_almost_equal(result[0, 0], 96.9388, decimal=3)
  np.testing.assert_almost_equal(result[0, 1], 30.6122, decimal=3)
  # Non-comp channel unchanged.
  np.testing.assert_almost_equal(result[0, 2], 1000.0)


def test_compensation_3x3() -> None:
  """3-channel compensation with spillover."""
  spec = _make_spec(
    channels=("FL1-A", "FL2-A", "FL3-A"),
    matrix=(
      (1.0, 0.1, 0.05),
      (0.2, 1.0, 0.1),
      (0.05, 0.05, 1.0),
    ),
  )
  events = np.array([
    [1000.0, 500.0, 200.0, 9999.0],
  ], dtype=np.float64)
  channels = ["FSC-A", "FL1-A", "FL2-A", "FL3-A"]

  result = apply_compensation(spec, events, channels)

  # FSC-A (non-comp channel) unchanged.
  np.testing.assert_almost_equal(result[0, 0], 1000.0)

  # Fluorescence channels changed by compensation.
  assert not np.allclose(result[0, 1], events[0, 1])


# ---------------------------------------------------------------------------
# Channel order alignment
# ---------------------------------------------------------------------------


def test_channel_order_mismatch_resolved_by_names() -> None:
  """Matrix channels listed in different order than data columns
  must be correctly aligned by name."""
  spec = _make_spec(
    channels=("FL2-A", "FL1-A"),  # reversed order
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )
  events = np.array([
    [100.0, 50.0],
  ], dtype=np.float64)
  channels = ["FL1-A", "FL2-A"]  # data order differs from matrix order

  result = apply_compensation(spec, events, channels)

  # The compensation should still be mathematically correct because
  # channel names are used for alignment.
  # spec.channels = ('FL2-A', 'FL1-A') so col_indices = [1, 0]
  # raw_block = events[:, [1,0]] = [[50, 100]]
  # inverse of [[1,0.1],[0.2,1]] = [[1.0204,-0.1020],[-0.2041,1.0204]]
  # comp_block = inverse @ [[50],[100]] = [[40.82],[91.84]]
  # Then compensated[:, [1,0]] = comp_block.T -> col1=40.82, col0=91.84
  np.testing.assert_almost_equal(result[0, 0], 91.8367, decimal=3)  # FL1-A
  np.testing.assert_almost_equal(result[0, 1], 40.8163, decimal=3)  # FL2-A


def test_missing_channel_raises_error() -> None:
  """If a compensation channel is absent from data, raise CompensationError."""
  spec = _make_spec(
    channels=("FL1-A", "FL4-A"),
    matrix=((1.0, 0.0), (0.0, 1.0)),
  )
  events = np.array([[100.0, 50.0]], dtype=np.float64)
  channels = ["FL1-A", "FL2-A"]

  with pytest.raises(CompensationError, match="not found"):
    apply_compensation(spec, events, channels)


# ---------------------------------------------------------------------------
# Raw immutability
# ---------------------------------------------------------------------------


def test_raw_input_unchanged() -> None:
  """The original events array must not be mutated."""
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )
  events = np.array([
    [100.0, 50.0],
    [200.0, 100.0],
  ], dtype=np.float64)
  original = events.copy()
  channels = ["FL1-A", "FL2-A"]

  _ = apply_compensation(spec, events, channels)

  np.testing.assert_array_equal(events, original)


def test_result_is_new_array() -> None:
  """The returned array must not share memory with the input."""
  spec = _make_spec(
    channels=("FL1-A",),
    matrix=((1.0,),),
  )
  events = np.array([[100.0]], dtype=np.float64)
  channels = ["FL1-A"]

  result = apply_compensation(spec, events, channels)

  assert result is not events
  # Modifying result does not affect input.
  result[0, 0] = 999.0
  assert events[0, 0] == 100.0


# ---------------------------------------------------------------------------
# Shape validation
# ---------------------------------------------------------------------------


def test_events_shape_mismatch_raises() -> None:
  """events columns must match channel_names length."""
  spec = _make_spec(
    channels=("FL1-A",),
    matrix=((1.0,),),
  )
  events = np.array([[100.0, 50.0]], dtype=np.float64)
  channels = ["FL1-A"]  # only 1 name for 2 columns

  with pytest.raises(CompensationError, match="columns count"):
    apply_compensation(spec, events, channels)


def test_1d_events_raises() -> None:
  """events must be 2-D."""
  spec = _make_spec(
    channels=("FL1-A",),
    matrix=((1.0,),),
  )
  events = np.array([100.0], dtype=np.float64)
  channels = ["FL1-A"]

  with pytest.raises(CompensationError, match="2-D"):
    apply_compensation(spec, events, channels)


# ---------------------------------------------------------------------------
# Multiple events
# ---------------------------------------------------------------------------


def test_multiple_events_compensated_independently() -> None:
  """Each event row is compensated independently."""
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.5), (0.3, 1.0)),
  )
  events = np.array([
    [100.0, 200.0],
    [50.0, 10.0],
    [0.0, 0.0],
  ], dtype=np.float64)
  channels = ["FL1-A", "FL2-A"]

  result = apply_compensation(spec, events, channels)

  # Zero event should remain zero after compensation.
  np.testing.assert_array_almost_equal(result[2], [0.0, 0.0])

  # Shape preserved.
  assert result.shape == events.shape
