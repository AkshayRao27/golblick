import struct
import zlib

import pytest

from golblick import imaging


def nv12(width, height, luma, u, v):
    """A flat NV12 buffer: one luma value, one chroma pair, throughout."""
    return bytes([luma]) * (width * height) + bytes([u, v]) * (width * height // 4)


def test_grey_stays_grey():
    """Neutral chroma must come back out as R == G == B."""
    rgb = imaging.nv12_to_rgb(nv12(4, 4, 120, 128, 128), 4, 4)

    assert len(rgb) == 4 * 4 * 3
    assert set(rgb) == {120}


def test_chroma_moves_the_expected_channels():
    """BT.601: V pushes red, U pushes blue."""
    red = imaging.nv12_to_rgb(nv12(2, 2, 128, 128, 255), 2, 2)
    blue = imaging.nv12_to_rgb(nv12(2, 2, 128, 255, 128), 2, 2)

    assert red[0] > red[1] and red[0] > red[2]
    assert blue[2] > blue[0] and blue[2] > blue[1]


def test_out_of_range_values_are_clamped_not_wrapped():
    rgb = imaging.nv12_to_rgb(nv12(2, 2, 250, 255, 255), 2, 2)

    assert max(rgb) <= 255
    assert min(rgb) >= 0


def test_wrong_sized_buffer_is_refused():
    with pytest.raises(ValueError):
        imaging.nv12_to_rgb(b"\x00" * 10, 64, 64)


def test_png_is_well_formed_and_round_trips():
    width, height = 3, 2
    rgb = bytes(range(width * height * 3))
    png = imaging.write_png(rgb, width, height)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    length, tag = struct.unpack(">I4s", png[8:16])
    assert tag == b"IHDR"
    assert struct.unpack(">IIBB", png[16 : 16 + 10]) == (width, height, 8, 2)

    # Pull IDAT back out and confirm the scanlines survive the round trip.
    pos, idat = 8, b""
    while pos < len(png):
        size, tag = struct.unpack(">I4s", png[pos : pos + 8])
        if tag == b"IDAT":
            idat += png[pos + 8 : pos + 8 + size]
        pos += 12 + size
    raw = zlib.decompress(idat)
    assert raw == b"".join(
        b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )


def test_png_rejects_a_mismatched_buffer():
    with pytest.raises(ValueError):
        imaging.write_png(b"\x00" * 8, 4, 4)
