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
    ALL_KNOWN_VERSIONS,
    CURRENT_PROJECT_VERSION,
    LEGACY_PROJECT_VERSIONS,
    MIGRATION_REGISTRY,
  MigrationReport,
  ProjectMigrationError,
  _get_migration_path,
  migrate_manifest,
  migrate_manifest_with_report,
)
from flowdesk_storage.project import (
  load_gating_strategy,
  load_project,
  resolve_sample_paths,
  save_project,
)
from flowdesk_storage.serialization import atomic_write_json

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

  def test_advanced_group_display_setting_must_be_boolean(self) -> None:
    data = dict(MINIMAL_MANIFEST)
    data["project_version"] = CURRENT_PROJECT_VERSION
    data["advanced_groups_enabled"] = "yes"
    with pytest.raises(ManifestValidationError, match="advanced_groups_enabled"):
      validate_manifest(data)

  def test_current_group_binding_references_are_validated(self) -> None:
    data = migrate_manifest(MINIMAL_MANIFEST)
    data["group_strategy_bindings"][0]["gating_strategy_id"] = "missing"
    with pytest.raises(ManifestValidationError, match="unknown strategy"):
      validate_manifest(data)

  def test_integrated_comparison_metadata_is_validated_separately_from_groups(self) -> None:
    data = migrate_manifest(MINIMAL_MANIFEST)
    data["samples"] = [
      {"id": "s1", "name": "S1", "path": "", "channels": []},
      {"id": "s2", "name": "S2", "path": "", "channels": []},
    ]
    data["comparison_set_definitions"] = [{
      "id": "pair-1",
      "name": "Pair",
      "members": [
        {"sample_id": "s1", "role": "reference"},
        {"sample_id": "s2", "role": "target"},
      ],
    }]
    data["comparison_role_colors"] = {"reference": "#123456"}
    validate_manifest(data)
    data["comparison_set_definitions"][0]["members"][1]["sample_id"] = "missing"
    with pytest.raises(ManifestValidationError, match="unknown sample"):
      validate_manifest(data)


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
  def test_statistic_definition_preserved(self, tmp_path: Path) -> None:
    manifest = migrate_manifest(MINIMAL_MANIFEST)
    statistic = {
      "id": "stat_mean_fl1",
      "name": "Mean FL1",
      "population_id": "all_events",
      "parameter_id": "FL1-A",
      "metric": "mean",
      "source_stage": "transformed",
      "transform_id": "linear-fl1",
      "value_policy": "full_events",
      "settings": {},
      "format": ".3f",
      "notes": "publication statistic",
    }
    manifest["transforms"] = [{
      "id": "linear-fl1",
      "name": "Linear FL1",
      "transform_type": "linear",
      "parameter": "FL1-A",
      "role": "analysis",
      "settings": {"scale": 1.0, "offset": 0.0},
    }]
    manifest["statistics"] = [statistic]
    bundle = tmp_path / "statistics.flowdesk"

    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["statistics"] == [statistic]

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

  def test_published_logicle_parameters_and_version_are_preserved(
    self,
    tmp_path: Path,
  ) -> None:
    manifest = migrate_manifest(MINIMAL_MANIFEST)
    manifest["transforms"] = [{
      "id": "logicle_signal",
      "name": "Logicle signal",
      "transform_type": "logicle",
      "parameter": "signal",
      "settings": {
        "T": 262144.0,
        "W": 0.5,
        "M": 4.5,
        "A": 0.0,
        "implementation_version": "logicle-gml2-moore-parks-2012-v1",
      },
      "role": "analysis",
    }]
    bundle = tmp_path / "published-logicle.flowdesk"

    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["transforms"] == manifest["transforms"]

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

  def test_v1_2_logicle_like_is_renamed_without_changing_settings(self) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.2.0",
      "samples": [{"id": "s1", "channels": []}],
      "transforms": [{
        "id": "legacy_scale",
        "name": "Legacy scale",
        "transform_type": "logicle_like",
        "parameter": "signal",
        "settings": {"w": 0.3, "td": 500000.0, "tn": 5000.0},
        "vendor_extension": {"keep": True},
      }, {
        "id": "existing_log",
        "name": "Existing log",
        "transform_type": "log",
        "parameter": "signal",
        "settings": {
          "base": 10.0,
          "invalid_value_policy": "to_nan",
        },
      }],
    }

    migrated = migrate_manifest(legacy)

    transform = migrated["transforms"][0]
    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert transform == {
      "id": "legacy_scale",
      "name": "Legacy scale",
      "transform_type": "legacy_logicle_approximation",
      "parameter": "signal",
      "settings": {"w": 0.3, "td": 500000.0, "tn": 5000.0},
      "role": "analysis",
      "vendor_extension": {"keep": True},
    }
    assert migrated["migration_diagnostics"] == [{
      "code": "legacy_logicle_approximation",
      "severity": "warning",
      "stage": "migration",
      "message": (
        "Transform 'legacy_scale' used the historical logicle_like "
        "approximation; it was renamed without changing numeric behavior"
      ),
      "transform_id": "legacy_scale",
      "details": {
        "old_type": "logicle_like",
        "new_type": "legacy_logicle_approximation",
        "numeric_behavior_preserved": True,
      },
    }]
    assert legacy["transforms"][0]["transform_type"] == "logicle_like"
    assert migrated["transforms"][1] == {
      **legacy["transforms"][1],
      "role": "analysis",
    }
    assert migrate_manifest(migrated) == migrated

  def test_current_project_rejects_ambiguous_logicle_like_name(self) -> None:
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [],
      "transforms": [{
        "id": "ambiguous",
        "name": "Ambiguous",
        "transform_type": "logicle_like",
        "parameter": "signal",
        "settings": {},
      }],
    }

    with pytest.raises(ManifestValidationError, match="transform_type"):
      validate_manifest(current)

  def test_v1_4_gate_axis_is_bound_to_matching_project_transform(self) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.4.0",
      "samples": [{"id": "s1", "channels": []}],
      "transforms": [{
        "id": "scale_signal",
        "name": "Scale signal",
        "transform_type": "linear",
        "parameter": "signal",
        "settings": {"scale": 2.0, "offset": 0.0},
      }],
      "gating_strategies_data": {
        "default": {
          "id": "default",
          "gates": [{
            "id": "signal_gate",
            "name": "Signal gate",
            "gate_type": "range",
            "x_parameter": "signal",
            "x_scale": "linear",
            "thresholds": {"min": 1.0},
          }],
        },
      },
    }

    migrated = migrate_manifest(legacy)

    assert migrated["transforms"][0]["role"] == "analysis"
    gate = migrated["gating_strategies_data"]["default"]["gates"][0]
    assert gate["x_transform_id"] == "scale_signal"
    validate_manifest(migrated)

  def test_current_gate_rejects_transform_id_plus_legacy_scale(self) -> None:
    manifest = migrate_manifest(MINIMAL_MANIFEST)
    manifest["transforms"] = [{
      "id": "log_signal",
      "name": "Log signal",
      "transform_type": "log",
      "parameter": "signal",
      "settings": {"base": 10.0, "invalid_value_policy": "to_nan"},
      "role": "analysis",
    }]
    manifest["gating_strategies_data"] = {
      "default": {
        "id": "default",
        "gates": [{
          "id": "double",
          "gate_type": "range",
          "x_parameter": "signal",
          "x_scale": "log10",
          "x_transform_id": "log_signal",
          "thresholds": {"min": 0.0},
        }],
      },
    }

    with pytest.raises(ManifestValidationError, match="double transform"):
      validate_manifest(manifest)

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


