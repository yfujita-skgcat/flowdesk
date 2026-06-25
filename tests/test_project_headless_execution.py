def test_pipeline_runner_imports_without_gui_dependency() -> None:
  import flowdesk_core.pipeline_runner as pipeline_runner

  assert pipeline_runner.PipelineRunner is not None
