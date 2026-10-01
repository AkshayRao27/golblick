"""Just enough image handling to write what the cameras already give us.

This is deliberately not a rendering module.  It converts a preview the camera
has *already* produced into something a viewer can open, and nothing else: no
resampling, no projection, no filtering.  Anything that reprojects pixels
belongs behind the ``render`` extra, with numpy.

Everything here is standard library.  ``zlib`` is all a PNG writer needs, and
the colour conversion runs in about three seconds for a 2560x1280 frame -- slow
by numpy's standards, irrelevant for a one-off CLI invocation, and it keeps the
CLI working inside a container with no toolchain, which is the point.
"""

from __future__ import annotations

import struct
import zlib

from . import gpano

# Index by ``value + _BIAS`` to clamp into 0..255 without a branch per channel.
_BIAS = 512
_CLAMP = bytes(min(255, max(0, index - _BIAS)) for index in range(2 * _BIAS + 256))


def nv12_to_rgb(data: bytes, width: int, height: int) -> bytes:
    """Convert an NV12 (YUV 4:2:0, interleaved chroma) buffer to packed RGB.

    NV12 stores a full-resolution luma plane followed by one interleaved
    chroma plane at half resolution in both axes, so each chroma pair serves a
    2x2 block of pixels.  Coefficients are BT.601, which is what the cameras
    measured so far encode against.
    """
    expected = width * height * 3 // 2
    if len(data) != expected:
        raise ValueError(f"NV12 {width}x{height} needs {expected} bytes, got {len(data)}")

    luma = data[: width * height]
    chroma = data[width * height :]
    rows = []
    for y in range(height):
        luma_row = luma[y * width : (y + 1) * width]
        # Two luma rows share one chroma row.
        chroma_row = chroma[(y // 2) * width : (y // 2) * width + width]
        out = bytearray(width * 3)
        for x in range(width):
            value = luma_row[x]
            pair = (x >> 1) << 1
            u = chroma_row[pair] - 128
            v = chroma_row[pair + 1] - 128
            out[x * 3] = _CLAMP[int(value + 1.402 * v) + _BIAS]
            out[x * 3 + 1] = _CLAMP[int(value - 0.344136 * u - 0.714136 * v) + _BIAS]
            out[x * 3 + 2] = _CLAMP[int(value + 1.772 * u) + _BIAS]
        rows.append(bytes(out))
    return b"".join(rows)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload))
    )


def write_png(rgb: bytes, width: int, height: int, xmp: bytes | None = None) -> bytes:
    """Encode packed RGB as a PNG, optionally carrying an XMP packet.

    ``xmp`` goes in an ``iTXt`` chunk between IHDR and IDAT -- metadata before
    pixels, so a reader that stops at the first IDAT still sees it.  Build one
    with :func:`golblick.gpano.packet`.
    """
    if len(rgb) != width * height * 3:
        raise ValueError(f"RGB {width}x{height} needs {width * height * 3} bytes, got {len(rgb)}")

    # Filter type 0 (none) in front of every scanline: the preview is already
    # JPEG-compressed upstream, so paying for filter selection buys very little.
    raw = b"".join(
        b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )
    text = b"" if xmp is None else gpano.png_chunk(xmp)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + text
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )
