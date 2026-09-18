"""The vendor registry: detection is by content, not by file extension."""

from conftest import write_file
from kugelblick import detect
from kugelblick.vendors import VENDORS, owned_extensions
from kugelblick.vendors.insta360 import METADATA


def test_detects_by_trailer_magic_not_extension(tmp_path):
    """A renamed file is still recognised."""
    path = write_file(tmp_path / "holiday.jpg", [(METADATA, b"meta")])

    vendor = detect(path)

    assert vendor is not None
    assert vendor.NAME == "insta360"


def test_right_extension_wrong_content_is_not_claimed(tmp_path):
    path = tmp_path / "impostor.insp"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"an ordinary jpeg" * 20)

    assert detect(path) is None


def test_missing_file_does_not_raise(tmp_path):
    assert detect(tmp_path / "nope.insp") is None


def test_every_vendor_satisfies_the_contract():
    for vendor in VENDORS:
        for attribute in (
            "NAME", "DESCRIPTION", "EXTENSIONS",
            "matches", "classify", "describe", "extract_thumbnail",
        ):
            assert hasattr(vendor, attribute), f"{vendor!r} is missing {attribute}"


def test_owned_extensions_are_collected():
    assert "insp" in owned_extensions()
    assert "insv" in owned_extensions()
