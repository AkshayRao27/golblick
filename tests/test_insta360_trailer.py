import struct

import pytest

from conftest import build_trailer, write_file
from kugelblick.errors import FormatError, UnsupportedFile
from kugelblick.vendors.insta360.trailer import METADATA, read_trailer


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
    from kugelblick.vendors.insta360.trailer import MAGIC

    path = tmp_path / "bad.insp"
    path.write_bytes(b"\xff\xd8" + struct.pack("<II", 1 << 30, 3) + MAGIC)

    with pytest.raises(FormatError):
        read_trailer(path)


def test_corrupt_record_sizes_are_rejected(tmp_path):
    """A walk that does not land on the boundary must fail rather than guess."""
    from kugelblick.vendors.insta360.trailer import MAGIC

    body = b"data" + struct.pack("<HI", METADATA, 999999)
    body += b"\x00" * 32
    size = len(body) + 8 + len(MAGIC)
    path = tmp_path / "corrupt.insp"
    path.write_bytes(b"\xff\xd8" + body + struct.pack("<II", size, 3) + MAGIC)

    with pytest.raises(FormatError):
        read_trailer(path)
