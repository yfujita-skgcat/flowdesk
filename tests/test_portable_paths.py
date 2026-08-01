from pathlib import Path

from flowdesk_core.portable_paths import portable_filename_key, portable_output_component


def test_filename_key_collapses_case_and_unicode_normalization() -> None:
  left = portable_filename_key(Path("A\u030a/output.PNG"))
  right = portable_filename_key("\u00e5/OUTPUT.png")
  assert left == right


def test_output_component_avoids_windows_device_names_and_empty_values() -> None:
  assert portable_output_component("CON") == "_CON"
  assert portable_output_component("report. ") == "report"
  assert portable_output_component("***") == "output"
