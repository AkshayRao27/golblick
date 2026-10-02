"""Pairing masters with proxies, and finding the ones whose master is gone.

360 cameras commonly write two files per clip: a full-quality master and a
low-resolution proxy used for scrubbing in the vendor's phone app.  While both
are present the proxy is pure duplication.  Once the master is deleted the
proxy becomes the only surviving copy of that clip -- at a fraction of the
quality, and usually without the owner realising.

Nothing in the files records whether such a deletion was deliberate, so this
module reports the situation and leaves the judgement to a human.

The pairing logic here is vendor-neutral.  Recognising filenames is not, so each
vendor supplies :func:`classify` returning an :class:`AssetInfo`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: Roles a file can play within a clip.
MASTER = "master"
PROXY = "proxy"
PHOTO = "photo"

#: Resulting state of a clip.
PAIRED = "paired"
ORPHAN_PROXY = "orphan-proxy"
MASTER_ONLY = "master-only"


@dataclass(frozen=True)
class AssetInfo:
    """What a vendor can tell from a filename alone."""

    role: str
    #: Opaque key identifying the clip *within its directory*.  Sequence
    #: numbers restart, so this must not be treated as globally unique.
    group: str
    vendor: str
    extension: str


@dataclass(frozen=True)
class Asset:
    path: Path
    info: AssetInfo
    size: int

    @property
    def role(self) -> str:
        return self.info.role

    @property
    def vendor(self) -> str:
        return self.info.vendor


@dataclass
class Clip:
    """A master/proxy group, keyed on directory plus vendor plus group."""

    directory: Path
    group: str
    vendor: str
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
        """Proxy bytes duplicating a master that is still present."""
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


def scan(root: str | Path, *, recursive: bool = True, vendors=None) -> Report:
    """Walk ``root`` and group assets into clips.

    Classification is by filename, not by content: triage runs over whole photo
    libraries, and opening every file to sniff it would be far slower for no
    gain.  A file carrying a vendor's extension whose name does not parse is
    reported under ``unmatched`` rather than silently dropped.
    """
    # Imported here rather than at module level: vendor modules import this one
    # for AssetInfo, so a top-level import would be circular.
    if vendors is None:
        from .vendors import VENDORS as vendors  # noqa: PLC0415

    owned = frozenset().union(*(vendor.EXTENSIONS for vendor in vendors)) if vendors else frozenset()

    root = Path(root)
    report = Report()
    clips: dict[tuple[Path, str, str], Clip] = {}

    paths = sorted(root.rglob("*") if recursive else root.glob("*"))
    for path in paths:
        try:
            if not path.is_file():
                continue
        except OSError:
            # Sync clients leave names that stat() rejects (one NTFS mount
            # returns EINVAL).  One odd file must not abort a library-wide
            # scan, and the name is all classification needs anyway.
            pass

        info = None
        for vendor in vendors:
            info = vendor.classify(path)
            if info is not None:
                break

        if info is None:
            if path.suffix.lower().lstrip(".") in owned:
                report.unmatched.append(path)
            continue

        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        asset = Asset(path=path, info=info, size=size)

        if info.role == PHOTO:
            report.photos.append(asset)
            continue

        key = (path.parent, info.vendor, info.group)
        clip = clips.get(key)
        if clip is None:
            clip = Clip(directory=path.parent, group=info.group, vendor=info.vendor)
            clips[key] = clip
            report.clips.append(clip)

        if info.role == MASTER:
            clip.masters.append(asset)
        else:
            clip.proxies.append(asset)

    return report
