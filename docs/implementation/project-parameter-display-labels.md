# Project parameter display labels

## Goal

Channels must expose both the selected sample's real metadata and a project-wide
display mapping. The mapping is presentation-only: it must never rename a
`ChannelSpec.id`, derived output ID, expression input, gate axis, transform
parameter, statistic parameter, or exported scientific value.

## Persisted contract

The project manifest may contain:

```json
"parameter_display_mappings": [
  {
    "parameter_id": "stable-channel-or-derived-output-id",
    "plot_label": "APC-A",
    "annotation": "iRFP670"
  }
]
```

`parameter_id` is the stable acquired channel ID or derived `output_channel_id`.
Unknown fields must survive load/save. Empty `plot_label` and `annotation` are
equivalent to no override and may be omitted when the user clears both cells.

The display resolver returns:

1. `annotation + " (" + plot_label + ")"` when both are present;
2. `plot_label` when only the plot label is present;
3. the caller's existing label when no mapping is present.

The mapping key is never `$PnN` alone. `$PnN`/`$PnS` text is shown for user
recognition, while stable identity remains the actual binding. If two files have
different stable identities despite similar visible names, they appear as
separate project rows and are not silently merged.

## Channels workspace

The upper table is one row per parameter in the selected sample. Acquired rows
include FCS metadata (`$PnN`, `$PnS`, detector, stain, FCS index, and optional
numeric metadata); derived rows show `—` for fields that do not originate in FCS.
The lower editable table is the project-wide mapping union:

```text
Actual parameter | Plot display name | Biological label / note | Samples
```

The actual parameter cell is read-only. Only the two display fields are editable.
Editing emits a GUI state change, marks the project dirty, refreshes all display
consumers, and does not start a scientific pipeline run.

The `Samples` column is project coverage, not an event-data cache indicator. For
acquired parameters it counts the samples whose FCS metadata contains the stable
channel identity. For a derived definition it counts all samples in the project,
because the definition is project-scoped and the pipeline evaluates it for each
sample. It must not use the lazily populated GUI `_sample_data` cache; changing
the active sample must therefore not change this value.

## Consumers

The resolver is applied to:

- Plot Parameters selector labels and automatic axis labels;
- Channels selected-sample parameter catalog;
- Derived Parameters `Insert parameter` and `Expression inputs` labels;
- batch plot metadata labels when no fixed custom axis label is persisted.

Qt item data and all headless requests continue to use stable IDs. Derived
expressions insert IDs, not aliases. A fixed custom X/Y axis label in Plot
Presentation remains an explicit view-level override and takes precedence over
the automatic parameter label.

## Required tests

- round-trip the mapping through project save/load;
- resolve `iRFP670 (APC-A)` and fallback labels deterministically;
- show acquired metadata and derived blank metadata in the upper table;
- edit both lower-table display fields and emit the stable parameter ID;
- refresh Plot, Derived Parameters, Channels, and batch export labels without
  changing IDs, expressions, gates, transforms, statistics, or pipeline results;
- keep different stable identities with similar `$PnN`/`$PnS` values separate.
