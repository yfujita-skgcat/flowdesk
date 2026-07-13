"""Tests for linear, log, asinh, and the legacy Logicle approximation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flowdesk_core.models import TransformSpec
from flowdesk_core.transforms import (
  TransformError,
  apply_transform,
  apply_transform_to_column,
  inverse_transform,
  validate_transform,
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_transform_model_can_be_created() -> None:
  spec = TransformSpec(
    id="asinh_fl1",
    name="asinh FL1-A",
    transform_type="asinh",
    parameter="FL1-A",
    settings={"cofactor": 150.0},
  )
  assert spec.settings["cofactor"] == 150.0


# ---------------------------------------------------------------------------
# Linear transform
# ---------------------------------------------------------------------------


def test_linear_identity() -> None:
  """Linear with default settings returns input unchanged."""
  spec = TransformSpec(
    id="t1",
    name="linear",
    transform_type="linear",
    parameter="FL1-A",
  )
  values = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
  result = apply_transform(spec, values)
  np.testing.assert_array_almost_equal(result, values)


def test_linear_scale_only() -> None:
  spec = TransformSpec(
    id="t2",
    name="linear_scale",
    transform_type="linear",
    parameter="FL1-A",
    settings={"scale": 2.0},
  )
  values = np.array([1.0, 2.0, 3.0], dtype=np.float64)
  result = apply_transform(spec, values)
  np.testing.assert_array_almost_equal(result, [2.0, 4.0, 6.0])


def test_linear_offset_only() -> None:
  spec = TransformSpec(
    id="t3",
    name="linear_offset",
    transform_type="linear",
    parameter="FL1-A",
    settings={"offset": 10.0},
  )
  values = np.array([1.0, 2.0, 3.0], dtype=np.float64)
  result = apply_transform(spec, values)
  np.testing.assert_array_almost_equal(result, [11.0, 12.0, 13.0])


def test_linear_scale_and_offset() -> None:
  spec = TransformSpec(
    id="t4",
    name="linear_full",
    transform_type="linear",
    parameter="FL1-A",
    settings={"scale": 2.0, "offset": 5.0},
  )
  values = np.array([1.0, 2.0, 3.0], dtype=np.float64)
  result = apply_transform(spec, values)
  # y = 2*x + 5 -> [7, 9, 11]
  np.testing.assert_array_almost_equal(result, [7.0, 9.0, 11.0])


# ---------------------------------------------------------------------------
# Log transform
# ---------------------------------------------------------------------------


def test_log10_positive_values() -> None:
  spec = TransformSpec(
    id="t5",
    name="log10",
    transform_type="log",
    parameter="FL1-A",
    settings={"base": 10.0},
  )
  values = np.array([1.0, 10.0, 100.0, 1000.0], dtype=np.float64)
  result = apply_transform(spec, values)
  np.testing.assert_array_almost_equal(result, [0.0, 1.0, 2.0, 3.0])


def test_log2_positive_values() -> None:
  spec = TransformSpec(
    id="t6",
    name="log2",
    transform_type="log",
    parameter="FL1-A",
    settings={"base": 2.0},
  )
  values = np.array([1.0, 2.0, 4.0, 8.0], dtype=np.float64)
  result = apply_transform(spec, values)
  np.testing.assert_array_almost_equal(result, [0.0, 1.0, 2.0, 3.0])


def test_log_negative_to_nan() -> None:
  """Default policy is to_nan for non-positive values."""
  spec = TransformSpec(
    id="t7",
    name="log_nan_policy",
    transform_type="log",
    parameter="FL1-A",
  )
  values = np.array([1.0, 0.0, -1.0, 100.0], dtype=np.float64)
  result = apply_transform(spec, values)

  assert math.isfinite(result[0])
  assert np.isnan(result[1])
  assert np.isnan(result[2])
  assert math.isfinite(result[3])


def test_log_negative_to_zero() -> None:
  spec = TransformSpec(
    id="t8",
    name="log_zero_policy",
    transform_type="log",
    parameter="FL1-A",
    settings={"invalid_value_policy": "to_zero"},
  )
  values = np.array([10.0, 0.0, -5.0], dtype=np.float64)
  result = apply_transform(spec, values)

  assert math.isfinite(result[0])
  assert result[1] == 0.0
  assert result[2] == 0.0


def test_log_clip_to_one() -> None:
  spec = TransformSpec(
    id="t9",
    name="log_clip_policy",
    transform_type="log",
    parameter="FL1-A",
    settings={
      "base": 10.0,
      "invalid_value_policy": "clip_to_one",
    },
  )
  values = np.array([100.0, 0.0, -10.0], dtype=np.float64)
  result = apply_transform(spec, values)

  # log10(100) = 2.0
  np.testing.assert_almost_equal(result[0], 2.0)
  # log10(1) = 0.0 for clipped values
  np.testing.assert_almost_equal(result[1], 0.0)
  np.testing.assert_almost_equal(result[2], 0.0)


def test_log_invalid_policy_raises() -> None:
  spec = TransformSpec(
    id="t10",
    name="log_bad_policy",
    transform_type="log",
    parameter="FL1-A",
    settings={"invalid_value_policy": "drop"},
  )
  values = np.array([1.0], dtype=np.float64)
  with pytest.raises(TransformError, match="unknown invalid_value_policy"):
    apply_transform(spec, values)


def test_log_bad_base_raises() -> None:
  spec = TransformSpec(
    id="t11",
    name="log_bad_base",
    transform_type="log",
    parameter="FL1-A",
    settings={"base": 1.0},
  )
  values = np.array([10.0], dtype=np.float64)
  with pytest.raises(TransformError, match="base must be positive"):
    apply_transform(spec, values)


# ---------------------------------------------------------------------------
# Asinh transform
# ---------------------------------------------------------------------------


def test_asinh_default() -> None:
  """Pure asinh with cofactor=1."""
  spec = TransformSpec(
    id="t12",
    name="asinh_default",
    transform_type="asinh",
    parameter="FL1-A",
  )
  values = np.array([0.0, 1.0, -1.0], dtype=np.float64)
  result = apply_transform(spec, values)

  np.testing.assert_almost_equal(result[0], 0.0)
  np.testing.assert_almost_equal(result[1], math.asinh(1.0))
  np.testing.assert_almost_equal(result[2], math.asinh(-1.0))


def test_asinh_with_cofactor() -> None:
  """asinh with custom cofactor."""
  spec = TransformSpec(
    id="t13",
    name="asinh_cofactor",
    transform_type="asinh",
    parameter="FL1-A",
    settings={"cofactor": 100.0},
  )
  values = np.array([0.0, 100.0, -100.0], dtype=np.float64)
  result = apply_transform(spec, values)

  # asinh(0/100)*100 = 0
  np.testing.assert_almost_equal(result[0], 0.0)
  # asinh(100/100)*100 = asinh(1)*100
  np.testing.assert_almost_equal(result[1], math.asinh(1.0) * 100.0)
  # asinh(-100/100)*100 = asinh(-1)*100
  np.testing.assert_almost_equal(result[2], math.asinh(-1.0) * 100.0)


def test_asinh_negative_cofactor_raises() -> None:
  spec = TransformSpec(
    id="t14",
    name="asinh_bad_cofactor",
    transform_type="asinh",
    parameter="FL1-A",
    settings={"cofactor": -1.0},
  )
  values = np.array([1.0], dtype=np.float64)
  with pytest.raises(TransformError, match="cofactor must be positive"):
    apply_transform(spec, values)


@pytest.mark.parametrize(
  ("spec", "values"),
  [
    (
      TransformSpec(
        id="linear_inverse",
        name="linear inverse",
        transform_type="linear",
        parameter="signal",
        settings={"scale": 2.5, "offset": -7.0},
      ),
      np.array([-10.0, 0.0, 10.0], dtype=np.float64),
    ),
    (
      TransformSpec(
        id="log_inverse",
        name="log inverse",
        transform_type="log",
        parameter="signal",
        settings={"base": 10.0},
      ),
      np.array([0.1, 1.0, 10.0, 1e6], dtype=np.float64),
    ),
    (
      TransformSpec(
        id="asinh_inverse",
        name="asinh inverse",
        transform_type="asinh",
        parameter="signal",
        settings={"cofactor": 150.0},
      ),
      np.array([-1e5, -150.0, 0.0, 150.0, 1e5], dtype=np.float64),
    ),
  ],
  ids=("linear", "log", "asinh"),
)
def test_forward_inverse_round_trip(
  spec: TransformSpec,
  values: np.ndarray,
) -> None:
  transformed = apply_transform(spec, values)
  restored = inverse_transform(spec, transformed)

  np.testing.assert_allclose(restored, values, rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize(
  "spec",
  [
    TransformSpec(
      id="zero_scale",
      name="zero scale",
      transform_type="linear",
      parameter="signal",
      settings={"scale": 0.0},
    ),
    TransformSpec(
      id="infinite_scale",
      name="infinite scale",
      transform_type="linear",
      parameter="signal",
      settings={"scale": np.inf},
    ),
    TransformSpec(
      id="nan_base",
      name="NaN base",
      transform_type="log",
      parameter="signal",
      settings={"base": np.nan},
    ),
    TransformSpec(
      id="infinite_cofactor",
      name="infinite cofactor",
      transform_type="asinh",
      parameter="signal",
      settings={"cofactor": np.inf},
    ),
  ],
  ids=("zero-linear-scale", "infinite-linear-scale", "nan-log-base", "infinite-asinh-cofactor"),
)
def test_transform_protocol_rejects_noninvertible_or_nonfinite_settings(
  spec: TransformSpec,
) -> None:
  with pytest.raises(TransformError) as error:
    validate_transform(spec)

  assert error.value.code == "invalid_transform_settings"


def test_legacy_logicle_approximation_has_no_claimed_inverse() -> None:
  spec = TransformSpec(
    id="legacy_logicle",
    name="legacy logicle approximation",
    transform_type="legacy_logicle_approximation",
    parameter="signal",
  )

  with pytest.raises(TransformError) as error:
    inverse_transform(spec, np.array([0.0], dtype=np.float64))

  assert error.value.code == "transform_inverse_unavailable"


# ---------------------------------------------------------------------------
# Logicle-like transform
# ---------------------------------------------------------------------------


def test_legacy_logicle_approximation_preserves_shape() -> None:
  spec = TransformSpec(
    id="t15",
    name="logicle",
    transform_type="legacy_logicle_approximation",
    parameter="FL1-A",
  )
  values = np.array([0.0, 100.0, 10000.0, 100000.0], dtype=np.float64)
  result = apply_transform(spec, values)
  assert result.shape == values.shape


def test_legacy_logicle_approximation_handles_negative() -> None:
  """Logicle-like must handle negative values without error or NaN."""
  spec = TransformSpec(
    id="t16",
    name="logicle_neg",
    transform_type="legacy_logicle_approximation",
    parameter="FL1-A",
  )
  values = np.array([-100.0, -10.0, 0.0, 10.0, 1000.0], dtype=np.float64)
  result = apply_transform(spec, values)
  assert np.all(np.isfinite(result))


def test_legacy_logicle_approximation_bad_w_raises() -> None:
  spec = TransformSpec(
    id="t17",
    name="logicle_bad_w",
    transform_type="legacy_logicle_approximation",
    parameter="FL1-A",
    settings={"w": 2.0},
  )
  values = np.array([1.0], dtype=np.float64)
  with pytest.raises(TransformError, match="w must be in"):
    apply_transform(spec, values)


# ---------------------------------------------------------------------------
# Unknown transform type
# ---------------------------------------------------------------------------


def test_unknown_transform_raises() -> None:
  spec = TransformSpec(
    id="t18",
    name="unknown",
    transform_type="unknown_type",  # type: ignore  # intentional bad value
    parameter="FL1-A",
  )
  values = np.array([1.0], dtype=np.float64)
  with pytest.raises(TransformError, match="unknown transform type"):
    apply_transform(spec, values)


# ---------------------------------------------------------------------------
# Column-level transform
# ---------------------------------------------------------------------------


def test_apply_transform_to_column() -> None:
  spec = TransformSpec(
    id="t19",
    name="log_fl1",
    transform_type="log",
    parameter="FL1-A",
    settings={"base": 10.0},
  )
  data = np.array([
    [10.0, 200.0, 500.0],
    [100.0, 300.0, 600.0],
  ], dtype=np.float64)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  result = apply_transform_to_column(spec, data, channels)

  # FL1-A column transformed: log10(10)=1, log10(100)=2
  np.testing.assert_almost_equal(result[0, 0], 1.0)
  np.testing.assert_almost_equal(result[1, 0], 2.0)

  # Other columns unchanged
  np.testing.assert_array_almost_equal(result[:, 1], data[:, 1])
  np.testing.assert_array_almost_equal(result[:, 2], data[:, 2])


def test_apply_transform_to_column_missing_param() -> None:
  spec = TransformSpec(
    id="t20",
    name="log_fl3",
    transform_type="log",
    parameter="FL3-A",
  )
  data = np.array([[1.0, 2.0]], dtype=np.float64)
  channels = ["FL1-A", "FL2-A"]

  with pytest.raises(TransformError, match="not found"):
    apply_transform_to_column(spec, data, channels)


def test_apply_transform_to_column_raw_unchanged() -> None:
  """Original data must not be mutated."""
  spec = TransformSpec(
    id="t21",
    name="log",
    transform_type="log",
    parameter="FL1-A",
  )
  data = np.array([[10.0, 200.0]], dtype=np.float64)
  original = data.copy()
  channels = ["FL1-A", "FL2-A"]

  _ = apply_transform_to_column(spec, data, channels)
  np.testing.assert_array_equal(data, original)


# ---------------------------------------------------------------------------
# NaN and Inf handling
# ---------------------------------------------------------------------------


def test_transform_does_not_drop_nan() -> None:
  """NaN values must be preserved, not silently dropped."""
  spec = TransformSpec(
    id="t22",
    name="asinh",
    transform_type="asinh",
    parameter="FL1-A",
  )
  values = np.array([1.0, np.nan, 3.0], dtype=np.float64)
  result = apply_transform(spec, values)

  assert np.isnan(result[1])
  assert len(result) == 3


def test_transform_does_not_drop_inf() -> None:
  """Inf values must be preserved."""
  spec = TransformSpec(
    id="t23",
    name="asinh",
    transform_type="asinh",
    parameter="FL1-A",
  )
  values = np.array([1.0, np.inf, -np.inf], dtype=np.float64)
  result = apply_transform(spec, values)

  assert np.isinf(result[1])
  assert np.isinf(result[2])
  assert len(result) == 3
