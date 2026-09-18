"""Insta360's file naming convention, and what each role means.

The camera writes a full-quality master and a low-resolution proxy for every
video clip::

    VID_20260227_142557_00_005.insv    master, two HEVC fisheye streams
    LRV_20260227_142557_01_005.lrv     proxy, one low-bitrate H.264 stream
    IMG_20260314_090809_00_007.insp    still

Sequence numbers restart, so the timestamp and sequence together identify a clip
only *within a directory*.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...triage import MASTER, PHOTO, PROXY, AssetInfo

_NAME = re.compile(
    r"^(?P<prefix>VID|LRV|IMG)"
    r"_(?P<stamp>\d{8}_\d{6})"
    r"_(?P<marker>\d{2})"
    r"_(?P<sequence>\d+)"
    r"\.(?P<extension>insv|lrv|insp)$",
    re.IGNORECASE,
)

_ROLES = {"insv": MASTER, "lrv": PROXY, "insp": PHOTO}

#: Extensions this vendor owns, used to flag files whose names do not parse
#: rather than silently ignoring them.
EXTENSIONS = frozenset(_ROLES)


def classify(path: Path) -> AssetInfo | None:
    """Describe ``path`` if it follows the convention, else None."""
    match = _NAME.match(path.name)
    if match is None:
        return None
    extension = match["extension"].lower()
    return AssetInfo(
        role=_ROLES[extension],
        group=f"{match['stamp']}_{match['sequence']}",
        vendor="insta360",
        extension=extension,
    )
