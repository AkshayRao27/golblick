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


#: The application icon: the Nextcloud app's glyph (Material Design Icons
#: "panorama-sphere-outline", Apache-2.0, https://pictogrammers.com) in white on
#: a blue tile, since a desktop shows application icons in colour.
ICON_NAME = "golblick"
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a9be0"/><stop offset="1" stop-color="#0068a8"/></linearGradient></defs>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#g)"/>
  <path transform="translate(10,10) scale(1.8333)" fill="#fff" d="M22 8.1C21.7 8 21.3 7.8 21 7.7C19.4 4.3 16 2 12 2S4.6 4.3 3 7.7C2.7 7.8 2.3 8 2.1 8.1C1.4 8.5 1 9.2 1 9.9V14.1C1 14.8 1.4 15.5 2 15.9C2.3 16 2.7 16.2 3 16.3C4.6 19.7 8 22 12 22S19.4 19.7 21 16.3C21.3 16.2 21.6 16 21.9 15.8C22.5 15.4 23 14.8 23 14V9.9C23 9.2 22.6 8.5 22 8.1M21 9.9V14.1C18.8 15.3 15.5 16 12 16S5.2 15.3 3 14.1V9.9C5.2 8.7 8.5 8 12 8S18.8 8.7 21 9.9M12 4C14.4 4 16.5 5 18 6.7C16.2 6.2 14.1 6 12 6S7.8 6.2 6.1 6.7C7.5 5 9.6 4 12 4M12 20C9.6 20 7.5 19 6.1 17.3C7.8 17.8 9.9 18 12 18S16.2 17.8 18 17.3C16.5 19 14.4 20 12 20Z"/>
</svg>
"""


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


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
    icon.write_text(ICON_SVG, encoding="utf-8")
    done.append(f"wrote {icon}")

    done += _refresh(home)
    if _run(["xdg-mime", "default", DESKTOP_FILE, *MIME_TYPES]):
        done.append(f"made it the default for {', '.join(MIME_TYPES)}")
    return done


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
