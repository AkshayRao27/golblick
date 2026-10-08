"""The opening frame of a OneR or X3 video, as the camera stores it in the trailer.

Measured over every video in one library (345 files):

=====================  ==========================  ==========================
File                   record ``0x0200``           record ``0x0500``
=====================  ==========================  ==========================
OneR, X3 ``_00_``      keyframe of lens 0          keyframe of lens 1
OneR, X3 proxy         keyframe, both lenses       the same bytes (80 of 80)
X5 master and proxy    NV12 stitch, see preview    absent
=====================  ==========================  ==========================

Each keyframe record is a 22-byte header and then an Annex B stream in the
clip's own codec (H.264 or HEVC) that decodes to exactly one picture.  On a
master that picture is one 2880x2880 fisheye, and on the three clips checked
it matches frame 0 of the clip to within one grey level; on a proxy it is
both fisheyes side by side.  So a master carries a whole lens pair of its
opening frame, even though the second lens's video is in another file.

⚠️ The header is not decoded: only its length is relied on, and the reader
checks that a start code follows it.  Nothing here decodes video either --
that needs a video decoder, which the library deliberately does not carry.
The CLI hands the streams to ffmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...errors import FormatError
from .trailer import read_trailer

LENS_0 = 0x0200
LENS_1 = 0x0500
_HEADER = 22
_START = b"\x00\x00\x00\x01"

#: What the streams hold: one fisheye each, or one frame with both.
LENS_PAIR = "lens-pair"
DUAL_FISHEYE = "dual-fisheye"


@dataclass(frozen=True)
class Keyframes:
    """Compressed opening frame(s) of a video, ready for a video decoder."""

    codec: str  # "h264" or "hevc"
    layout: str  # LENS_PAIR (two streams) or DUAL_FISHEYE (one)
    streams: tuple[bytes, ...]


def is_keyframe(data: bytes) -> bool:
    """Whether a record has the keyframe layout: the header, then a start code."""
    return data[_HEADER:_HEADER + 4] == _START


def _codec(stream: bytes) -> str:
    """The codec, from the type of the first NAL unit, which is a parameter set."""
    first = stream[4]
    if (first >> 1) & 0x3F == 32:  # HEVC video parameter set
        return "hevc"
    if first & 0x1F == 7:  # H.264 sequence parameter set
        return "h264"
    raise FormatError(f"keyframe starts with NAL byte 0x{first:02x}, not a parameter set of a known codec")


def parse(lens0: bytes, lens1: bytes | None) -> Keyframes:
    """Keyframes from the two records' payloads.  Refuses anything else."""
    if not is_keyframe(lens0):
        raise FormatError("record 0x0200 is not a video keyframe")
    stream0 = lens0[_HEADER:]
    codec = _codec(stream0)
    if lens1 is None:
        raise FormatError("record 0x0500, the second keyframe, is missing")
    if lens1 == lens0:
        # A proxy: one frame with both lenses in it, stored twice.
        return Keyframes(codec, DUAL_FISHEYE, (stream0,))
    if not is_keyframe(lens1):
        raise FormatError("record 0x0500 is not a video keyframe")
    stream1 = lens1[_HEADER:]
    if _codec(stream1) != codec:
        raise FormatError("the two keyframes are in different codecs")
    return Keyframes(codec, LENS_PAIR, (stream0, stream1))


def extract(path: str | Path) -> Keyframes:
    """The opening frame of the video at ``path``, still compressed."""
    trailer = read_trailer(path)
    record0, record1 = trailer.get(LENS_0), trailer.get(LENS_1)
    if record0 is None:
        raise FormatError(f"{path}: no record 0x0200")
    return parse(record0.data, None if record1 is None else record1.data)
