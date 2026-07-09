---
name: fcs-io
description: Guidance for implementing and reviewing Flowdesk FCS loading, metadata parsing, event array handling, channel identity mapping, and spillover matrix extraction. Use when changing FCS readers, FCS metadata models, channel naming, raw event immutability, or FCS fixture strategy.
---

# FCS I/O Skill

Use this skill when changing FCS loading, metadata parsing, channel mapping, or spillover matrix extraction.

- Keep raw FCS event data immutable.
- Parse metadata separately from event arrays.
- Preserve original channel names and provide stable internal ids.
- Extract spillover matrix metadata into `CompensationMatrixSpec`.
- Do not put FCS parsing logic in Qt widgets.
- Add synthetic tests first; add real FCS fixtures only when small and explicitly licensed.
