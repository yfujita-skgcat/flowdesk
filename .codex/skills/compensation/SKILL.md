# Compensation Skill

Use this skill when changing compensation matrix representation or application.

- Store matrix id, name, source, channels, matrix values, creation metadata, and notes.
- Align matrix rows and columns by channel id/name before applying.
- Treat compensation as a derived analysis step; never mutate raw events.
- Apply compensation before default derived parameter calculation.
- Record any matrix source ambiguity in docs and tests.
