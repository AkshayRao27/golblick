"""GPano XMP: the metadata that turns a wide image into a sphere.

Everything here is byte-level, so the tests read the bytes back rather than
trusting the writer -- a packet that is almost right looks exactly like one
that is right until a viewer opens it.
"""

import struct
import zlib

import pytest

from golblick import gpano, imaging

REQUIRED = (
    "UsePanoramaViewer",
    "ProjectionType",
    "CroppedAreaImageWidthPixels",
    "CroppedAreaImageHeightPixels",
    "FullPanoWidthPixels",
    "FullPanoHeightPixels",
    "CroppedAreaLeftPixels",
    "CroppedAreaTopPixels",
)


def test_packet_carries_every_required_field():
    text = gpano.packet(4096, 2048).decode("utf-8")

    for field in REQUIRED:
        assert f"GPano:{field}=" in text, f"{field} is missing"
    assert gpano.NAMESPACE in text
    assert 'GPano:ProjectionType="equirectangular"' in text


def test_packet_defaults_the_full_sphere_to_the_stored_size():
    text = gpano.packet(4096, 2048).decode("utf-8")

    assert 'GPano:FullPanoWidthPixels="4096"' in text
    assert 'GPano:CroppedAreaLeftPixels="0"' in text


def test_packet_describes_a_partial_panorama():
    """Without these a viewer stretches the crop around the whole sphere.

    That failure looks plausible rather than broken, which is why the fields
    are always written.
    """
    text = gpano.packet(1000, 500, full_width=4000, full_height=2000, left=300, top=100)
    text = text.decode("utf-8")

    assert 'GPano:CroppedAreaImageWidthPixels="1000"' in text
    assert 'GPano:FullPanoWidthPixels="4000"' in text
    assert 'GPano:CroppedAreaLeftPixels="300"' in text
    assert 'GPano:CroppedAreaTopPixels="100"' in text


def test_packet_states_no_pose():
    """Heading and pose are deliberately absent -- see the module docstring.

    A fabricated 0.0 is indistinguishable downstream from a measured one.
    """
    text = gpano.packet(4096, 2048).decode("utf-8")

    assert "PoseHeadingDegrees" not in text
    assert "PosePitchDegrees" not in text
    assert "PoseRollDegrees" not in text
    assert "InitialViewHeadingDegrees" not in text


def test_packet_refuses_a_crop_that_does_not_fit():
    with pytest.raises(gpano.GPanoError, match="does not fit"):
        gpano.packet(1000, 500, full_width=1200, full_height=600, left=300, top=0)


def test_packet_refuses_an_empty_image():
    with pytest.raises(gpano.GPanoError):
        gpano.packet(0, 100)


def test_packet_escapes_the_creator_tool():
    text = gpano.packet(64, 32, software='we<b>ird "tool" & co').decode("utf-8")

    assert "&lt;b&gt;" in text and "&quot;tool&quot;" in text and "&amp;" in text
    # The attribute must not be terminated early by the raw quote.
    assert text.count('xmp:CreatorTool="') == 1


# --------------------------------------------------------------------- JPEG


def _jpeg(*segments: bytes) -> bytes:
    return b"\xff\xd8" + b"".join(segments) + b"\xff\xda" + b"scan" + b"\xff\xd9"


