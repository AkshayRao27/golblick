#!/usr/bin/env bash
# Builds golblick-<version>-x86_64.AppImage and its .zsync from this tree, into build/appimage/out/.
#
#   packaging/appimage/build.sh
#
# Python comes from python-build-standalone (through uv), and golblick[desktop]
# is installed into it at the versions pinned in uv.lock. ffmpeg stays a system
# dependency, as with a pip install. GOLBLICK_APPIMAGE_UPDATE replaces the
# embedded update information, for test builds served from somewhere else.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$REPO/build/appimage
APPDIR=$WORK/AppDir
OUTDIR=$WORK/out
PYVER=3.12
# appimagetool 1.9.1, checked against the digest GitHub lists for the asset.
TOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
TOOL_SHA=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('$REPO/pyproject.toml', 'rb'))['project']['version'])")
NAME=golblick-$VERSION-x86_64.AppImage
# Gear Lever and AppImageUpdate look for the newest release with a matching
# .zsync. "latest-pre" includes prereleases, which every golblick release is so far.
UPDATE=${GOLBLICK_APPIMAGE_UPDATE:-"gh-releases-zsync|AkshayRao27|golblick|latest-pre|golblick-*-x86_64.AppImage.zsync"}

rm -rf "$APPDIR" "$WORK/python" "$WORK/dist" "$OUTDIR"
mkdir -p "$WORK/dl" "$OUTDIR"

# 1. A relocatable CPython.
UV_PYTHON_INSTALL_DIR=$WORK/python uv python install "$PYVER" --no-bin >/dev/null
# uv adds a cpython-3.12-… symlink beside the real directory; copy the target.
SRC=$(readlink -f "$(ls -d "$WORK"/python/cpython-"$PYVER"*-linux-x86_64-gnu | head -1)")
mkdir -p "$APPDIR/usr"
cp -a "$SRC" "$APPDIR/usr/python"
rm -f "$APPDIR"/usr/python/lib/python"$PYVER"/EXTERNALLY-MANAGED
PY=$APPDIR/usr/python/bin/python$PYVER

# 2. golblick[desktop] from this tree, its dependencies at the locked versions.
(cd "$REPO" && uv build --wheel --out-dir "$WORK/dist" >/dev/null \
  && uv export --frozen --no-dev --no-emit-project --extra desktop --python "$PYVER" -o "$WORK/dist/requirements.txt" >/dev/null)
"$PY" -m pip install --no-cache-dir --disable-pip-version-check -q --require-hashes --no-deps -r "$WORK/dist/requirements.txt"
"$PY" -m pip install --no-cache-dir --disable-pip-version-check -q --no-deps "$WORK"/dist/golblick-*.whl

# 3. Drop the Qt modules the viewer never loads: 263 MB installed becomes about 100 MB.
"$PY" - "$APPDIR" <<'EOF'
import pathlib, shutil, subprocess, sys
site = next(pathlib.Path(sys.argv[1], "usr/python/lib").glob("python3*/site-packages"))
qt = site / "PySide6"
keep = {"Core", "Gui", "Widgets", "Svg", "OpenGL", "OpenGLWidgets", "Multimedia",
        "Network", "DBus", "XcbQpa", "WaylandClient", "WaylandEglClientHwIntegration",
        "EglFSDeviceIntegration", "EglFsKmsSupport", "Concurrent",
        # Qt Multimedia's FFmpeg plugin, the viewer's audio output, links these;
        # without them a video plays silently.
        "Qml", "Quick", "QmlMeta", "QmlModels", "QmlWorkerScript"}
gone = 0
for p in list((qt / "Qt" / "lib").glob("libQt6*.so*")):
    mod = p.name[len("libQt6"):].split(".so")[0]
    if mod not in keep and not mod.startswith("FFmpegStub"):
        gone += p.stat().st_size; p.unlink()
