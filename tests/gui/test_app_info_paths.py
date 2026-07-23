"""Tests for packaged-app identity and user-writable directories."""

from __future__ import annotations

import pytest

from flowdesk_qt.app_info import APP_NAME, application_version
from flowdesk_qt.app_paths import app_data_directory, cache_directory

pytestmark = pytest.mark.gui


def test_application_version_is_available(qapp) -> None:
  assert APP_NAME == "Flowdesk"
  assert application_version()


def test_user_directories_are_absolute_and_created(qapp) -> None:
  cache = cache_directory()
  app_data = app_data_directory()
  assert cache.is_absolute()
  assert app_data.is_absolute()
  assert cache.is_dir()
  assert app_data.is_dir()
