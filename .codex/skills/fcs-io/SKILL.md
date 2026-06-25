# FCS I/O Skill

Use this skill when changing FCS loading, metadata parsing, channel mapping, or spillover matrix extraction.

- Keep raw FCS event data immutable.
- Parse metadata separately from event arrays.
- Preserve original channel names and provide stable internal ids.
- Extract spillover matrix metadata into `CompensationMatrixSpec`.
- Do not put FCS parsing logic in Qt widgets.
- Add synthetic tests first; add real FCS fixtures only when small and explicitly licensed.
