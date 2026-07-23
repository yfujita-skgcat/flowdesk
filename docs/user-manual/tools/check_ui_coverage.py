#!/usr/bin/env python3
"""Static UI coverage check for the Flowdesk Markdown user manual.

The checker scans ``src/flowdesk_qt`` without importing PySide6. It verifies:

1. every literal ``setObjectName(...)`` value appears in the manual; and
2. every literal label used by actions, buttons, checkboxes, menus, tabs, and
   combo-box items appears in the manual after light normalization.

Dynamic controls and standard Qt dialog buttons remain a manual-review item and
are listed separately in the manual's UI inventory.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path


INTERACTIVE_CONSTRUCTORS = {
  "QAction",
  "QPushButton",
  "QCheckBox",
  "QRadioButton",
  "QToolButton",
}
INTERACTIVE_TEXT_METHODS = {
  "addAction",
  "addMenu",
  "addTab",
  "addItem",
  "addItems",
}


@dataclass(frozen=True)
class Occurrence:
  module: str
  line: int
  kind: str
  text: str


def called_name(node: ast.AST) -> str:
  if isinstance(node, ast.Name):
    return node.id
  if isinstance(node, ast.Attribute):
    return node.attr
  return ""


def literal_strings(node: ast.AST) -> list[str]:
  if isinstance(node, ast.Constant) and isinstance(node.value, str):
    return [node.value]
  if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
    values: list[str] = []
    for element in node.elts:
      values.extend(literal_strings(element))
    return values
  return []


def normalize(text: str) -> str:
  text = unicodedata.normalize("NFKC", text)
  text = text.replace("&", "")
  text = text.replace("…", "...")
  text = re.sub(r"[`*_#|<>]", "", text)
  text = re.sub(r"\s+", " ", text)
  return text.strip().casefold()


def scan_python(
  source_dir: Path,
) -> tuple[list[Occurrence], list[Occurrence], list[Occurrence]]:
  object_names: list[Occurrence] = []
  dynamic_object_names: list[Occurrence] = []
  interactive_texts: list[Occurrence] = []

  for path in sorted(source_dir.glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = path.name
    for node in ast.walk(tree):
      if not isinstance(node, ast.Call):
        continue
      called = called_name(node.func)

      if called == "setObjectName" and node.args:
        values = literal_strings(node.args[0])
        if values:
          for value in values:
            object_names.append(Occurrence(module, node.lineno, "objectName", value))
        else:
          try:
            expression = ast.unparse(node.args[0])
          except Exception:
            expression = "<dynamic expression>"
          dynamic_object_names.append(
            Occurrence(module, node.lineno, "dynamic objectName", expression)
          )

      if called in INTERACTIVE_CONSTRUCTORS and node.args:
        for value in literal_strings(node.args[0]):
          if value.strip():
            interactive_texts.append(Occurrence(module, node.lineno, called, value))

      if called in INTERACTIVE_TEXT_METHODS and node.args:
        for value in literal_strings(node.args[0]):
          if value.strip():
            interactive_texts.append(Occurrence(module, node.lineno, called, value))

  return object_names, dynamic_object_names, interactive_texts


def unique_occurrences(items: list[Occurrence]) -> list[Occurrence]:
  seen: set[tuple[str, str]] = set()
  result: list[Occurrence] = []
  for item in items:
    key = (item.kind, item.text)
    if key in seen:
      continue
    seen.add(key)
    result.append(item)
  return result


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--source", type=Path, required=True)
  parser.add_argument("--manual", type=Path, required=True)
  parser.add_argument("--report", type=Path)
  args = parser.parse_args()

  manual_raw = args.manual.read_text(encoding="utf-8")
  manual_normalized = normalize(manual_raw)
  object_names, dynamic_objects, interactive_texts = scan_python(args.source)

  missing_objects = [item for item in object_names if item.text not in manual_raw]
  unique_interactive = unique_occurrences(interactive_texts)
  missing_interactive = [
    item for item in unique_interactive
    if normalize(item.text) not in manual_normalized
  ]

  module_count = len(list(args.source.glob("*.py")))
  result_passed = not missing_objects and not missing_interactive

  lines = [
    "# Flowdesk UI coverage report",
    "",
    f"- Source directory: `{args.source}`",
    f"- Manual: `{args.manual}`",
    f"- Python GUI modules scanned: {module_count}",
    f"- Literal objectName occurrences: {len(object_names)}",
    f"- Unique literal objectName values: {len({item.text for item in object_names})}",
    f"- Dynamic objectName expressions: {len(dynamic_objects)}",
    f"- Interactive UI text occurrences: {len(interactive_texts)}",
    f"- Unique interactive UI text literals: {len(unique_interactive)}",
    f"- Missing literal objectName values: {len(missing_objects)}",
    f"- Missing interactive UI text literals: {len(missing_interactive)}",
    "",
    "## Result",
    "",
  ]
  if result_passed:
    lines.append(
      "**PASS:** Every literal `setObjectName(...)` value and every literal label "
      "used by actions, buttons, checkboxes, menus, tabs, and combo-box items found "
      "by the static scan is represented in the manual."
    )
  else:
    lines.append("**FAIL:** One or more statically discoverable UI elements are absent.")

  lines.extend(["", "## Dynamic objectName expressions", ""])
  if dynamic_objects:
    lines.extend(
      f"- `{item.module}:{item.line}` — `{item.text}`" for item in dynamic_objects
    )
  else:
    lines.append("None.")

  lines.extend(["", "## Missing literal objectName values", ""])
  if missing_objects:
    lines.extend(
      f"- `{item.module}:{item.line}` — `{item.text}`" for item in missing_objects
    )
  else:
    lines.append("None.")

  lines.extend(["", "## Missing interactive UI text literals", ""])
  if missing_interactive:
    lines.extend(
      f"- `{item.module}:{item.line}` `{item.kind}` — `{item.text}`"
      for item in missing_interactive
    )
  else:
    lines.append("None.")

  lines.extend([
    "",
    "## Scope limitation",
    "",
    "This is a static source scan and does not import or run PySide6. Runtime-generated "
    "controls, conditional menu branches, standard `QDialogButtonBox` buttons, and controls "
    "whose labels are assembled from variables still require source review. These categories "
    "are documented explicitly in section 19.2 of the manual.",
    "",
  ])

  report = "\n".join(lines)
  if args.report:
    args.report.write_text(report, encoding="utf-8")
  print(report)
  return 0 if result_passed else 1


if __name__ == "__main__":
  sys.exit(main())