# -- Compensation matrix validation --


class TestCompensationMatrixValidation:
  """Validate compensation matrices in the current project format."""

  _identity_2x2 = [[1.0, 0.0], [0.0, 1.0]]
  _valid_matrix = {
    "id": "comp_1",
    "name": "Identity matrix",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": _identity_2x2,
    "provenance": {},
  }

  def _make_manifest(self, **kwargs) -> dict[str, Any]:
    manifest: dict[str, Any] = {
      "project_id": "test_proj",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      **kwargs,
    }
    return manifest

  def test_valid_matrix_passes(self) -> None:
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix]
    )
    validate_manifest(manifest)

  def test_valid_sources(self) -> None:
    for source in ("fcs_metadata_spillover", "user_defined", "imported"):
      matrix = dict(self._valid_matrix, source=source)
      manifest = self._make_manifest(compensation_matrices=[matrix])
      validate_manifest(manifest)

  def test_invalid_source_raises(self) -> None:
    matrix = dict(self._valid_matrix, source="invalid_source")
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="invalid source"):
      validate_manifest(manifest)

  def test_missing_id_raises(self) -> None:
    matrix = dict(self._valid_matrix)
    del matrix["id"]
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="must be a non-empty string"):
      validate_manifest(manifest)

  def test_empty_id_raises(self) -> None:
    matrix = dict(self._valid_matrix, id="")
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="must be a non-empty string"):
      validate_manifest(manifest)

  def test_missing_name_raises(self) -> None:
    matrix = dict(self._valid_matrix)
    del matrix["name"]
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="name must be"):
      validate_manifest(manifest)

  def test_empty_name_raises(self) -> None:
    matrix = dict(self._valid_matrix, name="")
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="name must be"):
      validate_manifest(manifest)

  def test_duplicate_matrix_ids_raises(self) -> None:
    matrices = [
      self._valid_matrix,
      dict(self._valid_matrix, id="comp_1", name="Duplicate"),
    ]
    manifest = self._make_manifest(compensation_matrices=matrices)
    with pytest.raises(ManifestValidationError, match="duplicate"):
      validate_manifest(manifest)

  def test_non_square_matrix_raises(self) -> None:
    matrix = {
      **self._valid_matrix,
      "matrix": [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]],
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="row count"):
      validate_manifest(manifest)

  def test_row_length_mismatch_raises(self) -> None:
    matrix = {
      **self._valid_matrix,
      "matrix": [[1.0, 0.0], [0.0]],
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="must have"):
      validate_manifest(manifest)

  def test_non_numeric_cell_raises(self) -> None:
    matrix = {
      **self._valid_matrix,
      "matrix": [[1.0, "0.0"], [0.0, 1.0]],
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="must be a number"):
      validate_manifest(manifest)

  def test_bool_cell_raises(self) -> None:
    matrix = {
      **self._valid_matrix,
      "matrix": [[True, 0.0], [0.0, 1.0]],
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="must be a number"):
      validate_manifest(manifest)

  def test_empty_channels_raises(self) -> None:
    matrix = dict(self._valid_matrix, channels=[], matrix=[])
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="channels"):
      validate_manifest(manifest)

  def test_duplicate_channels_raises(self) -> None:
    matrix = {
      **self._valid_matrix,
      "channels": ["FL1-A", "FL1-A"],
      "matrix": [[1.0, 0.0], [0.0, 1.0]],
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="duplicate"):
      validate_manifest(manifest)

  def test_provenance_missing_defaults_to_empty(self) -> None:
    matrix = dict(self._valid_matrix)
    del matrix["provenance"]
    manifest = self._make_manifest(compensation_matrices=[matrix])
    validate_manifest(manifest)

  def test_provenance_must_be_object(self) -> None:
    matrix = dict(self._valid_matrix, provenance="invalid")
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="provenance must be"):
      validate_manifest(manifest)

  def test_manual_edits_must_be_array(self) -> None:
    matrix = dict(
      self._valid_matrix,
      provenance={"manual_edits": "not_array"},
    )
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="manual_edits"):
      validate_manifest(manifest)

  def test_manual_edit_missing_channel_id_raises(self) -> None:
    matrix = dict(
      self._valid_matrix,
      provenance={
        "manual_edits": [
          {
            "row_channel_id": "FL1-A",
            "column_channel_id": "",
            "old_value": 0.0,
            "new_value": 0.1,
          }
        ],
        "derived_from_matrix_id": "comp_1",
      },
    )
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="column_channel_id"):
      validate_manifest(manifest)

  def test_manual_edit_non_numeric_value_raises(self) -> None:
    matrix = dict(
      self._valid_matrix,
      provenance={
        "manual_edits": [
          {
            "row_channel_id": "FL1-A",
            "column_channel_id": "FL2-A",
            "old_value": "0.0",
            "new_value": 0.1,
          }
        ],
        "derived_from_matrix_id": "comp_1",
      },
    )
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="old_value"):
      validate_manifest(manifest)

  def test_manual_edits_require_derived_from_matrix_id(self) -> None:
    matrix = dict(
      self._valid_matrix,
      provenance={
        "manual_edits": [
          {
            "row_channel_id": "FL1-A",
            "column_channel_id": "FL2-A",
            "old_value": 0.0,
            "new_value": 0.1,
          }
        ],
      },
    )
    manifest = self._make_manifest(compensation_matrices=[matrix])
    with pytest.raises(ManifestValidationError, match="derived_from_matrix_id"):
      validate_manifest(manifest)

  def test_matrix_with_provenance_and_edit_history_passes(self) -> None:
    matrix = {
      **self._valid_matrix,
      "provenance": {
        "source_sample_id": "control_1",
        "source_metadata_key": "SPILLOVER",
        "control_sample_ids": ["control_1", "control_2"],
        "control_population_ids": ["singlets"],
        "algorithm": "traditional",
        "algorithm_version": "1.0",
        "software_version": "1.5.0",
        "derived_from_matrix_id": "comp_original",
        "manual_edits": [
          {
            "row_channel_id": "FL1-A",
            "column_channel_id": "FL2-A",
            "old_value": 0.0,
            "new_value": 0.1,
            "edited_at": "2024-01-01T00:00:00Z",
            "edited_by": "user",
            "reason": "manual correction",
          }
        ],
      },
    }
    manifest = self._make_manifest(compensation_matrices=[matrix])
    validate_manifest(manifest)


