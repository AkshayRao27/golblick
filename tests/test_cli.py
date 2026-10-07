from conftest import build_exif_jpeg, write_file

from golblick import cli

FAKE_THUMBNAIL = b"\xff\xd8\xff\xdbthumbnail bytes\xff\xd9"


def test_writes_next_to_the_original_by_default(tmp_path):
    source = write_file(tmp_path / "a.insp", [], leading=build_exif_jpeg(FAKE_THUMBNAIL))

    assert cli.main(["thumb", str(source)]) == 0
    assert (tmp_path / "a.thumb.jpg").read_bytes() == FAKE_THUMBNAIL


def test_refuses_to_write_over_the_file_being_read(tmp_path):
    source = write_file(tmp_path / "a.insp", [], leading=build_exif_jpeg(FAKE_THUMBNAIL))
    original = source.read_bytes()

    # Spelled differently from the input, so a string comparison would miss it.
    assert cli.main(["thumb", str(source), "-o", str(tmp_path / "." / "a.insp")]) == 1
    assert source.read_bytes() == original
