"""GUI diagnostics, callback logging, and debug artifact helpers."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def strict_callbacks_enabled() -> bool:
  return os.environ.get("FLOWDESK_GUI_STRICT_CALLBACKS") == "1"


def invoke_callback(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
  """Invoke a GUI callback, always logging failures and optionally re-raising."""
  try:
    return callback(*args, **kwargs)
  except Exception:
    logger.exception("GUI callback failed: %r", callback)
    if strict_callbacks_enabled():
      raise
    return None


def configure_gui_logging(
  artifacts_dir: str | Path,
  log_level: str = "INFO",
) -> Path:
  """Configure the Flowdesk GUI file log and return its path."""
  log_dir = Path(artifacts_dir) / "logs"
  log_dir.mkdir(parents=True, exist_ok=True)
  log_path = log_dir / "application.log"
  handler = logging.FileHandler(log_path, encoding="utf-8")
  handler.setFormatter(
    logging.Formatter(
      "%(asctime)s %(levelname)s %(name)s pid=%(process)d "
      "thread=%(threadName)s %(message)s"
    )
  )
  root = logging.getLogger("flowdesk_qt")
  root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
  root.addHandler(handler)
  return log_path


def install_exception_hook() -> Callable[..., Any]:
  """Install an exception hook that logs and then calls the original hook."""
  original_hook = sys.excepthook

  def hook(exc_type: type[BaseException], exc: BaseException, traceback: Any) -> None:
    logger.critical("Unhandled GUI exception", exc_info=(exc_type, exc, traceback))
    original_hook(exc_type, exc, traceback)

  sys.excepthook = hook
  return original_hook


def default_run_id() -> str:
  return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def write_json_artifact(path: str | Path, value: object) -> None:
  artifact_path = Path(path)
  artifact_path.parent.mkdir(parents=True, exist_ok=True)
  artifact_path.write_text(
    json.dumps(value, indent=2, sort_keys=True, default=str),
    encoding="utf-8",
  )