# -- Compensation binding validation --


class TestCompensationBindingValidation:
  """Validate compensation bindings in the current project format."""

  _valid_matrix = {
    "id": "comp_1",
    "name": "Test matrix",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": [[1.0, 0.0], [0.0, 1.0]],
    "provenance": {},
  }
  _valid_binding = {
    "id": "bind_1",
    "matrix_id": "comp_1",
    "scope": "sample",
    "target_id": "s1",
  }

  def _make_manifest(self, **kwargs) -> dict[str, Any]:
    manifest: dict[str, Any] = {
      "project_id": "test_proj",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      **kwargs,
    }
    return manifest

  def test_valid_binding_passes(self) -> None:
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[self._valid_binding],
    )
    validate_manifest(manifest)

  def test_valid_scopes(self) -> None:
    for scope, target in [
      ("sample", "s1"),
      ("group", "group_a"),
      ("execution_profile", "profile_1"),
    ]:
      binding = {
        **self._valid_binding,
        "scope": scope,
        "target_id": target,
      }
      manifest = self._make_manifest(
        compensation_matrices=[self._valid_matrix],
        compensation_bindings=[binding],
      )
      validate_manifest(manifest)

  def test_invalid_scope_raises(self) -> None:
    binding = dict(self._valid_binding, scope="invalid_scope")
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[binding],
    )
    with pytest.raises(ManifestValidationError, match="invalid scope"):
      validate_manifest(manifest)

  def test_unknown_matrix_id_raises(self) -> None:
    binding = dict(self._valid_binding, matrix_id="nonexistent")
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[binding],
    )
    with pytest.raises(ManifestValidationError, match="unknown"):
      validate_manifest(manifest)

  def test_duplicate_binding_ids_raises(self) -> None:
    bindings = [
      self._valid_binding,
      dict(self._valid_binding, id="bind_1"),
    ]
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=bindings,
    )
    with pytest.raises(ManifestValidationError, match="duplicate"):
      validate_manifest(manifest)

  def test_duplicate_scope_target_raises(self) -> None:
    bindings = [
      self._valid_binding,
      {
        "id": "bind_2",
        "matrix_id": "comp_1",
        "scope": "sample",
        "target_id": "s1",
      },
    ]
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=bindings,
    )
    with pytest.raises(ManifestValidationError, match="duplicate"):
      validate_manifest(manifest)

  def test_empty_binding_id_raises(self) -> None:
    binding = dict(self._valid_binding, id="")
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[binding],
    )
    with pytest.raises(ManifestValidationError, match="must be a non-empty string"):
      validate_manifest(manifest)

  def test_empty_target_id_raises(self) -> None:
    binding = dict(self._valid_binding, target_id="")
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[binding],
    )
    with pytest.raises(ManifestValidationError, match="target_id must"):
      validate_manifest(manifest)

  def test_empty_matrix_id_raises(self) -> None:
    binding = dict(self._valid_binding, matrix_id="")
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=[binding],
    )
    with pytest.raises(ManifestValidationError, match="matrix_id must"):
      validate_manifest(manifest)

  def test_multiple_bindings_different_scopes_pass(self) -> None:
    bindings = [
      {
        "id": "bind_sample",
        "matrix_id": "comp_1",
        "scope": "sample",
        "target_id": "s1",
      },
      {
        "id": "bind_group",
        "matrix_id": "comp_1",
        "scope": "group",
        "target_id": "group_a",
      },
      {
        "id": "bind_profile",
        "matrix_id": "comp_1",
        "scope": "execution_profile",
        "target_id": "profile_1",
      },
    ]
    manifest = self._make_manifest(
      compensation_matrices=[self._valid_matrix],
      compensation_bindings=bindings,
    )
    validate_manifest(manifest)


