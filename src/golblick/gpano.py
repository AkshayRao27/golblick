"""GPano XMP -- the metadata that makes a panorama open as a sphere.

A correctly projected equirectangular image is still just a wide picture as far
as any viewer is concerned.  What makes it a panorama is a block of XMP saying
so, in the namespace Google defined for Photo Sphere and everything else
adopted: Google Photos, Facebook, Nextcloud's photo viewers, Pannellum,
Photo Sphere Viewer, and the ``exiftool`` that Nextcloud Memories already runs
over every indexed file.

Spec: https://developers.google.com/streetview/spherical-metadata

Everything here is standard library.  Writing the metadata is text and byte
splicing; only *encoding pixels* needs a real imaging library, which is why
this module sits outside the ``render`` extra and can be used by a caller that
has a JPEG from somewhere else entirely.

WHAT IS WRITTEN, AND WHAT IS DELIBERATELY NOT
---------------------------------------------
The geometry fields are written, because they are known: the renderer chose the
output size and whether the sphere is complete.

The **pose** fields are not, and that is a deliberate refusal rather than an
omission.  ``PoseHeadingDegrees`` would state which compass direction the
centre of the image faces; nothing in the container fixes that.  Yaw against an
X5's own stitch is a constant 180.3 degrees, which is a frame convention and
not a bearing, and a camera that embeds no stitch fixes the yaw not at all.
``PosePitchDegrees`` and ``PoseRollDegrees`` would assert the panorama is
level, which is only true to the extent the levelling worked -- and
``body_orientation`` corrects the sensor mounting, not the camera's attitude.

A viewer that finds no pose fields assumes an unknown heading and a level
horizon, which is exactly the honest claim.  Writing a fabricated 0.0 would
look identical to a measured 0.0 to everything downstream.
``docs/formats/insta360-agent-notes.md`` owns the measurements behind this.
"""

from __future__ import annotations

import struct
import zlib

#: The namespace GPano fields live in.
NAMESPACE = "http://ns.google.com/photos/1.0/panorama/"

#: The APP1 identifier that marks a JPEG segment as XMP, NUL terminated.
JPEG_IDENTIFIER = b"http://ns.adobe.com/xap/1.0/\x00"

#: The PNG ``iTXt`` keyword that marks a text chunk as XMP.
PNG_KEYWORD = b"XML:com.adobe.xmp"

EQUIRECTANGULAR = "equirectangular"

# A JPEG segment carries a 16-bit length that includes itself, so the payload
# cannot exceed this.  XMP has an extension mechanism for larger packets; we do
# not need it (a full packet here is well under a kilobyte) and refuse instead
# of writing something a reader would silently truncate.
_MAX_SEGMENT = 0xFFFF - 2


class GPanoError(Exception):
    """The metadata could not be built or embedded."""


def packet(
    width: int,
    height: int,
    full_width: int | None = None,
    full_height: int | None = None,
    left: int = 0,
    top: int = 0,
    projection: str = EQUIRECTANGULAR,
    software: str | None = None,
) -> bytes:
    """Build an XMP packet describing an equirectangular image.

    ``width`` and ``height`` are the image as stored.  ``full_width`` and
    ``full_height`` describe the complete sphere it is a crop of; they default
    to the stored size, which is the ordinary full-sphere case.  ``left`` and
    ``top`` place the crop within that sphere.

    A partial panorama is the case that goes wrong quietly: without the cropped
    area fields a viewer stretches the crop around the whole sphere, and the
    result looks plausible rather than broken.  So the fields are always
    written, even when they are trivially the full frame.
    """
    if width <= 0 or height <= 0:
        raise GPanoError(f"image size {width}x{height} is not positive")

    full_width = width if full_width is None else full_width
    full_height = height if full_height is None else full_height

    if full_width < width + left or full_height < height + top:
        raise GPanoError(
            f"crop {width}x{height} at ({left},{top}) does not fit inside "
            f"{full_width}x{full_height}"
        )
    if left < 0 or top < 0:
        raise GPanoError(f"crop origin ({left},{top}) is negative")

    fields = {
        "UsePanoramaViewer": "True",
        "ProjectionType": projection,
        "CroppedAreaImageWidthPixels": width,
        "CroppedAreaImageHeightPixels": height,
        "FullPanoWidthPixels": full_width,
        "FullPanoHeightPixels": full_height,
        "CroppedAreaLeftPixels": left,
        "CroppedAreaTopPixels": top,
    }
    attributes = "\n   ".join(f'GPano:{key}="{value}"' for key, value in fields.items())

    extra = ""
    if software is not None:
        extra = f'\n   xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n   xmp:CreatorTool="{_escape(software)}"'

    # The BOM in the begin attribute is part of the packet convention: it is how
    # a reader scanning raw bytes detects the encoding.
    text = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        f'   xmlns:GPano="{NAMESPACE}"{extra}\n'
        f"   {attributes}/>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )
    return text.encode("utf-8")


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def jpeg_segment(xmp: bytes) -> bytes:
    """Wrap an XMP packet as a JPEG APP1 segment."""
    payload = JPEG_IDENTIFIER + xmp
    if len(payload) > _MAX_SEGMENT:
        raise GPanoError(
            f"XMP packet is {len(payload)} bytes; a JPEG segment holds {_MAX_SEGMENT}. "
            f"Writing it would need the XMP extension mechanism, which is not implemented"
        )
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def embed_jpeg(jpeg: bytes, xmp: bytes) -> bytes:
    """Insert ``xmp`` into ``jpeg`` as an APP1 segment.

    The segment goes after any leading APP0 (JFIF), because readers expect JFIF
    first where it is present, and before everything else.  An existing XMP
    segment is *replaced* rather than appended to, so re-running this does not
    leave two packets behind for a reader to choose between.
    """
    if jpeg[:2] != b"\xff\xd8":
        raise GPanoError("not a JPEG: no start-of-image marker")

    pos = 2
    insert_at = 2
    while pos + 4 <= len(jpeg) and jpeg[pos] == 0xFF:
        marker = jpeg[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            break
        length = struct.unpack_from(">H", jpeg, pos + 2)[0]
        if length < 2:
            raise GPanoError(f"segment at {pos} declares an impossible length {length}")
        end = pos + 2 + length
        segment = jpeg[pos + 4 : end]

        if marker == 0xE0:  # APP0/JFIF: keep it first, insert after.
            insert_at = end
        elif marker == 0xE1 and segment.startswith(JPEG_IDENTIFIER):
            # Drop the old packet and put the new one exactly where it was.
            return jpeg[:pos] + jpeg_segment(xmp) + jpeg[end:]
        elif marker != 0xE0:
            break
        pos = end

    return jpeg[:insert_at] + jpeg_segment(xmp) + jpeg[insert_at:]


def png_chunk(xmp: bytes) -> bytes:
    """Wrap an XMP packet as an uncompressed PNG ``iTXt`` chunk.

    ⚠️ PNG is the lossless option, not the compatible one. GPano is specified
    against JPEG, and viewers that read it from a PNG are the exception rather
    than the rule -- ``exiftool`` does, many web viewers do not. Prefer JPEG
    when the output is meant to be opened by something else.
    """
    payload = (
        PNG_KEYWORD
        + b"\x00"       # end of keyword
        + b"\x00\x00"   # not compressed; compression method is then ignored
        + b"\x00"       # empty language tag
        + b"\x00"       # empty translated keyword
        + xmp
    )
    return (
        struct.pack(">I", len(payload))
        + b"iTXt"
        + payload
        + struct.pack(">I", zlib.crc32(b"iTXt" + payload))
    )
