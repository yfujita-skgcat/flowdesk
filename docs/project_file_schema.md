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

The current project format is `1.8.0`. Analysis transforms require
`role: analysis`; geometric gate axes reference them using only
`x_transform_id`/`y_transform_id`. `plot_display_settings` remains explicitly
display-only. Formal `logicle` transforms require `T`, `W`, `M`, `A`, and an
implementation version. Version
`1.2.0` transform definitions
named `logicle_like` migrate to `legacy_logicle_approximation` with a persisted
warning and unchanged numeric settings.

Plot views store the display-only scatter limit as
`rendering_downsample.max_points`. The default is `20000`; `0` disables scatter
sampling. The current main-plot value is also mirrored in
`plot_display_settings.display_max_points` for GUI restoration. Neither field may be
used by the pipeline runner for gates, population counts, frequencies, or statistics.
Plot view `presentation.single_color` stores the six-digit hexadecimal color used
when a scatter/dot view selects `Single color`; it is display-only and is ignored
when density coloring or an overlay source is active.
`presentation.single_dot_size` stores the display-only base-layer marker size for
single-sample scatter/dot views. Overlay source marker sizes remain in
`presentation.source_styles`.
