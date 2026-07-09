---
name: gate-engine
description: Guidance for implementing and reviewing Flowdesk gate representation, parent-child population relationships, analytical gate membership evaluation, gate cache invalidation, and gate-derived population frequencies. Use when changing rectangle, polygon, range, boolean gate definitions, gate execution, or gate statistics.
---

# Gate Engine Skill

Use this skill when changing gate representation or membership evaluation.

- Store gates in data coordinates or transformed data coordinates, not screen pixels.
- Support rectangle, polygon, range, and boolean gate definitions.
- Preserve parent-child population relationships.
- Compute frequency of parent and frequency of total from full event data.
- Invalidate caches when compensation, derived parameters, transforms, or gates change.
- Do not use GUI display downsampling for analytical results.
