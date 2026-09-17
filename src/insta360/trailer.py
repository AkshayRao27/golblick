"""Reader for the binary trailer Insta360 appends to ``.insp`` and ``.insv`` files.

Both formats are ordinary media containers (JPEG and MP4 respectively) with a
proprietary trailer bolted onto the end.  Standard decoders ignore it, which is
why the files play at all, and why everything interesting about them is
invisible to standard tooling.

Layout, reading backwards from EOF::

    ...record data...
    [pad]                  see _CANDIDATE_PADS
    uint32   trailer_size  total trailer length, this footer and magic included
    uint32   version       3 on the files measured so far
    char[32] MAGIC

Records sit in front of that footer and are walked *backwards*, because each
record is followed by its own six-byte footer rather than preceded by a header::

    uint16 record_id
    uint32 record_size     length of the data immediately preceding this footer

Verified against an Insta360 X5 on firmware v1.10.7_build2 (trailer version 3).
The padding between the last record and the trailer footer was 32 zero bytes on
every file measured, but nothing in the format announces it, so the reader tries
the plausible widths and keeps whichever one makes the record walk land exactly
on the start of the trailer.  That check is the parser's correctness proof: a
wrong pad width leaves the walk ending somewhere other than the boundary.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"8db42d694ccc418790edff439fe026bf"

_FOOTER = struct.Struct("<II")  # trailer_size, version
_REC_FOOTER = struct.Struct("<HI")  # record_id, record_size
_CANDIDATE_PADS = (32, 0, 16, 8, 64)

# Record ids seen so far.  Names are descriptive, not authoritative -- Insta360
# publishes no schema, so these come from matching payloads against exiftool's
# output and from direct inspection.
RECORD_NAMES = {
    0x0101: "metadata",       # protobuf: serial, model, firmware, calibration
    0x0200: "unknown_0200",   # 40-byte header + 4,915,200 bytes; not a JPEG
    0x0300: "imu",            # 20-byte entries: int64 timecode + 12-byte payload
    0x0900: "unknown_0900",
    0x0B00: "unknown_0b00",
}

METADATA = 0x0101
IMU = 0x0300


class Insta360Error(Exception):
    """Base class for every error this package raises."""


class NotInsta360(Insta360Error):
    """The file carries no Insta360 trailer."""


class TrailerError(Insta360Error):
    """The trailer is present but could not be parsed."""


@dataclass(frozen=True)
class Record:
    """One trailer record.  ``offset`` is absolute within the file."""

    id: int
    offset: int
    size: int
    data: bytes

    @property
    def name(self) -> str:
        return RECORD_NAMES.get(self.id, f"unknown_{self.id:04x}")


@dataclass(frozen=True)
class Trailer:
    """A parsed trailer.  ``offset`` is where it starts within the file."""

    version: int
    offset: int
    size: int
    pad: int
    records: tuple[Record, ...]

    def get(self, record_id: int) -> Record | None:
        for record in self.records:
            if record.id == record_id:
                return record
        return None

    def __contains__(self, record_id: object) -> bool:
        return any(record.id == record_id for record in self.records)


def _walk(blob: bytes, end: int) -> tuple[list[Record], int]:
    """Walk records backwards from ``end``.  Returns the records and where it stopped."""
    records: list[Record] = []
    pos = end
    while pos >= _REC_FOOTER.size:
        record_id, size = _REC_FOOTER.unpack_from(blob, pos - _REC_FOOTER.size)
        start = pos - _REC_FOOTER.size - size
        if size == 0 or start < 0:
            break
        records.append(Record(record_id, start, size, blob[start : pos - _REC_FOOTER.size]))
        pos = start
    records.reverse()
    return records, pos


def read_trailer(path: str | Path) -> Trailer:
    """Read and parse the trailer of ``path``.

    Only the trailer itself is read, never the whole file -- ``.insv`` masters
    run to many gigabytes and the trailer is a handful of megabytes at the end.
    """
    path = Path(path)
    with path.open("rb") as handle:
        handle.seek(0, 2)
        file_size = handle.tell()
        if file_size < len(MAGIC) + _FOOTER.size:
            raise NotInsta360(f"{path}: too small to carry a trailer")

        handle.seek(-len(MAGIC), 2)
        if handle.read(len(MAGIC)) != MAGIC:
            raise NotInsta360(f"{path}: no Insta360 trailer magic")

        handle.seek(-(len(MAGIC) + _FOOTER.size), 2)
        size, version = _FOOTER.unpack(handle.read(_FOOTER.size))
        if not 0 < size <= file_size:
            raise TrailerError(f"{path}: trailer size {size} is impossible in {file_size} bytes")

        trailer_offset = file_size - size
        handle.seek(trailer_offset)
        blob = handle.read(size)

    if len(blob) != size:
        raise TrailerError(f"{path}: short read of trailer ({len(blob)} of {size})")

    footer_start = size - len(MAGIC) - _FOOTER.size
    for pad in _CANDIDATE_PADS:
        end = footer_start - pad
        if end < 0:
            continue
        records, stopped = _walk(blob, end)
        # The walk is only trustworthy if it consumes the records region exactly.
        if stopped == 0 and records:
            return Trailer(
                version=version,
                offset=trailer_offset,
                size=size,
                pad=pad,
                records=tuple(
                    Record(r.id, trailer_offset + r.offset, r.size, r.data) for r in records
                ),
            )

    raise TrailerError(
        f"{path}: no padding width in {_CANDIDATE_PADS} makes the record walk "
        f"consume the trailer exactly; the layout may have changed"
    )
