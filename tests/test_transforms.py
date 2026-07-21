"""Tests for linear, log, asinh, and the legacy Logicle approximation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flowdesk_core.models import TransformSpec
from flowdesk_core.transforms import (
  LOGICLE_IMPLEMENTATION_VERSION,
  TransformError,
  apply_transform,
  apply_transform_to_column,
  generate_log_ticks,
  generate_transform_ticks,
  inverse_transform,
  validate_transform,
)

LOGICLE_REFERENCE_VALUES = np.array([
  -10000.0,
  -1000.0,
  -100.0,
  -10.0,
  0.0,
  10.0,
  100.0,
  1000.0,
  10000.0,
  100000.0,
  262144.0,
  1000000.0,
], dtype=np.float64)

# Generated with Moore-Parks Logicle.cpp from Bioconductor flowCore commit
# 4935c7bf318697b3128ee50dae81018a6b246ab8 (Revised BSD license).
LOGICLE_REFERENCE_SCALES = {
  0.0: np.array([
    -0.46161043500433507,
    -0.23211535395017646,
    0.009041134692025388,
    0.099917946544774,
    0.1111111111111111,
    0.12230427567744821,
    0.21318108753019682,
    0.45433757617239867,
    0.6838326572265573,
    0.9069275914814589,
    1.0,
    1.1292427085676322,
  ], dtype=np.float64),
  1.0: np.array([
    -0.19586308318536516,
    -0.008094380504689802,
    0.1892154738389299,
    0.26356922899117874,
    0.2727272727272727,
    0.2818853164633667,
    0.3562390716156155,
    0.5535489259592352,
    0.7413176286399106,
    0.923849847575739,
    1.0,
    1.1057440342826081,
  ], dtype=np.float64),
}


def _logicle_spec(*, additional_negative_decades: float = 0.0) -> TransformSpec:
  return TransformSpec(
    id="published_logicle",
    name="Published Logicle",
    transform_type="logicle",
    parameter="signal",
    settings={
      "T": 262144.0,
      "W": 0.5,
      "M": 4.5,
      "A": additional_negative_decades,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
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


@pytest.mark.parametrize("additional_negative_decades", (0.0, 1.0))
def test_published_logicle_matches_moore_parks_reference_vector(
  additional_negative_decades: float,
) -> None:
  spec = _logicle_spec(
    additional_negative_decades=additional_negative_decades
  )

  result = apply_transform(spec, LOGICLE_REFERENCE_VALUES)

  np.testing.assert_allclose(
    result,
    LOGICLE_REFERENCE_SCALES[additional_negative_decades],
    rtol=0.0,
    atol=1e-12,
  )


@pytest.mark.parametrize("additional_negative_decades", (0.0, 1.0))
def test_published_logicle_inverse_matches_reference_values(
  additional_negative_decades: float,
) -> None:
  spec = _logicle_spec(
    additional_negative_decades=additional_negative_decades
  )

  restored = inverse_transform(
    spec,
    LOGICLE_REFERENCE_SCALES[additional_negative_decades],
  )

  np.testing.assert_allclose(
    restored,
    LOGICLE_REFERENCE_VALUES,
    rtol=1e-12,
    atol=262144.0e-12,
  )


def test_published_logicle_inverse_forward_round_trip() -> None:
  spec = _logicle_spec()
  restored = inverse_transform(
    spec,
    apply_transform(spec, LOGICLE_REFERENCE_VALUES),
  )

  np.testing.assert_allclose(
    restored,
    LOGICLE_REFERENCE_VALUES,
    rtol=1e-12,
    atol=262144.0e-12,
  )


def test_published_logicle_exact_zero_and_top_scale_anchors() -> None:
  spec = _logicle_spec()
  result = apply_transform(
    spec,
    np.array([0.0, 262144.0], dtype=np.float64),
  )

  np.testing.assert_allclose(
    result,
    [0.5 / 4.5, 1.0],
    rtol=0.0,
    atol=8 * np.finfo(np.float64).eps,
  )


@pytest.mark.parametrize(
  ("width", "additional"),
  (
    (0.0, 0.0),
    (0.5, -0.5),
    (0.5, 3.5),
    (2.25, 0.0),
  ),
  ids=("zero-W", "minimum-A", "maximum-A", "maximum-W"),
)
def test_published_logicle_accepts_parameter_boundaries(
  width: float,
  additional: float,
) -> None:
  spec = TransformSpec(
    id="boundary_logicle",
    name="Boundary Logicle",
    transform_type="logicle",
    parameter="signal",
    settings={
      "T": 262144.0,
      "W": width,
      "M": 4.5,
      "A": additional,
      "implementation_version": LOGICLE_IMPLEMENTATION_VERSION,
    },
  )
  values = np.array([-100.0, 0.0, 100.0, 262144.0], dtype=np.float64)

  validate_transform(spec)
  restored = inverse_transform(spec, apply_transform(spec, values))

  np.testing.assert_allclose(
    restored,
    values,
    rtol=1e-12,
    atol=262144.0e-12,
  )

@pytest.mark.parametrize(
  "settings",
  [
    {},
    {"T": 0.0, "W": 0.5, "M": 4.5, "A": 0.0},
    {"T": 262144.0, "W": -0.1, "M": 4.5, "A": 0.0},
    {"T": 262144.0, "W": 2.3, "M": 4.5, "A": 0.0},
    {"T": 262144.0, "W": 0.5, "M": 4.5, "A": -0.6},
    {"T": 262144.0, "W": 0.5, "M": 4.5, "A": 3.6},
    {
      "T": 262144.0,
      "W": 0.5,
      "M": 4.5,
      "A": 0.0,
      "implementation_version": "unknown-logicle",
    },
  ],
  ids=(
    "missing",
    "non-positive-T",
    "negative-W",
    "W-over-half-M",
    "A-below-negative-W",
    "A-above-M-minus-two-W",
    "unknown-version",
  ),
)
def test_published_logicle_rejects_invalid_parameters(
  settings: dict[str, object],
) -> None:
  complete_settings = dict(settings)
  if complete_settings:
    complete_settings.setdefault(
      "implementation_version", LOGICLE_IMPLEMENTATION_VERSION
    )
  spec = TransformSpec(
    id="invalid_logicle",
    name="Invalid Logicle",
    transform_type="logicle",
    parameter="signal",
    settings=complete_settings,
  )

  with pytest.raises(TransformError) as error:
    validate_transform(spec)

  assert error.value.code == "invalid_transform_settings"


@pytest.mark.parametrize("value", (np.nan, np.inf, -np.inf))
def test_published_logicle_rejects_nonfinite_event_values(value: float) -> None:
  with pytest.raises(TransformError) as error:
    apply_transform(
      _logicle_spec(),
      np.array([0.0, value], dtype=np.float64),
    )

  assert error.value.code == "transform_domain_error"


def test_published_logicle_reports_non_convergence(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr(
    "flowdesk_core.transforms._LOGICLE_MAX_ITERATIONS",
    0,
  )

  with pytest.raises(TransformError) as error:
    apply_transform(
      _logicle_spec(),
      np.array([100.0], dtype=np.float64),
    )

  assert error.value.code == "transform_non_convergence"


def test_logicle_ticks_use_the_same_forward_and_inverse_definition() -> None:
  spec = _logicle_spec()

  ticks = generate_transform_ticks(spec, -0.5, 1.0)
  by_value = {tick.event_value: tick.coordinate for tick in ticks}

  assert 0.0 in by_value
  assert 262144.0 in by_value
  expected = apply_transform(
    spec,
    np.array([0.0, 262144.0], dtype=np.float64),
  )
  assert by_value[0.0] == pytest.approx(expected[0], abs=1e-15)
  assert by_value[262144.0] == pytest.approx(expected[1], abs=1e-15)


def test_log_ticks_prefer_decades_and_keep_minor_ticks_unlabelled() -> None:
  ticks = generate_log_ticks(1e4, 1e7, "auto")
  assert [tick.event_value for tick in ticks if tick.level == "major"] == [
    1e4, 1e5, 1e6, 1e7,
  ]
  assert 2e5 in [tick.event_value for tick in ticks if tick.level == "minor"]

  short = generate_log_ticks(3e5, 3e6, "auto")
  assert [tick.event_value for tick in short if tick.level == "major"] == [
    5e5, 1e6, 2e6,
  ]


def test_log_ticks_include_exact_view_boundaries_after_float_conversion() -> None:
  ticks = generate_log_ticks(10_000.000000000002, 100_000_000.0000001, "decades")
  assert [tick.event_value for tick in ticks] == [1e4, 1e5, 1e6, 1e7, 1e8]


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
