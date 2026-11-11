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


def test_install_registers_insp_and_insv_as_kinds_of_jpeg_and_mp4_and_opens_them_with_golblick(home):
    tmp, ran = home

    done = desktop.install("/opt/my tools/golblick")

    mime = (tmp / "data/mime/packages/golblick.xml").read_text()
    photo = mime[mime.index('<mime-type type="image/x-insta360-insp">'):]
    photo = photo[:photo.index("</mime-type>")]
    assert '<sub-class-of type="image/jpeg"/>' in photo and '<glob pattern="*.insp"' in photo
    clip = mime[mime.index('<mime-type type="video/x-insta360-insv">'):]
    clip = clip[:clip.index("</mime-type>")]
    assert '<sub-class-of type="video/mp4"/>' in clip and '<glob pattern="*.insv"' in clip
    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    # A path with a space has to be quoted for the Exec key.
    assert 'Exec="/opt/my tools/golblick" open %f' in entry
    assert "MimeType=image/x-insta360-insp;video/x-insta360-insv;\n" in entry
    # The icon is found by name in the user's own hicolor theme.
    assert "Icon=golblick\n" in entry
    assert (tmp / "data/icons/hicolor/scalable/apps/golblick.svg").read_text().startswith("<svg")
    assert ["xdg-mime", "default", "golblick-open.desktop", "image/x-insta360-insp", "video/x-insta360-insv"] in ran
    assert any("default" in line for line in done)


def test_uninstall_removes_what_install_wrote(home):
    tmp, _ = home
    desktop.install("/usr/bin/golblick")

    desktop.uninstall()

    assert not (tmp / "data/mime/packages/golblick.xml").exists()
    assert not (tmp / "data/applications/golblick-open.desktop").exists()
    assert not (tmp / "data/icons/hicolor/scalable/apps/golblick.svg").exists()


def test_the_mime_types_do_not_claim_plain_jpegs_or_mp4s():
    """Only the .insp and .insv extensions, and no magic that would match every JPEG or MP4."""
    assert "<magic" not in desktop.MIME_XML
    globs = [line.split('"')[1] for line in desktop.MIME_XML.splitlines() if "<glob" in line]
    assert globs == ["*.insp", "*.insv"]


def test_the_second_lens_file_of_a_clip_leads_to_the_first(tmp_path):
    """A OneR or X3 _10_ file has no record of its own; a double-click on it opens the clip."""
    from golblick.vendors import lead_file

    second = tmp_path / "VID_20240516_105342_10_022.insv"
    second.write_bytes(b"x")
    assert lead_file(second) is None   # its partner isn't there
    first = tmp_path / "VID_20240516_105342_00_022.insv"
    first.write_bytes(b"x")
    assert lead_file(second) == first
    assert lead_file(first) is None
    assert lead_file(tmp_path / "IMG_20240516_105342_10_022.insp") is None


def test_desktop_install_from_the_cli_takes_the_given_command(home, capsys):
    tmp, _ = home

    assert cli.main(["desktop", "install", "--executable", "/usr/local/bin/golblick"]) == 0

    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    assert 'Exec="/usr/local/bin/golblick" open %f' in entry
    assert "/usr/local/bin/golblick open" in capsys.readouterr().out


@pytest.fixture
def inside_appimage(tmp_path, monkeypatch):
    """As the AppImage runtime starts golblick: its interpreter inside $APPDIR."""
    image = tmp_path / "Apps" / "golblick.AppImage"
    image.parent.mkdir()
    image.write_bytes(b"x")
    appdir = tmp_path / "mount"
    (appdir / "usr/python/bin").mkdir(parents=True)
    monkeypatch.setenv("APPIMAGE", str(image))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setattr("sys.executable", str(appdir / "usr/python/bin/python3"))
    return image


def test_desktop_install_inside_an_appimage_registers_the_appimage_file(home, inside_appimage):
    tmp, _ = home

    assert cli.main(["desktop", "install"]) == 0

    entry = (tmp / "data/applications/golblick-open.desktop").read_text()
    assert f'Exec="{inside_appimage}" open %f' in entry


def test_an_appimage_path_inherited_by_another_golblick_is_ignored(inside_appimage, monkeypatch):
    assert desktop.appimage() == str(inside_appimage)
    monkeypatch.setattr("sys.executable", "/usr/bin/python3")
    assert desktop.appimage() is None


class _Settings(dict):
    """viewer.conf, in memory."""

    def value(self, key, default=None):
        return self.get(key, default)

    setValue = dict.__setitem__


@pytest.fixture
def viewer_stand_in(monkeypatch):
    """The viewer's question and file picker, recorded instead of shown, and its settings in memory."""
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    pytest.importorskip("PySide6")
    from golblick import viewer

    settings = _Settings()
    monkeypatch.setattr(viewer, "_settings", lambda: settings)
    offered = []

    def offer(command, parent=None):
        offered.append(command)
        desktop.install(command)
        return True

    monkeypatch.setattr(viewer, "offer_double_click", offer)
    monkeypatch.setattr(viewer, "choose_file", lambda: None)
    monkeypatch.setattr(viewer, "run", lambda path: pytest.fail("a cancelled choice opened a window"))
    return offered, settings


def test_an_appimage_started_from_its_menu_entry_offers_double_click_once_then_asks_for_a_file(
        home, inside_appimage, viewer_stand_in):
    """Gear Lever's menu entry runs 'open' with no file, and adds no file types of its own."""
    offered, _ = viewer_stand_in

    assert cli.main(["open"]) == 0
    assert offered == [str(inside_appimage)]

    # Set up now, so the next start just asks for a file.
    assert cli.main(["open"]) == 0
    assert offered == [str(inside_appimage)]


