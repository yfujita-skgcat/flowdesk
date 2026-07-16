"""Tests for compensation matrix validation and application."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from flowdesk_core.compensation import (
  COMPENSATION_CONDITION_WARNING_THRESHOLD,
  CompensationError,
  apply_compensation,
  calculate_spillover_matrix,
  inspect_compensation_matrix,
  resolve_compensation_binding,
  validate_compensation_matrix,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import (
  CompensationBindingSpec,
  CompensationCalculationControlSpec,
  CompensationCalculationSpec,
  CompensationManualEditSpec,
  CompensationMatrixSpec,
  CompensationProvenanceSpec,
)

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


def test_compensation_provenance_and_manual_edits_are_immutable_typed_records() -> None:
  edit = CompensationManualEditSpec(
    row_channel_id="FL1-A",
    column_channel_id="FL2-A",
    old_value=0.1,
    new_value=0.12,
    edited_at="2026-07-13T12:00:00+09:00",
    edited_by="operator",
    reason="Reviewed against control",
  )
  provenance = CompensationProvenanceSpec(
    source_sample_id="control-1",
    source_metadata_key="$SPILLOVER",
    control_sample_ids=("control-1", "control-2"),
    control_population_ids=("positive", "negative"),
    algorithm="manual_matrix_edit",
    algorithm_version="1",
    software_version="flowdesk-0.1.0",
    derived_from_matrix_id="original-matrix",
    manual_edits=(edit,),
  )
  spec = CompensationMatrixSpec(
    id="edited-matrix",
    name="Edited matrix",
    source="user_defined",
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.12), (0.2, 1.0)),
    provenance=provenance,
  )

  assert spec.provenance.manual_edits == (edit,)
  assert spec.provenance.control_sample_ids == ("control-1", "control-2")


def test_manual_edit_history_requires_duplicate_lineage() -> None:
  edit = CompensationManualEditSpec(
    row_channel_id="FL1-A",
    column_channel_id="FL2-A",
    old_value=0.1,
    new_value=0.2,
  )

  with pytest.raises(ValueError, match="derived_from_matrix_id"):
    CompensationProvenanceSpec(manual_edits=(edit,))


@pytest.mark.parametrize(
  ("scope", "target_id"),
  (("sample", "sample-1"), ("group", "group-1"), ("execution_profile", "default")),
)
def test_compensation_binding_has_explicit_scope_and_target(
  scope: str, target_id: str
) -> None:
  binding = CompensationBindingSpec(
    id=f"binding-{scope}",
    matrix_id="matrix-1",
    scope=scope,
    target_id=target_id,
  )

  assert binding.scope == scope
  assert binding.target_id == target_id


def test_compensation_binding_rejects_ambiguous_or_empty_identity() -> None:
  with pytest.raises(ValueError, match="scope"):
    CompensationBindingSpec(
      id="binding", matrix_id="matrix", scope="project", target_id="project"
    )
  with pytest.raises(ValueError, match="non-empty"):
    CompensationBindingSpec(
      id="binding", matrix_id="", scope="sample", target_id="sample-1"
    )


def test_existing_matrix_constructor_keeps_empty_provenance_compatibility() -> None:
  spec = _make_spec(("FL1-A",), ((1.0,),))

  assert spec.provenance == CompensationProvenanceSpec()


def _binding(
  binding_id: str, matrix_id: str, scope: str, target_id: str
) -> CompensationBindingSpec:
  return CompensationBindingSpec(
    id=binding_id,
    matrix_id=matrix_id,
    scope=scope,
    target_id=target_id,
  )


def test_binding_resolution_priority_is_sample_profile_group_default() -> None:
  bindings = (
    _binding("sample", "m_sample", "sample", "s1"),
    _binding("profile", "m_profile", "execution_profile", "profile"),
    _binding("group", "m_group", "group", "g1"),
  )
  known = {"m_sample", "m_profile", "m_group", "m_default"}

  sample = resolve_compensation_binding(
    bindings,
    sample_id="s1",
    execution_profile_id="profile",
    group_ids=("g1",),
    default_matrix_id="m_default",
    known_matrix_ids=known,
  )
  profile = resolve_compensation_binding(
    bindings[1:],
    sample_id="s1",
    execution_profile_id="profile",
    group_ids=("g1",),
    default_matrix_id="m_default",
    known_matrix_ids=known,
  )
  group = resolve_compensation_binding(
    bindings[2:],
    sample_id="s1",
    execution_profile_id="other",
    group_ids=("g1",),
    default_matrix_id="m_default",
    known_matrix_ids=known,
  )
  default = resolve_compensation_binding(
    (),
    sample_id="s1",
    execution_profile_id="other",
    group_ids=(),
    default_matrix_id="m_default",
    known_matrix_ids=known,
  )

  assert (sample.matrix_id, sample.priority) == ("m_sample", "sample")
  assert (profile.matrix_id, profile.priority) == ("m_profile", "execution_profile")
  assert (group.matrix_id, group.priority) == ("m_group", "group")
  assert (default.matrix_id, default.priority) == ("m_default", "project_default")


def test_same_matrix_group_bindings_are_unambiguous() -> None:
  resolution = resolve_compensation_binding(
    (
      _binding("g1-binding", "matrix", "group", "g1"),
      _binding("g2-binding", "matrix", "group", "g2"),
    ),
    sample_id="s1",
    execution_profile_id="default",
    group_ids=("g1", "g2"),
    default_matrix_id=None,
    known_matrix_ids={"matrix"},
  )

  assert resolution.matrix_id == "matrix"
  assert resolution.binding_ids == ("g1-binding", "g2-binding")
  assert resolution.target_ids == ("g1", "g2")


def test_binding_conflicts_and_unknown_matrix_never_fall_through() -> None:
  with pytest.raises(CompensationError) as conflict:
    resolve_compensation_binding(
      (
        _binding("g1", "m1", "group", "g1"),
        _binding("g2", "m2", "group", "g2"),
      ),
      sample_id="s1",
      execution_profile_id="default",
      group_ids=("g1", "g2"),
      default_matrix_id="fallback",
      known_matrix_ids={"m1", "m2", "fallback"},
    )
  assert conflict.value.code == "compensation_binding_conflict"

  with pytest.raises(CompensationError) as unknown:
    resolve_compensation_binding(
      (_binding("sample", "missing", "sample", "s1"),),
      sample_id="s1",
      execution_profile_id="default",
      group_ids=(),
      default_matrix_id="fallback",
      known_matrix_ids={"fallback"},
    )
  assert unknown.value.code == "unknown_compensation_matrix"


def test_duplicate_binding_scope_target_is_invalid() -> None:
  with pytest.raises(CompensationError) as error:
    resolve_compensation_binding(
      (
        _binding("first", "m1", "sample", "s1"),
        _binding("second", "m1", "sample", "s1"),
      ),
      sample_id="s1",
      execution_profile_id="default",
      group_ids=(),
      default_matrix_id=None,
      known_matrix_ids={"m1"},
    )
  assert error.value.code == "compensation_binding_conflict"


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


def test_inspection_returns_channel_alignment_and_condition_number() -> None:
  spec = _make_spec(
    channels=("FL2-A", "FL1-A"),
    matrix=((1.0, 0.1), (0.2, 1.0)),
  )

  result = inspect_compensation_matrix(
    spec, available_channel_ids=("FSC-A", "FL1-A", "FL2-A")
  )

  assert result.is_valid
  assert result.channel_order == ("FL2-A", "FL1-A")
  assert result.channel_indices == (2, 1)
  assert result.condition_number == pytest.approx(
    np.linalg.cond(np.array(spec.matrix)), rel=1e-15
  )
  assert result.diagnostics == ()


def test_ill_conditioned_matrix_returns_nonfatal_structured_warning() -> None:
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.0), (0.0, 1e-10)),
  )

  result = inspect_compensation_matrix(spec)

  assert result.is_valid
  assert result.condition_number == pytest.approx(1e10)
  assert [diagnostic.code for diagnostic in result.diagnostics] == [
    "compensation_condition_warning"
  ]
  assert result.diagnostics[0].severity == "warning"
  validate_compensation_matrix(spec)


def test_numerically_singular_matrix_is_structured_error() -> None:
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.0), (0.0, 1e-17)),
  )

  result = inspect_compensation_matrix(spec)

  assert not result.is_valid
  assert result.diagnostics[0].code == "invalid_compensation_matrix"
  assert result.diagnostics[0].details["reason"] == "numerically_singular"
  with pytest.raises(CompensationError) as error:
    validate_compensation_matrix(spec)
  assert error.value.code == "invalid_compensation_matrix"


def test_missing_and_duplicate_event_channels_have_stable_diagnostic_codes() -> None:
  spec = _make_spec(
    channels=("FL1-A", "FL2-A"),
    matrix=((1.0, 0.0), (0.0, 1.0)),
  )

  missing = inspect_compensation_matrix(
    spec, available_channel_ids=("FL1-A", "FSC-A")
  )
  duplicate = inspect_compensation_matrix(
    spec, available_channel_ids=("FL1-A", "FL2-A", "FL2-A")
  )

  assert missing.diagnostics[0].code == "missing_compensation_channel"
  assert missing.diagnostics[0].details["missing_channel_ids"] == ["FL2-A"]
  assert duplicate.diagnostics[0].code == "ambiguous_compensation_channel"
  assert duplicate.diagnostics[0].details["duplicate_channel_ids"] == ["FL2-A"]


def test_nonfinite_matrix_has_stable_structured_error() -> None:
  result = inspect_compensation_matrix(
    _make_spec(
      channels=("FL1-A", "FL2-A"),
      matrix=((1.0, float("nan")), (0.0, 1.0)),
    )
  )

  assert not result.is_valid
  assert result.condition_number is None
  assert result.diagnostics[0].code == "invalid_compensation_matrix"
  assert result.diagnostics[0].details["reason"] == "nonfinite_values"


def test_matrix_channel_set_rejects_empty_stable_id() -> None:
  result = inspect_compensation_matrix(
    _make_spec(channels=("",), matrix=((1.0,),))
  )

  assert not result.is_valid
  assert result.diagnostics[0].code == "invalid_compensation_matrix"
  assert result.diagnostics[0].details["reason"] == "invalid_matrix_channels"


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


# ---------------------------------------------------------------------------
# CompensationCalculationSpec model
# ---------------------------------------------------------------------------


def test_calculation_spec_basic() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="FL1-A",
    positive_population_id="pos_FL1",
    negative_population_id="neg_FL1",
  )
  spec = CompensationCalculationSpec(
    id="calc1",
    name="Single-stain calculation",
    controls=(control,),
  )
  assert spec.regression_method == "linear"
  assert spec.outlier_policy == "iqr"
  assert spec.minimum_positive_events == 100
  assert spec.minimum_negative_events == 50


def test_calculation_spec_multiple_detectors() -> None:
  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
    CompensationCalculationControlSpec(
      detector_channel_id="FL2-A",
      positive_population_id="pos_FL2",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc2",
    name="Two-color",
    controls=controls,
    regression_method="median",
    outlier_policy="zscore",
  )
  assert len(spec.controls) == 2
  assert spec.regression_method == "median"
  assert spec.outlier_policy == "zscore"


def test_calculation_spec_rejects_empty_id() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="FL1-A",
    positive_population_id="pos",
    negative_population_id="neg",
  )
  with pytest.raises(ValueError, match="non-empty"):
    CompensationCalculationSpec(id="", name="x", controls=(control,))


def test_calculation_spec_rejects_no_controls() -> None:
  with pytest.raises(ValueError, match="at least one"):
    CompensationCalculationSpec(id="x", name="x", controls=())


def test_calculation_spec_rejects_duplicate_detectors() -> None:
  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos",
      negative_population_id="neg",
    ),
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos2",
      negative_population_id="neg2",
    ),
  )
  with pytest.raises(ValueError, match="unique"):
    CompensationCalculationSpec(id="x", name="x", controls=controls)


def test_calculation_spec_rejects_empty_detector_id() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="",
    positive_population_id="pos",
    negative_population_id="neg",
  )
  with pytest.raises(ValueError, match="detector"):
    CompensationCalculationSpec(id="x", name="x", controls=(control,))


def test_calculation_spec_rejects_empty_population_id() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="FL1-A",
    positive_population_id="",
    negative_population_id="neg",
  )
  with pytest.raises(ValueError, match="positive"):
    CompensationCalculationSpec(id="x", name="x", controls=(control,))


def test_calculation_spec_rejects_invalid_regression_method() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="FL1-A",
    positive_population_id="pos",
    negative_population_id="neg",
  )
  with pytest.raises(ValueError, match="regression"):
    CompensationCalculationSpec(
      id="x", name="x", controls=(control,),
      regression_method="ols",  # type: ignore[arg-type]
    )


def test_calculation_spec_rejects_invalid_outlier_policy() -> None:
  control = CompensationCalculationControlSpec(
    detector_channel_id="FL1-A",
    positive_population_id="pos",
    negative_population_id="neg",
  )
  with pytest.raises(ValueError, match="outlier"):
    CompensationCalculationSpec(
      id="x", name="x", controls=(control,),
      outlier_policy="mad",  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Spillover matrix calculation - synthetic fixtures
# ---------------------------------------------------------------------------


def _make_synthetic_single_stain_events(
  rng: np.random.Generator,
  n_per_stain: int = 1000,
  fl1_median: float = 10000.0,
  fl2_median: float = 8000.0,
  spillover_fl1_to_fl2: float = 0.2,
  spillover_fl2_to_fl1: float = 0.1,
  background: float = 100.0,
) -> tuple[NDArray[np.float64], dict[str, NDArray[np.bool_]]]:
  """Create synthetic single-stain control events for 2 detectors.

  Three populations: FL1-positive, FL2-positive, negative (unlabeled).
  Returns (events, population_masks_dict).
  """
  total = n_per_stain * 3
  events = np.zeros((total, 3), dtype=np.float64)
  events[:, 2] = rng.exponential(1000, total)

  masks: dict[str, NDArray[np.bool_]] = {}

  # FL1-positive single-stain control.
  idx = 0
  fl1_pos_mask = np.zeros(total, dtype=np.bool_)
  fl1_pos_mask[idx:idx+n_per_stain] = True
  masks["pos_FL1"] = fl1_pos_mask
  events[idx:idx+n_per_stain, 0] = rng.normal(fl1_median, fl1_median*0.05, n_per_stain)
  events[idx:idx+n_per_stain, 1] = rng.normal(
    background + spillover_fl1_to_fl2 * fl1_median, background * 0.2, n_per_stain,
  )
  idx += n_per_stain

  # FL2-positive single-stain control.
  fl2_pos_mask = np.zeros(total, dtype=np.bool_)
  fl2_pos_mask[idx:idx+n_per_stain] = True
  masks["pos_FL2"] = fl2_pos_mask
  events[idx:idx+n_per_stain, 0] = rng.normal(
    background + spillover_fl2_to_fl1 * fl2_median, background * 0.2, n_per_stain,
  )
  events[idx:idx+n_per_stain, 1] = rng.normal(fl2_median, fl2_median*0.05, n_per_stain)
  idx += n_per_stain

  # Negative (unlabeled) control.
  neg_mask = np.zeros(total, dtype=np.bool_)
  neg_mask[idx:idx+n_per_stain] = True
  masks["neg"] = neg_mask
  events[idx:idx+n_per_stain, 0] = rng.normal(background, background*0.1, n_per_stain)
  events[idx:idx+n_per_stain, 1] = rng.normal(background, background*0.1, n_per_stain)

  return events, masks


def _make_synthetic_2color_events(
  rng: np.random.Generator,
  n_events: int = 2000,
  positive_fraction: float = 0.5,
  fl1_median: float = 10000.0,
  spillover_fl1_to_fl2: float = 0.2,
  background: float = 100.0,
) -> tuple[NDArray[np.float64], NDArray[np.bool_], NDArray[np.bool_]]:
  """Create synthetic 2-color events with known spillover.

  Returns (events, positive_mask, negative_mask).
  """
  pos_count = int(n_events * positive_fraction)
  neg_count = n_events - pos_count

  neg_fl1 = rng.normal(background, background * 0.1, neg_count)
  neg_fl2 = rng.normal(background, background * 0.1, neg_count)

  pos_fl1 = rng.normal(fl1_median, fl1_median * 0.05, pos_count)
  pos_fl2 = rng.normal(
    background + spillover_fl1_to_fl2 * fl1_median,
    background * 0.2,
    pos_count,
  )

  events = np.zeros((n_events, 3), dtype=np.float64)
  events[:, 2] = rng.exponential(1000, n_events)

  pos_mask = np.zeros(n_events, dtype=np.bool_)
  neg_mask = np.zeros(n_events, dtype=np.bool_)

  events[:pos_count, 0] = pos_fl1
  events[:pos_count, 1] = pos_fl2
  pos_mask[:pos_count] = True

  events[pos_count:, 0] = neg_fl1
  events[pos_count:, 1] = neg_fl2
  neg_mask[pos_count:] = True

  return events, pos_mask, neg_mask


def test_calculate_spillover_matrix_produces_invertible_matrix() -> None:
  rng = np.random.default_rng(123)
  events, masks = _make_synthetic_single_stain_events(
    rng,
    spillover_fl1_to_fl2=0.15,
    spillover_fl2_to_fl1=0.1,
  )
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
    CompensationCalculationControlSpec(
      detector_channel_id="FL2-A",
      positive_population_id="pos_FL2",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_inv",
    name="Invertibility test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(spec, events, channels, masks)

  matrix = np.array(result.matrix_spec.matrix)
  assert matrix[0, 0] == pytest.approx(1.0)
  assert matrix[1, 1] == pytest.approx(1.0)
  assert result.condition_number < COMPENSATION_CONDITION_WARNING_THRESHOLD


def test_calculate_spillover_matrix_captures_spillover() -> None:
  rng = np.random.default_rng(456)
  events, masks = _make_synthetic_single_stain_events(
    rng,
    spillover_fl1_to_fl2=0.2,
    spillover_fl2_to_fl1=0.0,
  )
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
    CompensationCalculationControlSpec(
      detector_channel_id="FL2-A",
      positive_population_id="pos_FL2",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_spill",
    name="Spillover capture test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(spec, events, channels, masks)

  matrix = np.array(result.matrix_spec.matrix)
  # Rows are receiving detectors and columns are single-stain sources, matching
  # apply_compensation's inverse @ event-column-vector convention.
  assert matrix[1, 0] > 0.1  # FL1 source spills into FL2 detector.
  assert matrix[0, 1] < 0.05  # FL2 source barely spills into FL1 detector.


def test_calculated_matrix_removes_known_asymmetric_single_stain_spillover() -> None:
  events = np.array([
    [1000.0, 200.0], [1000.0, 200.0],
    [100.0, 1000.0], [100.0, 1000.0],
    [0.0, 0.0], [0.0, 0.0],
  ])
  masks = {
    "pos_a": np.array([True, True, False, False, False, False]),
    "pos_b": np.array([False, False, True, True, False, False]),
    "neg": np.array([False, False, False, False, True, True]),
  }
  spec = CompensationCalculationSpec(
    id="asymmetric",
    name="Asymmetric",
    controls=(
      CompensationCalculationControlSpec("A", "pos_a", "neg"),
      CompensationCalculationControlSpec("B", "pos_b", "neg"),
    ),
    outlier_policy="none",
    minimum_positive_events=2,
    minimum_negative_events=2,
  )
  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(spec, events, ("A", "B"), masks)

  compensated = apply_compensation(
    result.matrix_spec, np.array([[1000.0, 200.0]]), ("A", "B")
  )
  np.testing.assert_allclose(compensated, [[1000.0, 0.0]], atol=1e-10)


def test_calculate_spillover_matrix_uses_each_control_sample_and_channel_ids() -> None:
  """Separate single-stain files may use different visible channel orders."""
  sample_a = np.array([
    [1000.0, 200.0], [1000.0, 200.0], [0.0, 0.0], [0.0, 0.0],
  ])
  # This sample is stored as B, A rather than A, B.
  sample_b = np.array([
    [1000.0, 100.0], [1000.0, 100.0], [0.0, 0.0], [0.0, 0.0],
  ])
  masks = {
    "control-a": {
      "positive": np.array([True, True, False, False]),
      "negative": np.array([False, False, True, True]),
    },
    "control-b": {
      "positive": np.array([True, True, False, False]),
      "negative": np.array([False, False, True, True]),
    },
  }
  spec = CompensationCalculationSpec(
    id="multi-sample",
    name="Two control samples",
    controls=(
      CompensationCalculationControlSpec("A", "positive", "negative", "control-a"),
      CompensationCalculationControlSpec("B", "positive", "negative", "control-b"),
    ),
    outlier_policy="none",
    minimum_positive_events=2,
    minimum_negative_events=2,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(
    spec,
    {"control-a": sample_a, "control-b": sample_b},
    {"control-a": ("A", "B"), "control-b": ("B", "A")},
    masks,
  )

  np.testing.assert_allclose(
    result.matrix_spec.matrix, ((1.0, 0.1), (0.2, 1.0)), atol=1e-10
  )
  assert result.matrix_spec.provenance.control_sample_ids == (
    "control-a", "control-b"
  )


def test_calculate_spillover_matrix_missing_population_raises() -> None:
  rng = np.random.default_rng(789)
  events, masks = _make_synthetic_single_stain_events(rng)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="missing",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_miss",
    name="Missing pop test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  with pytest.raises(CompensationError, match="population"):
    calculate_spillover_matrix(spec, events, channels, masks)


def test_calculate_spillover_matrix_missing_channel_raises() -> None:
  rng = np.random.default_rng(790)
  events, masks = _make_synthetic_single_stain_events(rng)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL99-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_miss_ch",
    name="Missing channel test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  with pytest.raises(CompensationError, match="channel"):
    calculate_spillover_matrix(spec, events, channels, masks)


def test_calculate_spillover_matrix_source_is_calculated() -> None:
  rng = np.random.default_rng(999)
  events, masks = _make_synthetic_single_stain_events(rng)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_src",
    name="Source test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(spec, events, channels, masks)
  assert result.matrix_spec.source == "calculated"
  assert result.matrix_spec.provenance.algorithm == (
    "traditional_linear_background_subtracted"
  )


def test_calculate_spillover_matrix_diagnostics_populated() -> None:
  rng = np.random.default_rng(111)
  events, masks = _make_synthetic_single_stain_events(rng, n_per_stain=500)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
    CompensationCalculationControlSpec(
      detector_channel_id="FL2-A",
      positive_population_id="pos_FL2",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_diag",
    name="Diagnostics test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  result = calculate_spillover_matrix(spec, events, channels, masks)

  assert len(result.channel_diagnostics) == 2
  for diag in result.channel_diagnostics:
    assert diag.positive_event_count > 0
    assert diag.negative_event_count > 0
    assert diag.median_positive > 0
    assert diag.median_negative > 0


def test_calculate_spillover_matrix_low_events_is_rejected() -> None:
  rng = np.random.default_rng(222)
  events, masks = _make_synthetic_single_stain_events(rng, n_per_stain=10)
  channels = ["FL1-A", "FL2-A", "FSC-A"]

  controls = (
    CompensationCalculationControlSpec(
      detector_channel_id="FL1-A",
      positive_population_id="pos_FL1",
      negative_population_id="neg",
    ),
  )
  spec = CompensationCalculationSpec(
    id="calc_warn",
    name="Low events test",
    controls=controls,
  )

  from flowdesk_core.compensation import calculate_spillover_matrix
  with pytest.raises(CompensationError) as error:
    calculate_spillover_matrix(spec, events, channels, masks)
  assert error.value.code == "calculation_insufficient_positive_events"


def test_independent_numeric_verification_3color_known_matrix() -> None:
  """Verify calculation against a hand-computed 3-color spillover matrix.

  Known spillover matrix S (rows=receiving, columns=source):
    A   B   C
  A 1.0 0.0 0.05
  B 0.15 1.0 0.0
  C 0.0  0.2 1.0

  Create synthetic single-stain controls where each positive population
  has exactly the signal predicted by the known matrix, and the negative
  population has zero signal. The calculation should recover S exactly.
  """
  n = 10  # events per population
  total = n * 4  # 3 positive + 1 negative

  # Negative: all zero.
  neg_a = np.zeros((n, 3))
  neg_b = np.zeros((n, 3))
  neg_c = np.zeros((n, 3))
  neg = np.zeros((n, 3))

  # Positive A: A=1000, B=0.15*1000=150, C=0.
  pos_a = np.full((n, 3), [1000.0, 150.0, 0.0])

  # Positive B: A=0, B=1000, C=0.2*1000=200.
  pos_b = np.full((n, 3), [0.0, 1000.0, 200.0])

  # Positive C: A=0.05*1000=50, B=0, C=1000.
  pos_c = np.full((n, 3), [50.0, 0.0, 1000.0])

  events = np.vstack([pos_a, pos_b, pos_c, neg])

  masks = {
    "pos_A": np.array(
      [True]*n + [False]*(total - n), dtype=np.bool_
    ),
    "pos_B": np.array(
      [False]*n + [True]*n + [False]*(total - 2*n), dtype=np.bool_
    ),
    "pos_C": np.array(
      [False]*(2*n) + [True]*n + [False]*n, dtype=np.bool_
    ),
    "neg": np.array(
      [False]*(3*n) + [True]*n, dtype=np.bool_
    ),
  }

  controls = (
    CompensationCalculationControlSpec("A", "pos_A", "neg"),
    CompensationCalculationControlSpec("B", "pos_B", "neg"),
    CompensationCalculationControlSpec("C", "pos_C", "neg"),
  )
  spec = CompensationCalculationSpec(
    id="numeric_verify",
    name="3-color numeric verification",
    controls=controls,
    outlier_policy="none",
    minimum_positive_events=2,
    minimum_negative_events=2,
  )

  result = calculate_spillover_matrix(spec, events, ("A", "B", "C"), masks)

  expected = np.array([
    [1.0, 0.0, 0.05],
    [0.15, 1.0, 0.0],
    [0.0, 0.2, 1.0],
  ])
  np.testing.assert_allclose(
    result.matrix_spec.matrix, expected, atol=1e-10
  )

  # Verify that applying the calculated matrix correctly compensates.
  raw = np.array([[1000.0, 150.0, 200.0]])  # Mixed signal
  compensated = apply_compensation(result.matrix_spec, raw, ("A", "B", "C"))

  # Independent calculation: inverse of S @ [1000, 150, 200]^T
  inv_s = np.linalg.inv(expected)
  expected_comp = (inv_s @ raw.T).T
  np.testing.assert_allclose(compensated, expected_comp, atol=1e-10)


def test_median_method_independent_verification() -> None:
  """Verify the median regression method against hand-computed values.

  With median method and no outliers:
  spillover[i] = median(cleaned[:, i]) / median(cleaned[:, reference])
  """
  # Positive A: A=1000, B=300 (30% spill)
  # Negative: A=0, B=0
  n = 6
  total = n * 3
  events = np.zeros((total, 2))
  events[:n, 0] = 1000.0
  events[:n, 1] = 300.0
  events[n:2*n, 0] = 0.0
  events[n:2*n, 1] = 0.0
  # Positive B: A=0, B=1000
  events[2*n:, 1] = 1000.0

  masks = {
    "pos_A": np.array([True]*n + [False]*(total - n), dtype=np.bool_),
    "pos_B": np.array([False]*(2*n) + [True]*n, dtype=np.bool_),
    "neg": np.array([False]*(total), dtype=np.bool_),
  }
  # Use a subset of events as negative (first n of pos_A have zero in col 1).
  # Actually, let's just use all-zero negative.
  masks["neg"] = np.array(
    [True]*n + [False]*(total - n), dtype=np.bool_
  )
  # Override: negative is the B-positive events which have A=0, B=1000
  # This is wrong. Let's create proper negative.
  # Redesign: events = [pos_A, neg, pos_B]
  events = np.zeros((total, 2))
  events[:n, 0] = 1000.0
  events[:n, 1] = 300.0
  # neg: all zero
  events[n:2*n] = 0.0
  # pos_B: B=1000, A=0
  events[2*n:, 1] = 1000.0

  masks["pos_A"] = np.array([True]*n + [False]*(total - n), dtype=np.bool_)
  masks["neg"] = np.array(
    [False]*n + [True]*n + [False]*n, dtype=np.bool_
  )
  masks["pos_B"] = np.array(
    [False]*(2*n) + [True]*n, dtype=np.bool_
  )

  controls = (
    CompensationCalculationControlSpec("A", "pos_A", "neg"),
    CompensationCalculationControlSpec("B", "pos_B", "neg"),
  )
  spec = CompensationCalculationSpec(
    id="median_verify",
    name="Median method verification",
    controls=controls,
    regression_method="median",
    outlier_policy="none",
    minimum_positive_events=2,
    minimum_negative_events=2,
  )

  result = calculate_spillover_matrix(spec, events, ("A", "B"), masks)

  # median of pos_A after neg subtraction = [1000, 300]
  # reference = median of col A = 1000
  # coefficients for source A = [1000/1000, 300/1000] = [1.0, 0.3]
  # median of pos_B after neg subtraction = [0, 1000]
  # reference = median of col B = 1000
  # coefficients for source B = [0/1000, 1000/1000] = [0.0, 1.0]
  # Matrix convention: rows=receiving, columns=source.
  # column 0 (source A): [1.0, 0.3], column 1 (source B): [0.0, 1.0]
  expected = np.array([
    [1.0, 0.0],
    [0.3, 1.0],
  ])
  np.testing.assert_allclose(
    result.matrix_spec.matrix, expected, atol=1e-10
  )


def test_calculation_provenance_records_controls_and_algorithm() -> None:
  """Verify that calculation provenance captures all control references."""
  events = np.array([
    [1000.0, 200.0], [1000.0, 200.0],
    [0.0, 0.0], [0.0, 0.0],
  ])
  masks = {
    "pos": np.array([True, True, False, False]),
    "neg": np.array([False, False, True, True]),
  }
  spec = CompensationCalculationSpec(
    id="prov_test",
    name="Provenance test",
    controls=(
      CompensationCalculationControlSpec(
        "A", "pos", "neg", sample_id="ctrl-1",
      ),
    ),
    regression_method="median",
    outlier_policy="zscore",
    minimum_positive_events=2,
    minimum_negative_events=2,
  )

  result = calculate_spillover_matrix(
    spec,
    {"ctrl-1": events},
    {"ctrl-1": ("A", "B")},
    {"ctrl-1": masks},
  )

  prov = result.matrix_spec.provenance
  assert "ctrl-1" in prov.control_sample_ids
  assert "ctrl-1:pos" in prov.control_population_ids
  assert "ctrl-1:neg" in prov.control_population_ids
  assert prov.algorithm == "traditional_median_background_subtracted"
  assert prov.algorithm_version is not None


def test_calculated_matrix_is_immutable_and_edits_require_duplicate() -> None:
  """A calculated matrix has source='calculated' and manual edits require
  derived_from_matrix_id."""
  events = np.array([
    [1000.0, 200.0], [1000.0, 200.0],
    [0.0, 0.0], [0.0, 0.0],
  ])
  masks = {
    "pos": np.array([True, True, False, False]),
    "neg": np.array([False, False, True, True]),
  }
  spec = CompensationCalculationSpec(
    id="immut_test",
    name="Immutability test",
    controls=(
      CompensationCalculationControlSpec("A", "pos", "neg"),
    ),
    minimum_positive_events=2,
    minimum_negative_events=2,
  )

  result = calculate_spillover_matrix(spec, events, ("A", "B"), masks)
  assert result.matrix_spec.source == "calculated"

  # Attempting to create provenance with manual edits but no
  # derived_from_matrix_id must fail.
  edit = CompensationManualEditSpec(
    row_channel_id="A",
    column_channel_id="B",
    old_value=0.2,
    new_value=0.25,
  )
  with pytest.raises(ValueError, match="derived_from_matrix_id"):
    CompensationProvenanceSpec(manual_edits=(edit,))

  # Creating provenance with derived_from_matrix_id succeeds.
  prov = CompensationProvenanceSpec(
    derived_from_matrix_id=result.matrix_spec.id,
    manual_edits=(edit,),
  )
  assert prov.derived_from_matrix_id == result.matrix_spec.id


def test_duplicate_of_calculated_matrix_becomes_editable_user_defined_copy() -> None:
  """A derivative of a calculated result must not retain calculated source."""
  original = CompensationMatrixSpec(
    id="calculated-original",
    name="Calculated original",
    source="calculated",
    channels=("A",),
    matrix=((1.0,),),
  )

  from flowdesk_core.compensation import duplicate_compensation_matrix

  duplicate = duplicate_compensation_matrix(
    original,
    matrix_id="calculated-original-edit",
    name="Calculated original (edit copy)",
  )

  assert duplicate.source == "user_defined"
  assert duplicate.provenance.derived_from_matrix_id == original.id
  assert duplicate.provenance.manual_edits == ()