for p in list(qt.glob("Qt*.abi3.so")) + list(qt.glob("Qt*.pyi")):
    if p.name.split(".")[0][2:] not in keep:
        gone += p.stat().st_size; p.unlink()
for d in ["Qt/libexec", "Qt/translations", "Qt/qml", "Qt/resources", "Qt/metatypes",
          "Qt/plugins/sqldrivers", "Qt/plugins/designer", "Qt/plugins/qmltooling",
          "Qt/plugins/sceneparsers", "Qt/plugins/geometryloaders", "Qt/plugins/renderers",
          "Qt/plugins/webview", "Qt/plugins/position", "Qt/plugins/sensors",
          "Qt/plugins/canbus", "Qt/plugins/texttospeech", "Qt/plugins/assetimporters",
          "include", "typesystems", "glue", "scripts", "examples", "doc"]:
    t = qt / d
    if t.exists():
        gone += sum(f.stat().st_size for f in t.rglob("*") if f.is_file()); shutil.rmtree(t)
for d in ["Designer", "assistant", "designer", "linguist", "lrelease", "lupdate", "qmlls", "qmlformat"]:
    for f in qt.glob(d + "*"):
        if f.is_file():
            gone += f.stat().st_size; f.unlink()
# A plugin that links a Qt library removed above can never load.
present = {p.name for p in (qt / "Qt" / "lib").glob("libQt6*.so*")}
for so in list((qt / "Qt" / "plugins").rglob("*.so")):
    deps = subprocess.run(["ldd", str(so)], capture_output=True, text=True).stdout
    need = {line.split()[0] for line in deps.splitlines() if line.strip().startswith("libQt6")}
    if any(n not in present for n in need):
        gone += so.stat().st_size; so.unlink()
print(f"pruned {gone / 1e6:.0f} MB")
EOF
find "$APPDIR/usr/python" -name __pycache__ -prune -exec rm -rf {} +

# 4. AppRun, desktop entry, icon.
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/python/bin/python3" -I -c 'import sys; from golblick.cli import main; sys.argv[0] = "golblick"; sys.exit(main())' "$@"
EOF
chmod +x "$APPDIR/AppRun"
cp "$REPO/src/golblick/golblick.svg" "$APPDIR/golblick.svg"
# The SVG's viewBox is 64 px, and integrators that rasterise .DirIcon at its
# own size (Gear Lever) showed a blurry icon. A 512 px PNG doesn't.
QT_QPA_PLATFORM=offscreen "$PY" -I - "$APPDIR" <<'EOF'
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication([])
img = QImage(512, 512, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
QSvgRenderer(sys.argv[1] + "/golblick.svg").render(p)
p.end()
assert img.save(sys.argv[1] + "/golblick.png")
EOF
ln -sf golblick.png "$APPDIR/.DirIcon"
cat > "$APPDIR/golblick.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=golblick
Comment=View Insta360 360 photos and videos
Exec=golblick open %f
Icon=golblick
Categories=Graphics;Viewer;
MimeType=image/x-insta360-insp;video/x-insta360-insv;
Terminal=false
EOF

# 5. Pack. appimagetool writes the .zsync beside the AppImage.
TOOL=$WORK/dl/appimagetool
if ! echo "$TOOL_SHA  $TOOL" | sha256sum -c --quiet >/dev/null 2>&1; then
  curl -fsSL -o "$TOOL.part" "$TOOL_URL"
  echo "$TOOL_SHA  $TOOL.part" | sha256sum -c --quiet
  mv "$TOOL.part" "$TOOL"
  chmod +x "$TOOL"
fi
(cd "$OUTDIR" && ARCH=x86_64 "$TOOL" --appimage-extract-and-run -n -u "$UPDATE" "$APPDIR" "$NAME") >"$WORK/appimagetool.log" 2>&1 \
  || { tail -20 "$WORK/appimagetool.log"; exit 1; }
ls -l "$OUTDIR"