def test_an_appimage_told_not_to_ask_goes_straight_to_the_file(home, inside_appimage, viewer_stand_in):
    offered, settings = viewer_stand_in
    settings["desktop/ask"] = "false"   # as QSettings reads it back from the file

    assert cli.main(["open"]) == 0
    assert offered == []


def test_a_file_opened_with_an_appimage_leaves_double_click_alone(home, inside_appimage, viewer_stand_in,
                                                                  tmp_path, monkeypatch):
    from golblick import viewer

    offered, _ = viewer_stand_in
    photo = tmp_path / "IMG_1.insp"
    photo.write_bytes(b"x")
    monkeypatch.setattr(cli, "detect", lambda path: object())
    monkeypatch.setattr(cli, "_require_vendor", lambda name: None)
    shown = []
    monkeypatch.setattr(viewer, "run", lambda path: shown.append(path) or 0)

    assert cli.main(["open", str(photo)]) == 0

    assert shown == [photo] and offered == []


def test_the_appimage_file_itself_double_clicked_does_what_its_menu_entry_does(home, inside_appimage, monkeypatch):
    asked = []
    monkeypatch.setattr(cli, "_open", lambda args: asked.append((args.command, args.file)) or 0)

    assert cli.main([]) == 0

    assert asked == [("open", None)]


def test_golblick_with_no_arguments_outside_an_appimage_still_asks_for_a_command(home, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    with pytest.raises(SystemExit):
        cli.main([])


def test_open_with_no_file_outside_an_appimage_asks_for_one_and_offers_nothing(home, viewer_stand_in, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    offered, _ = viewer_stand_in

    assert cli.main(["open"]) == 0
    assert offered == []


@pytest.fixture
def qt(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Chosen, so golblick keeps it: a portal file dialog would open on the real desktop.
    monkeypatch.setenv("QT_QPA_PLATFORMTHEME", "")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from golblick import viewer

    settings = _Settings()
    monkeypatch.setattr(viewer, "_settings", lambda: settings)
    return viewer, settings


def _answer(button: str, tick: bool | None = None) -> None:
    """Answer the question golblick is about to ask, once it is on screen."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def click() -> None:
        box = QApplication.activeModalWidget()
        if box is None:
            QTimer.singleShot(10, click)
            return
        if tick is not None:
            box.checkBox().setChecked(tick)
        next(b for b in box.buttons() if b.text() == button).click()

    QTimer.singleShot(0, click)


def test_the_double_click_question_sets_up_only_on_yes_and_remembers_dont_ask(home, qt):
    tmp, _ = home
    viewer, settings = qt
    entry = tmp / "data/applications/golblick-open.desktop"

    _answer("Not now", tick=True)
    assert viewer.offer_double_click("/opt/golblick.AppImage") is False
    assert not entry.exists() and not viewer.asks_about_double_click()

    # Asked again from the More menu, the box shows as ticked; cleared, the question at start comes back.
    _answer("Not now", tick=False)
    assert viewer.offer_double_click("/opt/golblick.AppImage") is False
    assert viewer.asks_about_double_click()

    _answer("Set up")
    assert viewer.offer_double_click("/opt/golblick.AppImage") is True
    assert desktop.is_installed("/opt/golblick.AppImage")


def test_the_desktops_file_dialog_is_used_through_its_portal_only_when_qt_cant_load_the_desktops_theme(
        qt, monkeypatch):
    from PySide6.QtCore import QLibraryInfo

    viewer, _ = qt
    bundled = {}
    viewer.prefer_portal_dialogs(bundled)   # this test run's PySide6 is a wheel, with Qt inside it
    assert bundled == {"QT_QPA_PLATFORMTHEME": "xdgdesktopportal"}

    chosen = {"QT_QPA_PLATFORMTHEME": "gtk3"}
    viewer.prefer_portal_dialogs(chosen)
    assert chosen == {"QT_QPA_PLATFORMTHEME": "gtk3"}

    monkeypatch.setattr(QLibraryInfo, "path", staticmethod(lambda which: "/usr/lib/x86_64-linux-gnu/qt6/plugins"))
    distribution = {}
    viewer.prefer_portal_dialogs(distribution)
    assert distribution == {}


def test_the_file_picker_starts_where_the_last_file_came_from(tmp_path, qt, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    viewer, _ = qt
    shown = []
    trip = tmp_path / "trip"
    trip.mkdir()

    def dialog(parent, title, folder, filters, **options):
        shown.append(folder)
        return str(trip / "IMG_1.insp"), filters

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(dialog))

    assert viewer.choose_file() == trip / "IMG_1.insp"
    assert viewer.choose_file() == trip / "IMG_1.insp"
    assert shown[1] == str(trip) and shown[0] != str(trip)


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


def test_the_viewer_error_names_the_missing_library_rather_than_asking_for_pyside6():
    absent = cli._viewer_unavailable(ModuleNotFoundError("No module named 'PySide6'", name="PySide6"))
    assert "pip install 'golblick[desktop]'" in str(absent)

    no_gl = cli._viewer_unavailable(ImportError("libGL.so.1: cannot open shared object file: No such file or directory"))
    assert "libGL.so.1" in str(no_gl) and "package manager" in str(no_gl)
    assert "golblick[desktop]" not in str(no_gl)

    # PySide6 there but missing one of its modules: not "install PySide6" either.
    partial = cli._viewer_unavailable(
        ModuleNotFoundError("No module named 'PySide6.QtMultimedia'", name="PySide6.QtMultimedia"))
    assert "PySide6.QtMultimedia" in str(partial) and "golblick[desktop]" not in str(partial)


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
