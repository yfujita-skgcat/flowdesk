"""Gate-name validation tests across core commands and storage."""

from __future__ import annotations

import pytest

from flowdesk_core.models import GateSpec, validate_gate_name
from flowdesk_core.project_commands import (
  CopySubtreeCommand,
  CreateGateCommand,
  DuplicateGateCommand,
  EditGateCommand,
  ProjectCommandError,
  RenameGateCommand,
)
from flowdesk_storage.manifest import ManifestValidationError, validate_manifest


def _gate(name: str) -> GateSpec:
  return GateSpec("gate-1", name, "range", "all_events", x_parameter="FSC-A")


@pytest.mark.parametrize("name", ["Live", "GFP+", "CD4／CD8"])
def test_valid_gate_names(name: str) -> None:
  assert validate_gate_name(name) == name
  assert _gate(name).name == name


@pytest.mark.parametrize("name", ["Live/CD45", "/Live", "Live/", "/", "", "  "])
def test_invalid_gate_names(name: str) -> None:
  with pytest.raises(ValueError, match="gate name|Gate name"):
    _gate(name)


def _state() -> dict:
  return {"gating_strategies_data": {"strategy": {
    "id": "strategy", "name": "Strategy", "gates": [
      {
        "id": "gate-1", "name": "Live", "gate_type": "range",
        "parent_population_id": "all_events", "x_parameter": "FSC-A",
      },
    ],
  }}}


@pytest.mark.parametrize("command_factory", [
  lambda: CreateGateCommand("strategy", {
    "id": "gate-2", "name": "Live/CD45", "gate_type": "range",
  }),
  lambda: EditGateCommand("strategy", "gate-1", {"name": "Live/CD45"}),
  lambda: RenameGateCommand("strategy", "gate-1", "Live/CD45"),
  lambda: DuplicateGateCommand("strategy", "gate-1", "gate-2", name="Live/CD45"),
])
def test_commands_reject_slash_names(command_factory) -> None:
  with pytest.raises((ProjectCommandError, ValueError), match="reserved|gate name"):
    command_factory()


def test_copy_subtree_validates_copied_gate_name() -> None:
  state = _state()
  state["gating_strategies_data"]["strategy"]["gates"][0]["name"] = "Live/CD45"
  command = CopySubtreeCommand("strategy", "gate-1", {"gate-1": "gate-2"})
  with pytest.raises(ProjectCommandError, match="reserved|gate name"):
    command.apply(state)


def test_manifest_reports_strategy_gate_and_name() -> None:
  manifest = {
    "project_id": "p", "project_version": "1.0.0",
    "pipeline_version": "0.1", "samples": [],
    "gating_strategies_data": {"strategy": {
      "gates": [{"id": "live-gate", "name": "Live/CD45"}],
    }},
  }
  with pytest.raises(ManifestValidationError, match="strategy.*live-gate.*Live/CD45"):
    validate_manifest(manifest)