# -- Compensation migration --


class TestCompensationMigration:
  """Test legacy compensation matrix migration to current format."""

  _legacy_matrix = {
    "id": "legacy_comp",
    "name": "Legacy matrix",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": [[1.0, 0.2], [0.1, 1.0]],
  }

  def test_legacy_matrix_gets_provenance(self) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
      "compensation_matrices": [self._legacy_matrix],
    }

    migrated = migrate_manifest(legacy)

    assert migrated["project_version"] == CURRENT_PROJECT_VERSION
    assert migrated["compensation_matrices"][0]["provenance"] == {}
    assert migrated["compensation_bindings"] == []
    assert len(migrated["migration_diagnostics"]) >= 1
    diag = migrated["migration_diagnostics"][0]
    assert diag["code"] == "legacy_compensation_matrix_provenance"
    assert diag["severity"] == "info"

  def test_matrix_with_provenance_is_not_touched(self) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
      "compensation_matrices": [
        {
          **self._legacy_matrix,
          "provenance": {
            "source_sample_id": "control_1",
            "derived_from_matrix_id": None,
          },
        }
      ],
    }

    migrated = migrate_manifest(legacy)

    assert migrated["compensation_matrices"][0]["provenance"] == {
      "source_sample_id": "control_1",
      "derived_from_matrix_id": None,
    }

  def test_no_compensation_matrices_initializes_bindings(self) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
    }

    migrated = migrate_manifest(legacy)

    assert migrated["compensation_bindings"] == []

  def test_existing_bindings_preserved(self) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
      "compensation_matrices": [self._legacy_matrix],
      "compensation_bindings": [
        {
          "id": "bind_1",
          "matrix_id": "legacy_comp",
          "scope": "sample",
          "target_id": "s1",
        }
      ],
    }

    migrated = migrate_manifest(legacy)

    assert len(migrated["compensation_bindings"]) == 1
    assert migrated["compensation_bindings"][0]["id"] == "bind_1"

  def test_default_compensation_matrix_id_preserved(self) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
      "compensation_matrices": [self._legacy_matrix],
      "default_compensation_matrix_id": "legacy_comp",
    }

    migrated = migrate_manifest(legacy)

    assert migrated["default_compensation_matrix_id"] == "legacy_comp"
    assert migrated["compensation_bindings"] == []
    # Verify diagnostic was emitted
    diag_codes = [d["code"] for d in migrated.get("migration_diagnostics", [])]
    assert "legacy_default_compensation_preserved" in diag_codes

  def test_default_compensation_matrix_id_no_diag_when_bindings_exist(self) -> None:
    """When bindings already exist, no legacy default diagnostic is emitted."""
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
      "compensation_matrices": [self._legacy_matrix],
      "default_compensation_matrix_id": "legacy_comp",
      "compensation_bindings": [
        {
          "id": "bind_1",
          "matrix_id": "legacy_comp",
          "scope": "sample",
          "target_id": "s1",
        }
      ],
    }

    migrated = migrate_manifest(legacy)

    assert migrated["default_compensation_matrix_id"] == "legacy_comp"
    diag_codes = [d["code"] for d in migrated.get("migration_diagnostics", [])]
    assert "legacy_default_compensation_preserved" not in diag_codes


# -- Compensation round-trip --


