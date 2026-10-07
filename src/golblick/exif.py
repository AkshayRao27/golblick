"""Clear location, dates and descriptions from a JPEG's EXIF, in place.

Used to make a copy of a photo that is safe to share.  Every change keeps its
length: values are overwritten, nothing is inserted or removed, so no offset in
the file moves and everything else stays byte for byte as the camera wrote it.
That matters for container formats that index into the file from the end.

What it clears, and how:

* The GPS IFD: every value it points to is zeroed, then its entry count is set
  to 0, which leaves a valid, empty IFD.
* Dates (``DateTime``, ``DateTimeOriginal``, ``DateTimeDigitized``, and the
  sub-second and time-zone tags beside them): set to the EXIF standard's form
  for an unknown date, blanks around the colons.
* ``ImageDescription``: zeroed.  Cameras put the file name there, and file
  names carry the date and time.

It walks IFD0, the Exif IFD and IFD1 (the thumbnail's).  It refuses a layout
it cannot follow rather than skip it, because a scrubber that quietly misses a
block is worse than none.
"""

from __future__ import annotations

import struct

from .errors import FormatError

_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

_DESCRIPTION = 0x010E
_DATE_TIME = 0x0132
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATES = {0x0132, 0x9003, 0x9004}
#: Sub-second and time-zone companions of the dates; cleared to blanks too.
_DATE_PARTS = {0x9010, 0x9011, 0x9012, 0x9290, 0x9291, 0x9292}
_UNKNOWN_DATE = b"    :  :     :  :  "


def scrub_jpeg(buf: bytearray, start: int = 0) -> list[str]:
    """Scrub the EXIF of the JPEG that begins at ``buf[start]``; return what was cleared.

    A JPEG with no EXIF is left alone and returns an empty list.
    """
    if buf[start:start + 2] != b"\xff\xd8":
        raise FormatError("not a JPEG: no start-of-image marker")
    pos = start + 2
    while pos + 4 <= len(buf):
        if buf[pos] != 0xFF:
            raise FormatError(f"JPEG marker expected at byte {pos}")
        marker = buf[pos + 1]
        if marker == 0xDA:  # start of scan: no more metadata segments
            return []
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2
            continue
        (length,) = struct.unpack_from(">H", buf, pos + 2)
        body = pos + 4
        if marker == 0xE1 and bytes(buf[body:body + 6]) == b"Exif\0\0":
            return _scrub_tiff(buf, body + 6, body + length - 2)
        pos += 2 + length
    raise FormatError("JPEG ends before its image data")


def _scrub_tiff(buf: bytearray, tiff: int, end: int) -> list[str]:
    order = bytes(buf[tiff:tiff + 2])
    if order == b"II":
        endian = "<"
    elif order == b"MM":
        endian = ">"
    else:
        raise FormatError("EXIF block has no byte-order mark")
    u16, u32 = struct.Struct(endian + "H"), struct.Struct(endian + "I")

    def check(offset: int, size: int) -> int:
        if offset < 0 or tiff + offset + size > end:
            raise FormatError("EXIF offset points outside its block")
        return tiff + offset

    def entries(ifd: int):
        at = check(ifd, 2)
        (count,) = u16.unpack_from(buf, at)
        check(ifd + 2, count * 12 + 4)
        for index in range(count):
            entry = at + 2 + index * 12
            tag, kind, number = struct.unpack_from(endian + "HHI", buf, entry)
            size = _SIZES.get(kind, 1) * number
            value = entry + 8 if size <= 4 else check(u32.unpack_from(buf, entry + 8)[0], size)
            yield entry, tag, size, value

    def next_ifd(ifd: int) -> int:
        (count,) = u16.unpack_from(buf, check(ifd, 2))
        return u32.unpack_from(buf, check(ifd + 2 + count * 12, 4))[0]

    cleared: list[str] = []

    def clear_dates(ifd: int) -> None:
        for _, tag, size, value in entries(ifd):
            if tag in _DATES:
                buf[value:value + size] = (_UNKNOWN_DATE + b"\0" * size)[:size]
                cleared.append(f"date 0x{tag:04x}")
            elif tag in _DATE_PARTS:
                buf[value:value + size] = b" " * (size - 1) + b"\0" if size else b""
                cleared.append(f"date part 0x{tag:04x}")
            elif tag == _DESCRIPTION:
                buf[value:value + size] = b"\0" * size
                cleared.append("description")

    (ifd0,) = u32.unpack_from(buf, check(4, 4))
    clear_dates(ifd0)
    for entry, tag, _, _ in list(entries(ifd0)):
        (pointer,) = u32.unpack_from(buf, entry + 8)
        if tag == _EXIF_IFD:
            clear_dates(pointer)
        elif tag == _GPS_IFD:
            gps = list(entries(pointer))
            for gps_entry, _, size, value in gps:
                buf[value:value + size] = b"\0" * size
                buf[gps_entry:gps_entry + 12] = b"\0" * 12
            at = check(pointer, 2)
            buf[at:at + 2] = u16.pack(0)
            buf[at + 2:at + 6] = b"\0\0\0\0"  # the empty IFD's next-IFD offset
            cleared.append(f"GPS ({len(gps)} entries)")
    ifd1 = next_ifd(ifd0)
    if ifd1:
        clear_dates(ifd1)
    return cleared
