"""Extraction of the 320x160 thumbnail from EXIF IFD1.

Every ``.insp`` measured carries one, and on an X5 it is a genuine
equirectangular panorama that the camera stitched *and* horizon-levelled on
device -- which makes it ground truth, because a stitch built from the
calibration data can be scored against the camera's own answer.

WHETHER IT IS A STITCH DEPENDS ON THE CAMERA
--------------------------------------------
It is *not* a stitch on a OneR or an X3.  There the thumbnail is the
dual-fisheye pair shrunk to 320x160: two circles side by side, not viewable as
a panorama, and useless as ground truth.  Measured over 1,415 ``.insp`` files:
all 25 X5 files carry a stitch, and all 1,344 OneR and 40 X3 files do not.
An earlier version of this project generalised from two X5 stills and recorded
the stitch as a property of the format; it is a property of the camera.

So callers must not assume this returns something displayable.
:mod:`.preview` reports its layout explicitly, and is much larger besides.
"""

from __future__ import annotations

import struct
from pathlib import Path

from ...errors import ThumbnailError

_SOI = b"\xff\xd8"
_APP1 = 0xFFE1
_EXIF_SIGNATURE = b"Exif\x00\x00"

_TAG_THUMBNAIL_OFFSET = 0x0201
_TAG_THUMBNAIL_LENGTH = 0x0202


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
