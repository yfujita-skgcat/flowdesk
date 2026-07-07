"""Tests for project storage: loading, validation, saving, and round-trip."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_storage.manifest import (
  ManifestValidationError,
  load_manifest,
  validate_manifest,
)
from flowdesk_storage.project import (
  load_gating_strategy,
  load_project,
  resolve_sample_paths,
  save_project,
)

EXAMPLE_PROJECT = Path(__file__).parent.parent / "examples" / "example_project.flowdesk"

MINIMAL_MANIFEST: dict[str, Any] = {
  "project_id": "test_proj",
  "project_version": "0.1",
  "pipeline_version": "0.1",
  "samples": [],
}

MINIMAL_MANIFEST_WITH_PROFILE: dict[str, Any] = {
  "project_id": "test_proj",
  "project_version": "0.1",
  "pipeline_version": "0.1",
  "samples": [],
  "execution_profiles": [
    {
      "id": "default",
      "name": "Default analysis",
      "gating_strategy_id": "default_gating",
      "sample_selector": "all",
    }
  ],
  "derived_parameters": [
    {
      "id": "fl1_over_fl2",
      "name": "FL1_over_FL2",
      "expression": "FL1-A / FL2-A",
      "source_stage": "compensated",
      "input_parameters": ["FL1-A", "FL2-A"],
    }
  ],
}


# -- Manifest validation --


class TestValidateManifest:
  def test_valid_manifest_passes(self) -> None:
    validate_manifest(MINIMAL_MANIFEST)

  def test_missing_project_id_raises(self) -> None:
    data = dict(MINIMAL_MANIFEST)
    del data["project_id"]
    with pytest.raises(ManifestValidationError, match="missing required"):
      validate_manifest(data)

  def test_missing_all_required_fields_raises(self) -> None:
    with pytest.raises(ManifestValidationError, match="missing required"):
      validate_manifest({})

  def test_non_dict_raises(self) -> None:
    with pytest.raises(ManifestValidationError, match="must be a JSON object"):
      validate_manifest([])  # type: ignore[arg-type]

  def test_non_string_project_id_raises(self) -> None:
    data = dict(MINIMAL_MANIFEST)
    data["project_id"] = 123
    with pytest.raises(ManifestValidationError, match="project_id must be a string"):
      validate_manifest(data)

  def test_unknown_fields_are_preserved(self) -> None:
    data = dict(MINIMAL_MANIFEST)
    data["custom_field"] = "kept"
    validate_manifest(data)
    assert data["custom_field"] == "kept"


# -- Load manifest --


class TestLoadManifest:
  def test_load_example_project(self) -> None:
    data = load_manifest(str(EXAMPLE_PROJECT))
    assert data["project_id"] == "example_project"

  def test_missing_manifest_json_raises(self, tmp_path: Path) -> None:
    with pytest.raises(ManifestValidationError, match="manifest.json not found"):
      load_manifest(str(tmp_path))

  def test_invalid_json_raises(self, tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="invalid JSON"):
      load_manifest(str(tmp_path))

  def test_valid_json_missing_fields_raises(self, tmp_path: Path) -> None:
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"foo": "bar"}', encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="missing required"):
      load_manifest(str(tmp_path))


# -- Load project (alias) --


class TestLoadProject:
  def test_load_project_returns_manifest(self) -> None:
    manifest = load_project(str(EXAMPLE_PROJECT))
    assert "project_id" in manifest
    assert manifest["project_id"] == "example_project"


# -- Save project --


class TestSaveProject:
  def test_save_and_reload(self, tmp_path: Path) -> None:
    bundle = tmp_path / "test.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST)

    reloaded = load_project(bundle)
    assert reloaded["project_id"] == "test_proj"
    assert "updated_at" in reloaded

  def test_save_creates_directory_structure(self, tmp_path: Path) -> None:
    bundle = tmp_path / "new.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST)

    assert (bundle / "cache").is_dir()
    assert (bundle / "exports").is_dir()
    assert (bundle / "gates").is_dir()
    assert (bundle / "manifest.json").is_file()


# -- Load-save-load round-trip --


class TestRoundTrip:
  def test_execution_profiles_preserved(self, tmp_path: Path) -> None:
    bundle = tmp_path / "rt.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST_WITH_PROFILE)

    reloaded = load_project(bundle)
    profiles = reloaded.get("execution_profiles", [])
    assert len(profiles) == 1
    assert profiles[0]["id"] == "default"

  def test_derived_parameters_preserved(self, tmp_path: Path) -> None:
    bundle = tmp_path / "rt.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST_WITH_PROFILE)

    reloaded = load_project(bundle)
    params = reloaded.get("derived_parameters", [])
    assert len(params) == 1
    assert params[0]["expression"] == "FL1-A / FL2-A"

  def test_unknown_fields_preserved(self, tmp_path: Path) -> None:
    manifest = dict(MINIMAL_MANIFEST)
    manifest["experimental_flag"] = True
    manifest["metadata"] = {"author": "test"}

    bundle = tmp_path / "rt.flowdesk"
    save_project(bundle, manifest)

    reloaded = load_project(bundle)
    assert reloaded["experimental_flag"] is True
    assert reloaded["metadata"]["author"] == "test"


# -- Gating strategy --


class TestGatingStrategy:
  def test_load_example_gating_strategy(self) -> None:
    strategy = load_gating_strategy(str(EXAMPLE_PROJECT), "default_gating")
    assert strategy["id"] == "default_gating"
    assert strategy["name"] == "Default gating"

  def test_id_mismatch_raises(self, tmp_path: Path) -> None:
    bundle = tmp_path / "proj.flowdesk"
    gates_dir = bundle / "gates"
    gates_dir.mkdir(parents=True)
    (gates_dir / "gating_strategy.json").write_text(
      json.dumps({"id": "strategy_a", "name": "A", "gates": []}),
      encoding="utf-8",
    )

    with pytest.raises(ValueError, match="id mismatch"):
      load_gating_strategy(bundle, "strategy_b")

  def test_missing_file_raises(self, tmp_path: Path) -> None:
    bundle = tmp_path / "proj.flowdesk"
    with pytest.raises(FileNotFoundError):
      load_gating_strategy(bundle, "any_id")


# -- Sample path resolution --


class TestResolveSamplePaths:
  def test_relative_path_resolved(self, tmp_path: Path) -> None:
    manifest = {
      "project_id": "p1",
      "project_version": "0.1",
      "pipeline_version": "0.1",
      "samples": [{"id": "s1", "name": "test", "path": "data/sample.fcs"}],
      "sample_path_resolution_policy": "relative_to_project_or_absolute",
    }

    resolved = resolve_sample_paths(manifest, tmp_path)
    assert len(resolved) == 1
    assert resolved[0]["path"].endswith(str(tmp_path / "data" / "sample.fcs"))

  def test_absolute_path_kept(self, tmp_path: Path) -> None:
    manifest = {
      "project_id": "p1",
      "project_version": "0.1",
      "pipeline_version": "0.1",
      "samples": [{"id": "s1", "path": "/absolute/path/sample.fcs"}],
    }

    resolved = resolve_sample_paths(manifest, tmp_path)
    assert resolved[0]["path"] == "/absolute/path/sample.fcs"

  def test_absolute_policy_rejects_relative(self, tmp_path: Path) -> None:
    manifest = {
      "project_id": "p1",
      "project_version": "0.1",
      "pipeline_version": "0.1",
      "samples": [{"id": "s1", "path": "relative.fcs"}],
      "sample_path_resolution_policy": "absolute",
    }

    with pytest.raises(ManifestValidationError, match="relative but policy"):
      resolve_sample_paths(manifest, tmp_path)

  def test_default_policy_resolves_relative(self, tmp_path: Path) -> None:
    manifest = {
      "project_id": "p1",
      "project_version": "0.1",
      "pipeline_version": "0.1",
      "samples": [{"id": "s1", "path": "sample.fcs"}],
    }

    resolved = resolve_sample_paths(manifest, tmp_path)
    assert resolved[0]["path"].endswith(str(tmp_path / "sample.fcs"))


# -- Error hierarchy --


class TestErrorHierarchy:
  def test_manifest_error_is_flowdesk_error(self) -> None:
    assert issubclass(ManifestValidationError, FlowdeskError)