class TestCompensationRoundTrip:
  """Test save-load round-trip for compensation data."""

  _valid_matrix = {
    "id": "comp_1",
    "name": "Test matrix",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": [[1.0, 0.2], [0.1, 1.0]],
    "provenance": {
      "source_sample_id": "control_1",
      "algorithm": "traditional",
      "derived_from_matrix_id": None,
      "manual_edits": [],
    },
  }

  def test_matrix_round_trip(self, tmp_path: Path) -> None:
    manifest = {
      "project_id": "test",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._valid_matrix],
      "compensation_bindings": [],
    }

    bundle = tmp_path / "comp.flowdesk"
    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["compensation_matrices"] == [self._valid_matrix]

  def test_binding_round_trip(self, tmp_path: Path) -> None:
    binding = {
      "id": "bind_1",
      "matrix_id": "comp_1",
      "scope": "sample",
      "target_id": "s1",
      "created_at": "2024-01-01T00:00:00Z",
      "created_by": "test_user",
      "notes": "manual binding",
    }
    manifest = {
      "project_id": "test",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._valid_matrix],
      "compensation_bindings": [binding],
    }

    bundle = tmp_path / "comp.flowdesk"
    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["compensation_bindings"] == [binding]

  def test_matrix_with_edit_history_round_trip(self, tmp_path: Path) -> None:
    matrix_with_edits = {
      **self._valid_matrix,
      "id": "comp_edited",
      "name": "Edited matrix",
      "provenance": {
        "source_sample_id": "control_1",
        "derived_from_matrix_id": "comp_1",
        "manual_edits": [
          {
            "row_channel_id": "FL1-A",
            "column_channel_id": "FL2-A",
            "old_value": 0.2,
            "new_value": 0.25,
            "edited_at": "2024-06-01T10:00:00Z",
            "edited_by": "analyst",
            "reason": "corrected by visual inspection",
          },
          {
            "row_channel_id": "FL2-A",
            "column_channel_id": "FL1-A",
            "old_value": 0.1,
            "new_value": 0.15,
            "edited_at": "2024-06-01T10:01:00Z",
            "edited_by": "analyst",
            "reason": "matching correction",
          },
        ],
      },
    }
    manifest = {
      "project_id": "test",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._valid_matrix, matrix_with_edits],
      "compensation_bindings": [],
    }

    bundle = tmp_path / "comp.flowdesk"
    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    matrices = reloaded["compensation_matrices"]
    assert len(matrices) == 2
    assert matrices[1] == matrix_with_edits
    assert len(matrices[1]["provenance"]["manual_edits"]) == 2

  _legacy_matrix = {
    "id": "legacy_comp",
    "name": "Legacy matrix",
    "source": "user_defined",
    "channels": ["FL1-A", "FL2-A"],
    "matrix": [[1.0, 0.2], [0.1, 1.0]],
  }

  def test_legacy_matrix_migrates_and_round_trips(self, tmp_path: Path) -> None:
    legacy = {
      "project_id": "test",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._legacy_matrix],
      "default_compensation_matrix_id": "legacy_comp",
    }

    bundle = tmp_path / "legacy.flowdesk"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
      json.dumps(legacy),
      encoding="utf-8",
    )

    reloaded = load_project(bundle)

    assert reloaded["project_version"] == CURRENT_PROJECT_VERSION
    assert reloaded["compensation_matrices"][0]["provenance"] == {}
    assert reloaded["default_compensation_matrix_id"] == "legacy_comp"
    # Re-save and re-load should be idempotent
    save_project(bundle, reloaded)
    reloaded2 = load_project(bundle)
    assert reloaded2["compensation_matrices"] == reloaded["compensation_matrices"]

  def test_default_compensation_matrix_id_round_trip(
    self,
    tmp_path: Path,
  ) -> None:
    manifest = {
      "project_id": "test",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._valid_matrix],
      "compensation_bindings": [],
      "default_compensation_matrix_id": "comp_1",
    }

    bundle = tmp_path / "comp.flowdesk"
    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert reloaded["default_compensation_matrix_id"] == "comp_1"

  def test_multiple_matrices_and_bindings_round_trip(
    self,
    tmp_path: Path,
  ) -> None:
    matrix_2 = {
      **self._valid_matrix,
      "id": "comp_2",
      "name": "Second matrix",
      "source": "imported",
    }
    bindings = [
      {
        "id": "bind_sample",
        "matrix_id": "comp_1",
        "scope": "sample",
        "target_id": "s1",
      },
      {
        "id": "bind_group",
        "matrix_id": "comp_2",
        "scope": "group",
        "target_id": "group_a",
      },
    ]
    manifest = {
      "project_id": "test",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "name": "Sample 1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      "compensation_matrices": [self._valid_matrix, matrix_2],
      "compensation_bindings": bindings,
      "default_compensation_matrix_id": "comp_2",
    }

    bundle = tmp_path / "multi.flowdesk"
    save_project(bundle, manifest)
    reloaded = load_project(bundle)

    assert len(reloaded["compensation_matrices"]) == 2
    assert len(reloaded["compensation_bindings"]) == 2
    assert reloaded["default_compensation_matrix_id"] == "comp_2"


class TestCompensationCalculationValidation:
  """Manifest validation for compensation_calculations."""

  _minimal_manifest: dict[str, Any] = {
    "project_id": "test",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "1.0",
    "samples": [
      {
        "id": "s1",
        "name": "Sample 1",
        "channels": [
          {"id": "FL1-A", "name": "FL1-A"},
          {"id": "FL2-A", "name": "FL2-A"},
        ],
      }
    ],
  }

  def _make_valid_calc(self) -> dict[str, Any]:
    return {
      "id": "calc1",
      "name": "Single-stain calc",
      "controls": [
        {
          "sample_id": "s1",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "pos_FL1",
          "negative_population_id": "neg",
        },
      ],
    }

  def test_valid_calculation_accepted(self) -> None:
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [self._make_valid_calc()]
    assert validate_manifest(manifest) is None

  def test_valid_calculation_with_all_options(self) -> None:
    calc = self._make_valid_calc()
    calc["regression_method"] = "median"
    calc["outlier_policy"] = "zscore"
    calc["minimum_positive_events"] = 200
    calc["minimum_negative_events"] = 100
    calc["created_by"] = "test_user"
    calc["created_at"] = "2025-01-01T00:00:00Z"
    calc["notes"] = "test"
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    assert validate_manifest(manifest) is None

  def test_empty_calculations_accepted(self) -> None:
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = []
    assert validate_manifest(manifest) is None

  def test_missing_calculations_accepted(self) -> None:
    assert validate_manifest(self._minimal_manifest) is None

  def test_rejects_non_array(self) -> None:
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = "not an array"
    with pytest.raises(ManifestValidationError, match="array"):
      validate_manifest(manifest)

  def test_rejects_empty_id(self) -> None:
    calc = self._make_valid_calc()
    calc["id"] = ""
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="id"):
      validate_manifest(manifest)

  def test_rejects_duplicate_id(self) -> None:
    manifest = dict(self._minimal_manifest)
    calc = self._make_valid_calc()
    manifest["compensation_calculations"] = [calc, calc]
    with pytest.raises(ManifestValidationError, match="duplicate"):
      validate_manifest(manifest)

  def test_rejects_empty_name(self) -> None:
    calc = self._make_valid_calc()
    calc["name"] = ""
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="name"):
      validate_manifest(manifest)

  def test_rejects_empty_controls(self) -> None:
    calc = self._make_valid_calc()
    calc["controls"] = []
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="controls"):
      validate_manifest(manifest)

  def test_rejects_duplicate_detector(self) -> None:
    calc = self._make_valid_calc()
    calc["controls"].append({
      "sample_id": "s1",
      "detector_channel_id": "FL1-A",
      "positive_population_id": "pos2",
      "negative_population_id": "neg2",
    })
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="duplicate.*detector"):
      validate_manifest(manifest)

  def test_rejects_invalid_regression_method(self) -> None:
    calc = self._make_valid_calc()
    calc["regression_method"] = "ols"
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="regression_method"):
      validate_manifest(manifest)

  def test_rejects_invalid_outlier_policy(self) -> None:
    calc = self._make_valid_calc()
    calc["outlier_policy"] = "mad"
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="outlier_policy"):
      validate_manifest(manifest)

  def test_rejects_non_positive_min_events(self) -> None:
    calc = self._make_valid_calc()
    calc["minimum_positive_events"] = 0
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="minimum_positive"):
      validate_manifest(manifest)

  def test_rejects_empty_detector_channel_id(self) -> None:
    calc = self._make_valid_calc()
    calc["controls"][0]["detector_channel_id"] = ""
    manifest = dict(self._minimal_manifest)
    manifest["compensation_calculations"] = [calc]
    with pytest.raises(ManifestValidationError, match="detector_channel_id"):
      validate_manifest(manifest)

  def test_calculated_source_accepted_in_matrix(self) -> None:
    """A matrix with source='calculated' must pass validation."""
    manifest = dict(self._minimal_manifest)
    manifest["compensation_matrices"] = [
      {
        "id": "calc_matrix",
        "name": "Calculated matrix",
        "source": "calculated",
        "channels": ["FL1-A"],
        "matrix": [[1.0]],
      }
    ]
    assert validate_manifest(manifest) is None


