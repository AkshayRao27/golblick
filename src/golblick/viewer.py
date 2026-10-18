"""golblick's 360 viewer window: look around in a photo, projected on the GPU as it's drawn.

Needs the ``desktop`` extra (PySide6).  Nothing is rendered to a file first.
The window takes the camera's lens pair as it is stored, and a fragment shader
works out, for each pixel on screen, where in which lens that direction was
recorded (:mod:`golblick.scene` supplies the numbers, in
:mod:`golblick.render`'s conventions).  So the photo is on screen as soon as
the file is read and decoded, and what takes the CPU longer -- the routed
seam, an X5's lens guards and its own stitch to level against -- runs in the
background and updates the view when it's done.

The shader covers the whole window, so there is no sphere mesh to draw inside
out or mirror.  Directions are golblick's: longitude from the middle of the
panorama, rising to the right, latitude up from the horizon.
"""

from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QShortcut
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QWidget

from . import scene as scenes

# GLSL that desktop OpenGL 2.1 and OpenGL ES 2/3 both accept, since Wayland
# often hands out ES.
_VERTEX = """
attribute vec2 corner;
varying vec2 ndc;
void main() { ndc = corner; gl_Position = vec4(corner, 0.0, 1.0); }
"""

# render._project, render._sample's bilinear (the GPU's own, with mipmaps for
# when the view is zoomed out), and render.equirectangular's blend: each lens
# weighted by how far it is from the hand-over, routed or on the bisector,
# and tapered at its rim.
_FRAGMENT = """
#ifdef GL_ES
precision highp float;
#endif
uniform sampler2D lens0;
uniform sampler2D lens1;
uniform vec2 halfTan;
uniform float yaw;
uniform float pitch;
uniform vec3 world0, world1, world2;        // camera from world, by rows
uniform vec3 m00, m01, m02, m10, m11, m12;  // each lens from camera, by rows
uniform vec4 centres;                       // lens 0 x, y; lens 1 x, y (full-frame pixels)
uniform vec2 radii;
uniform float spin1;
uniform vec2 cell;                          // size of each lens's texture, pixels
uniform float thetaMax;
uniform float feather;
uniform float radial[64];
uniform int radialCount;
uniform float seam[256];
uniform int routed;
varying vec2 ndc;
const float PI = 3.14159265358979;

float corrected(float theta) {
    if (radialCount < 2) return theta;
    float f = degrees(theta) / 2.0;
    float i = clamp(floor(f), 0.0, float(radialCount - 2));
    float t = clamp(f - i, 0.0, 1.0);
    int k = int(i);
    return theta + radians(mix(radial[k], radial[k + 1], t));
}

// Where a camera-frame ray lands in one lens: texture coordinates, and the
// (corrected) angle off its axis.
vec3 project(vec3 ray, vec3 r0, vec3 r1, vec3 r2, vec2 centre, float radius, float spin, float left) {
    vec3 l = vec3(dot(r0, ray), dot(r1, ray), dot(r2, ray));
    float theta = corrected(acos(clamp(l.z, -1.0, 1.0)));
    float phi = atan(l.y, l.x) - spin;
    float r = radius * theta / thetaMax;
    vec2 at = vec2(centre.x + r * cos(phi) - left, centre.y - r * sin(phi));
    return vec3((at + 0.5) / cell, theta);
}

void main() {
    vec3 d = normalize(vec3(ndc * halfTan, 1.0));
    d = vec3(d.x, d.y * cos(pitch) + d.z * sin(pitch), -d.y * sin(pitch) + d.z * cos(pitch));
    d = vec3(d.x * cos(yaw) + d.z * sin(yaw), d.y, -d.x * sin(yaw) + d.z * cos(yaw));
    vec3 ray = vec3(dot(world0, d), dot(world1, d), dot(world2, d));

    vec3 a = project(ray, m00, m01, m02, centres.xy, radii.x, 0.0, 0.0);
    vec3 b = project(ray, m10, m11, m12, centres.zw, radii.y, spin1, cell.x);
    float va = a.z <= thetaMax ? 1.0 : 0.0;
    float vb = b.z <= thetaMax ? 1.0 : 0.0;
    float ta = va > 0.0 ? a.z : thetaMax + feather;
    float tb = vb > 0.0 ? b.z : thetaMax + feather;

    float wa, wb;
    if (routed == 1) {
        float dz = 2.0 * acos(clamp(ray.z, -1.0, 1.0)) - PI;
        float position = mod((atan(ray.y, ray.x) + PI) / (2.0 * PI) * 256.0, 256.0);
        float low = floor(position);
        int lo = int(low);
        int hi = lo == 255 ? 0 : lo + 1;
        float offset = mix(seam[lo], seam[hi], position - low);
        float share = clamp((feather - (dz - offset)) / (2.0 * feather), 0.0, 1.0);
        wa = share;
        wb = 1.0 - share;
    } else {
        float closest = min(ta, tb);
        wa = clamp((closest + feather - ta) / feather, 0.0, 1.0);
        wb = clamp((closest + feather - tb) / feather, 0.0, 1.0);
    }
    wa *= clamp((thetaMax - ta) / feather, 0.0, 1.0) * va;
    wb *= clamp((thetaMax - tb) / feather, 0.0, 1.0) * vb;
    vec3 colour = vec3(0.0);
    if (wa > 0.0) colour += texture2D(lens0, a.xy).rgb * wa;
    if (wb > 0.0) colour += texture2D(lens1, b.xy).rgb * wb;
    float total = wa + wb;
    gl_FragColor = vec4(total > 0.0 ? colour / total : vec3(0.0), 1.0);
}
"""


