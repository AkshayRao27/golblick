"""The full-resolution imagery the container wraps.

A ``.insp`` is an ordinary JPEG with the proprietary trailer bolted onto the
end, so the original frame is simply everything in front of the trailer -- no
decoding, no vendor software, and no re-encoding.  That frame is the dual
fisheye pair at full sensor resolution.

Measured over the 1,409 files in one library that carry a trailer:

=========  =============  ======  ===============================
Camera     Frame          Files   Note
=========  =============  ======  ===============================
OneR       6080 x 3040     1,344  the only size this body produces
X3         5952 x 2976        39
X3        11968 x 5984         1  high-resolution mode
X5         5888 x 2944         7
X5        11904 x 5952        18  high-resolution mode
=========  =============  ======  ===============================

⚠️ **The frame size is not a property of the model.** An X3 and an X5 each
shoot at two sizes, so it must be read from the frame and never assumed -- the
same mistake shape as the calibration reference frame.  Every size measured is
exactly 2:1, which is two square fisheye cells side by side and *not* evidence
of an equirectangular layout.

This is what a renderer should project from.  Record ``0x0200`` is the camera's
own preview at 1920x960 or 2560x1280, which is a twentieth of the pixels on a
OneR: fine for a thumbnail, wrong for an export.

⚠️ **The frame header is a long way in.** These containers carry a run of APP2
segments -- 10 or 11 on a OneR and X3, 76 on the X5 measured -- before the
SOF marker, so it sits 0.6 MB into a OneR file and 4.9 MB into an X5 one.  A
reader that caps how much it scans looking for the dimensions will find
nothing and must not conclude the file is malformed.  Those APP2 payloads
concatenate to a byte-identical copy of trailer record 0x0200's payload -- the
camera writes its preview twice -- measured on all 1,384 files that carry that
record.  ``docs/formats/insta360-agent-notes.md`` owns the detail.

⚠️ **The layout is the lens pair, not a panorama** -- on every camera, unlike
record ``0x0200``, where an X5 stores a stitch.  Nothing here is viewable as a
sphere without projecting it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...errors import FormatError
from .preview import DUAL_FISHEYE, jpeg_dimensions
from .trailer import read_trailer

_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"


@dataclass(frozen=True)
class Source:
    """The container's own full-resolution frame, in its stored encoding."""

    encoding: str  # "jpeg"
    width: int
    height: int
    layout: str  # always DUAL_FISHEYE for the cameras measured
    data: bytes


def extract(path: str | Path) -> Source:
    """Return the full-resolution frame ``path`` wraps.

    Refuses rather than guessing: the bytes in front of the trailer must be a
    complete JPEG, start marker to end marker.  A ``.insv`` is an MP4 and has
    no single frame to hand back, so it fails that check and raises instead of
    returning a truncated buffer that would decode to noise.
    """
    path = Path(path)
    trailer = read_trailer(path)
    with path.open("rb") as handle:
        data = handle.read(trailer.offset)

    if len(data) != trailer.offset:
        raise FormatError(f"{path}: short read of the container ({len(data)} bytes)")
    if data[:2] != _SOI:
        raise FormatError(
            f"{path}: the container is not a JPEG, so it carries no single "
            f"full-resolution frame (a .insv is an MP4 -- extract a frame first)"
        )
    if data[-2:] != _EOI:
        # The trailer is appended after the JPEG's own end marker, so the two
        # boundaries must coincide.  If they do not, the trailer offset is
        # wrong and everything downstream would be built on a bad parse.
        raise FormatError(
            f"{path}: the JPEG does not end where the trailer begins; "
            f"the container layout is not what it was read as"
        )

    width, height = jpeg_dimensions(data)
    return Source("jpeg", width, height, DUAL_FISHEYE, data)
