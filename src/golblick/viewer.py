"""golblick's 360 viewer window: look around in a panorama.

Needs the ``desktop`` extra (PySide6).  The window opens at once and the
panorama arrives when it has been rendered, which the first time takes a few
seconds; the render runs on a worker thread and its result, or its error, is
handed back to the window.

The sphere is drawn by a fragment shader over the whole window: each pixel's
ray, turned by the view's pitch and then its yaw, is looked up in the
equirectangular panorama.  There is no sphere mesh, so there is nothing to
draw inside out or mirror, and no seam where a mesh would close.  Directions
are golblick's: longitude from the middle column of the panorama, rising to
the right, latitude up from the horizon.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QShortcut, QSurfaceFormat
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QLabel

# GLSL that both desktop OpenGL 2.1 and OpenGL ES 2/3 accept, so the window
# works whichever the platform hands out (Wayland often gives ES).
_VERTEX = """
attribute vec2 corner;
varying vec2 ndc;
void main() { ndc = corner; gl_Position = vec4(corner, 0.0, 1.0); }
"""
_FRAGMENT = """
#ifdef GL_ES
precision highp float;
#endif
uniform sampler2D pano;
uniform vec2 halfTan;
uniform float yaw;
uniform float pitch;
varying vec2 ndc;
const float PI = 3.14159265358979;
void main() {
    vec3 d = normalize(vec3(ndc * halfTan, 1.0));
    d = vec3(d.x, d.y * cos(pitch) + d.z * sin(pitch), -d.y * sin(pitch) + d.z * cos(pitch));
    d = vec3(d.x * cos(yaw) + d.z * sin(yaw), d.y, -d.x * sin(yaw) + d.z * cos(yaw));
    float u = (atan(d.x, d.z) + PI) / (2.0 * PI);
    float v = (PI / 2.0 - asin(clamp(d.y, -1.0, 1.0))) / PI;
    gl_FragColor = texture2D(pano, vec2(u, v));
}
"""


class SphereWidget(QOpenGLWidget):
    """The panorama as a sphere: drag to look, scroll to zoom."""

    MIN_FOV, MAX_FOV = 25.0, 110.0

    def __init__(self, longitude: float = 0.0, latitude: float = 0.0, fov: float = 75.0):
        super().__init__()
        self.longitude, self.latitude, self.fov = longitude, latitude, fov
        self._image: QImage | None = None
        self._texture: QOpenGLTexture | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._last = None
        self.setMinimumSize(320, 200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_panorama(self, image: QImage) -> None:
        self._image = image
        self.update()

    def look(self, longitude: float, latitude: float, fov: float | None = None) -> None:
        self.longitude = longitude
        self.latitude = max(-89.0, min(89.0, latitude))
        if fov is not None:
            self.fov = max(self.MIN_FOV, min(self.MAX_FOV, fov))
        self.update()

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
        if self._texture is not None:
            self._texture.destroy()
            self._texture = None
        self.doneCurrent()

    def paintGL(self) -> None:
        gl = self.context().functions()
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(0x4000)  # GL_COLOR_BUFFER_BIT
        if self._image is not None and self._texture is None:
            # Rows go up as they are, so texture v = 0 is the panorama's top.
            texture = QOpenGLTexture(self._image.convertToFormat(QImage.Format.Format_RGB888),
                                     QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
            texture.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            # Round the back the panorama wraps; top and bottom don't.
            direction, wrap = QOpenGLTexture.CoordinateDirection, QOpenGLTexture.WrapMode
            texture.setWrapMode(direction.DirectionS, wrap.Repeat)
            texture.setWrapMode(direction.DirectionT, wrap.ClampToEdge)
            self._texture = texture
        if self._texture is None or self._program is None:
            return
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        gl.glViewport(0, 0, width, height)
        program = self._program
        program.bind()
        self._texture.bind(0)
        half = math.tan(math.radians(self.fov) / 2)
        program.setUniformValue1i(program.uniformLocation("pano"), 0)
        program.setUniformValue(program.uniformLocation("halfTan"), half * width / height, half)
        program.setUniformValue1f(program.uniformLocation("yaw"), math.radians(self.longitude))
        program.setUniformValue1f(program.uniformLocation("pitch"), math.radians(self.latitude))
        self._vao.bind()
        gl.glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._vao.release()

    def closeEvent(self, event) -> None:
        self._release()
        super().closeEvent(event)

    # -- Looking around --------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        self._last = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._last is None:
            return
        # The scene follows the pointer, at the speed it appears to move.
        per_pixel = self.fov / max(1, self.height())
        delta = event.position() - self._last
        self._last = event.position()
        self.look(self.longitude - delta.x() * per_pixel, self.latitude + delta.y() * per_pixel)

    def mouseReleaseEvent(self, event) -> None:
        self._last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        window = self.window()
        window.showNormal() if window.isFullScreen() else window.showFullScreen()

    def wheelEvent(self, event) -> None:
        self.look(self.longitude, self.latitude, self.fov * math.exp(-event.angleDelta().y() / 1200))

    def keyPressEvent(self, event) -> None:
        step = self.fov / 10
        key = event.key()
        moves = {
            Qt.Key.Key_Left: (-step, 0, 1.0), Qt.Key.Key_Right: (step, 0, 1.0),
            Qt.Key.Key_Up: (0, step, 1.0), Qt.Key.Key_Down: (0, -step, 1.0),
            Qt.Key.Key_Plus: (0, 0, 1 / 1.15), Qt.Key.Key_Equal: (0, 0, 1 / 1.15),
            Qt.Key.Key_Minus: (0, 0, 1.15),
        }
        if key in moves:
            dx, dy, zoom = moves[key]
            self.look(self.longitude + dx, self.latitude + dy, self.fov * zoom)
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.mouseDoubleClickEvent(event)
        elif key == Qt.Key.Key_Escape:
            window = self.window()
            window.showNormal() if window.isFullScreen() else window.close()
        else:
            super().keyPressEvent(event)


class _Rendered(QObject):
    """Carries the worker's result back to the window's thread."""

    done = Signal(str)
    failed = Signal(str)


def open_window(title: str, render: Callable[[], Path], longitude: float = 0.0) -> SphereWidget:
    """A viewer window titled ``title``.

    ``render`` runs on a worker thread and returns the panorama's path.
    """
    view = SphereWidget(longitude)
    view.setWindowTitle(f"{title} — golblick")
    view.resize(1280, 720)
    status = QLabel("Rendering the panorama…", view)
    status.setStyleSheet(
        "color: white; background: rgba(0, 0, 0, 140); padding: 6px 12px; border-radius: 12px;")
    status.adjustSize()
    status.move(16, 16)
    QShortcut(QKeySequence(QKeySequence.StandardKey.Close), view, view.close)
    QShortcut(QKeySequence("Ctrl+Q"), view, view.close)

    signals = _Rendered(view)

    def loaded(path: str) -> None:
        image = QImage(path)
        if image.isNull():
            failed(f"couldn't read {path}")
            return
        view.set_panorama(image)
        status.setText("Drag to look around · scroll to zoom · double-click for full screen")
        status.adjustSize()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(4000, status.hide)

    def failed(message: str) -> None:
        status.setText(f"Couldn't show this photo: {message}")
        status.setWordWrap(True)
        status.setMaximumWidth(view.width() - 32)
        status.adjustSize()

    signals.done.connect(loaded)
    signals.failed.connect(failed)

    def work() -> None:
        try:
            signals.done.emit(str(render()))
        except Exception as exc:  # shown in the window; there may be no terminal
            signals.failed.emit(str(exc))

    threading.Thread(target=work, daemon=True).start()
    view.show()
    return view


def run(title: str, render: Callable[[], Path], longitude: float = 0.0) -> int:
    """Open the window and run until it is closed."""
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setDepthBufferSize(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("golblick")
    app.setDesktopFileName("golblick-open")
    window = open_window(title, render, longitude)  # noqa: F841 - kept alive until exec returns
    return app.exec()
