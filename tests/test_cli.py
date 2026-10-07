from urllib.parse import unquote_plus

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


def _text_field(number: int, text: str) -> bytes:
    """One length-delimited protobuf field, as the metadata record stores text."""
    data = text.encode()
    assert number < 16 and len(data) < 128  # one-byte tag and length keep this short
    return bytes([number << 3 | 2, len(data)]) + data


def test_report_leaves_out_the_name_folder_and_serial(tmp_path, capsys):
    from golblick.vendors.insta360 import METADATA

    folder = tmp_path / "Summer holiday"
    folder.mkdir()
    metadata = (_text_field(1, "IXSE42SERIAL7") + _text_field(2, "Insta360 OneR")
                + _text_field(3, "v1.1.43_build1"))
    source = write_file(folder / "IMG_20240513_192749_00_004.insp", [(METADATA, metadata)])

    assert cli.main(["report", str(source)]) == 0
    captured = capsys.readouterr()
    out = captured.out
    # The issue link on stderr carries the report too, URL-encoded.
    link = unquote_plus(captured.err)

    assert "Insta360 OneR" in out and "v1.1.43_build1" in out
    # A OneR has a measured lens profile, so this is a photo problem, not an untested camera.
    assert "tested       yes" in out
    assert "template=photo-problem.yml" in link
    assert "title=Photo problem: Insta360 OneR, v1.1.43_build1 (command line)" in link
    for private in ("IXSE42SERIAL7", "Summer holiday", "20240513", "192749", str(tmp_path)):
        assert private not in out and private not in link


def test_report_carries_on_past_a_failure_and_hides_the_path(tmp_path, capsys):
    from golblick.vendors.insta360 import MAGIC

    # The magic is there, so the vendor claims the file, but the trailer is nonsense.
    source = tmp_path / "Secret place" / "IMG_20240101_000000_00_001.insp"
    source.parent.mkdir()
    source.write_bytes(b"\xff\xd8\xff" + b"\x01" * 64 + MAGIC)

    assert cli.main(["report", str(source)]) == 0
    out = capsys.readouterr().out

    assert "metadata     failed:" in out
    assert "<file>" in out
    assert "Secret place" not in out and "20240101" not in out


def test_report_says_what_an_unrecognised_file_looks_like(tmp_path, capsys):
    plain = tmp_path / "a.insp"
    plain.write_bytes(b"\xff\xd8\xff\xe0" + b"\x01" * 100 + b"\xff\xd9")
    damaged = tmp_path / "b.insp"
    damaged.write_bytes(b"\xff\xd8\xff\xe0" + b"\x01" * 100 + b"\x00" * 4096)

    cli.main(["report", str(plain)])
    assert "a complete JPEG with no camera data after it" in capsys.readouterr().out
    cli.main(["report", str(damaged)])
    assert "the last 4.0 KiB are zeros" in capsys.readouterr().out


def test_report_sends_an_unmeasured_camera_to_the_untested_camera_form(tmp_path, capsys):
    from golblick.vendors.insta360 import METADATA

    source = write_file(tmp_path / "a.insp", [(METADATA, _text_field(2, "Insta360 X4"))])

    assert cli.main(["report", str(source)]) == 0
    captured = capsys.readouterr()
    link = unquote_plus(captured.err)

    assert "tested       no" in captured.out
    assert "template=untested-camera.yml" in link
    assert "title=Untested camera: Insta360 X4 (command line)" in link
