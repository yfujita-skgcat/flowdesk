from __future__ import annotations

from flowdesk_core.project_commands import (
  EditOverlaySourcesCommand,
  EditPlotPresentationCommand,
  UndoStack,
)


def _source(source_id: str, order: int) -> dict[str, object]:
  return {
    "source_id": source_id,
    "sample_id": "s1",
    "population_id": "all_events",
    "display_name": source_id,
    "x_parameter_id": "x",
    "order": order,
    "visible": True,
  }


def test_overlay_source_command_is_definition_only_and_reversible() -> None:
  state = {
    "plot_views": [{"id": "view", "overlay_sources": [_source("old", 0)]}],
    "gating_strategies_data": {"strategy": {"gates": [{"id": "gate"}]}},
    "population_membership": [{"sample_id": "s1", "population_id": "gate"}],
    "statistics": [{"id": "stat", "population_id": "gate"}],
  }
  stack = UndoStack(state)
  updated = stack.execute(
    EditOverlaySourcesCommand("view", [_source("new", 0), _source("second", 1)])
  )

  assert [source["source_id"] for source in updated["plot_views"][0]["overlay_sources"]] == [
    "new", "second"
  ]
  assert updated["gating_strategies_data"] == state["gating_strategies_data"]
  assert updated["population_membership"] == state["population_membership"]
  assert updated["statistics"] == state["statistics"]
  assert stack.undo()["plot_views"][0]["overlay_sources"][0]["source_id"] == "old"
  assert stack.redo()["plot_views"][0]["overlay_sources"][1]["source_id"] == "second"


def test_plot_presentation_command_is_definition_only_and_reversible() -> None:
  state = {"plot_views": [{"id": "view", "presentation": {"title": "old"}}]}
  stack = UndoStack(state)
  updated = stack.execute(EditPlotPresentationCommand("view", {"title": "new"}))
  assert updated["plot_views"][0]["presentation"] == {"title": "new"}
  assert stack.undo()["plot_views"][0]["presentation"] == {"title": "old"}
  assert stack.redo()["plot_views"][0]["presentation"] == {"title": "new"}
