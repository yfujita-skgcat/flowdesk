---
name: qt-plot-widget
description: Guidance for implementing and reviewing Flowdesk Qt plotting widgets and gate editing UI while keeping scientific execution in GUI-independent core APIs. Use when changing PySide6 plot widgets, GUI gate editing, GUI-triggered analysis execution, or plotting display behavior.
---

# Qt Plot Widget Skill

Use this skill when changing Qt plotting or gate editing widgets.

- Qt widgets may call core APIs, update project state, and display results.
- Qt widgets must not implement FCS parsing, compensation, derived parameter calculation, gate membership, population statistics, or export logic.
- Gate editing should store data coordinates or transformed data coordinates.
- GUI-triggered execution must call the same pipeline runner used by CLI/headless execution.
