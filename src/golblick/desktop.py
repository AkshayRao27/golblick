"""Opening 360 photos and videos from a Linux desktop: the file association.

``golblick open`` shows a photo or plays a clip in golblick's own viewer
window (:mod:`golblick.viewer`, the ``desktop`` extra).

``golblick desktop install`` registers ``.insp`` and ``.insv`` as types of
their own, subtypes of JPEG and MP4 so every image viewer and video player
still opens them, and makes ``golblick open`` their default application, so
a double-click in the file manager shows the sphere.  It also installs the
application icon.  Everything goes in the
user's own data directory and is undone by ``golblick desktop uninstall``.

Standard library only: the rendering itself is :mod:`golblick.render`'s.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

#: The types ``.insp`` and ``.insv`` get on the desktop.  Subtypes of JPEG and
#: MP4: an Insta360 file is one of those with a trailer after it, and every
#: viewer or player that offers to open the plain kind should still offer to
#: open this one.
PHOTO_TYPE = "image/x-insta360-insp"
VIDEO_TYPE = "video/x-insta360-insv"
MIME_TYPES = (PHOTO_TYPE, VIDEO_TYPE)
DESKTOP_FILE = "golblick-open.desktop"
MIME_PACKAGE = "golblick.xml"

#: Matched by name only.  shared-mime-info's magic can only look at fixed
#: offsets from the start of a file, and what makes a file Insta360's is the
#: trailer at its end; the start is an ordinary JPEG or MP4.  So the extension
#: decides here, and ``golblick open`` checks the content and refuses a file
#: that isn't one.  ``.lrv`` proxies stay plain MP4s.
MIME_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="{PHOTO_TYPE}">
    <comment>Insta360 360° photo</comment>
    <sub-class-of type="image/jpeg"/>
    <glob pattern="*.insp" weight="60"/>
  </mime-type>
  <mime-type type="{VIDEO_TYPE}">
    <comment>Insta360 360° video</comment>
    <sub-class-of type="video/mp4"/>
    <glob pattern="*.insv" weight="60"/>
  </mime-type>
</mime-info>
"""


#: The application icon, ``golblick.svg`` beside this module: the Nextcloud
#: app's glyph (Material Design Icons "panorama-sphere-outline", Apache-2.0,
#: https://pictogrammers.com) in white on a blue tile, since a desktop shows
#: application icons in colour.
ICON_NAME = "golblick"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def appimage() -> str | None:
    """The AppImage file this golblick runs from, or None outside one.

    That file is what the desktop has to start: the directory golblick runs
    in is a mount that goes away when it exits.  The AppImage runtime says
    where both are in ``$APPIMAGE`` and ``$APPDIR``, but every process it
    starts inherits them, so they are believed only when this interpreter is
    inside ``$APPDIR``.  Otherwise a golblick installed with pip, run from a
    terminal that some other AppImage opened, would register that one.
    """
    image, appdir = os.environ.get("APPIMAGE"), os.environ.get("APPDIR")
    if not image or not appdir or not Path(image).is_file():
        return None
    try:
        Path(sys.executable).resolve().relative_to(Path(appdir).resolve())
    except ValueError:
        return None
    return image


def this_command() -> str | None:
    """The golblick command running now, the one whose environment has the extras.

    The AppImage file when it is one, since the directory it runs in goes away.
    """
    image = appimage()
    if image:
        return image
    here = Path(sys.argv[0]).resolve()
    return str(here) if here.name == "golblick" else shutil.which("golblick")


def install(executable: str, home: Path | None = None) -> list[str]:
    """Register ``.insp`` and ``.insv`` and make ``executable open`` their default application.

    Returns what was done, a line each, for the CLI to print.  Refreshing the
    desktop's caches is best effort: each tool is optional, and a desktop
    without one picks the files up at the next login.
    """
    home = home or data_home()
    done = []
    mime = home / "mime" / "packages" / MIME_PACKAGE
    mime.parent.mkdir(parents=True, exist_ok=True)
    mime.write_text(MIME_XML, encoding="utf-8")
    done.append(f"wrote {mime}")

    entry = home / "applications" / DESKTOP_FILE
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(_desktop_entry(executable), encoding="utf-8")
    done.append(f"wrote {entry}")

    icon = _icon_path(home)
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes((resources.files(__package__) / f"{ICON_NAME}.svg").read_bytes())
    done.append(f"wrote {icon}")

    done += _refresh(home)
    if _run(["xdg-mime", "default", DESKTOP_FILE, *MIME_TYPES]):
        done.append(f"made it the default for {', '.join(MIME_TYPES)}")
    return done


def is_installed(executable: str, home: Path | None = None) -> bool:
    """Whether :func:`install` has already been done for ``executable``, as this version does it.

    Doesn't ask which application is the default: someone who has since
    chosen another one keeps their choice.
    """
    home = home or data_home()
    try:
        return ((home / "applications" / DESKTOP_FILE).read_text(encoding="utf-8") == _desktop_entry(executable)
                and (home / "mime" / "packages" / MIME_PACKAGE).read_text(encoding="utf-8") == MIME_XML
                and _icon_path(home).is_file())
    except OSError:
        return False


def uninstall(home: Path | None = None) -> list[str]:
    """Undo :func:`install`."""
    home = home or data_home()
    done = []
    for path in (home / "mime" / "packages" / MIME_PACKAGE, home / "applications" / DESKTOP_FILE, _icon_path(home)):
        if path.exists():
            path.unlink()
            done.append(f"removed {path}")
    done += _refresh(home)
    return done


def _desktop_entry(executable: str) -> str:
    # The Exec key's own quoting: a path with spaces must be in double quotes.
    command = '"' + executable.replace("\\", "\\\\").replace('"', '\\"') + '" open %f'
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=golblick 360° viewer\n"
        "Comment=Look around in an Insta360 photo or video\n"
        f"Exec={command}\n"
        f"MimeType={';'.join(MIME_TYPES)};\n"
        f"Icon={ICON_NAME}\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "Categories=Graphics;Viewer;\n"
    )


def _icon_path(home: Path) -> Path:
    return home / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"


def _refresh(home: Path) -> list[str]:
    done = []
    if _run(["update-mime-database", str(home / "mime")]):
        done.append("updated the MIME database")
    if _run(["update-desktop-database", str(home / "applications")]):
        done.append("updated the application database")
    # KDE keeps its own cache of both.
    if _run(["kbuildsycoca6"]) or _run(["kbuildsycoca5"]):
        done.append("rebuilt KDE's service cache")
    return done


def _run(command: list[str]) -> bool:
    if shutil.which(command[0]) is None:
        return False
    try:
        return subprocess.run(command, capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
