"""Tests for compensation matrix validation and application."""

from __future__ import annotations

import numpy as np
import pytest

from flowdesk_core.compensation import (
  CompensationError,
  apply_compensation,
  inspect_compensation_matrix,
  resolve_compensation_binding,
  validate_compensation_matrix,
)
from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import (
  CompensationBindingSpec,
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
