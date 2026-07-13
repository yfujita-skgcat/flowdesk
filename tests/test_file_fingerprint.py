from pathlib import Path

import pytest

from flowdesk_core.file_fingerprint import (
  FileFingerprint,
  compare_file_fingerprints,
  compute_file_fingerprint,
)


def test_file_fingerprint_round_trip_and_content_comparison(tmp_path: Path) -> None:
  first = tmp_path / "first.fcs"
  second = tmp_path / "second.fcs"
  first.write_bytes(b"same FCS bytes")
  second.write_bytes(b"same FCS bytes")

  expected = compute_file_fingerprint(first)
  candidate = compute_file_fingerprint(second)
  restored = FileFingerprint.from_mapping(expected.to_mapping())

  assert restored == expected
  comparison = compare_file_fingerprints(expected, candidate)
  assert comparison.content_matches
  assert comparison.size_matches


def test_file_fingerprint_detects_changed_content_with_same_size(tmp_path: Path) -> None:
  first = tmp_path / "first.fcs"
  second = tmp_path / "second.fcs"
  first.write_bytes(b"abc")
  second.write_bytes(b"xyz")

  comparison = compare_file_fingerprints(
    compute_file_fingerprint(first),
    compute_file_fingerprint(second),
  )

  assert comparison.size_matches
  assert not comparison.content_matches


@pytest.mark.parametrize(
  "field,value",
  [("size", -1), ("mtime_ns", -1), ("hash_algorithm", "no-such-hash"),
   ("hash_value", "")],
)
def test_invalid_persisted_fingerprint_is_rejected(field: str, value: object) -> None:
  mapping: dict[str, object] = {
    "size": 1,
    "mtime_ns": 1,
    "hash_algorithm": "sha256",
    "hash_value": "abc",
  }
  mapping[field] = value
  with pytest.raises(ValueError):
    FileFingerprint.from_mapping(mapping)
