---
name: derived-parameters
description: Guidance for implementing and reviewing Flowdesk derived parameter definitions, safe expression parsing and evaluation, source stage handling, invalid value policy, and export behavior. Use when changing derived channel models, expression syntax, expression execution, or NaN handling for derived parameters.
---

# Derived Parameters Skill

Use this skill when changing derived parameter definitions or expression handling.

- Derived parameters must be usable like ordinary channels for plot, gate, and export.
- Store id, name, expression, source stage, input parameters, output label, invalid value policy, and notes.
- Do not use arbitrary Python `eval`.
- Implement expression handling through a safe parser/evaluator.
- Default source stage is `compensated`.
- Division by zero should produce `NaN`; export must handle `NaN` explicitly.
