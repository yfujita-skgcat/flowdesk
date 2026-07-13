# Project File Schema

Flowdesk projects are directory bundles, not single JSON files.

```text
example_project.flowdesk/
  manifest.json
  gates/
    gating_strategy.json
  cache/
  exports/
```

Samples initially use path references instead of copying FCS data into the project.

`manifest.json` stores project id, project version, pipeline version, timestamps, samples, compensation matrices, derived parameters, transforms, gating strategies, export settings, execution profiles, software metadata, sample path resolution policy, and the last execution report path.

Execution profiles allow one project to store multiple run configurations.

The current project format is `1.4.0`. It adds the formal `logicle` transform,
whose `T`, `W`, `M`, `A`, and implementation version are mandatory. Version
`1.2.0` transform definitions
named `logicle_like` migrate to `legacy_logicle_approximation` with a persisted
warning and unchanged numeric settings.