def test_saved_calculated_matrix_round_trips_with_provenance(tmp_path: Path) -> None:
  """A saved calculation result remains a reusable immutable project record."""
  bundle = tmp_path / "calculated.flowdesk"
  manifest = {
    "project_id": "calculated-project",
    "project_version": CURRENT_PROJECT_VERSION,
    "pipeline_version": "1.0",
    "samples": [],
    "compensation_matrices": [{
      "id": "calculated-calc1",
      "name": "Calculated: controls",
      "source": "calculated",
      "channels": ["FL1-A"],
      "matrix": [[1.0]],
      "created_at": "2026-07-16T00:00:00+00:00",
      "provenance": {
        "control_sample_ids": ["control-1"],
        "control_population_ids": ["control-1:positive", "control-1:negative"],
        "algorithm": "traditional_linear_background_subtracted",
        "algorithm_version": "1.0.0",
        "software_version": "1.5.0",
        "manual_edits": [],
      },
    }],
  }

  save_project(bundle, manifest)
  reloaded = load_project(bundle)

  assert reloaded["compensation_matrices"] == manifest["compensation_matrices"]


# -- MigrationReport --


class TestMigrationReport:
  """Test the typed MigrationReport from migrate_manifest_with_report."""

  def test_current_version_no_migration(self) -> None:
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
    }
    report = migrate_manifest_with_report(current)

    assert report.from_version == CURRENT_PROJECT_VERSION
    assert report.to_version == CURRENT_PROJECT_VERSION
    assert report.was_migrated is False
    assert report.diagnostics == []
    assert report.migrated is not None
    assert report.migrated == current

  def test_legacy_version_migrates(self) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.0.0",
      "samples": [{"id": "s1", "channels": []}],
    }
    report = migrate_manifest_with_report(legacy)

    assert report.from_version == "1.0.0"
    assert report.to_version == CURRENT_PROJECT_VERSION
    assert report.was_migrated is True
    assert report.migrated is not None
    assert report.migrated["project_version"] == CURRENT_PROJECT_VERSION

  def test_to_mapping(self) -> None:
    report = MigrationReport(
      from_version="0.1",
      to_version=CURRENT_PROJECT_VERSION,
      was_migrated=True,
      diagnostics=[{"code": "test", "severity": "info", "stage": "migration", "message": "test"}],
    )

    mapping = report.to_mapping()
    assert mapping["from_version"] == "0.1"
    assert mapping["to_version"] == CURRENT_PROJECT_VERSION
    assert mapping["was_migrated"] is True
    assert mapping["migration_path"] == []
    assert len(mapping["diagnostics"]) == 1
    assert mapping["diagnostics"][0]["code"] == "test"

  def test_diagnostics_preserved_from_legacy(self) -> None:
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.2.0",
      "samples": [{"id": "s1", "channels": []}],
      "transforms": [{
        "id": "legacy_scale",
        "name": "Legacy scale",
        "transform_type": "logicle_like",
        "parameter": "signal",
        "settings": {"w": 0.3, "td": 500000.0, "tn": 5000.0},
      }],
    }
    report = migrate_manifest_with_report(legacy)

    assert report.was_migrated is True
    diag_codes = [d["code"] for d in report.diagnostics]
    assert "legacy_logicle_approximation" in diag_codes

  def test_unsupported_version_still_raises(self) -> None:
    future = {
      **MINIMAL_MANIFEST,
      "project_version": "99.0.0",
    }
    with pytest.raises(ProjectMigrationError) as error:
      migrate_manifest_with_report(future)
    assert error.value.code == "unsupported_project_version"

  def test_backward_compat_wrapper_returns_dict(self) -> None:
    """The deprecated migrate_manifest() still returns a dict."""
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
    }
    result = migrate_manifest(current)
    assert isinstance(result, dict)
    assert result["project_version"] == CURRENT_PROJECT_VERSION

  def test_legacy_compat_wrapper_returns_migrated_dict(self) -> None:
    """The deprecated migrate_manifest() still returns migrated dict."""
    legacy = {
      **MINIMAL_MANIFEST,
      "project_version": "1.0.0",
      "samples": [{"id": "s1", "channels": []}],
    }
    result = migrate_manifest(legacy)
    assert isinstance(result, dict)
    assert result["project_version"] == CURRENT_PROJECT_VERSION


# -- Reference integrity validation --


