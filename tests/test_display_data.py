import numpy as np
import pytest

from flowdesk_core.display_data import prepare_display_data
from flowdesk_core.models import PlotViewRegistry, PlotViewSpec


def test_density_uses_finite_full_population_and_resolution_is_display_only() -> None:
  events = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [np.nan, 4.0], [3.0, np.inf]])
  view = PlotViewSpec(id="v", x_parameter="X", y_parameter="Y", plot_type="density",
                      aggregation={"bins": (2, 2)}, rendering_downsample={"max_points": 1})
  result = prepare_display_data(view, events, ["X", "Y"])
  assert int(result.values.sum()) == 3
  assert result.diagnostics[0]["finite_event_count"] == 4


@pytest.mark.parametrize("plot_type", ["histogram", "cdf"])
def test_1d_views_handle_empty_and_nonfinite(plot_type: str) -> None:
  view = PlotViewSpec(id="v", x_parameter="X", plot_type=plot_type)
  result = prepare_display_data(view, np.array([[np.nan], [np.inf]]), ["X"])
  assert result.x.size == (64 if plot_type == "histogram" else 0)
  assert result.diagnostics[0]["finite_event_count"] == 0


def test_invalid_population_membership_is_explicit() -> None:
  view = PlotViewSpec(id="v", population_id="p", x_parameter="X", y_parameter="Y")
  with pytest.raises(ValueError, match="membership is missing"):
    prepare_display_data(view, np.zeros((2, 2)), ["X", "Y"], sample_id="s1")


def test_plot_view_registry_duplicates_and_links_sample_navigation() -> None:
  view = PlotViewSpec(id="v", x_parameter="X", y_parameter="Y")
  registry = PlotViewRegistry((view,))
  duplicate = registry.duplicate("v", "v-copy")
  assert [item.id for item in duplicate.views] == ["v", "v-copy"]
  assert duplicate.active_view_id == "v-copy"
  assert duplicate.linked_sample_navigation is True
