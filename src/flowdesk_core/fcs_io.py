"""FCS I/O module wrapping flowio for reading and writing FCS files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# type: ignore[import-untyped]
import flowio  # type: ignore[import-untyped]
import numpy as np
from flowio.exceptions import FlowIOException, MultipleDataSetsError  # type: ignore[import-untyped]

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.models import ChannelSpec, CompensationMatrixSpec

PathLike = str | os.PathLike[str]


class FcsIoError(FlowdeskError):
  """Error during FCS file I/O operations."""


@dataclass(frozen=True)
class FcsFileInfo:
  """Metadata and channel specifications extracted from an FCS file."""

  fcs_version: str
  instrument: str
  date: str
  sample: str
  event_count: int
  channel_count: int
  channels: tuple[ChannelSpec, ...]
  metadata: dict[str, Any]


def _build_channel_specs(flow_data: flowio.FlowData) -> tuple[ChannelSpec, ...]:
  """Build ChannelSpec instances from flowio channel metadata."""
  specs: list[ChannelSpec] = []
  for idx in range(flow_data.channel_count):
    ch_info = flow_data.channels.get(idx + 1, {})
    pnn = ch_info.get("pnn", f"P{idx + 1}N")
    png = ch_info.get("png", "")
    pne = ch_info.get("pne", 0)
    pnr = ch_info.get("pnr", 0.0)

    specs.append(
      ChannelSpec(
        id=f"ch_{idx}",
        name=pnn,
        short_name=None,
        detector=None,
        unit=None,
        metadata={
          "png": png,
          "pne": pne,
          "pnr": pnr,
        },
      )
    )
  return tuple(specs)


def _build_metadata_dict(flow_data: flowio.FlowData) -> dict[str, Any]:
  """Build a metadata dictionary from flowio text and header sections."""
  result: dict[str, Any] = {}
  if hasattr(flow_data, "text") and flow_data.text is not None:
    result.update(flow_data.text)
  if hasattr(flow_data, "header") and flow_data.header is not None:
    result.update(flow_data.header)
  return result


def read_fcs_info(path: PathLike) -> FcsFileInfo:
  """Read FCS file metadata and channel specs without loading event data.

  Args:
    path: Path to the FCS file.

  Returns:
    FcsFileInfo with metadata and channel specifications.

  Raises:
    FcsIoError: If the file cannot be read or is malformed.
  """
  try:
    flow_data = flowio.FlowData(path, only_text=True)
  except MultipleDataSetsError as exc:
    raise FcsIoError(
      f"Multi-well FCS file is not supported: {path}. "
      "Please split into single-sample files first."
    ) from exc
  except FlowIOException as exc:
    raise FcsIoError(f"Failed to read FCS file metadata: {path}") from exc
  except Exception as exc:
    raise FcsIoError(f"Failed to read FCS file: {path}") from exc

  text = flow_data.text or {}
  header = flow_data.header or {}

  fcs_version = getattr(flow_data, "version", "unknown") or "unknown"
  instrument = text.get("$INST", header.get("$INST", ""))
  date_str = text.get("$DATE", header.get("$DATE", ""))
  sample = text.get("$SMP", header.get("$SMP", ""))
  event_count = getattr(flow_data, "event_count", 0) or 0
  channel_count = getattr(flow_data, "channel_count", 0) or 0

  channels = _build_channel_specs(flow_data)
  metadata = _build_metadata_dict(flow_data)

  return FcsFileInfo(
    fcs_version=str(fcs_version),
    instrument=str(instrument),
    date=str(date_str),
    sample=str(sample),
    event_count=int(event_count),
    channel_count=int(channel_count),
    channels=channels,
    metadata=metadata,
  )


def read_fcs_events(
  path: PathLike,
  preprocess: bool = True,
) -> tuple[FcsFileInfo, np.ndarray]:
  """Read FCS file with event data.

  Args:
    path: Path to the FCS file.
    preprocess: Whether to apply gain, log, and time scaling.

  Returns:
    Tuple of FcsFileInfo and a 2D numpy array of event data.
    The returned array is immutable.

  Raises:
    FcsIoError: If the file cannot be read or is malformed.
  """
  try:
    flow_data = flowio.FlowData(path)
  except MultipleDataSetsError as exc:
    raise FcsIoError(
      f"Multi-well FCS file is not supported: {path}. "
      "Please split into single-sample files first."
    ) from exc
  except FlowIOException as exc:
    raise FcsIoError(f"Failed to read FCS file: {path}") from exc
  except Exception as exc:
    raise FcsIoError(f"Failed to read FCS file: {path}") from exc

  channels = _build_channel_specs(flow_data)
  metadata = _build_metadata_dict(flow_data)

  text = flow_data.text or {}
  header = flow_data.header or {}

  fcs_version = getattr(flow_data, "version", "unknown") or "unknown"
  instrument = text.get("$INST", header.get("$INST", ""))
  date_str = text.get("$DATE", header.get("$DATE", ""))
  sample = text.get("$SMP", header.get("$SMP", ""))
  event_count = getattr(flow_data, "event_count", 0) or 0
  channel_count = getattr(flow_data, "channel_count", 0) or 0

  try:
    events = flow_data.as_array(preprocess=preprocess)
  except Exception as exc:
    raise FcsIoError(
      f"Failed to load event data from FCS file: {path}"
    ) from exc

  events.setflags(write=False)

  info = FcsFileInfo(
    fcs_version=str(fcs_version),
    instrument=str(instrument),
    date=str(date_str),
    sample=str(sample),
    event_count=int(event_count),
    channel_count=int(channel_count),
    channels=channels,
    metadata=metadata,
  )

  return info, events


def extract_spillover_matrix(
  path: PathLike,
) -> CompensationMatrixSpec | None:
  """Extract spillover matrix from FCS metadata if present.

  Parses the FlowJo-style $SPILLOVER or $SPILL keyword format:

  .. code-block:: text

    N
    chan1,v11,v12,...,v1N
    chan2,v21,v22,...,v2N
    ...
    chanN,vN1,vN2,...,vNN

  Args:
    path: Path to the FCS file.

  Returns:
    CompensationMatrixSpec if spillover data is present, else None.

  Raises:
    FcsIoError: If the file cannot be read or the spillover matrix
      is malformed.
  """
  try:
    flow_data = flowio.FlowData(path, only_text=True)
  except MultipleDataSetsError as exc:
    raise FcsIoError(
      f"Multi-well FCS file is not supported: {path}. "
      "Please split into single-sample files first."
    ) from exc
  except FlowIOException as exc:
    raise FcsIoError(f"Failed to read FCS file: {path}") from exc
  except Exception as exc:
    raise FcsIoError(f"Failed to read FCS file: {path}") from exc

  text = flow_data.text or {}
  spill_value = (
    text.get("$SPILLOVER")
    or text.get("$SPILL")
    or text.get("spillover")
    or text.get("spill")
  )

  if spill_value is None or spill_value.strip() == "":
    return None

  try:
    spill_text = str(spill_value)
  except Exception as exc:
    raise FcsIoError(
      f"Spillover metadata has unexpected type in FCS file: {path}"
    ) from exc

  try:
    parsed = _parse_spillover_text(spill_text, path)
  except ValueError as exc:
    raise FcsIoError(
      f"Malformed spillover matrix in FCS file: {path}. {exc}"
    ) from exc

  return parsed


def _parse_spillover_text(
  spill_text: str,
  path: PathLike,
) -> CompensationMatrixSpec:
  """Parse FlowJo-style spillover text into CompensationMatrixSpec."""
  lines = [line.strip() for line in spill_text.splitlines() if line.strip()]

  if len(lines) < 1:
    raise ValueError("spillover text is empty")

  try:
    num_channels = int(lines[0])
  except ValueError as exc:
    raise ValueError(
      f"first line of spillover must be an integer (got '{lines[0]}')"
    ) from exc

  data_lines = lines[1:]

  if len(data_lines) != num_channels:
    raise ValueError(
      f"expected {num_channels} data lines, got {len(data_lines)}"
    )

  channel_names: list[str] = []
  matrix_rows: list[list[float]] = []

  for row_idx, line in enumerate(data_lines):
    parts = [p.strip() for p in line.split(",")]

    if len(parts) != num_channels + 1:
      raise ValueError(
        f"row {row_idx + 1}: expected {num_channels + 1} comma-separated "
        f"values (channel name + {num_channels} numbers), "
        f"got {len(parts)}"
      )

    channel_names.append(parts[0])

    try:
      values = [float(v) for v in parts[1:]]
    except ValueError as exc:
      raise ValueError(
        f"row {row_idx + 1}: non-numeric value in spillover data: {exc}"
      ) from exc

    matrix_rows.append(values)

  matrix_tuple = tuple(tuple(row) for row in matrix_rows)
  channels_tuple = tuple(channel_names)

  return CompensationMatrixSpec(
    id="spill_fcs",
    name="FCS Spillover Matrix",
    source="fcs_metadata_spillover",
    channels=channels_tuple,
    matrix=matrix_tuple,
  )


def write_fcs_file(
  path: PathLike,
  event_data: np.ndarray,
  channel_names: list[str],
  metadata: dict[str, str] | None = None,
) -> None:
  """Write event data to a new FCS file.

  Args:
    path: Output FCS file path.
    event_data: 2D numpy array of event data.
    channel_names: List of channel names matching columns of event_data.
    metadata: Optional metadata key-value pairs.

  Raises:
    FcsIoError: If the file cannot be written.
  """
  if event_data.ndim != 2:
    raise FcsIoError("event_data must be a 2D numpy array")

  num_channels = event_data.shape[1]

  if len(channel_names) != num_channels:
    raise FcsIoError(
      f"channel_names length ({len(channel_names)}) does not match "
      f"number of data columns ({num_channels})"
    )

  flattened = event_data.flatten().tolist()

  try:
    with open(path, "wb") as fh:
      flowio.create_fcs(
        file_handle=fh,
        event_data=flattened,
        channel_names=channel_names,
        metadata_dict=metadata,
      )
  except FlowIOException as exc:
    raise FcsIoError(f"Failed to write FCS file: {path}") from exc
  except Exception as exc:
    raise FcsIoError(f"Failed to write FCS file: {path}") from exc
