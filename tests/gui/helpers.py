"""Helpers for GUI failure artifacts."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from flowdesk_qt.diagnostics import write_json_artifact

logger = logging.getLogger(__name__)


def sanitize_node_id(node_id: str) -> str:
  value = re.sub(r"[^A-Za-z0-9_.-]+", "_", node_id).strip("_")
  return value or "unknown-test"


def save_failure_artifacts(
  artifact_dir: Path,
  node_id: str,
  widgets: list[Any],
  failure_text: str,
) -> Path:
  """Save screenshots and state without raising artifact-specific failures."""
  test_dir = artifact_dir / "tests" / sanitize_node_id(node_id)
  try:
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "failure.txt").write_text(failure_text, encoding="utf-8")
  except Exception:
    logger.exception("Unable to create GUI failure artifact directory")
    return test_dir

  for index, widget in enumerate(widgets):
    try:
      name = "main-window.png" if index == 0 else f"visible-dialog-{index:02d}.png"
      widget.grab().save(str(test_dir / name), "PNG")
    except Exception:
      logger.exception("Unable to capture GUI screenshot for %r", widget)
    try:
      if index == 0 and hasattr(widget, "debug_state"):
        write_json_artifact(test_dir / "ui-state.json", widget.debug_state())
    except Exception:
      logger.exception("Unable to save GUI debug state for %r", widget)
  return test_dir
