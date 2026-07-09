---
name: compensation
description: Guidance for implementing and reviewing Flowdesk compensation matrix representation, channel alignment, compensation execution order, source metadata, and raw event immutability. Use when changing compensation matrix models, spillover application, matrix provenance, or compensation-related tests.
---

# Compensation Skill

Use this skill when changing compensation matrix representation or application.

- Store matrix id, name, source, channels, matrix values, creation metadata, and notes.
- Align matrix rows and columns by channel id/name before applying.
- Treat compensation as a derived analysis step; never mutate raw events.
- Apply compensation before default derived parameter calculation.
- Record any matrix source ambiguity in docs and tests.
