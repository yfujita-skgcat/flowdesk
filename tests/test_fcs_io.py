"""Tests for the fcs_io module."""

from __future__ import annotations

from pathlib import Path

import flowio
import numpy as np
import pytest

from flowdesk_core.errors import FlowdeskError
from flowdesk_core.fcs_io import (
    FcsFileInfo,
    FcsIoError,
    extract_spillover_matrix,
    read_fcs_events,
    read_fcs_info,
    write_fcs_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_fcs_with_events(
    tmp_path: Path,
    num_events: int = 10,
    num_channels: int = 3,
    channel_names: list[str] | None = None,
    metadata_dict: dict[str, str] | None = None,
) -> Path:
    """Create a synthetic FCS file using flowio."""
    if channel_names is None:
        channel_names = [f"FL{i}-A" for i in range(1, num_channels + 1)]
    event_data = np.random.rand(num_events * num_channels).tolist()
    path = tmp_path / "test.fcs"
    with open(path, "wb") as fh:
        flowio.create_fcs(
            file_handle=fh,
            event_data=event_data,
            channel_names=channel_names,
            metadata_dict=metadata_dict or {},
        )
    return path


def _create_fcs_with_spillover(
    tmp_path: Path,
    num_channels: int = 3,
    channel_names: list[str] | None = None,
) -> Path:
    """Create a synthetic FCS file with spillover metadata."""
    if channel_names is None:
        channel_names = [f"FL{i}-A" for i in range(1, num_channels + 1)]
    spill_lines = [str(num_channels)]
    for i, name in enumerate(channel_names):
        row = [name]
        for j in range(num_channels):
            row.append("1.0" if i == j else f"0.{i + j + 1}")
        spill_lines.append(",".join(row))
    spillover_text = "\n".join(spill_lines)
    event_data = np.random.rand(10 * num_channels).tolist()
    path = tmp_path / "spill_test.fcs"
    with open(path, "wb") as fh:
        flowio.create_fcs(
            file_handle=fh,
            event_data=event_data,
            channel_names=channel_names,
            metadata_dict={"$SPILLOVER": spillover_text},
        )
    return path


# ---------------------------------------------------------------------------
# Basic I/O tests
# ---------------------------------------------------------------------------


def test_fcs_io_error_is_flowdesk_error() -> None:
    assert issubclass(FcsIoError, FlowdeskError)


def test_write_and_read_fcs_file(tmp_path: Path) -> None:
    """Round-trip: write an FCS file then read it back."""
    event_data = np.array(
        [[100.0, 200.0], [300.0, 400.0], [500.0, 600.0]],
        dtype=np.float64,
    )
    channel_names = ["FL1-A", "FL2-A"]
    out_path = tmp_path / "roundtrip.fcs"

    write_fcs_file(out_path, event_data, channel_names)

    info, events = read_fcs_events(out_path)
    assert info.event_count == 3
    assert info.channel_count == 2
    assert events.shape == (3, 2)


def test_read_fcs_info_basic(tmp_path: Path) -> None:
    """Metadata fields are populated from a valid FCS file."""
    path = _create_fcs_with_events(tmp_path, num_events=5, num_channels=3)
    info = read_fcs_info(path)

    assert isinstance(info, FcsFileInfo)
    assert info.fcs_version != "unknown"
    assert info.event_count == 5
    assert info.channel_count == 3
    assert len(info.channels) == 3
    assert isinstance(info.metadata, dict)


def test_read_fcs_events_shape(tmp_path: Path) -> None:
    """Event array shape matches the number of events and channels."""
    num_events = 20
    num_channels = 4
    path = _create_fcs_with_events(
        tmp_path, num_events=num_events, num_channels=num_channels
    )
    info, events = read_fcs_events(path)

    assert events.shape == (num_events, num_channels)
    assert info.event_count == num_events
    assert info.channel_count == num_channels


def test_read_fcs_events_immutable(tmp_path: Path) -> None:
    """The returned event array is read-only."""
    path = _create_fcs_with_events(tmp_path, num_events=5, num_channels=2)
    _, events = read_fcs_events(path)

    assert not events.flags.writeable
    with pytest.raises(ValueError):
        events[0, 0] = 999.0


# ---------------------------------------------------------------------------
# Channel mapping tests
# ---------------------------------------------------------------------------


def test_channel_ids_normalized(tmp_path: Path) -> None:
    """Channel ids are ch_0, ch_1, etc."""
    path = _create_fcs_with_events(tmp_path, num_events=3, num_channels=4)
    info = read_fcs_info(path)

    for idx, ch in enumerate(info.channels):
        assert ch.id == f"ch_{idx}"


def test_channel_names_preserved(tmp_path: Path) -> None:
    """Original PnN channel names are preserved."""
    channel_names = ["FSC-H", "SSC-H", "FL1-A", "FL2-A"]
    path = _create_fcs_with_events(
        tmp_path, num_events=3, num_channels=4, channel_names=channel_names
    )
    info = read_fcs_info(path)

    for expected_name in channel_names:
        assert expected_name in [ch.name for ch in info.channels]


def test_channel_count_matches(tmp_path: Path) -> None:
    """Channel count in metadata matches data columns."""
    num_channels = 5
    path = _create_fcs_with_events(
        tmp_path, num_events=10, num_channels=num_channels
    )
    info, events = read_fcs_events(path)

    assert info.channel_count == num_channels
    assert len(info.channels) == num_channels
    assert events.shape[1] == num_channels


# ---------------------------------------------------------------------------
# Spillover matrix tests
# ---------------------------------------------------------------------------


def test_spillover_extraction_success(tmp_path: Path) -> None:
    """A valid spillover matrix is extracted from FCS metadata."""
    channel_names = ["FL1-A", "FL2-A", "FL3-A"]
    path = _create_fcs_with_spillover(tmp_path, num_channels=3, channel_names=channel_names)
    result = extract_spillover_matrix(path)

    assert result is not None
    assert len(result.channels) == 3
    assert result.id == "spill_fcs"


def test_spillover_missing_returns_none(tmp_path: Path) -> None:
    """FCS file without spillover metadata returns None."""
    path = _create_fcs_with_events(tmp_path, num_events=5, num_channels=3)
    result = extract_spillover_matrix(path)

    assert result is None


def test_spillover_matrix_is_square(tmp_path: Path) -> None:
    """The extracted spillover matrix is square."""
    num_channels = 4
    channel_names = [f"FL{i}-A" for i in range(1, num_channels + 1)]
    path = _create_fcs_with_spillover(
      tmp_path, num_channels=num_channels, channel_names=channel_names
    )
    result = extract_spillover_matrix(path)

    assert result is not None
    n = len(result.channels)
    assert len(result.matrix) == n
    for row in result.matrix:
        assert len(row) == n


def test_spillover_channels_match(tmp_path: Path) -> None:
    """Channels in the spillover matrix match the FCS channel names."""
    channel_names = ["FL1-A", "FL2-A", "FL3-A"]
    path = _create_fcs_with_spillover(tmp_path, num_channels=3, channel_names=channel_names)
    result = extract_spillover_matrix(path)

    assert result is not None
    assert set(result.channels) == set(channel_names)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_read_nonexistent_file() -> None:
    """Reading a nonexistent file raises FcsIoError."""
    with pytest.raises(FcsIoError):
        read_fcs_info("/nonexistent/path/to/file.fcs")

    with pytest.raises(FcsIoError):
        read_fcs_events("/nonexistent/path/to/file.fcs")


def test_write_invalid_shape(tmp_path: Path) -> None:
    """Writing a non-2D array raises FcsIoError."""
    out_path = tmp_path / "bad.fcs"
    bad_data = np.array([1.0, 2.0, 3.0])

    with pytest.raises(FcsIoError, match="2D"):
        write_fcs_file(out_path, bad_data, ["FL1-A"])


def test_write_channel_name_mismatch(tmp_path: Path) -> None:
    """Mismatched channel names and data columns raises FcsIoError."""
    out_path = tmp_path / "mismatch.fcs"
    event_data = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)

    with pytest.raises(FcsIoError, match="does not match"):
        write_fcs_file(out_path, event_data, ["FL1-A", "FL2-A"])
