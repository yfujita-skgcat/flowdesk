# Derived Parameters Skill

Use this skill when changing derived parameter definitions or expression handling.

- Derived parameters must be usable like ordinary channels for plot, gate, and export.
- Store id, name, expression, source stage, input parameters, output label, invalid value policy, and notes.
- Do not use arbitrary Python `eval`.
- Implement expression handling through a safe parser/evaluator.
- Default source stage is `compensated`.
- Division by zero should produce `NaN`; export must handle `NaN` explicitly.
