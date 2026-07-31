"""Scientific pipeline cache-key contracts."""

from copy import deepcopy

from flowdesk_storage.cache import build_pipeline_cache_key, definition_hash


def _project() -> dict[str, object]:
  return {
    "project_id": "cache-test",
    "samples": [{"id": "s1", "group_ids": ["g1"], "metadata": {"well": "A1"}}],
    "execution_profiles": [{"id": "default", "sample_selector": "all"}],
    "compensation_matrices": [{"id": "m1", "matrix": [[1.0]]}],
    "derived_parameters": [{"id": "d1", "expression": "x"}],
    "transforms": [{"id": "t1", "parameter": "x", "transform_type": "linear"}],
    "gating_strategies_data": {"default": {"gates": [{"id": "gate-1"}]}},
    "statistics": [{"id": "stat-1", "metric": "count"}],
  }


def test_definition_hash_is_order_independent() -> None:
  assert definition_hash({"b": 2, "a": [1, 2]}) == definition_hash(
    {"a": [1, 2], "b": 2}
  )


def test_cache_key_contains_input_and_stage_provenance_without_events() -> None:
  key = build_pipeline_cache_key(
    _project(), sample_id="s1", input_fingerprint="input-a"
  )
  mapping = key.to_mapping()
  assert mapping["input_fingerprint"] == "input-a"
  assert set(mapping["stage_hashes"]) == {
    "compensation", "derived_parameters", "transforms", "gating", "statistics",
  }
  assert all(len(value) == 64 for value in mapping["stage_keys"].values())
  assert "events" not in repr(mapping)


def test_upstream_changes_invalidate_only_downstream_stage_keys() -> None:
  original = build_pipeline_cache_key(
    _project(), sample_id="s1", input_fingerprint="input-a"
  )
  changed = deepcopy(_project())
  changed["derived_parameters"] = [{"id": "d1", "expression": "x + 1"}]
  updated = build_pipeline_cache_key(
    changed, sample_id="s1", input_fingerprint="input-a"
  )

  assert original.for_stage("compensation") == updated.for_stage("compensation")
  assert original.for_stage("derived_parameters") != updated.for_stage("derived_parameters")
  assert original.for_stage("transforms") != updated.for_stage("transforms")
  assert original.for_stage("gating") != updated.for_stage("gating")
  assert original.for_stage("statistics") != updated.for_stage("statistics")


def test_unrelated_display_and_runtime_fields_do_not_invalidate_scientific_keys() -> None:
  original = build_pipeline_cache_key(
    _project(), sample_id="s1", input_fingerprint="input-a"
  )
  changed = deepcopy(_project())
  changed["plot_display_settings"] = {"background_color": "#ffffff"}
  changed["batch_plot_exports"] = [{"id": "export", "output_dir": "/tmp/out"}]
  changed["runtime_options"] = {"max_workers": 8}
  updated = build_pipeline_cache_key(
    changed, sample_id="s1", input_fingerprint="input-a"
  )
  assert original.to_mapping()["stage_keys"] == updated.to_mapping()["stage_keys"]
