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
from flowdesk_storage.migrations import (
  CURRENT_PROJECT_VERSION,
  ProjectMigrationError,
  migrate_manifest,
)
from flowdesk_storage.project import (
  load_gating_strategy,
  load_project,
  resolve_sample_paths,
  save_project,
)

EXAMPLE_PROJECT = Path(__file__).parent.parent / "examples" / "example_project.flowdesk"
LEGACY_CHANNEL_PROJECT = (
  Path(__file__).parent / "fixtures" / "project_v0_1_channel_names.json"
)

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
    assert params[0]["output_channel_id"] == "fl1_over_fl2"
    assert params[0]["unit"] is None
    assert params[0]["invalid_value_policy"] == "emit_nan_with_warning"

  @pytest.mark.parametrize(
    "policy",
    ("fail_run", "fail_sample", "emit_nan_with_warning"),
  )
  def test_derived_failure_policy_preserved(
    self,
    tmp_path: Path,
    policy: str,
  ) -> None:
    manifest = migrate_manifest(MINIMAL_MANIFEST_WITH_PROFILE)
    manifest["derived_parameters"][0]["invalid_value_policy"] = policy
    bundle = tmp_path / f"policy-{policy}.flowdesk"

    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["derived_parameters"][0]["invalid_value_policy"] == policy

  def test_unknown_fields_preserved(self, tmp_path: Path) -> None:
    manifest = dict(MINIMAL_MANIFEST)
    manifest["experimental_flag"] = True
    manifest["metadata"] = {"author": "test"}

    bundle = tmp_path / "rt.flowdesk"
    save_project(bundle, manifest)

    reloaded = load_project(bundle)
    assert reloaded["experimental_flag"] is True
    assert reloaded["metadata"]["author"] == "test"

  def test_channel_identity_and_unknown_metadata_preserved(self, tmp_path: Path) -> None:
    channel = {
      "id": "fcs_b530_a_123456789abc",
      "name": "B530-A",
      "short_name": "CD3 FITC Fluorescence - Area",
      "detector": "PMT9524",
      "stain": "CD3",
      "unit": "a.u.",
      "fcs_parameter_index": 4,
      "metadata": {
        "p4n": "B530-A",
        "p4s": "CD3 FITC Fluorescence - Area",
        "vendor_unknown": {"preserve": [1, 2, 3]},
      },
      "unknown_channel_extension": "kept",
    }
    manifest = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "path": "data/sample.fcs",
          "channels": [channel],
          "unknown_sample_extension": {"kept": True},
        }
      ],
    }
    bundle = tmp_path / "identity.flowdesk"

    save_project(bundle, manifest)
    reloaded = load_project(bundle)
    save_project(bundle, reloaded)
    reloaded_again = load_project(bundle)

    assert reloaded_again["project_version"] == CURRENT_PROJECT_VERSION
    assert reloaded_again["samples"][0]["channels"] == [channel]
    assert reloaded_again["samples"][0]["unknown_sample_extension"] == {
      "kept": True
    }


