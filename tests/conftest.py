import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kugelblick.vendors.insta360 import MAGIC  # noqa: E402


def build_trailer(records, *, version=3, pad=32):
    """Assemble a trailer the way the camera does, for use as a test fixture.

    ``records`` is a sequence of ``(record_id, payload)`` in file order.
    """
    body = b"".join(data + struct.pack("<HI", record_id, len(data)) for record_id, data in records)
    body += b"\x00" * pad
    size = len(body) + 8 + len(MAGIC)
    return body + struct.pack("<II", size, version) + MAGIC


def write_file(path, records, *, leading=b"\xff\xd8\xff\xe0payload", **kwargs):
    path.write_bytes(leading + build_trailer(records, **kwargs))
    return path


def build_exif_jpeg(thumbnail: bytes) -> bytes:
    """A minimal JPEG carrying ``thumbnail`` in EXIF IFD1, as the camera does."""
    header = b"II" + struct.pack("<HI", 42, 8)
    ifd1_offset = 8 + 18
    thumb_offset = ifd1_offset + 30

    ifd0 = struct.pack("<H", 1)
    ifd0 += struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<HH", 1, 0)  # Orientation
    ifd0 += struct.pack("<I", ifd1_offset)

    ifd1 = struct.pack("<H", 2)
    ifd1 += struct.pack("<HHI", 0x0201, 4, 1) + struct.pack("<I", thumb_offset)
    ifd1 += struct.pack("<HHI", 0x0202, 4, 1) + struct.pack("<I", len(thumbnail))
    ifd1 += struct.pack("<I", 0)

    tiff = header + ifd0 + ifd1 + thumbnail
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