def _app(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _xmp_segments(jpeg: bytes) -> list[bytes]:
    """Every APP1 segment in ``jpeg`` whose payload is XMP."""
    found = []
    pos = 2
    while pos + 4 <= len(jpeg) and jpeg[pos] == 0xFF:
        marker = jpeg[pos + 1]
        if marker == 0xDA:
            break
        length = struct.unpack_from(">H", jpeg, pos + 2)[0]
        payload = jpeg[pos + 4 : pos + 2 + length]
        if marker == 0xE1 and payload.startswith(gpano.JPEG_IDENTIFIER):
            found.append(payload[len(gpano.JPEG_IDENTIFIER):])
        pos += 2 + length
    return found


def test_embed_jpeg_round_trips_the_packet():
    xmp = gpano.packet(4096, 2048)
    out = gpano.embed_jpeg(_jpeg(_app(0xE0, b"JFIF\x00rest")), xmp)

    assert _xmp_segments(out) == [xmp]
    assert out.endswith(b"\xff\xd9")


def test_embed_jpeg_keeps_jfif_first():
    """Readers expect APP0 at the front where it is present."""
    out = gpano.embed_jpeg(_jpeg(_app(0xE0, b"JFIF\x00rest")), gpano.packet(64, 32))

    assert out[2:4] == b"\xff\xe0", "JFIF should still be the first segment"
    assert out[4 + struct.unpack_from(">H", out, 4)[0] : ][:2] == b"\xff\xe1"


def test_embed_jpeg_replaces_rather_than_appends():
    """Running twice must not leave two packets for a reader to choose between."""
    once = gpano.embed_jpeg(_jpeg(_app(0xE0, b"JFIF\x00")), gpano.packet(64, 32))
    twice = gpano.embed_jpeg(once, gpano.packet(128, 64))

    packets = _xmp_segments(twice)
    assert len(packets) == 1
    assert b'CroppedAreaImageWidthPixels="128"' in packets[0]


def test_embed_jpeg_works_without_a_jfif_segment():
    out = gpano.embed_jpeg(_jpeg(), gpano.packet(64, 32))

    assert out[2:4] == b"\xff\xe1"
    assert len(_xmp_segments(out)) == 1


def test_embed_jpeg_refuses_something_that_is_not_a_jpeg():
    with pytest.raises(gpano.GPanoError, match="not a JPEG"):
        gpano.embed_jpeg(b"\x89PNG\r\n\x1a\n", gpano.packet(64, 32))


def test_jpeg_segment_refuses_a_packet_too_large_to_carry():
    with pytest.raises(gpano.GPanoError, match="extension mechanism"):
        gpano.jpeg_segment(b"x" * 70000)


# ---------------------------------------------------------------------- PNG


def _png_chunks(png: bytes):
    pos = 8
    while pos < len(png):
        length = struct.unpack_from(">I", png, pos)[0]
        tag = png[pos + 4 : pos + 8]
        payload = png[pos + 8 : pos + 8 + length]
        stored = struct.unpack_from(">I", png, pos + 8 + length)[0]
        assert stored == zlib.crc32(tag + payload), f"{tag!r} has a bad CRC"
        yield tag, payload
        pos += 12 + length


def test_write_png_carries_the_packet_before_the_pixels():
    xmp = gpano.packet(2, 1)
    png = imaging.write_png(b"\xff\x00\x00\x00\xff\x00", 2, 1, xmp=xmp)

    tags = [tag for tag, _ in _png_chunks(png)]
    assert tags == [b"IHDR", b"iTXt", b"IDAT", b"IEND"]

    payload = next(body for tag, body in _png_chunks(png) if tag == b"iTXt")
    keyword, rest = payload.split(b"\x00", 1)
    assert keyword == gpano.PNG_KEYWORD
    # compression flag, compression method, empty language, empty translation
    assert rest[:2] == b"\x00\x00"
    assert rest[2:4] == b"\x00\x00"
    assert rest[4:] == xmp


def test_write_png_without_xmp_is_unchanged():
    plain = imaging.write_png(b"\xff\x00\x00", 1, 1)

    assert [tag for tag, _ in _png_chunks(plain)] == [b"IHDR", b"IDAT", b"IEND"]


def test_the_cli_render_command_asks_for_the_extra_rather_than_traceback(monkeypatch):
    """The dependency-free promise: a missing extra is an instruction, not a stack.

    Rendering is the one thing in the package that needs numpy, so it is also
    the one place a user can hit an ImportError from three frames down.
    """
    import builtins

    from golblick import cli
    from golblick.errors import MissingDependency

    real_import = builtins.__import__

    def without_numpy(name, *args, **kwargs):
        if name in ("numpy", "PIL"):
            raise ImportError(f"no {name} here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_numpy)

    with pytest.raises(MissingDependency, match="render"):
        cli._require_render_extra()

