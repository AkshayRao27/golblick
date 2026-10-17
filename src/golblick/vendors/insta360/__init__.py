"""Insta360 reader.

Implements the vendor contract described in :mod:`golblick.vendors`.
"""

from __future__ import annotations

from pathlib import Path

from . import calibration as _calibration
from . import metadata as _metadata
from .imu import Motion, gravity_up, gravity_up_nearby, motion
from .keyframe import Keyframes, lens_streams
from .keyframe import extract as extract_keyframes
from .lens import LensProfile, lens_profile
from .naming import EXTENSIONS, classify
from .preview import Preview
from .preview import extract as extract_preview
from .share import shareable
from .source import Source
from .source import extract as extract_source
from .thumbnail import extract as extract_thumbnail
from .trailer import MAGIC, METADATA, Record, Trailer, read_trailer

NAME = "insta360"
DESCRIPTION = "Insta360 .insp / .insv / .lrv"

#: Where a still opens: the render frame's -z, the same on the OneR, X3 and X5.
#: Insta360 Studio opens each export looking along this direction's
#: projection onto the horizon. Measured against Studio's exports of 15 OneR,
#: 12 X3 and 12 X5 photos, levelled from gravity: median 1.3, 3.4 and 0.5
#: degrees off, worst 8.3, 18.3 and 1.3. A fixed half turn fits the X3 and X5
#: as well but misses tilted OneR photos by up to 70 degrees, which this
#: follows. The X3 photos were all held at much the same tilt, so they can't
#: tell this axis from +y; the OneR and X5 can. Videos aren't measured.
PHOTO_FORWARD = (0.0, 0.0, -1.0)

__all__ = [
    "DESCRIPTION",
    "EXTENSIONS",
    "Keyframes",
    "LensProfile",
    "MAGIC",
    "METADATA",
    "Motion",
    "NAME",
    "PHOTO_FORWARD",
    "Preview",
    "Record",
    "Source",
    "Trailer",
    "classify",
    "describe",
    "extract_keyframes",
    "extract_preview",
    "extract_source",
    "extract_thumbnail",
    "gravity_up",
    "gravity_up_nearby",
    "lens_profile",
    "lens_streams",
    "matches",
    "motion",
    "read_trailer",
    "shareable",
]


def matches(path: str | Path) -> bool:
    """True if ``path`` carries an Insta360 trailer.

    Sniffs the magic at EOF rather than trusting the extension, so a renamed
    file is still recognised and a ``.insp`` that is not really one is not.
    """
    path = Path(path)
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            if handle.tell() < len(MAGIC):
                return False
            handle.seek(-len(MAGIC), 2)
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def describe(path: str | Path) -> dict:
    """Everything readable about ``path``, for display or scripting."""
    trailer = read_trailer(path)
    record = trailer.get(METADATA)
    info: dict = {
        "vendor": NAME,
        "trailer": trailer,
        "serial": None,
        "model": None,
        "firmware": None,
        "dimensions": None,
        "calibrations": {},
    }
    if record is None:
        return info

    grouped = _metadata.by_number(record.data)
    info["serial"] = _metadata.first_text(grouped, _metadata.SERIAL)
    info["model"] = _metadata.first_text(grouped, _metadata.MODEL)
    info["firmware"] = _metadata.first_text(grouped, _metadata.FIRMWARE)
    info["dimensions"] = _metadata.dimensions(grouped)
    info["calibrations"] = _calibration.from_metadata(grouped)
    return info
