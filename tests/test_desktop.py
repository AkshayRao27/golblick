"""The desktop integration: file association, the viewer's numbers and the open command's checks.

Nothing here touches the real desktop: everything is written under a temporary
XDG data directory, and the tools that refresh the desktop's caches are
replaced so none of them runs.
"""

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


def test_desktop_install_from_the_cli_takes_the_given_command(home, capsys):
    tmp, _ = home

    assert cli.main(["desktop", "install", "--executable", "/usr/local/bin/golblick"]) == 0

    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    assert 'Exec="/usr/local/bin/golblick" open %f' in entry
    assert "/usr/local/bin/golblick open" in capsys.readouterr().out


def test_open_refuses_a_missing_file(home, capsys):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")

    assert cli.main(["open", "/nonexistent/IMG_1.insp"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_the_shader_lens_numbers_land_where_render_projects():
    """scene hands the GPU each lens as a matrix and a few numbers; the formula
    the shader applies to them must give render._project's answer.  A lopsided
    lens, tilted and spun, so a transposed matrix or a missed flip shows."""
    numpy = pytest.importorskip("numpy")
    from golblick import render, scene

    lenses = (render.Lens(radius=1400.0, centre_x=1510.0, centre_y=1530.0, spin=0.0, tilt=(0.01, -0.02)),
              render.Lens(radius=1390.0, centre_x=4570.0, centre_y=1515.0, spin=0.03, tilt=(-0.015, 0.005)))
    theta_max = numpy.deg2rad(97.0)
    rays = numpy.random.default_rng(1).normal(size=(500, 3))
    rays /= numpy.linalg.norm(rays, axis=1, keepdims=True)
    for index, lens in enumerate(lenses):
        u, v, theta = render._project(rays, lens, index, theta_max)
        shader = scene._shader_lens(lens, index, render)
        local = rays @ numpy.asarray(shader.matrix).T
        their_theta = numpy.arccos(numpy.clip(local[:, 2], -1, 1))
        phi = numpy.arctan2(local[:, 1], local[:, 0]) - shader.spin
        r = shader.radius * their_theta / theta_max
        assert numpy.allclose(their_theta, theta, atol=1e-9)
        assert numpy.allclose(shader.centre_x + r * numpy.cos(phi), u, atol=1e-6)
        assert numpy.allclose(shader.centre_y - r * numpy.sin(phi), v, atol=1e-6)


def test_an_opening_view_is_kept_by_name_and_size_and_can_be_forgotten(home, tmp_path):
    pytest.importorskip("PySide6")
    from golblick import viewer

    photo = tmp_path / "IMG_20260314_090825_00_008.insp"
    photo.write_bytes(b"x" * 10)
    assert viewer.load_view(photo) is None

    viewer.save_view(photo, {"longitude": 91.234, "latitude": -5.0, "fov": 60.0})
    moved = tmp_path / "elsewhere" / photo.name
    moved.parent.mkdir()
    moved.write_bytes(b"x" * 10)
    assert viewer.load_view(moved) == {"longitude": 91.23, "latitude": -5.0, "fov": 60.0}

    viewer.save_view(photo, None)
    assert viewer.load_view(photo) is None
