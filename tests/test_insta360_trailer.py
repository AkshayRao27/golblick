import struct

import pytest

from conftest import build_trailer, write_file
from golblick.errors import FormatError, UnsupportedFile
from golblick.vendors.insta360.trailer import METADATA, read_trailer


def test_reads_records_in_file_order(tmp_path):
    path = write_file(tmp_path / "a.insp", [(METADATA, b"meta"), (0x0300, b"imu-payload")])
    trailer = read_trailer(path)

    assert trailer.version == 3
    assert [record.id for record in trailer.records] == [METADATA, 0x0300]
    assert trailer.get(METADATA).data == b"meta"
    assert trailer.get(0x0300).data == b"imu-payload"


def test_record_offsets_are_absolute(tmp_path):
    leading = b"\xff\xd8" + b"x" * 500
    path = write_file(tmp_path / "a.insp", [(METADATA, b"meta")], leading=leading)
    trailer = read_trailer(path)

    record = trailer.get(METADATA)
    assert path.read_bytes()[record.offset : record.offset + record.size] == b"meta"


@pytest.mark.parametrize("pad", [0, 8, 16, 32, 64])
def test_pad_width_is_discovered(tmp_path, pad):
    """The pad is not announced anywhere, so the reader must find it."""
    path = write_file(tmp_path / f"p{pad}.insp", [(METADATA, b"meta")], pad=pad)
    trailer = read_trailer(path)

    assert trailer.pad == pad
    assert trailer.get(METADATA).data == b"meta"


def test_zero_length_records_are_read(tmp_path):
    """OneR and X3 files declare 0x0900 and 0x0b00 with no payload.

    Treating an empty record as the end of the walk stopped six bytes short of
    the trailer boundary and failed the self-check, which refused 63% of a real
    library.  The empty records must be read, and must keep their ids.
    """
    path = write_file(tmp_path / "a.insp", [(0x0B00, b""), (0x0900, b""), (METADATA, b"meta")])
    trailer = read_trailer(path)

    assert [record.id for record in trailer.records] == [0x0B00, 0x0900, METADATA]
    assert trailer.get(0x0900).size == 0
    assert trailer.get(METADATA).data == b"meta"


def test_all_zero_footer_is_padding_not_a_record(tmp_path):
    """A pad whose length divides by six must not read as phantom records.

    Six zero bytes look exactly like a record footer with id 0 and size 0, so
    without this the discovered pad width is ambiguous and the boundary check
    stops being decisive.
    """
    path = write_file(tmp_path / "a.insp", [(METADATA, b"meta")], pad=64)
    trailer = read_trailer(path)

    assert trailer.pad == 64
    assert [record.id for record in trailer.records] == [METADATA]


def test_walk_consumes_the_trailer_exactly(tmp_path):
    """Offset plus size must equal the file length -- the parser's correctness proof."""
    path = write_file(tmp_path / "a.insp", [(METADATA, b"meta"), (0x0900, b"z" * 64)])
    trailer = read_trailer(path)

    assert trailer.offset + trailer.size == path.stat().st_size


def test_file_without_magic_is_rejected(tmp_path):
    path = tmp_path / "plain.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"not an insta360 file" * 10)

    with pytest.raises(UnsupportedFile):
        read_trailer(path)


def test_tiny_file_is_rejected(tmp_path):
    path = tmp_path / "tiny.insp"
    path.write_bytes(b"short")

    with pytest.raises(UnsupportedFile):
        read_trailer(path)


def test_impossible_trailer_size_is_rejected(tmp_path):
    from golblick.vendors.insta360.trailer import MAGIC

    path = tmp_path / "bad.insp"
    path.write_bytes(b"\xff\xd8" + struct.pack("<II", 1 << 30, 3) + MAGIC)

    with pytest.raises(FormatError):
        read_trailer(path)


def test_corrupt_record_sizes_are_rejected(tmp_path):
    """A walk that does not land on the boundary must fail rather than guess."""
    from golblick.vendors.insta360.trailer import MAGIC

    body = b"data" + struct.pack("<HI", METADATA, 999999)
    body += b"\x00" * 32
    size = len(body) + 8 + len(MAGIC)
    path = tmp_path / "corrupt.insp"
    path.write_bytes(b"\xff\xd8" + body + struct.pack("<II", size, 3) + MAGIC)

    with pytest.raises(FormatError):
        read_trailer(path)


# X5 video: records scattered through the trailer, located by an id-0 index.
# The gap contents are deliberately record-like and non-zero, as the camera's
# stale bytes are, so a reader that walked through them would be caught.
_X5_RECORDS = [(0x1D00, b"late-record"), (0x0300, b"imu" * 7), (0x0200, b"preview"), (METADATA, b"meta")]
_X5_GAPS = [b"\x32\x3f" * 40, b"\x00" * 64, b"\x00\x02\x28\xc0\x12\x00stale" * 3, b""]


def _write_indexed(path, trailer):
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"m" * 100 + trailer)
    return path


def test_indexed_trailer_is_read(tmp_path):
    from conftest import build_indexed_trailer

    path = _write_indexed(tmp_path / "a.insv", build_indexed_trailer(_X5_RECORDS, gaps=_X5_GAPS))
    trailer = read_trailer(path)

    assert trailer.pad == 32
    assert [record.id for record in trailer.records] == [0x1D00, 0x0300, 0x0200, METADATA]
    assert trailer.get(METADATA).data == b"meta"
    blob = path.read_bytes()
    for record in trailer.records:
        assert blob[record.offset : record.offset + record.size] == record.data
    assert trailer.get(0x1D00).name == "unknown_1d00"


@pytest.mark.parametrize(
    "corrupt",
    [
        "entry_size",       # an entry whose size disagrees with the record's own footer
        "entry_id",         # an entry whose id disagrees with the record's own footer
        "entry_offset",     # an entry pointing past the index
        "gap_before_index", # the last record no longer ends where the index begins
        "index_length",     # an index that is not a whole number of entries
    ],
)
def test_corrupt_index_is_refused(tmp_path, corrupt):
    from conftest import build_indexed_trailer

    trailer = bytearray(build_indexed_trailer(_X5_RECORDS, gaps=_X5_GAPS))
    index_footer = len(trailer) - 40 - 32 - 6
    index_size = struct.unpack_from("<I", trailer, index_footer + 2)[0]
    index_start = index_footer - index_size
    metadata_entry = index_start + 10  # slot 1 holds 0x0101

    if corrupt == "entry_size":
        struct.pack_into("<I", trailer, metadata_entry + 2, 3)
    elif corrupt == "entry_id":
        struct.pack_into(">H", trailer, metadata_entry, 0x0102)
    elif corrupt == "entry_offset":
        struct.pack_into("<I", trailer, metadata_entry + 6, index_start)
    elif corrupt == "gap_before_index":
        trailer[index_start:index_start] = b"\x00" * 10
    elif corrupt == "index_length":
        struct.pack_into("<I", trailer, index_footer + 2, index_size - 4)

    path = _write_indexed(tmp_path / "bad.insv", bytes(trailer))
    with pytest.raises(FormatError):
        read_trailer(path)
