"""Insta360 reader.

Implements the vendor contract described in :mod:`golblick.vendors`.
"""

from __future__ import annotations

from pathlib import Path

from . import calibration as _calibration
from . import metadata as _metadata
from .imu import gravity_up, gravity_up_nearby
from .lens import LensProfile, lens_profile
from .naming import EXTENSIONS, classify
from .preview import Preview
from .preview import extract as extract_preview
from .source import Source
from .source import extract as extract_source
from .thumbnail import extract as extract_thumbnail
from .trailer import MAGIC, METADATA, Record, Trailer, read_trailer

NAME = "insta360"
DESCRIPTION = "Insta360 .insp / .insv / .lrv"

__all__ = [
    "DESCRIPTION",
    "EXTENSIONS",
    "LensProfile",
    "MAGIC",
    "METADATA",
    "NAME",
    "Preview",
    "Record",
    "Source",
    "Trailer",
    "classify",
    "describe",
    "extract_preview",
    "extract_source",
    "extract_thumbnail",
    "gravity_up",
    "gravity_up_nearby",
    "lens_profile",
    "matches",
    "read_trailer",
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
