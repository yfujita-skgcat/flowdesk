"""GUI-independent input file fingerprinting for reproducible reconnects."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileFingerprint:
  """Persistable identity and diagnostic metadata for one input file."""

  size: int
  mtime_ns: int
  hash_algorithm: str
  hash_value: str

  def to_mapping(self) -> dict[str, Any]:
    """Return the JSON-serializable project representation."""
    return asdict(self)

  @classmethod
  def from_mapping(cls, value: dict[str, Any]) -> FileFingerprint:
    """Build a validated fingerprint from project data."""
    algorithm = str(value.get("hash_algorithm", ""))
    if algorithm not in hashlib.algorithms_available:
      raise ValueError(f"unsupported fingerprint hash algorithm {algorithm!r}")
    size = value.get("size")
    mtime_ns = value.get("mtime_ns")
    hash_value = value.get("hash_value")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
      raise ValueError("fingerprint size must be a non-negative integer")
    if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool) or mtime_ns < 0:
      raise ValueError("fingerprint mtime_ns must be a non-negative integer")
    if not isinstance(hash_value, str) or not hash_value:
      raise ValueError("fingerprint hash_value must be a non-empty string")
    return cls(size, mtime_ns, algorithm, hash_value)


@dataclass(frozen=True)
class FingerprintComparison:
  """Detailed comparison; content equality is determined by the hash."""

  content_matches: bool
  size_matches: bool
  mtime_matches: bool


def compute_file_fingerprint(
  path: str | Path,
  hash_algorithm: str = "sha256",
  chunk_size: int = 1024 * 1024,
) -> FileFingerprint:
  """Hash *path* without loading the entire FCS file into memory."""
  source = Path(path)
  digest = hashlib.new(hash_algorithm)
  with source.open("rb") as handle:
    while chunk := handle.read(chunk_size):
      digest.update(chunk)
  stat = source.stat()
  return FileFingerprint(
    size=stat.st_size,
    mtime_ns=stat.st_mtime_ns,
    hash_algorithm=hash_algorithm,
    hash_value=digest.hexdigest(),
  )


def compare_file_fingerprints(
  expected: FileFingerprint,
  candidate: FileFingerprint,
) -> FingerprintComparison:
  """Compare fingerprints without treating timestamps as file identity."""
  content_matches = (
    expected.hash_algorithm == candidate.hash_algorithm
    and expected.hash_value == candidate.hash_value
  )
  return FingerprintComparison(
    content_matches=content_matches,
    size_matches=expected.size == candidate.size,
    mtime_matches=expected.mtime_ns == candidate.mtime_ns,
  )
