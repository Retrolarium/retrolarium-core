"""Strict parsing and payload replacement for one raw FDS disk side."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class FdsError(ValueError):
    """The input is not a supported raw FDS side."""


@dataclass(frozen=True)
class FdsFileRecord:
    file_number: int
    file_id: int
    name: bytes
    load_address: int
    size: int
    file_type: int
    header_offset: int
    data_offset: int


@dataclass(frozen=True)
class FdsPayloadRange:
    file_offset: int
    payload_offset: int
    size: int


def parse_fds_side(image: bytes) -> tuple[FdsFileRecord, ...]:
    if len(image) != 65_500 or image[0] != 1:
        raise FdsError("FDS image must be one 65500-byte raw disk side")
    position = 56
    if image[position] != 2:
        raise FdsError("invalid FDS file-count block")
    file_count = image[position + 1]
    position += 2
    records = []
    for index in range(file_count):
        header_offset = position
        header_end = header_offset + 16
        if header_end > len(image) or image[header_offset] != 3:
            raise FdsError(f"invalid FDS file-header block {index}")
        header = image[header_offset:header_end]
        size = int.from_bytes(header[13:15], "little")
        if header_end >= len(image) or image[header_end] != 4:
            raise FdsError(f"invalid FDS file-data block {index}")
        data_offset = header_end + 1
        data_end = data_offset + size
        if data_end > len(image):
            raise FdsError(f"truncated FDS file-data block {index}")
        records.append(
            FdsFileRecord(
                file_number=header[1],
                file_id=header[2],
                name=header[3:11],
                load_address=int.from_bytes(header[11:13], "little"),
                size=size,
                file_type=header[15],
                header_offset=header_offset,
                data_offset=data_offset,
            )
        )
        position = data_end
    if any(image[position:]):
        raise FdsError("FDS side has nonzero data after its declared files")
    return tuple(records)


def _selected_records(image: bytes, record_ids: Iterable[int]) -> tuple[FdsFileRecord, ...]:
    identifiers = tuple(record_ids)
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise FdsError("FDS payload record IDs must be non-empty and unique")
    records = parse_fds_side(image)
    selected = []
    for identifier in identifiers:
        matches = [record for record in records if record.file_id == identifier]
        if len(matches) != 1:
            raise FdsError(f"FDS file ID is not unique: {identifier}")
        selected.append(matches[0])
    return tuple(selected)


def fds_payload(image: bytes, record_ids: Iterable[int]) -> bytes:
    return b"".join(
        image[record.data_offset : record.data_offset + record.size] for record in _selected_records(image, record_ids)
    )


def fds_payload_ranges(
    image: bytes,
    record_ids: Iterable[int],
    offset: int,
    size: int,
) -> tuple[FdsPayloadRange, ...]:
    selected = _selected_records(image, record_ids)
    total_size = sum(record.size for record in selected)
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or offset < 0
        or size <= 0
        or offset + size > total_size
    ):
        raise FdsError(f"FDS payload range {offset}+{size} exceeds {total_size} bytes")
    result = []
    logical_start = 0
    requested_end = offset + size
    for record in selected:
        logical_end = logical_start + record.size
        overlap_start = max(offset, logical_start)
        overlap_end = min(requested_end, logical_end)
        if overlap_start < overlap_end:
            result.append(
                FdsPayloadRange(
                    file_offset=record.data_offset + overlap_start - logical_start,
                    payload_offset=overlap_start - offset,
                    size=overlap_end - overlap_start,
                )
            )
        logical_start = logical_end
    return tuple(result)


def replace_fds_payload(image: bytes, record_ids: Iterable[int], payload: bytes) -> bytes:
    selected = _selected_records(image, record_ids)
    expected_size = sum(record.size for record in selected)
    if len(payload) != expected_size:
        raise FdsError(f"FDS replacement payload is {len(payload)} bytes, expected {expected_size}")
    result = bytearray(image)
    position = 0
    for record in selected:
        end = position + record.size
        result[record.data_offset : record.data_offset + record.size] = payload[position:end]
        position = end
    return bytes(result)
