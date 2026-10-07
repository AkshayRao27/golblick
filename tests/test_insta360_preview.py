import struct

import pytest
from conftest import write_file

from golblick.errors import FormatError, ThumbnailError
from golblick.vendors.insta360 import preview
from golblick.vendors.insta360.trailer import METADATA


def nv12_record(width, height, *, declared=None, payload_bytes=None):
    """A 0x0200 payload in the X5's NV12 form."""
    declared_width, declared_height = declared or (width, height)
    header = bytearray(40)
    struct.pack_into("<II", header, 16, declared_width, declared_height)
    size = width * height * 3 // 2 if payload_bytes is None else payload_bytes
    return bytes(header) + b"\x80" * size


def jpeg_record(width, height):
    """A JPEG carrying nothing but a frame header, which is all the reader reads."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x00\x00\x00"
    return b"\xff\xd8" + sof + b"\xff\xd9"


def test_nv12_preview_is_read_as_a_stitch():
    parsed = preview.parse(nv12_record(2560, 1280))

    assert parsed.encoding == "nv12"
    assert (parsed.width, parsed.height) == (2560, 1280)
    assert parsed.layout == preview.EQUIRECTANGULAR
    assert parsed.is_stitched
    assert len(parsed.data) == 2560 * 1280 * 3 // 2


def test_jpeg_preview_is_read_as_the_lens_pair():
    """OneR and X3 store the fisheye pair here, so it is not displayable."""
    parsed = preview.parse(jpeg_record(1920, 960))

    assert parsed.encoding == "jpeg"
    assert (parsed.width, parsed.height) == (1920, 960)
    assert parsed.layout == preview.DUAL_FISHEYE
    assert not parsed.is_stitched


def test_declared_geometry_must_match_the_payload():
    """The header states its own dimensions, so the reader can check them.

    Refusing beats handing back a buffer that would decode into garbage.
    """
    with pytest.raises(FormatError):
        preview.parse(nv12_record(2560, 1280, declared=(2560, 1281)))


def test_truncated_nv12_payload_is_refused():
    with pytest.raises(FormatError):
        preview.parse(nv12_record(64, 32, payload_bytes=100))


def test_missing_preview_record_is_reported(tmp_path):
    path = write_file(tmp_path / "a.insp", [(METADATA, b"meta")])

    with pytest.raises(ThumbnailError):
        preview.extract(path)


def test_extract_reads_the_record_from_the_trailer(tmp_path):
    payload = nv12_record(16, 8)
    path = write_file(tmp_path / "a.insp", [(preview.PREVIEW, payload), (METADATA, b"meta")])

    parsed = preview.extract(path)

    assert (parsed.width, parsed.height) == (16, 8)
    assert parsed.encoding == "nv12"
