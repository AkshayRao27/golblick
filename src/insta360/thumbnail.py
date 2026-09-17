"""Extraction of the stitched preview the camera embeds in every ``.insp``.

This is the most useful thing in the file for anyone who just wants to *see* the
photo.  An ``.insp`` is a dual-fisheye JPEG -- two circles side by side, useless
to display directly -- but its EXIF IFD1 thumbnail is a genuine equirectangular
panorama that the camera has already stitched *and* horizon-levelled on device.

It is small (320x160 on the X5), so it is no substitute for a real stitch.  It
is, however, free, instant, correct, and enough for a photo-grid thumbnail.  It
also serves as ground truth: a stitch produced from the calibration data can be
scored against it, which is how this project measures its own accuracy without
needing reference renders from Insta360 Studio.
"""

from __future__ import annotations

import struct
from pathlib import Path

from .trailer import Insta360Error

_SOI = b"\xff\xd8"
_APP1 = 0xFFE1
_EXIF_SIGNATURE = b"Exif\x00\x00"

_TAG_THUMBNAIL_OFFSET = 0x0201
_TAG_THUMBNAIL_LENGTH = 0x0202


class ThumbnailError(Insta360Error):
    """No embedded thumbnail could be extracted."""


def _read_app1(handle) -> bytes:
    """Return the APP1/Exif payload, without its signature."""
    if handle.read(2) != _SOI:
        raise ThumbnailError("not a JPEG")
    while True:
        header = handle.read(2)
        if len(header) != 2 or header[0] != 0xFF:
            raise ThumbnailError("no APP1/Exif segment found")
        marker = struct.unpack(">H", header)[0]
        if marker in (0xFFD8, 0xFFD9):
            continue
        size_bytes = handle.read(2)
        if len(size_bytes) != 2:
            raise ThumbnailError("truncated segment header")
        size = struct.unpack(">H", size_bytes)[0] - 2
        payload = handle.read(size)
        if marker == _APP1 and payload.startswith(_EXIF_SIGNATURE):
            return payload[len(_EXIF_SIGNATURE) :]
        if marker == 0xFFDA:  # start of scan; EXIF cannot follow
            raise ThumbnailError("no APP1/Exif segment before image data")


def _walk_ifd(tiff: bytes, offset: int, endian: str) -> tuple[dict[int, int], int]:
    """Read one IFD, returning its scalar tag values and the next IFD offset."""
    if offset + 2 > len(tiff):
        raise ThumbnailError("IFD offset past end of EXIF block")
    count = struct.unpack_from(endian + "H", tiff, offset)[0]
    tags: dict[int, int] = {}
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            raise ThumbnailError("truncated IFD entry")
        tag, kind, values = struct.unpack_from(endian + "HHI", tiff, pos)
        # Only the LONG/SHORT scalars matter here, and those live inline.
        if kind == 3:
            tags[tag] = struct.unpack_from(endian + "H", tiff, pos + 8)[0]
        elif kind == 4:
            tags[tag] = struct.unpack_from(endian + "I", tiff, pos + 8)[0]
        pos += 12
    next_offset = 0
    if pos + 4 <= len(tiff):
        next_offset = struct.unpack_from(endian + "I", tiff, pos)[0]
    return tags, next_offset


def extract(path: str | Path) -> bytes:
    """Return the embedded JPEG thumbnail of ``path`` as bytes."""
    path = Path(path)
    with path.open("rb") as handle:
        tiff = _read_app1(handle)

    if len(tiff) < 8:
        raise ThumbnailError("EXIF block too small")
    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        raise ThumbnailError("bad TIFF byte order marker")

    ifd0_offset = struct.unpack_from(endian + "I", tiff, 4)[0]
    _, ifd1_offset = _walk_ifd(tiff, ifd0_offset, endian)
    if not ifd1_offset:
        raise ThumbnailError("no IFD1, so no embedded thumbnail")

    tags, _ = _walk_ifd(tiff, ifd1_offset, endian)
    offset = tags.get(_TAG_THUMBNAIL_OFFSET)
    length = tags.get(_TAG_THUMBNAIL_LENGTH)
    if offset is None or length is None:
        raise ThumbnailError("IFD1 carries no thumbnail offset/length")
    if offset + length > len(tiff):
        raise ThumbnailError("thumbnail runs past the EXIF block")

    data = tiff[offset : offset + length]
    if not data.startswith(_SOI):
        raise ThumbnailError("thumbnail is not a JPEG")
    return data