class TestReferenceIntegrity:
  """Test that dangling gate and statistic references are rejected."""

  def _make_manifest(self, **kwargs) -> dict[str, Any]:
    manifest: dict[str, Any] = {
      "project_id": "test_proj",
      "project_version": CURRENT_PROJECT_VERSION,
      "pipeline_version": "1.0",
      "samples": [
        {
          "id": "s1",
          "channels": [
            {"id": "FL1-A", "name": "FL1-A"},
            {"id": "FL2-A", "name": "FL2-A"},
          ],
        }
      ],
      **kwargs,
    }
    return manifest

  def test_gate_parent_all_events_is_allowed(self) -> None:
    manifest = self._make_manifest(
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [{
            "id": "g1",
            "gate_type": "rectangle",
            "parent_population_id": "all_events",
            "x_parameter": "FL1-A",
            "y_parameter": "FL2-A",
          }],
        },
      },
    )
    validate_manifest(manifest)

  def test_gate_parent_null_is_allowed(self) -> None:
    manifest = self._make_manifest(
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [{
            "id": "g1",
            "gate_type": "rectangle",
            "parent_population_id": None,
            "x_parameter": "FL1-A",
            "y_parameter": "FL2-A",
          }],
        },
      },
    )
    validate_manifest(manifest)

  def test_gate_parent_another_gate_is_allowed(self) -> None:
    manifest = self._make_manifest(
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [
            {
              "id": "g1",
              "gate_type": "rectangle",
              "parent_population_id": "all_events",
              "x_parameter": "FL1-A",
              "y_parameter": "FL2-A",
            },
            {
              "id": "g2",
              "gate_type": "rectangle",
              "parent_population_id": "g1",
              "x_parameter": "FL1-A",
              "y_parameter": "FL2-A",
            },
          ],
        },
      },
    )
    validate_manifest(manifest)

  def test_gate_parent_unknown_gate_raises(self) -> None:
    manifest = self._make_manifest(
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [{
            "id": "g1",
            "gate_type": "rectangle",
            "parent_population_id": "nonexistent",
            "x_parameter": "FL1-A",
            "y_parameter": "FL2-A",
          }],
        },
      },
    )
    with pytest.raises(ManifestValidationError, match="unknown parent_population_id"):
      validate_manifest(manifest)

  def test_gate_parent_empty_string_raises(self) -> None:
    manifest = self._make_manifest(
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [{
            "id": "g1",
            "gate_type": "rectangle",
            "parent_population_id": "",
            "x_parameter": "FL1-A",
            "y_parameter": "FL2-A",
          }],
        },
      },
    )
    with pytest.raises(
      ManifestValidationError,
      match="parent_population_id must be a non-empty string",
    ):
      validate_manifest(manifest)

  def test_dangling_transform_reference_raises(self) -> None:
    manifest = self._make_manifest(
      transforms=[{
        "id": "t1",
        "name": "T1",
        "transform_type": "linear",
        "parameter": "FL1-A",
        "role": "analysis",
        "settings": {"scale": 1.0, "offset": 0.0},
      }],
      gating_strategies_data={
        "default": {
          "id": "default",
          "gates": [{
            "id": "g1",
            "gate_type": "rectangle",
            "parent_population_id": None,
            "x_parameter": "FL1-A",
            "x_transform_id": "unknown_transform",
          }],
        },
      },
    )
    with pytest.raises(ManifestValidationError, match="unknown transform"):
      validate_manifest(manifest)

  def test_dangling_matrix_binding_reference_raises(self) -> None:
    manifest = self._make_manifest(
      compensation_bindings=[{
        "id": "bind_1",
        "matrix_id": "nonexistent_matrix",
        "scope": "sample",
        "target_id": "s1",
      }],
    )
    with pytest.raises(ManifestValidationError, match="unknown.*matrix"):
      validate_manifest(manifest)

  def test_dangling_sample_in_calculation_raises(self) -> None:
    manifest = self._make_manifest(
      compensation_calculations=[{
        "id": "calc1",
        "name": "Calc",
        "controls": [{
          "sample_id": "nonexistent_sample",
          "detector_channel_id": "FL1-A",
          "positive_population_id": "pos",
          "negative_population_id": "neg",
        }],
      }],
    )
    with pytest.raises(ManifestValidationError, match="unknown sample"):
      validate_manifest(manifest)


# -- Migration registry --


class TestMigrationRegistry:
  """Test version path computation and per-version migration fixtures."""

  def test_current_version_has_empty_path(self) -> None:
    assert _get_migration_path(CURRENT_PROJECT_VERSION) == []

  def test_legacy_versions_have_non_empty_path(self) -> None:
    for version in LEGACY_PROJECT_VERSIONS:
      path = _get_migration_path(version)
      assert len(path) > 0, f"{version} should have a migration path"
      assert path[-1] == CURRENT_PROJECT_VERSION

  def test_unknown_version_has_empty_path(self) -> None:
    assert _get_migration_path("99.0.0") == []

  def test_v0_1_migration_path(self) -> None:
    path = _get_migration_path("0.1")
    assert path == [
      "1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0",
      CURRENT_PROJECT_VERSION,
    ]

  def test_v1_4_migration_path(self) -> None:
    path = _get_migration_path("1.4.0")
    assert path == ["1.5.0", CURRENT_PROJECT_VERSION]

  def test_every_adjacent_transition_has_a_registered_migration(self) -> None:
    for from_version, to_version in zip(
      ALL_KNOWN_VERSIONS,
      ALL_KNOWN_VERSIONS[1:],
      strict=False,
    ):
      assert (from_version, to_version) in MIGRATION_REGISTRY

  def test_all_legacy_versions_migrate_to_current(self, tmp_path: Path) -> None:
    """Every legacy version migrates and validates at the current version."""
    for version in LEGACY_PROJECT_VERSIONS:
      legacy = {
        "project_id": f"test-{version}",
        "project_version": version,
        "pipeline_version": "0.1",
        "samples": [{"id": "s1", "channels": []}],
      }
      report = migrate_manifest_with_report(legacy)
      assert report.from_version == version
      assert report.to_version == CURRENT_PROJECT_VERSION
      assert report.was_migrated is True
      assert report.migration_path == tuple(_get_migration_path(version))
      assert report.migrated["project_version"] == CURRENT_PROJECT_VERSION
      # The migrated manifest should validate.
      validate_manifest(report.migrated)

  def test_migration_idempotent_at_current(self) -> None:
    """Migrating an already-current manifest is idempotent."""
    current = {
      **MINIMAL_MANIFEST,
      "project_version": CURRENT_PROJECT_VERSION,
      "samples": [{"id": "s1", "channels": []}],
    }
    r1 = migrate_manifest_with_report(current)
    r2 = migrate_manifest_with_report(r1.migrated)
    assert r1.was_migrated is False
    assert r2.was_migrated is False
    assert r1.migrated == r2.migrated

  def test_unsupported_version_rejected_without_mutation(self) -> None:
    future = {
      **MINIMAL_MANIFEST,
      "project_version": "99.0.0",
      "future_extension": {"keep": True},
    }
    original = json.loads(json.dumps(future))
    with pytest.raises(ProjectMigrationError) as error:
      migrate_manifest_with_report(future)
    assert error.value.code == "unsupported_project_version"
    assert future == original


