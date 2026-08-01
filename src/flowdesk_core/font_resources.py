"""Deterministic fonts used by the headless raster renderer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from PIL import ImageFont


class BundledFontError(RuntimeError):
  """Raised when a required bundled scalable font cannot be loaded."""


_FONT_PACKAGE = "flowdesk_core"
_FONT_DIRECTORY = ("assets", "fonts")
_FONT_FILES = {
  False: "DejaVuSans.ttf",
  True: "DejaVuSans-Bold.ttf",
}


def bundled_font_filename(*, bold: bool = False) -> str:
  """Return the deterministic bundled font filename for a weight."""
  return _FONT_FILES[bool(bold)]


@contextmanager
def bundled_font_path(*, bold: bool = False) -> Iterator[Path]:
  """Yield a source- or frozen-safe path to a bundled font resource."""
  resource = files(_FONT_PACKAGE)
  for part in (*_FONT_DIRECTORY, bundled_font_filename(bold=bold)):
    resource = resource.joinpath(part)
  try:
    with as_file(resource) as path:
      if not path.is_file():
        raise BundledFontError(f"bundled font is missing: {resource}")
      yield path
  except BundledFontError:
    raise
  except (OSError, ModuleNotFoundError, TypeError) as exc:
    raise BundledFontError(
      f"unable to resolve bundled font {bundled_font_filename(bold=bold)}"
    ) from exc


def load_bundled_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
  """Load the requested scalable bundled font at an explicit pixel size."""
  if size < 1:
    raise ValueError("font size must be positive")
  with bundled_font_path(bold=bold) as path:
    try:
      font = ImageFont.truetype(str(path), size)
    except OSError as exc:
      raise BundledFontError(
        f"unable to load bundled font {path.name} at {size}px"
      ) from exc
  if not isinstance(font, ImageFont.FreeTypeFont):
    raise BundledFontError(f"bundled font is not scalable: {path.name}")
  return font
