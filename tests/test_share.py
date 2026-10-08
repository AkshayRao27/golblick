import struct

import pytest
from conftest import write_file

from golblick import cli
from golblick.errors import FormatError
from golblick.vendors.insta360 import METADATA, describe, metadata, read_trailer, shareable
from golblick.vendors.insta360.trailer import IMU

SERIAL = "IXSE42SERIAL7"
LATITUDE, LONGITUDE = 12.345678, 45.678901  # open ocean, deliberately nowhere
STAMP = "20240513_192749"


def _tiff_exif() -> bytes:
    """A little-endian EXIF block with GPS, dates and a description, as cameras write it."""
    data = bytearray()

    def ifd(entries, data_start):
        """entries: (tag, type, count, payload bytes); payloads over 4 bytes go after the IFD."""
        body, extra = bytearray(struct.pack("<H", len(entries))), bytearray()
        tail = data_start + 2 + 12 * len(entries) + 4
        for tag, kind, count, payload in entries:
            if len(payload) <= 4:
                body += struct.pack("<HHI", tag, kind, count) + payload.ljust(4, b"\0")
            else:
                body += struct.pack("<HHII", tag, kind, count, tail + len(extra))
                extra += payload
        return bytes(body + struct.pack("<I", 0) + extra)

    date = b"2024:05:13 19:27:49\0"
    rational = lambda value: b"".join(struct.pack("<II", int(part * 10000), 10000)  # noqa: E731
                                      for part in (int(value), (value % 1) * 60, 0))
    # Layout: header (8) | IFD0 | Exif IFD | GPS IFD, each followed by its own payloads.
    ifd0_at = 8
    ifd0_size = 2 + 12 * 4 + 4 + 32 + 20
    exif_at = ifd0_at + ifd0_size
    exif_size = 2 + 12 + 4 + 20
    gps_at = exif_at + exif_size
    ifd0 = ifd([(0x010E, 2, 32, f"IMG_{STAMP}_00_004.insp".encode().ljust(32, b"\0")),
                (0x0132, 2, 20, date),
                (0x8769, 4, 1, struct.pack("<I", exif_at)),
                (0x8825, 4, 1, struct.pack("<I", gps_at))], ifd0_at)
    exif = ifd([(0x9003, 2, 20, date)], exif_at)
    gps = ifd([(1, 2, 2, b"N\0"), (2, 5, 3, rational(LATITUDE)),
               (3, 2, 2, b"E\0"), (4, 5, 3, rational(LONGITUDE))], gps_at)
    assert len(ifd0) == ifd0_size and len(exif) == exif_size
    data += b"II*\0" + struct.pack("<I", ifd0_at) + ifd0 + exif + gps
    return bytes(data)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        out.append((value & 0x7F) | (0x80 if value > 0x7F else 0))
        value >>= 7
        if not value:
            return bytes(out)


def _text(number: int, value: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(value)) + value


def _metadata(extra: bytes = b"") -> bytes:
    path = f"./DCIM/Camera01/IMG_{STAMP}_00_004.insp".encode()
    capture = _varint(7 << 3) + _varint(int(STAMP.replace("_", "")))
    return (_text(1, SERIAL.encode()) + _text(2, b"Insta360 OneR") + capture
            + _text(11, struct.pack("<ddd", LATITUDE, LONGITUDE, 512.0))
            + _text(26, _text(3, path)) + extra)


def _photo(tmp_path, metadata=None, imu=b"\x01" * 40):
    tiff = _tiff_exif()
    app1 = b"\xff\xe1" + struct.pack(">H", len(tiff) + 8) + b"Exif\0\0" + tiff
    jpeg = b"\xff\xd8" + app1 + b"\xff\xda\x00\x02" + b"pixels" * 20 + b"\xff\xd9"
    return write_file(tmp_path / f"IMG_{STAMP}_00_004.insp",
                      [(IMU, imu), (METADATA, metadata or _metadata())], leading=jpeg)


def test_a_shareable_copy_carries_no_location_dates_or_serial(tmp_path):
    source = _photo(tmp_path)
    original = source.read_bytes()

    data, cleared = shareable(source)

    assert len(data) == len(original)
    for secret in (SERIAL.encode(), struct.pack("<d", LATITUDE), struct.pack("<d", LONGITUDE),
                   STAMP.encode(), b"2024:05:13"):
        assert secret in original and secret not in data
    assert "GPS (4 entries)" in cleared
    # Everything else is left as the camera wrote it.
    copy = tmp_path / "copy.insp"
    copy.write_bytes(data)
    assert read_trailer(copy).get(IMU).data == read_trailer(source).get(IMU).data
    assert describe(copy)["model"] == "Insta360 OneR"
    # The capture time is a binary number, not text: read it back.
    fields = metadata.by_number(read_trailer(copy).get(METADATA).data)
    assert fields[7][0].value == 0


def test_a_copy_can_be_shared_again_and_comes_out_unchanged(tmp_path):
    """Someone sending on a copy they were sent; its zeros are not identifiers."""
    first = tmp_path / "IMG_00000000_000000_00_001.insp"
    first.write_bytes(shareable(_photo(tmp_path))[0])

    data, _ = shareable(first)

    assert data == first.read_bytes()


def test_the_copy_is_refused_if_the_serial_turns_up_anywhere_else(tmp_path):
    """The check has to be able to fire, or it only looks like a check."""
    source = _photo(tmp_path, imu=b"\x01" * 8 + SERIAL.encode() + b"\x01" * 19)

    with pytest.raises(FormatError, match="refusing"):
        shareable(source)


def test_the_cli_names_copies_without_the_date_and_will_not_overwrite(tmp_path, capsys):
    source = _photo(tmp_path)
    out = tmp_path / "out"

    assert cli.main(["share", str(source), "-o", str(out)]) == 0
    target = out / "IMG_00000000_000000_00_001.insp"
    assert target.exists() and SERIAL.encode() not in target.read_bytes()

    assert cli.main(["share", str(source), "-o", str(out)]) == 1
    assert "already exists" in capsys.readouterr().err
