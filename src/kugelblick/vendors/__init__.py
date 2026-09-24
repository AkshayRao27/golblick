"""Vendor registry.

Every 360 camera vendor wraps its footage in its own container, so support is
organised per vendor behind a small contract.  A vendor module provides:

``NAME``
    Short identifier, e.g. ``"insta360"``.
``DESCRIPTION``
    Human-readable summary of the formats it handles.
``EXTENSIONS``
    File extensions the vendor owns, without the leading dot.
``matches(path) -> bool``
    Whether this vendor recognises the file.  Sniff content where possible
    rather than trusting the extension.
``classify(path) -> AssetInfo | None``
    Role and grouping key for master/proxy pairing.  See :mod:`kugelblick.triage`.
``describe(path) -> dict``
    Metadata for display.
``extract_thumbnail(path) -> bytes``
    An embedded preview image, if the format carries one.
``extract_preview(path) -> Preview``
    Optional.  The camera's own full-size preview, where one exists and is
    bigger or better than the thumbnail.  It reports its own encoding and
    layout, because a preview that is a fisheye pair cannot be displayed as
    a panorama and a caller has to be able to tell.
``gravity_up(path) -> (x, y, z)``
    Optional.  Which way is up in the render's own frame, from an inertial
    record if the format carries one.  Must raise rather than guess for a
    camera whose axis mapping has not been measured: a borrowed mapping
    produces a confident, wrong horizon.
``extract_source(path) -> Source``
    Optional.  The full-resolution imagery the container wraps, for a renderer
    to project from.  Reports its own encoding, size and layout.  Distinct from
    ``extract_preview`` on purpose: a preview is what the camera chose to show,
    and is typically a small fraction of the pixels.

Adding a vendor means writing a module with those names and listing it in
``VENDORS`` -- nothing else in the package needs to change.
"""

from __future__ import annotations

from pathlib import Path

from . import insta360

#: Registered vendors, tried in order.
VENDORS = (insta360,)


def detect(path: str | Path):
    """Return the vendor module that recognises ``path``, or None."""
    path = Path(path)
    for vendor in VENDORS:
        if vendor.matches(path):
            return vendor
    return None


def owned_extensions() -> frozenset[str]:
    """Every extension claimed by a registered vendor."""
    return frozenset().union(*(vendor.EXTENSIONS for vendor in VENDORS))
