# Pipeline Runner

`PipelineRunner` is the GUI-independent execution engine.

Inputs: project bundle or project object, execution profile, output directory, and optional cache policy.

Outputs: `ExecutionReport`, population statistics, export files, and reproducibility metadata.

Execution order:

1. Validate project manifest.
2. Resolve sample paths.
3. Apply compensation.
4. Compute derived parameters.
5. Apply transforms.
6. Evaluate gates.
7. Compute population statistics.
8. Export results.
9. Save an execution report.

Errors should include enough context to reproduce the failure. Execution reports should include software version, project version, pipeline version, input file path, size, mtime, and hash when available.
