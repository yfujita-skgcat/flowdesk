import numpy as np
import pytest

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import BackgatingSpec, OverlaySpec, PopulationMembership
from flowdesk_core.overlays import prepare_backgating, prepare_overlay_1d, prepare_overlay_2d


def _report() -> ExecutionReport:
  return ExecutionReport(
    project_id="p", execution_profile_id="e", pipeline_version="1", status="success",
    population_membership=(
      PopulationMembership("s1", "all_events", np.array([True, True, True, True])),
      PopulationMembership("s1", "target", np.array([False, True, True, False])),
      PopulationMembership("s1", "ancestor", np.array([True, True, True, False])),
    ),
  )


def test_overlay_normalizations_use_report_membership_only() -> None:
  events = np.array([[1.0], [2.0], [2.0], [np.nan]])
  for normalization in ("count", "mode", "unit_area"):
    layers = prepare_overlay_1d(
      OverlaySpec("o", ("target",), "X", normalization=normalization, bins=2),
      events, ["X"], _report(), "s1",
    )
    assert layers[0].finite_event_count == 2
    assert np.all(np.isfinite(layers[0].values))


def test_backgating_target_is_checked_against_ancestor() -> None:
  layers = prepare_backgating(BackgatingSpec("b", "target", ("ancestor",)), _report(), "s1")
  assert [layer.population_id for layer in layers] == ["target", "ancestor"]
  assert np.array_equal(layers[0].mask, [False, True, True, False])


def test_backgating_rejects_non_subset_target() -> None:
  report = ExecutionReport(
    project_id="p", execution_profile_id="e", pipeline_version="1", status="success",
    population_membership=(
      PopulationMembership("s1", "target", np.array([True, False])),
      PopulationMembership("s1", "ancestor", np.array([False, True])),
    ),
  )
  with pytest.raises(ValueError, match="not a subset"):
    prepare_backgating(BackgatingSpec("b", "target", ("ancestor",)), report, "s1")


def test_overlay_2d_keeps_population_style_order() -> None:
  events = np.arange(8.0).reshape(4, 2)
  layers = prepare_overlay_2d(
    ("ancestor", "target"), events, 0, 1, _report(), "s1",
    {"ancestor": {"color": "blue", "alpha": 0.2}, "target": {"color": "red", "alpha": 1.0}},
  )
  assert [layer.population_id for layer in layers] == ["ancestor", "target"]
  assert layers[1].style["color"] == "red"
