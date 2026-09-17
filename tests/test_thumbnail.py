import pytest

from conftest import build_exif_jpeg
from insta360.thumbnail import ThumbnailError, extract

FAKE_THUMBNAIL = b"\xff\xd8\xff\xdbthumbnail bytes\xff\xd9"


def test_extracts_ifd1_thumbnail(tmp_path):
    path = tmp_path / "a.insp"
    path.write_bytes(build_exif_jpeg(FAKE_THUMBNAIL))

    assert extract(path) == FAKE_THUMBNAIL


def test_non_jpeg_is_rejected(tmp_path):
    path = tmp_path / "a.insp"
    path.write_bytes(b"not a jpeg at all")

    with pytest.raises(ThumbnailError):
        extract(path)


def test_jpeg_without_exif_is_rejected(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"\xff\xd8" + b"\xff\xda" + b"\x00\x02" + b"scan data" + b"\xff\xd9")

    with pytest.raises(ThumbnailError):
        extract(path)