class SphereView(QOpenGLWidget):
    """A photo's lens pair as a sphere: drag or swipe to look, scroll or pinch to zoom."""

    MIN_FOV, MAX_FOV = 25.0, 110.0
    changed = Signal()

    def __init__(self, longitude: float = 0.0, latitude: float = 0.0, fov: float = 75.0):
        super().__init__()
        self.longitude, self.latitude, self.fov = longitude, latitude, fov
        self._scene: scenes.Scene | None = None
        self._halves: tuple[QImage, QImage] | None = None
        self._textures: list[QOpenGLTexture] = []
        self._program: QOpenGLShaderProgram | None = None
        self._last = None
        self._pinch_fov = None
        self.setMinimumSize(320, 200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grabGesture(Qt.GestureType.PinchGesture)

    def show_scene(self, scene: scenes.Scene, halves: tuple[QImage, QImage] | None = None) -> None:
        """Show ``scene``; ``halves``, the lens pair split in two, only when the picture is new."""
        self._scene = scene
        if halves is not None:
            self._halves = halves
        self.update()

    def look(self, longitude: float, latitude: float, fov: float | None = None) -> None:
        self.longitude = (longitude + 180.0) % 360.0 - 180.0
        self.latitude = max(-89.0, min(89.0, latitude))
        if fov is not None:
            self.fov = max(self.MIN_FOV, min(self.MAX_FOV, fov))
        self.update()
        self.changed.emit()

    def turn(self, longitude: float = 0.0, latitude: float = 0.0, zoom: float = 1.0) -> None:
        self.look(self.longitude + longitude, self.latitude + latitude, self.fov * zoom)

    def toggle_full_screen(self) -> None:
        window = self.window()
        window.showNormal() if window.isFullScreen() else window.showFullScreen()

    # -- OpenGL --------------------------------------------------------------

    def initializeGL(self) -> None:
        program = QOpenGLShaderProgram(self)
        if not (program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX)
                and program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT)):
            raise RuntimeError(f"the viewer's shader didn't compile: {program.log()}")
        program.bindAttributeLocation("corner", 0)
        if not program.link():
            raise RuntimeError(f"the viewer's shader didn't link: {program.log()}")
        self._program = program
        # GL objects have to go while their context is still current.
        self.context().aboutToBeDestroyed.connect(self._release)
        # A core profile draws nothing without a vertex array bound.
        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vao.bind()
        self._corners = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._corners.create()
        self._corners.bind()
        import struct

        self._corners.allocate(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1), 32)
        program.bind()
        program.enableAttributeArray(0)
        program.setAttributeBuffer(0, 0x1406, 0, 2)  # GL_FLOAT
        self._vao.release()

    def _release(self) -> None:
        self.makeCurrent()
        for texture in self._textures:
            texture.destroy()
        self._textures = []
        self.doneCurrent()

    def _upload(self) -> None:
        for texture in self._textures:
            texture.destroy()
        self._textures = []
        for half in self._halves:
            texture = QOpenGLTexture(half, QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
            # Mipmapped, because zoomed out a screen pixel covers many of the
            # camera's, and plain bilinear would shimmer.
            texture.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
            texture.setMaximumAnisotropy(16.0)
            texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
            self._textures.append(texture)
        self._halves = None  # on the GPU now; the copies in memory can go

    def paintGL(self) -> None:
        gl = self.context().functions()
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(0x4000)  # GL_COLOR_BUFFER_BIT
        if self._halves is not None:
            self._upload()
        scene, program = self._scene, self._program
        if scene is None or program is None or len(self._textures) != 2:
            return
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        gl.glViewport(0, 0, width, height)
        program.bind()
        self._textures[0].bind(0)
        self._textures[1].bind(1)
        uniform = program.uniformLocation
        program.setUniformValue1i(uniform("lens0"), 0)
        program.setUniformValue1i(uniform("lens1"), 1)
        half = math.tan(math.radians(self.fov) / 2)
        program.setUniformValue(uniform("halfTan"), half * width / height, half)
        program.setUniformValue1f(uniform("yaw"), math.radians(self.longitude))
        program.setUniformValue1f(uniform("pitch"), math.radians(self.latitude))
        for k, row in enumerate(scene.camera_from_world):
            program.setUniformValue(uniform(f"world{k}"), *row)
        for i, lens in enumerate(scene.lenses):
            for k, row in enumerate(lens.matrix):
                program.setUniformValue(uniform(f"m{i}{k}"), *row)
        first, second = scene.lenses
        program.setUniformValue(uniform("centres"),
                                first.centre_x, first.centre_y, second.centre_x, second.centre_y)
        program.setUniformValue(uniform("radii"), first.radius, second.radius)
        program.setUniformValue1f(uniform("spin1"), second.spin)
        program.setUniformValue(uniform("cell"), scene.width / 2, scene.height)
        program.setUniformValue1f(uniform("thetaMax"), scene.theta_max)
        program.setUniformValue1f(uniform("feather"), scene.feather)
        radial = list(scene.radial[:64])
        for k, value in enumerate(radial):
            program.setUniformValue1f(uniform(f"radial[{k}]"), value)
        program.setUniformValue1i(uniform("radialCount"), len(radial))
        if scene.seam is not None:
            for k, value in enumerate(scene.seam):
                program.setUniformValue1f(uniform(f"seam[{k}]"), value)
        program.setUniformValue1i(uniform("routed"), 1 if scene.seam is not None else 0)
        self._vao.bind()
        gl.glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._vao.release()

    def closeEvent(self, event) -> None:
        self._release()
        super().closeEvent(event)

    # -- Looking around --------------------------------------------------------

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                if pinch.state() == Qt.GestureState.GestureStarted:
                    self._pinch_fov = self.fov
                if self._pinch_fov is not None and pinch.totalScaleFactor() > 0:
                    self.look(self.longitude, self.latitude, self._pinch_fov / pinch.totalScaleFactor())
                if pinch.state() in (Qt.GestureState.GestureFinished, Qt.GestureState.GestureCanceled):
                    self._pinch_fov = None
                return True
        return super().event(event)

    def mousePressEvent(self, event) -> None:
        self._last = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._last is None or self._pinch_fov is not None:
            return
        # The scene follows the pointer, at the speed it appears to move.
        per_pixel = self.fov / max(1, self.height())
        delta = event.position() - self._last
        self._last = event.position()
        self.turn(-delta.x() * per_pixel, delta.y() * per_pixel)

    def mouseReleaseEvent(self, event) -> None:
        self._last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_full_screen()

    def wheelEvent(self, event) -> None:
        self.turn(zoom=math.exp(-event.angleDelta().y() / 1200))

    def keyPressEvent(self, event) -> None:
        step = self.fov / 10
        moves = {
            Qt.Key.Key_Left: (-step, 0, 1.0), Qt.Key.Key_Right: (step, 0, 1.0),
            Qt.Key.Key_Up: (0, step, 1.0), Qt.Key.Key_Down: (0, -step, 1.0),
            Qt.Key.Key_Plus: (0, 0, 1 / 1.15), Qt.Key.Key_Equal: (0, 0, 1 / 1.15),
            Qt.Key.Key_Minus: (0, 0, 1.15),
        }
        key = event.key()
        if key in moves:
            self.turn(*moves[key])
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_full_screen()
        elif key == Qt.Key.Key_Escape:
            self.window().showNormal() if self.window().isFullScreen() else self.window().close()
        else:
            super().keyPressEvent(event)


# -- Opening views -----------------------------------------------------------------


def views_path() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data / "golblick" / "views.json"


def view_key(path: str | Path) -> str:
    """A photo's key: its name and size, so the view follows it when it's moved or synced elsewhere."""
    path = Path(path)
    return f"{path.name}:{path.stat().st_size}"


def load_view(path: str | Path) -> dict | None:
    try:
        views = json.loads(views_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    view = views.get(view_key(path))
    return view if isinstance(view, dict) else None


def save_view(path: str | Path, view: dict | None) -> None:
    """Make ``view`` (longitude, latitude, fov) where ``path`` opens, or forget it with None."""
    target = views_path()
    try:
        views = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        views = {}
    if view is None:
        views.pop(view_key(path), None)
    else:
        views[view_key(path)] = {k: round(float(view[k]), 2) for k in ("longitude", "latitude", "fov")}
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(views, indent=1, sort_keys=True), encoding="utf-8")
    partial.replace(target)


# -- The window ----------------------------------------------------------------------


class _Loaded(QObject):
    """Carries the worker's results back to the window's thread."""

    scene = Signal(object, object)
    refined = Signal(object)
    failed = Signal(str)


def _icon(name: str, colour: str = "white") -> QIcon:
    """One of :data:`golblick.icons.PATHS` in ``colour``: white for the dark bar."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    from .icons import PATHS

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           f'<path fill="{colour}" d="{PATHS[name]}"/></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for scale in (1, 2, 3):
        pixmap = QPixmap(24 * scale, 24 * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def _button(name: str, tip: str, parent: QWidget) -> QToolButton:
    button = QToolButton(parent)
    button.setIcon(_icon(name))
    button.setIconSize(QSize(24, 24))
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    # Big enough for a finger, and clearly something to press.
    button.setMinimumSize(44, 44)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _controls(view: SphereView, path: Path, say) -> QWidget:
    """A bar of buttons along the bottom, for a touchscreen or anyone without a wheel.

    The same buttons, icons and order as the Nextcloud app's viewer
    (nextcloud-app/src/overlay.ts), so the two work alike.
    """
    from PySide6.QtWidgets import QMenu

    bar = QWidget(view)
    bar.setObjectName("controls")
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    bar.setStyleSheet(
        "#controls { background: rgba(0, 0, 0, 150); border-radius: 22px; }"
        "QToolButton { color: white; background: transparent; border: 0; border-radius: 20px; }"
        "QToolButton:hover { background: rgba(255, 255, 255, 30); }"
        "QToolButton:pressed { background: rgba(255, 255, 255, 60); }"
        "QToolButton::menu-indicator { image: none; }")
    row = QHBoxLayout(bar)
    row.setContentsMargins(8, 2, 8, 2)
    row.setSpacing(2)

    def held(button: QToolButton, action) -> QToolButton:
        # Held down, it keeps going, like a key.
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(250)
        button.setAutoRepeatInterval(40)
        button.clicked.connect(action)
        return button

    def step() -> float:
        return view.fov / 30

    buttons = [
        held(_button("turn_left", "Turn left", bar), lambda: view.turn(-step())),
        held(_button("look_up", "Look up", bar), lambda: view.turn(0, step())),
        held(_button("look_down", "Look down", bar), lambda: view.turn(0, -step())),
        held(_button("turn_right", "Turn right", bar), lambda: view.turn(step())),
        held(_button("zoom_out", "Zoom out", bar), lambda: view.turn(zoom=1.03)),
        held(_button("zoom_in", "Zoom in", bar), lambda: view.turn(zoom=1 / 1.03)),
    ]
    full = _button("full_screen", "Full screen", bar)
    full.clicked.connect(view.toggle_full_screen)

    def windowed_or_not() -> None:
        on = view.window().isFullScreen()
        full.setIcon(_icon("leave_full_screen" if on else "full_screen"))
        full.setToolTip("Leave full screen" if on else "Full screen")

    class _States(QObject):
        def eventFilter(self, watched, event) -> bool:
            if event.type() == QEvent.Type.WindowStateChange:
                windowed_or_not()
            return False

    view.installEventFilter(_States(bar))

    more = _button("more", "More", bar)
    menu = QMenu(more)
    # The menu follows the desktop's theme, so its icons take the theme's text colour.
    ink = QApplication.palette().windowText().color().name()
    here = menu.addAction(_icon("open_here", ink), "Open at this view next time")
    reset = menu.addAction(_icon("open_default", ink), "Open the default way")
    reset.setEnabled(load_view(path) is not None)

    def show_menu() -> None:
        # Upwards: the bar sits along the bottom of the window.
        from PySide6.QtCore import QPoint

        size = menu.sizeHint()
        menu.exec(more.mapToGlobal(QPoint(more.width() - size.width(), -size.height() - 4)))

    more.clicked.connect(show_menu)

    def keep() -> None:
        save_view(path, {"longitude": view.longitude, "latitude": view.latitude, "fov": view.fov})
        reset.setEnabled(True)
        say("It opens at this view now.")

    def forget() -> None:
        save_view(path, None)
        reset.setEnabled(False)
        view.look(0.0, 0.0, 75.0)
        say("It opens the default way again.")

    here.triggered.connect(keep)
    reset.triggered.connect(forget)
    for button in [*buttons, full, more]:
        row.addWidget(button)
    bar.adjustSize()
    return bar


class _Follow(QObject):
    """Keeps the control bar centred along the bottom as the window is resized."""

    def __init__(self, view: QWidget, bar: QWidget):
        super().__init__(view)
        self._view, self._bar = view, bar
        view.installEventFilter(self)
        self.place()

    def place(self) -> None:
        view, bar = self._view, self._bar
        bar.move((view.width() - bar.width()) // 2, view.height() - bar.height() - 16)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False


def open_window(path: str | Path) -> SphereView:
    """A viewer window for the photo at ``path``; it loads in the background."""
    path = Path(path)
    start = load_view(path) or {}
    view = SphereView(start.get("longitude", 0.0), start.get("latitude", 0.0), start.get("fov", 75.0))
    view.setWindowTitle(f"{path.name} — golblick")
    view.resize(1280, 720)

    status = QLabel(view)
    status.setStyleSheet(
        "color: white; background: rgba(0, 0, 0, 150); padding: 6px 12px; border-radius: 12px;")
    status.setWordWrap(True)
    status.move(16, 16)

    def say(text: str, seconds: float | None = 3.0) -> None:
        status.setText(text)
        status.setMaximumWidth(max(200, view.width() - 32))
        status.adjustSize()
        status.show()
        if seconds:
            QTimer.singleShot(int(seconds * 1000), lambda: status.text() == text and status.hide())

    say("Opening…", None)
    _Follow(view, _controls(view, path, say))
    QShortcut(QKeySequence(QKeySequence.StandardKey.Close), view, view.close)
    QShortcut(QKeySequence("Ctrl+Q"), view, view.close)

    loaded = _Loaded(view)
    loaded.scene.connect(lambda scene, halves: (view.show_scene(scene, halves),
                                                say("Drag to look around · scroll or pinch to zoom")))
    loaded.refined.connect(view.show_scene)
    loaded.failed.connect(lambda message: say(f"Couldn't show this photo: {message}", None))

    def work() -> None:
        try:
            quick = scenes.photo_scene(path)
            image = QImage.fromData(quick.jpeg)
            if image.isNull():
                raise ValueError("the photo couldn't be decoded")
            image = image.convertToFormat(QImage.Format.Format_RGB888)
            half = image.width() // 2
            halves = (image.copy(0, 0, half, image.height()), image.copy(half, 0, half, image.height()))
            del image
            loaded.scene.emit(quick, halves)
            loaded.refined.emit(scenes.refine(path, quick))
        except Exception as exc:  # shown in the window; there may be no terminal
            loaded.failed.emit(str(exc))

    threading.Thread(target=work, daemon=True).start()
    view.show()
    return view


def run(path: str | Path) -> int:
    """Open the window and run until it is closed."""
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("golblick")
    app.setDesktopFileName("golblick-open")
    window = open_window(path)  # noqa: F841 - kept alive until exec returns
    return app.exec()
