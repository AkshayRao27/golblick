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
    Role and grouping key for master/proxy pairing.  See :mod:`golblick.triage`.
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
``gravity_up_nearby(path) -> (x, y, z)``
    Optional, and the one a renderer should prefer.  Same answer, but allowed
    to read the *directory*: where a still carries no inertial record, another
    frame of the same burst usually does, and on Insta360 hardware that record
    is byte-identical across the burst rather than merely similar.
    ⚠️ It is a separate entry point on purpose.  Everything else here is handed
    a path and reports what is inside it; this is the one that looks outside,
    so a caller that must not touch the filesystem can still use ``gravity_up``.
``lens_profile(path) -> profile | None``
    Optional.  What the file does not carry about the lenses but a renderer
    needs: ``field_of_view``, and ``radial``, a measured correction to the
    equidistant model (see ``render.Lens.radial``).  Per camera model and
    measured, never guessed; None for a camera nobody has measured.
``extract_source(path) -> Source``
    Optional.  The full-resolution imagery the container wraps, for a renderer
    to project from.  Reports its own encoding, size and layout.  Distinct from
    ``extract_preview`` on purpose: a preview is what the camera chose to show,
    and is typically a small fraction of the pixels.

``extract_keyframes(path) -> Keyframes``
    Optional.  A video's opening frame as the camera stored it, still
    compressed: ``codec``, ``layout`` (one stream per lens, or one stream with
    both) and the ``streams``.  The library carries no video decoder, so this
    hands over bytes for something else to decode; the CLI uses ffmpeg.

``shareable(path) -> (bytes, cleared)``
    Optional.  A copy of the file that is safe to send to someone else: no
    location, no dates, no serial number, everything else unchanged.  Must
    check its own result and raise rather than return a copy that still
    carries any of them.

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
