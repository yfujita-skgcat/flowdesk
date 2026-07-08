"""Inspect FCS file metadata."""

from __future__ import annotations

import sys

from flowdesk_core.fcs_io import FcsIoError, extract_spillover_matrix, read_fcs_info


def inspect_fcs_command(fcs_path: str) -> int:
  """CLI adapter for FCS metadata inspection.

  Prints file-level metadata and channel information to stdout.

  Args:
    fcs_path: Path to the FCS file.

  Returns:
    Exit code: 0 on success, 1 on error.
  """

  try:
    info = read_fcs_info(fcs_path)
  except FileNotFoundError as exc:
    print(f"Error: file not found: {fcs_path}", file=sys.stderr)
    print(f"  {exc}", file=sys.stderr)
    return 1
  except FcsIoError as exc:
    print(f"Error: {exc}", file=sys.stderr)
    return 1

  # ------------------------------------------------------------------
  # Print file metadata
  # ------------------------------------------------------------------
  print(f"FCS file: {fcs_path}")
  print(f"  FCS version:  {info.fcs_version}")
  print(f"  Instrument:   {info.instrument or '(none)'}")
  print(f"  Date:         {info.date or '(none)'}")
  print(f"  Sample:       {info.sample or '(none)'}")
  print(f"  Events:       {info.event_count}")
  print(f"  Channels:     {info.channel_count}")

  # ------------------------------------------------------------------
  # Print channel list
  # ------------------------------------------------------------------
  print()
  print("Channels:")
  for ch in info.channels:
    meta = ch.metadata or {}
    png = meta.get("png", "")
    pne = meta.get("pne", "")
    pnr = meta.get("pnr", "")
    extra = []
    if png:
      extra.append(f"gain={png}")
    if pne:
      extra.append(f"amplification={pne}")
    if pnr:
      extra.append(f"max_range={pnr}")
    detail = ", ".join(extra) if extra else ""
    print(f"  {ch.name:20s} {detail}")

  # ------------------------------------------------------------------
  # Check for spillover matrix
  # ------------------------------------------------------------------
  try:
    spill = extract_spillover_matrix(fcs_path)
    if spill is not None:
      print()
      print(f"Spillover matrix ({len(spill.channels)} channels):")
      print(f"  Channels: {', '.join(spill.channels)}")
      for row_idx, row in enumerate(spill.matrix):
        vals = ", ".join(f"{v:.4f}" for v in row)
        print(f"  {spill.channels[row_idx]:20s} [{vals}]")
    else:
      print()
      print("Spillover matrix: (none)")
  except FcsIoError as exc:
    print()
    print(f"Spillover matrix: error ({exc})")

  return 0
