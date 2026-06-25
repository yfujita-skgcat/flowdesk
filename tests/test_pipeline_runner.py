from flowdesk_core.pipeline_runner import run_project_pipeline


def test_project_object_can_call_pipeline_runner() -> None:
  project = {
    "project_id": "example",
    "pipeline_version": "0.1",
    "execution_profiles": [{"id": "default", "name": "Default analysis"}],
    "population_results": [
      {
        "sample_id": "s1",
        "population_id": "all_events",
        "event_count": 10,
        "frequency_of_parent": None,
        "frequency_of_total": 1.0,
      }
    ],
  }

  report = run_project_pipeline(project, execution_profile_id="default")

  assert report.execution_profile_id == "default"
  assert report.population_results[0].event_count == 10