# -- Atomic write --


class TestAtomicWrite:
  """Test atomic_write_json and save_project atomic behavior."""

  def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    atomic_write_json(target, {"key": "value"})
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"key": "value"}

  def test_atomic_write_replaces_existing(self, tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["v"] == 2

  def test_atomic_write_on_failure_preserves_original(self, tmp_path: Path) -> None:
    """Simulate write failure by making the directory read-only."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    target = subdir / "data.json"
    atomic_write_json(target, {"v": 1})

    # Make the subdirectory read-only to trigger an atomic write failure.
    subdir.chmod(0o444)
    try:
      with pytest.raises(PermissionError):
        atomic_write_json(target, {"v": 2})
    finally:
      subdir.chmod(0o755)
    # After restoring permissions, original file should still be intact.
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["v"] == 1
    # No leftover temp files.
    tmp_files = list(subdir.glob("*.tmp"))
    assert tmp_files == []

  def test_replace_failure_preserves_original_and_cleans_temp(
    self,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
  ) -> None:
    target = tmp_path / "data.json"
    atomic_write_json(target, {"v": 1})

    def fail_replace(*args, **kwargs) -> None:
      raise OSError("simulated replace failure")

    monkeypatch.setattr("flowdesk_storage.serialization.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
      atomic_write_json(target, {"v": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
    assert list(tmp_path.glob("*.tmp")) == []


# -- Newer schema rejection --


class TestNewerSchemaRejection:
  """Newer unsupported schema must not be modified on load or save."""

  def test_load_rejects_newer_version(self, tmp_path: Path) -> None:
    bundle = tmp_path / "newer.flowdesk"
    bundle.mkdir()
    future = {
      "project_id": "future_proj",
      "project_version": "99.0.0",
      "pipeline_version": "1.0",
      "samples": [],
    }
    (bundle / "manifest.json").write_text(
      json.dumps(future),
      encoding="utf-8",
    )
    with pytest.raises(ProjectMigrationError, match="unsupported project version"):
      load_project(bundle)
    # Original file must be unchanged.
    remaining = json.loads(
      (bundle / "manifest.json").read_text(encoding="utf-8")
    )
    assert remaining["project_version"] == "99.0.0"

  def test_save_rejects_newer_version(self, tmp_path: Path) -> None:
    bundle = tmp_path / "newer.flowdesk"
    future = {
      "project_id": "future_proj",
      "project_version": "99.0.0",
      "pipeline_version": "1.0",
      "samples": [],
    }
    with pytest.raises(ProjectMigrationError, match="unsupported project version"):
      save_project(bundle, future)
    # No partial write.
    assert not bundle.exists()

  def test_save_project_is_atomic(self, tmp_path: Path) -> None:
    """save_project uses atomic writes; failure should not corrupt."""
    bundle = tmp_path / "test.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST)

    manifest_path = bundle / "manifest.json"
    assert manifest_path.exists()

    # Re-save should succeed atomically.
    save_project(bundle, MINIMAL_MANIFEST)
    reloaded = load_project(bundle)
    assert reloaded["project_id"] == "test_proj"

  def test_no_temp_files_left_after_save(self, tmp_path: Path) -> None:
    """After a successful save, no .tmp files remain."""
    bundle = tmp_path / "test.flowdesk"
    save_project(bundle, MINIMAL_MANIFEST)

    tmp_files = list(bundle.rglob("*.tmp"))
    assert tmp_files == []

  def test_legacy_save_preserves_pre_migration_backup(self, tmp_path: Path) -> None:
    bundle = tmp_path / "legacy.flowdesk"
    legacy = {
      "project_id": "legacy-project",
      "project_version": "1.4.0",
      "pipeline_version": "1.0",
      "samples": [{"id": "s1", "channels": []}],
    }

    save_project(bundle, legacy)

    backup_path = bundle / "backups" / "manifest.pre-migration-1.4.0.json"
    assert json.loads(backup_path.read_text(encoding="utf-8")) == legacy
    assert load_project(bundle)["project_version"] == CURRENT_PROJECT_VERSION


def test_sample_title_annotation_round_trip_is_non_destructive(tmp_path: Path) -> None:
  bundle = tmp_path / "titles.flowdesk"
  manifest = {
    **MINIMAL_MANIFEST,
    "samples": [{"id": "s1", "name": "Original", "path": "sample.fcs"}],
    "annotations": [{
      "sample_id": "s1", "keyword": "sample_title",
      "value": "Treatment A", "source": "workspace",
    }],
  }
  save_project(bundle, manifest)
  loaded = load_project(bundle)
  assert loaded["annotations"][0]["value"] == "Treatment A"
  assert loaded["samples"][0]["name"] == "Original"
