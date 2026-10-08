"""A copy of a still that is safe to send to someone else.

What a ``.insp`` carries that identifies a person, measured on the OneR, X3
and X5 (``docs/formats/insta360-agent-notes.md`` has the inventory):

| Where | What |
|---|---|
| EXIF GPS | latitude, longitude, altitude |
| metadata field 11 | latitude and longitude **again**, as doubles |
| metadata field 1 | the camera's serial number, its only occurrence in the file |
| EXIF dates, metadata field 7 | when the photo was taken |
| EXIF ImageDescription, metadata field 26 | the file name or the SD-card path, which carry the date |

All of it is overwritten in place, keeping every length, so nothing moves:
the image, the calibration, the inertial record and the preview are left
byte for byte as the camera wrote them, and a render of the copy matches a
render of the original.

🔴 **Then it checks its own work and refuses rather than hand back a copy that
still leaks.** Every identifier collected from the original -- the serial,
each form of the date, the coordinates -- is searched for in the whole copy,
not just where it was expected to be.  The undecoded records ``0x0900`` and
``0x0b00`` are left alone; neither the serial nor the coordinates were found
in them on any of the three cameras, and the search covers them anyway.
"""

from __future__ import annotations

import re
from pathlib import Path

from ...errors import FormatError
from ...exif import scrub_jpeg
from . import metadata as _metadata
from .trailer import METADATA, read_trailer

#: Metadata fields cleared, by what they hold.
_SERIAL = _metadata.SERIAL
_CAPTURE_TIME = 7      # YYYYMMDDhhmmss as a varint; X5, not on every OneR
_LOCATION = 11         # three doubles: latitude, longitude, and a third value
_STAMP = re.compile(rb"\d{8}_\d{6}")


def shareable(path: str | Path) -> tuple[bytes, list[str]]:
    """The cleaned copy's bytes, and a list of what was cleared."""
    path = Path(path)
    data = bytearray(path.read_bytes())
    trailer = read_trailer(path)
    record = trailer.get(METADATA)
    if record is None:
        raise FormatError(f"{path}: no metadata record, so nothing to check the copy against")

    secrets: list[bytes] = []
    stamps: set[str] = set()
    if match := _STAMP.search(path.name.encode()):
        stamps.add(match.group().decode().replace("_", ""))
    cleared: list[str] = []

    for number, wire, start, end in _metadata.spans(record.data):
        at, until = record.offset + start, record.offset + end
        value = bytes(data[at:until])
        if number == _SERIAL and wire == _metadata.WIRE_LEN:
            # A copy made by share already has a serial of zeros, and zeros are everywhere.
            if value.strip(b"0"):
                secrets.append(value)
            data[at:until] = b"0" * len(value)
            cleared.append("serial number")
        elif number == _CAPTURE_TIME and wire == _metadata.WIRE_VARINT:
            stamps.add(str(_metadata._varint(value, 0)[0]))
            # A varint of zero, padded to the same length: valid protobuf.
            data[at:until] = b"\x80" * (len(value) - 1) + b"\x00"
            cleared.append("capture time")
        elif number == _LOCATION and wire == _metadata.WIRE_LEN:
            for offset in range(0, len(value) - 7, 8):
                if value[offset:offset + 8] != b"\0" * 8:
                    secrets.append(value[offset:offset + 8])
            data[at:until] = b"\0" * len(value)
            cleared.append("location (camera metadata)")

    # File names and SD-card paths inside the metadata carry the date.
    meta = bytes(data[record.offset:record.offset + record.size])
    for found in _STAMP.finditer(meta):
        stamps.add(found.group().decode().replace("_", ""))
        start = record.offset + found.start()
        data[start:start + len(found.group())] = re.sub(rb"\d", b"0", found.group())
        cleared.append("file name in camera metadata")

    cleared += scrub_jpeg(data, 0)

    _verify(data, secrets, stamps)
    return bytes(data), cleared


def _verify(data: bytearray, secrets: list[bytes], stamps: set[str]) -> None:
    """Refuse if anything collected from the original is still in the copy."""
    for secret in secrets:
        if secret and secret in data:
            raise FormatError("the copy still contains the serial number or the location; "
                              "refusing to write it")
    for stamp in stamps:
        if len(stamp) < 8 or not stamp.strip("0"):
            continue
        day, time = stamp[:8], stamp[8:14]
        forms = {stamp, f"{day}_{time}", f"{day[:4]}:{day[4:6]}:{day[6:8]}",
                 f"{day[:4]}-{day[4:6]}-{day[6:8]}"}
        for form in forms:
            if len(form) >= 8 and form.encode() in data:
                raise FormatError(f"the copy still contains the date the photo was taken "
                                  f"(as {len(form)} characters); refusing to write it")
    # The EXIF GPS block must now be empty: scrubbing a copy again finds no entries.
    again = scrub_jpeg(bytearray(data), 0)
    if any(item.startswith("GPS (") and item != "GPS (0 entries)" for item in again):
        raise FormatError("the copy's EXIF still has GPS entries; refusing to write it")
