# AI Development Workflow

Work in small, reviewable increments.

Before a change, identify the purpose, files to edit, and acceptance criteria. After a change, report tests run and remaining limitations.

Do not put scientific execution logic in Qt widgets. Do not use arbitrary Python `eval` for derived parameters. Do not add large FCS files to git.

When changing behavior that affects results, update the core model, schemas, docs, and tests before or alongside GUI work.

Review scientific assumptions explicitly. If a compensation, transform, or gate behavior is uncertain, document it and add a focused test or xfail.

## Implementation Guide Workflow

For each implementation task, the agent should first read `AGENTS.md` and the relevant file under `docs/implementation/`. The implementation is not complete until the guide's required tests and acceptance criteria have been addressed, or any skipped criterion is explicitly justified in the final report.

When creating a new task area, add a new implementation guide with scope, target files, implementation rules, required tests, and acceptance criteria before coding.
