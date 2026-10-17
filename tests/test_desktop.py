"""The desktop integration: file association, cache and the open command's checks.

Nothing here touches the real desktop: everything is written under a temporary
XDG data directory, and the tools that refresh the desktop's caches are
replaced so none of them runs.
"""

import os
import time

import pytest

from golblick import cli, desktop


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ran = []
    monkeypatch.setattr(desktop, "_run", lambda command: ran.append(command) or True)
    return tmp_path, ran


def test_install_registers_insp_as_a_kind_of_jpeg_and_opens_it_with_golblick(home):
    tmp, ran = home

    done = desktop.install("/opt/my tools/golblick")

    mime = (tmp / "data/mime/packages/golblick.xml").read_text()
    assert '<mime-type type="image/x-insta360-insp">' in mime
    assert '<sub-class-of type="image/jpeg"/>' in mime
    assert '<glob pattern="*.insp"' in mime
    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    # A path with a space has to be quoted for the Exec key.
    assert 'Exec="/opt/my tools/golblick" open %f' in entry
    assert "MimeType=image/x-insta360-insp;" in entry
    assert ["xdg-mime", "default", "golblick-open.desktop", "image/x-insta360-insp"] in ran
    assert any("default" in line for line in done)


def test_uninstall_removes_both_files(home):
    tmp, _ = home
    desktop.install("/usr/bin/golblick")

    desktop.uninstall()

    assert not (tmp / "data/mime/packages/golblick.xml").exists()
    assert not (tmp / "data/applications/golblick-open.desktop").exists()


def test_the_mime_type_does_not_claim_plain_jpegs():
    """Only the .insp extension, and no magic that would match every JPEG."""
    assert "<magic" not in desktop.MIME_XML
    assert "*.jpg" not in desktop.MIME_XML and "*.jpeg" not in desktop.MIME_XML


def test_the_cache_key_follows_the_file_and_the_renderer(tmp_path):
    photo = tmp_path / "IMG_1.insp"
    photo.write_bytes(b"one")
    first = desktop.cache_key(photo, "0.6.0", 4096)

    assert desktop.cache_key(photo, "0.6.0", 4096) == first
    assert desktop.cache_key(photo, "0.6.1", 4096) != first
    assert desktop.cache_key(photo, "0.6.0", 2048) != first
    photo.write_bytes(b"changed")
    os.utime(photo, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert desktop.cache_key(photo, "0.6.0", 4096) != first


def test_prune_keeps_the_most_recently_used(tmp_path):
    for k in range(5):
        entry = tmp_path / f"{k}.jpg"
        entry.write_bytes(b"x")
        os.utime(entry, (1_000_000 + k, 1_000_000 + k))

    desktop.prune(tmp_path, keep=2)

    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["3.jpg", "4.jpg"]


def test_desktop_install_from_the_cli_takes_the_given_command(home, capsys):
    tmp, _ = home

    assert cli.main(["desktop", "install", "--executable", "/usr/local/bin/golblick"]) == 0

    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    assert 'Exec="/usr/local/bin/golblick" open %f' in entry
    assert "/usr/local/bin/golblick open" in capsys.readouterr().out


def test_open_refuses_a_missing_file(home, capsys):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")

    assert cli.main(["open", "/nonexistent/IMG_1.insp", "--no-window"]) == 1
    assert "no such file" in capsys.readouterr().err
