"""The full-resolution frame in front of the trailer.

The interesting cases are all refusals: this returns the bytes a renderer will
project tens of megapixels from, so handing back a buffer that merely looks
like a JPEG is worse than raising.
"""

import struct

import pytest
from conftest import write_file

from golblick.errors import FormatError, UnsupportedFile
from golblick.vendors.insta360 import source
from golblick.vendors.insta360.preview import DUAL_FISHEYE


def _jpeg(width: int, height: int, *, padding: bytes = b"") -> bytes:
    """A minimal JPEG whose frame header declares ``width`` x ``height``."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 8 + 3, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + padding + sof + b"\xff\xda" + b"scan" + b"\xff\xd9"


def _app2(payload: bytes) -> bytes:
    return b"\xff\xe2" + struct.pack(">H", len(payload) + 2) + payload


def test_extracts_the_frame_in_front_of_the_trailer(tmp_path):
    path = write_file(tmp_path / "a.insp", [(0x0101, b"meta")], leading=_jpeg(6080, 3040))

    frame = source.extract(path)

    assert frame.encoding == "jpeg"
    assert (frame.width, frame.height) == (6080, 3040)
    assert frame.layout == DUAL_FISHEYE
    assert frame.data.startswith(b"\xff\xd8") and frame.data.endswith(b"\xff\xd9")


def test_finds_a_frame_header_behind_a_long_run_of_app2(tmp_path):
    """Real files bury the header megabytes in -- 4.9 MB on the X5 measured.

    A reader that scans only the first part of the file finds nothing.
    """
    padding = b"".join(_app2(b"\xcf" * 60000) for _ in range(20))
    path = write_file(tmp_path / "a.insp", [(0x0101, b"meta")],
                      leading=_jpeg(11904, 5952, padding=padding))

    frame = source.extract(path)

    assert (frame.width, frame.height) == (11904, 5952)


def test_refuses_a_container_that_is_not_a_jpeg(tmp_path):
    """A .insv is an MP4: there is no single frame to hand back."""
    path = write_file(tmp_path / "a.insv", [(0x0101, b"meta")],
                      leading=b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    with pytest.raises(FormatError, match="not a JPEG"):
        source.extract(path)


def test_refuses_when_the_jpeg_does_not_end_at_the_trailer(tmp_path):
    """The two boundaries must coincide, or the trailer offset is wrong.

    Everything downstream would then be built on a bad parse.
    """
    path = write_file(tmp_path / "a.insp", [(0x0101, b"meta")],
                      leading=_jpeg(64, 32) + b"leftover")

    with pytest.raises(FormatError, match="does not end where the trailer begins"):
        source.extract(path)


def test_refuses_a_file_with_no_trailer(tmp_path):
    path = tmp_path / "plain.jpg"
    path.write_bytes(_jpeg(64, 32))

    with pytest.raises(UnsupportedFile):
        source.extract(path)


def test_refuses_a_jpeg_with_no_frame_header(tmp_path):
    headerless = b"\xff\xd8" + _app2(b"only padding") + b"\xff\xd9"
    path = write_file(tmp_path / "a.insp", [(0x0101, b"meta")], leading=headerless)

    with pytest.raises(FormatError, match="no frame header"):
        source.extract(path)
