"""Record ``0x0200`` -- the camera's own full-size preview.

Every ``.insp`` measured carries this record, and it is far larger than the
320x160 EXIF thumbnail: 2560x1280 on an X5, 1920x960 on a OneR or X3.  What it
*contains* depends on the camera, and the difference matters more than the size:

=========  ==================  =======================  =====================
Camera     Encoding            Dimensions               Layout
=========  ==================  =======================  =====================
X5         NV12 (YUV 4:2:0)    2560x1280, declared      equirectangular stitch
OneR, X3   JPEG                1920x960                 dual fisheye
=========  ==================  =======================  =====================

Measured over all 1,415 ``.insp`` files in one library: 1,319 OneR and 40 X3
files carry a JPEG, and the corner brightness of every one of them stays below
25, which is what a pair of fisheye circles on a black field looks like.  All 25
X5 files carry NV12, and 24 of them have bright corners (median 189); the
twenty-fifth is an all-black frame that says nothing either way.  So the
encoding predicts the layout on every file measured -- but it is an observation
about two camera generations, not something the format announces, which is why
:attr:`Preview.layout` records how it was derived.

The X5's stitch is the useful find.  It is the same image the camera puts in
its EXIF thumbnail, at 64x the pixel count, already horizon-levelled -- so it
is both a displayable preview and a much better ground truth for scoring a
stitch built from the calibration data.

The NV12 header states its own dimensions, and this reader checks them: the
payload must be exactly ``width * height * 3 // 2`` bytes or it refuses, rather
than handing back a buffer that would decode as garbage.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ...errors import FormatError, ThumbnailError
from .trailer import read_trailer

PREVIEW = 0x0200

#: Fixed header in front of the pixel data in the NV12 variant.
_NV12_HEADER = 40
_NV12_DIMENSIONS = struct.Struct("<II")  # at offset 16: width, height

_SOI = b"\xff\xd8"
# SOF markers that carry frame dimensions.  DHT/DAC/RST and friends do not.
_SOF_MARKERS = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})

EQUIRECTANGULAR = "equirectangular"
DUAL_FISHEYE = "dual-fisheye"


@dataclass(frozen=True)
class Preview:
    """The camera's own preview, as it is stored.

    ``data`` is handed back in the file's own encoding rather than converted,
    so that reading a preview stays dependency-free.  A JPEG preview can be
    written straight to disk; NV12 needs a colour conversion, which belongs
    with the rest of the pixel work behind the ``render`` extra.
    """

    encoding: str  # "jpeg" or "nv12"
    width: int
    height: int
    layout: str  # EQUIRECTANGULAR or DUAL_FISHEYE -- see the module docstring
    data: bytes

    @property
    def is_stitched(self) -> bool:
        """Whether this preview can be displayed as a panorama as it stands."""
        return self.layout == EQUIRECTANGULAR


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height from a JPEG's frame header."""
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in _SOF_MARKERS:
            if pos + 9 > len(data):
                break
            height, width = struct.unpack_from(">HH", data, pos + 5)
            return width, height
        if marker == 0xD8 or 0xD0 <= marker <= 0xD9:
            pos += 2
            continue
        segment = struct.unpack_from(">H", data, pos + 2)[0]
        if segment < 2:
            break
        pos += 2 + segment
    raise FormatError("preview JPEG carries no frame header")


def parse(data: bytes) -> Preview:
    """Interpret the payload of record ``0x0200``."""
    if data[:2] == _SOI:
        width, height = _jpeg_dimensions(data)
        return Preview("jpeg", width, height, DUAL_FISHEYE, data)

    if len(data) < _NV12_HEADER:
        raise FormatError(f"preview record is {len(data)} bytes, too small for its header")

    width, height = _NV12_DIMENSIONS.unpack_from(data, 16)
    pixels = data[_NV12_HEADER:]
    expected = width * height * 3 // 2
    if width <= 0 or height <= 0 or len(pixels) != expected:
        # The header declares its own geometry, so this is checkable rather than
        # assumed.  A mismatch means the layout is not what it is read as, and a
        # buffer that decodes to garbage is worse than an error.
        raise FormatError(
            f"preview declares {width}x{height} (NV12 needs {expected} bytes) "
            f"but carries {len(pixels)}"
        )
    return Preview("nv12", width, height, EQUIRECTANGULAR, pixels)


def extract(path: str | Path) -> Preview:
    """Return the camera's own preview from ``path``."""
    record = read_trailer(path).get(PREVIEW)
    if record is None:
        raise ThumbnailError(f"{path}: no preview record (0x{PREVIEW:04x})")
    return parse(record.data)
