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

X5 video (``.insv`` and ``.lrv``) lays the same records out differently: they
are scattered through the trailer with gaps of zeros or stale bytes between
them, so no backward walk can close.  The last record before the pad then has
id 0 and is an index of 10-byte entries::

    uint16be record_id     the footer's id, bytes in the opposite order
    uint32   record_size
    uint32   offset        of the record data, from the start of the trailer

with all-zero entries for unused slots.  See ``_read_index`` for the checks
that stand in for the walk's boundary proof.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ...errors import FormatError, UnsupportedFile

MAGIC = b"8db42d694ccc418790edff439fe026bf"

_FOOTER = struct.Struct("<II")  # trailer_size, version
_REC_FOOTER = struct.Struct("<HI")  # record_id, record_size
_CANDIDATE_PADS = (32, 0, 16, 8, 64)
_INDEX_ENTRY = struct.Struct(">H")  # then _SIZE_OFFSET; the id alone is big-endian
_SIZE_OFFSET = struct.Struct("<II")  # record_size, offset within the trailer
_INDEX_ENTRY_SIZE = _INDEX_ENTRY.size + _SIZE_OFFSET.size

# Record ids seen so far.  Names are descriptive, not authoritative -- Insta360
# publishes no schema, so these come from matching payloads against exiftool's
# output and from direct inspection.
RECORD_NAMES = {
    0x0101: "metadata",       # protobuf: serial, model, firmware, calibration
    0x0200: "preview",        # full-size preview: NV12 stitch (X5) or JPEG pair (OneR, X3)
    0x0300: "imu",            # 20-byte entries: int64 timecode + 12-byte payload
    0x0900: "unknown_0900",
    0x0B00: "unknown_0b00",
}

METADATA = 0x0101
IMU = 0x0300


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
        # A zero-length record is legal and common: OneR and X3 files declare
        # 0x0900 and 0x0b00 with no payload, and refusing those loses 63% of a
        # real library.  But an all-zero footer is the *pad*, not a record, and
        # a run of zero bytes that divides by six would otherwise be read as
        # phantom records and make the pad width ambiguous.  Id 0 only ever
        # appears as the index of an X5 video trailer, which a walk cannot
        # read anyway, so treating it as the end of the walk keeps the boundary
        # check decisive and leaves the index to ``_read_index``.
        if start < 0 or record_id == 0:
            break
        records.append(Record(record_id, start, size, blob[start : pos - _REC_FOOTER.size]))
        pos = start
    records.reverse()
    return records, pos


def _read_index(blob: bytes, end: int) -> list[Record] | None:
    """Read an indexed trailer whose index record ends at ``end``, or return None.

    The gaps between indexed records hold stale data, so nothing can be said to
    consume the trailer exactly.  What replaces that proof: every entry must
    point at a record whose own footer repeats the entry's id and size, the
    records must not overlap, and the last of them must end exactly where the
    index begins -- the one boundary this layout still has.  All 83 X5 videos
    measured satisfy all three, and anything else is refused.
    """
    if end < _REC_FOOTER.size:
        return None
    record_id, size = _REC_FOOTER.unpack_from(blob, end - _REC_FOOTER.size)
    index_start = end - _REC_FOOTER.size - size
    if record_id != 0 or size == 0 or size % _INDEX_ENTRY_SIZE or index_start < 0:
        return None

    records: list[Record] = []
    for pos in range(index_start, index_start + size, _INDEX_ENTRY_SIZE):
        (entry_id,) = _INDEX_ENTRY.unpack_from(blob, pos)
        entry_size, offset = _SIZE_OFFSET.unpack_from(blob, pos + _INDEX_ENTRY.size)
        if entry_id == 0 and entry_size == 0 and offset == 0:
            continue
        footer = offset + entry_size
        if entry_id == 0 or footer + _REC_FOOTER.size > index_start:
            return None
        if _REC_FOOTER.unpack_from(blob, footer) != (entry_id, entry_size):
            return None
        records.append(Record(entry_id, offset, entry_size, blob[offset:footer]))

    records.sort(key=lambda record: record.offset)
    for before, after in zip(records, records[1:]):
        if before.offset + before.size + _REC_FOOTER.size > after.offset:
            return None
    if not records or records[-1].offset + records[-1].size + _REC_FOOTER.size != index_start:
        return None
    return records


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
            raise UnsupportedFile(f"{path}: too small to carry a trailer")

        handle.seek(-len(MAGIC), 2)
        if handle.read(len(MAGIC)) != MAGIC:
            raise UnsupportedFile(f"{path}: no Insta360 trailer magic")

        handle.seek(-(len(MAGIC) + _FOOTER.size), 2)
        size, version = _FOOTER.unpack(handle.read(_FOOTER.size))
        if not 0 < size <= file_size:
            raise FormatError(f"{path}: trailer size {size} is impossible in {file_size} bytes")

        trailer_offset = file_size - size
        handle.seek(trailer_offset)
        blob = handle.read(size)

    if len(blob) != size:
        raise FormatError(f"{path}: short read of trailer ({len(blob)} of {size})")

    footer_start = size - len(MAGIC) - _FOOTER.size
    found = None
    for pad in _CANDIDATE_PADS:
        end = footer_start - pad
        if end < 0:
            continue
        records, stopped = _walk(blob, end)
        # The walk is only trustworthy if it consumes the records region exactly.
        if stopped == 0 and records:
            found = pad, records
            break
    else:
        # Only once no walk closes, so a layout that already parsed is never
        # reinterpreted.  An id-0 footer is what stopped the walks above.
        for pad in _CANDIDATE_PADS:
            end = footer_start - pad
            records = _read_index(blob, end) if end >= 0 else None
            if records:
                found = pad, records
                break

    if found is None:
        raise FormatError(
            f"{path}: no padding width in {_CANDIDATE_PADS} makes the record walk "
            f"consume the trailer exactly, or ends on a consistent record index; "
            f"the layout may have changed"
        )
    pad, records = found
    return Trailer(
        version=version,
        offset=trailer_offset,
        size=size,
        pad=pad,
        records=tuple(Record(r.id, trailer_offset + r.offset, r.size, r.data) for r in records),
    )
