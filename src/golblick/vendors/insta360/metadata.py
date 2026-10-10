"""A dependency-free reader for the protobuf blob in trailer record 0x0101.

Insta360 publishes no ``.proto`` schema, so this deliberately does *not* try to
model the message.  It walks the protobuf wire format and hands back fields by
number, which is both simpler and more robust: a firmware revision that adds or
renumbers fields degrades to "that field is missing" instead of failing to
parse.  Only a handful of field numbers are actually needed, and they are named
in FIELDS below.

Wire format reference: https://protobuf.dev/programming-guides/encoding/
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

WIRE_VARINT = 0
WIRE_F64 = 1
WIRE_LEN = 2
WIRE_F32 = 5

# Field numbers verified against an X5 .insp (firmware v1.10.7_build2) by
# cross-checking decoded values with exiftool's Insta360 module.
SERIAL = 1
MODEL = 2
FIRMWARE = 3
CALIBRATION_EQUIDISTANT = 5     # exiftool exposes this one as "Parameters"
DIMENSIONS = 19                 # {1: width, 2: height}
FIRST_FRAME = 24                # video: frame 0's timecode on the inertial clock
CALIBRATION_POLY = 53
CALIBRATION_MEI = 54
CALIBRATION_MEI_EXTENDED = 111  # X5 only; see docs/formats/insta360-agent-notes.md

FIELDS = {
    SERIAL: "serial",
    MODEL: "model",
    FIRMWARE: "firmware",
    CALIBRATION_EQUIDISTANT: "calibration_equidistant",
    DIMENSIONS: "dimensions",
    CALIBRATION_POLY: "calibration_poly",
    CALIBRATION_MEI: "calibration_mei",
    CALIBRATION_MEI_EXTENDED: "calibration_mei_extended",
}

# Calibration strings, cheapest model first.  Later entries are richer.
CALIBRATION_FIELDS = (
    CALIBRATION_EQUIDISTANT,
    CALIBRATION_POLY,
    CALIBRATION_MEI,
    CALIBRATION_MEI_EXTENDED,
)


class ProtobufError(Exception):
    """The blob is not decodable as protobuf wire format."""


@dataclass(frozen=True)
class Field:
    number: int
    wire: int
    value: int | float | bytes

    @property
    def text(self) -> str | None:
        """The value as text, if it decodes as UTF-8."""
        if not isinstance(self.value, bytes):
            return None
        try:
            return self.value.decode("utf-8")
        except UnicodeDecodeError:
            return None


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf):
            raise ProtobufError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ProtobufError("varint too long")


def parse(buf: bytes) -> list[Field]:
    """Decode ``buf`` as a flat sequence of protobuf fields."""
    fields: list[Field] = []
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ProtobufError("field number 0 is not valid")
        if wire == WIRE_VARINT:
            value, pos = _varint(buf, pos)
        elif wire == WIRE_LEN:
            length, pos = _varint(buf, pos)
            if pos + length > len(buf):
                raise ProtobufError("length-delimited field runs past the buffer")
            value = buf[pos : pos + length]
            pos += length
        elif wire == WIRE_F32:
            if pos + 4 > len(buf):
                raise ProtobufError("truncated fixed32")
            value = struct.unpack_from("<f", buf, pos)[0]
            pos += 4
        elif wire == WIRE_F64:
            if pos + 8 > len(buf):
                raise ProtobufError("truncated fixed64")
            value = struct.unpack_from("<d", buf, pos)[0]
            pos += 8
        else:
            raise ProtobufError(f"unsupported wire type {wire}")
        fields.append(Field(number, wire, value))
    return fields


def spans(buf: bytes) -> list[tuple[int, int, int, int]]:
    """``(number, wire, start, end)`` for each top-level field's value bytes.

    For a varint that is the varint itself; for a length-delimited field, its
    payload.  What :func:`parse` decodes, located, so a field can be
    overwritten in place.
    """
    out = []
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        start = pos
        if wire == WIRE_VARINT:
            _, pos = _varint(buf, pos)
        elif wire == WIRE_LEN:
            length, start = _varint(buf, pos)
            pos = start + length
        elif wire == WIRE_F32:
            pos += 4
        elif wire == WIRE_F64:
            pos += 8
        else:
            raise ProtobufError(f"unsupported wire type {wire}")
        if pos > len(buf):
            raise ProtobufError("field runs past the buffer")
        out.append((number, wire, start, pos))
    return out


def by_number(buf: bytes) -> dict[int, list[Field]]:
    """Group ``parse`` output by field number, preserving order within a number."""
    grouped: dict[int, list[Field]] = {}
    for field in parse(buf):
        grouped.setdefault(field.number, []).append(field)
    return grouped


def first_text(grouped: dict[int, list[Field]], number: int) -> str | None:
    """The first field ``number`` decoded as text, or None."""
    for field in grouped.get(number, ()):
        if (text := field.text) is not None:
            return text
    return None


def dimensions(grouped: dict[int, list[Field]]) -> tuple[int, int] | None:
    """Source image dimensions from the nested DIMENSIONS submessage."""
    for field in grouped.get(DIMENSIONS, ()):
        if not isinstance(field.value, bytes):
            continue
        try:
            inner = by_number(field.value)
        except ProtobufError:
            continue
        width = inner.get(1, [None])[0]
        height = inner.get(2, [None])[0]
        if width is not None and height is not None:
            if isinstance(width.value, int) and isinstance(height.value, int):
                return width.value, height.value
    return None
