"""Pairing of Insta360 masters with their proxies, and detection of orphans.

The camera writes two files per video clip: a full-quality master and a
low-resolution proxy it uses for scrubbing in the phone app.

    VID_20260227_142557_00_005.insv    master, two HEVC fisheye streams
    LRV_20260227_142557_01_005.lrv     proxy, one low-bitrate H.264 stream

Both are dual-fisheye; the proxy is *not* a stitched preview, so it is of no use
for viewing and is pure duplication -- as long as its master is present.

A proxy whose master has gone missing is the case worth surfacing.  It may be
deliberate (the master was deleted to reclaim space) or it may be data loss, and
the difference is invisible without checking.  Nothing in the file says which,
so this module reports the fact and leaves the judgement to a human.

This runs on metadata alone -- no decoding, no stitching, no camera software --
which is the point: it answers the question on Linux.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: PREFIX_<date>_<time>_<marker>_<sequence>.<ext>
_NAME = re.compile(
    r"^(?P<prefix>VID|LRV|IMG)"
    r"_(?P<stamp>\d{8}_\d{6})"
    r"_(?P<marker>\d{2})"
    r"_(?P<sequence>\d+)"
    r"\.(?P<extension>insv|lrv|insp)$",
    re.IGNORECASE,
)

MASTER_EXTENSIONS = {"insv"}
PROXY_EXTENSIONS = {"lrv"}
PHOTO_EXTENSIONS = {"insp"}

PAIRED = "paired"
ORPHAN_PROXY = "orphan-proxy"
MASTER_ONLY = "master-only"


@dataclass(frozen=True)
class Asset:
    path: Path
    prefix: str
    stamp: str
    marker: str
    sequence: str
    extension: str
    size: int


@dataclass
class Clip:
    """A master/proxy group, keyed on directory plus timestamp plus sequence."""

    directory: Path
    stamp: str
    sequence: str
    masters: list[Asset] = field(default_factory=list)
    proxies: list[Asset] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.masters and self.proxies:
            return PAIRED
        if self.proxies:
            return ORPHAN_PROXY
        return MASTER_ONLY

    @property
    def size(self) -> int:
        return sum(asset.size for asset in (*self.masters, *self.proxies))

    @property
    def redundant_bytes(self) -> int:
        """Proxy bytes that duplicate a master that is still present."""
        if self.status != PAIRED:
            return 0
        return sum(asset.size for asset in self.proxies)

    @property
    def at_risk_bytes(self) -> int:
        """Proxy bytes that are the only surviving copy of a clip."""
        if self.status != ORPHAN_PROXY:
            return 0
        return sum(asset.size for asset in self.proxies)


@dataclass
class Report:
    clips: list[Clip] = field(default_factory=list)
    photos: list[Asset] = field(default_factory=list)
    unmatched: list[Path] = field(default_factory=list)

    def of_status(self, status: str) -> list[Clip]:
        return [clip for clip in self.clips if clip.status == status]

    @property
    def redundant_bytes(self) -> int:
        return sum(clip.redundant_bytes for clip in self.clips)

    @property
    def at_risk_bytes(self) -> int:
        return sum(clip.at_risk_bytes for clip in self.clips)


def _classify(path: Path) -> Asset | None:
    match = _NAME.match(path.name)
    if not match:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return Asset(
        path=path,
        prefix=match["prefix"].upper(),
        stamp=match["stamp"],
        marker=match["marker"],
        sequence=match["sequence"],
        extension=match["extension"].lower(),
        size=size,
    )


def scan(root: str | Path, *, recursive: bool = True) -> Report:
    """Walk ``root`` and group Insta360 assets into clips."""
    root = Path(root)
    report = Report()
    clips: dict[tuple[Path, str, str], Clip] = {}

    paths = sorted(root.rglob("*") if recursive else root.glob("*"))
    for path in paths:
        if not path.is_file():
            continue
        asset = _classify(path)
        if asset is None:
            if path.suffix.lower().lstrip(".") in (
                MASTER_EXTENSIONS | PROXY_EXTENSIONS | PHOTO_EXTENSIONS
            ):
                report.unmatched.append(path)
            continue

        if asset.extension in PHOTO_EXTENSIONS:
            report.photos.append(asset)
            continue

        key = (path.parent, asset.stamp, asset.sequence)
        clip = clips.get(key)
        if clip is None:
            clip = Clip(directory=path.parent, stamp=asset.stamp, sequence=asset.sequence)
            clips[key] = clip
            report.clips.append(clip)

        if asset.extension in MASTER_EXTENSIONS:
            clip.masters.append(asset)
        else:
            clip.proxies.append(asset)

    return report
