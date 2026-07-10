"""Phase 1 tests: Population display names and column headers.

Verifies that:
- Population column displays gate names instead of IDs.
- Qt.UserRole retains the internal population ID.
- Root population displays as "All Events".
- Column headers are "% of Parent" and "% of Total".
- Parent column also uses display names.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from flowdesk_core.execution_report import ExecutionReport
from flowdesk_core.models import PopulationResult
from flowdesk_qt.population_tree import PopulationTree

pytestmark = pytest.mark.gui


def _make_report(
    pop_ids: list[str],
    event_counts: list[int],
    sample_id: str = "sample_1",
) -> ExecutionReport:
  results = tuple(
    PopulationResult(
      sample_id=sample_id,
      population_id=pid,
      event_count=ec,
      frequency_of_parent=ec / event_counts[0] if ec else 0.0,
      frequency_of_total=ec / event_counts[0] if ec else 0.0,
    )
    for pid, ec in zip(pop_ids, event_counts, strict=True)
  )
  return ExecutionReport(
    project_id="test_project",
    execution_profile_id="default",
    pipeline_version="0.1",
    status="success",
    population_results=results,
  )


def test_population_displays_gate_name(qapp) -> None:
  """Gate id ``gate_ab12`` with name ``CD45 positive`` should display the name."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  pop_item = tree._table.item(1, 0)
  assert pop_item is not None
  assert "CD45 positive" in pop_item.text()


def test_user_role_retains_population_id(qapp) -> None:
  """Qt.UserRole must hold the internal population ID, not the display name."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  pop_item = tree._table.item(1, 0)
  assert pop_item is not None
  assert pop_item.data(Qt.UserRole) == "gate_ab12"


def test_root_displays_all_events(qapp) -> None:
  """Root population must display as 'All Events'."""
  tree = PopulationTree()
  report = _make_report(["all_events"], [100])
  tree.set_population_parents({"all_events": None})
  tree.set_population_names({"all_events": "All Events"})
  tree.set_report(report)

  pop_item = tree._table.item(0, 0)
  assert pop_item is not None
  assert "All Events" in pop_item.text()
  assert pop_item.data(Qt.UserRole) == "all_events"


def test_parent_column_uses_display_name(qapp) -> None:
  """Parent column should also show display names, not IDs."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  parent_item = tree._table.item(1, 1)
  assert parent_item is not None
  assert "All Events" in parent_item.text()
  assert parent_item.data(Qt.UserRole) == "all_events"


def test_column_headers_are_percent_labels(qapp) -> None:
  """Headers must be '% of Parent' and '% of Total'."""
  tree = PopulationTree()
  headers = [
    tree._table.horizontalHeaderItem(col).text()
    for col in range(tree._table.columnCount())
  ]
  assert headers == [
    "Population",
    "Parent",
    "Sample",
    "Events",
    "% of Parent",
    "% of Total",
  ]


def test_frequency_values_unchanged(qapp) -> None:
  """Cell values for frequency columns must remain 0-1 fractions."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  # Row 1 (gate_ab12): freq = 30/100 = 0.3
  freq_parent_item = tree._table.item(1, 4)
  freq_total_item = tree._table.item(1, 5)
  assert freq_parent_item is not None
  assert freq_total_item is not None
  assert freq_parent_item.text() == "0.3000"
  assert freq_total_item.text() == "0.3000"


def test_parent_child_indent_maintained(qapp) -> None:
  """Indentation for parent-child hierarchy must be preserved."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12", "gate_child"], [100, 30, 10])
  tree.set_population_parents(
    {"all_events": None, "gate_ab12": "all_events", "gate_child": "gate_ab12"}
  )
  tree.set_population_names(
    {
      "all_events": "All Events",
      "gate_ab12": "CD45 positive",
      "gate_child": "CD4 T cells",
    }
  )
  tree.set_report(report)

  # Row 0: all_events (depth 0, no indent)
  item0 = tree._table.item(0, 0)
  assert item0 is not None
  assert item0.text().startswith("All Events")
  assert "  " not in item0.text().split("All Events")[0]

  # Row 1: gate_ab12 (depth 1, has indent)
  item1 = tree._table.item(1, 0)
  assert item1 is not None
  assert "CD45 positive" in item1.text()

  # Row 2: gate_child (depth 2, more indent than row 1)
  item2 = tree._table.item(2, 0)
  assert item2 is not None
  assert "CD4 T cells" in item2.text()
  # The child should have more leading whitespace than the parent gate
  text1 = item1.text()
  text2 = item2.text()
  leading1 = len(text1) - len(text1.lstrip())
  leading2 = len(text2) - len(text2.lstrip())
  assert leading2 > leading1


def test_rename_updates_display_but_id_stays(qapp) -> None:
  """After renaming a gate, the display updates but the UserRole ID is unchanged."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})

  # Initial names
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  item = tree._table.item(1, 0)
  assert item is not None
  assert "CD45 positive" in item.text()
  assert item.data(Qt.UserRole) == "gate_ab12"

  # Rename gate
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 Bright"})
  tree.set_report(report)

  item = tree._table.item(1, 0)
  assert item is not None
  assert "CD45 Bright" in item.text()
  assert item.data(Qt.UserRole) == "gate_ab12"


def test_get_selected_population_id(qapp) -> None:
  """get_selected_population_id returns the ID from UserRole, not display name."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_ab12"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_ab12": "all_events"})
  tree.set_population_names({"all_events": "All Events", "gate_ab12": "CD45 positive"})
  tree.set_report(report)

  # No selection
  assert tree.get_selected_population_id() is None

  # Select row 1
  tree._table.selectRow(1)
  assert tree.get_selected_population_id() == "gate_ab12"

  # Select row 0
  tree._table.selectRow(0)
  assert tree.get_selected_population_id() == "all_events"


def test_clear_resets_names(qapp) -> None:
  """clear() should reset population names."""
  tree = PopulationTree()
  tree.set_population_names({"all_events": "All Events", "g1": "Gate 1"})
  assert tree._population_names == {"all_events": "All Events", "g1": "Gate 1"}
  tree.clear()
  assert tree._population_names == {}


def test_fallback_to_id_when_name_missing(qapp) -> None:
  """If a population ID has no name mapping, display the raw ID."""
  tree = PopulationTree()
  report = _make_report(["all_events", "gate_unknown"], [100, 30])
  tree.set_population_parents({"all_events": None, "gate_unknown": "all_events"})
  # Only map all_events, not gate_unknown
  tree.set_population_names({"all_events": "All Events"})
  tree.set_report(report)

  item = tree._table.item(1, 0)
  assert item is not None
  assert "gate_unknown" in item.text()
  assert item.data(Qt.UserRole) == "gate_unknown"