class TestChannelIdentityMigration:
  def test_legacy_unique_channel_names_migrate_without_rewriting_references(
    self,
  ) -> None:
    legacy = json.loads(LEGACY_CHANNEL_PROJECT.read_text(encoding="utf-8"))

    migrated = migrate_manifest(legacy)

    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert migrated["samples"][0]["channels"] == [
      {"id": "FSC-A", "name": "FSC-A", "metadata": {"identity_source": "legacy_name"}},
      {"id": "CD3-A", "name": "CD3-A", "metadata": {"identity_source": "legacy_name"}},
    ]
    gate = migrated["gating_strategies_data"]["legacy_strategy"]["gates"][0]
    assert gate["x_parameter"] == "FSC-A"
    assert gate["y_parameter"] == "CD3-A"
    assert migrated["unknown_project_extension"] == {"keep": "unchanged"}
    assert legacy["project_version"] == "0.1"
    assert "channels" not in legacy["samples"][0]

  def test_duplicate_legacy_channel_names_raise_typed_error(self) -> None:
    legacy = json.loads(LEGACY_CHANNEL_PROJECT.read_text(encoding="utf-8"))
    legacy["samples"][0]["channel_names"] = ["CD3", "CD3"]

    with pytest.raises(ProjectMigrationError) as error:
      migrate_manifest(legacy)

    assert error.value.code == "ambiguous_legacy_channel_label"
    assert error.value.sample_id == "s1"
    assert error.value.candidate_labels == ("CD3",)

  def test_load_project_migrates_legacy_fixture(self, tmp_path: Path) -> None:
    bundle = tmp_path / "legacy.flowdesk"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
      LEGACY_CHANNEL_PROJECT.read_text(encoding="utf-8"),
      encoding="utf-8",
    )

    migrated = load_project(bundle)

    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert [
      channel["id"] for channel in migrated["samples"][0]["channels"]
    ] == ["FSC-A", "CD3-A"]

  def test_gui_version_without_channel_metadata_migrates_without_guessing(self) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.0.0",
      "samples": [{"id": "s1", "path": "data/sample.fcs"}],
    }

    migrated = migrate_manifest(legacy)

    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert migrated["samples"][0]["channels"] == []

  def test_v1_1_derived_parameters_migrate_with_explicit_source_semantics(
    self,
    tmp_path: Path,
  ) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.1.0",
      "samples": [{"id": "s1", "channels": []}],
      "derived_parameters": [{
        "id": "legacy_ratio",
        "name": "Legacy ratio",
        "expression": "signal / reference",
        "source_stage": "transformed",
        "vendor_extension": {"keep": True},
      }],
    }

    migrated = migrate_manifest(legacy)

    definition = migrated["derived_parameters"][0]
    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert definition["output_channel_id"] == "legacy_ratio"
    assert definition["unit"] is None
    assert definition["input_parameters"] == []
    assert definition["invalid_value_policy"] == "emit_nan_with_warning"
    assert definition["source_stage"] == "transformed"
    assert definition["legacy_source_stage_policy"] == "reject"
    assert definition["vendor_extension"] == {"keep": True}
    assert migrated["migration_diagnostics"] == [{
      "code": "legacy_transformed_derived_source",
      "severity": "error",
      "stage": "migration",
      "message": (
        "Derived parameter 'legacy_ratio' uses legacy transformed source and "
        "cannot run in the canonical pipeline"
      ),
      "parameter_id": "legacy_ratio",
      "details": {"compatibility_policy": "reject"},
    }]
    assert migrate_manifest(migrated) == migrated

    bundle = tmp_path / "migrated-derived.flowdesk"
    save_project(bundle, migrated)
    reloaded = load_project(bundle)
    assert reloaded["derived_parameters"] == migrated["derived_parameters"]
    assert reloaded["migration_diagnostics"] == migrated["migration_diagnostics"]

  def test_current_transformed_source_requires_explicit_legacy_policy(self) -> None:
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [],
      "derived_parameters": [{
        "id": "legacy",
        "name": "Legacy",
        "expression": "signal",
        "output_channel_id": "legacy_output",
        "unit": None,
        "source_stage": "transformed",
        "input_parameters": ["signal"],
        "invalid_value_policy": "fail_run",
      }],
    }

    with pytest.raises(ManifestValidationError, match="legacy_source_stage_policy"):
      validate_manifest(current)

    current["derived_parameters"][0]["legacy_source_stage_policy"] = "reject"
    validate_manifest(current)

  def test_current_migration_is_idempotent(self) -> None:
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [{"id": "s1", "channels": []}],
    }

    migrated = migrate_manifest(current)

    assert migrated == current
    assert migrated is not current
    assert migrated["samples"] is not current["samples"]

  def test_unsupported_future_version_is_rejected_without_mutation(self) -> None:
    future = {
      **MINIMAL_MANIFEST,
      "project_version": "99.0.0",
      "future_extension": {"keep": True},
    }
    original = json.loads(json.dumps(future))

    with pytest.raises(ProjectMigrationError) as error:
      migrate_manifest(future)

    assert error.value.code == "unsupported_project_version"
    assert future == original

  def test_current_duplicate_channel_ids_fail_validation(self) -> None:
    manifest = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [
        {
          "id": "s1",
          "channels": [
            {"id": "cd3", "name": "B530-A"},
            {"id": "cd3", "name": "B530-H"},
          ],
        }
      ],
    }

    with pytest.raises(ManifestValidationError, match="duplicate channel ID"):
      validate_manifest(manifest)

  def test_current_file_fingerprint_fields_are_validated(self) -> None:
    manifest = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [{
        "id": "s1",
        "channels": [],
        "fingerprint": {
          "size": 10,
          "mtime_ns": 20,
          "hash_algorithm": "sha256",
          "hash_value": "abc",
        },
      }],
    }
    validate_manifest(manifest)

    manifest["samples"][0]["fingerprint"]["size"] = -1
    with pytest.raises(ManifestValidationError, match="fingerprint size"):
      validate_manifest(manifest)


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
