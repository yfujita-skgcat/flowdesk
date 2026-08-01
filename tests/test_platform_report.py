from tools.platform_report import collect_report


def test_platform_report_contains_non_sensitive_runtime_identity() -> None:
  report = collect_report()
  assert report["os"]
  assert report["architecture"]
  assert report["python"]
  assert "packages" in report
  assert "filesystem_encoding" in report
