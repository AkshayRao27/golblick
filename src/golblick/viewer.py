"""golblick's 360 viewer window: look around in a photo or a playing clip, projected on the GPU as it's drawn.

Needs the ``desktop`` extra (PySide6).  Nothing is rendered to a file first.
The window takes the camera's lens pair as it is stored, and a fragment shader
works out, for each pixel on screen, where in which lens that direction was
recorded (:mod:`golblick.scene` supplies the numbers, in
:mod:`golblick.render`'s conventions).  So the photo is on screen as soon as
the file is read and decoded, and what takes the CPU longer -- the routed
seam, an X5's lens guards and its own stitch to level against -- runs in the
background and updates the view when it's done.

A clip plays the same way, from the lens pair :mod:`golblick.playback`
decodes, each frame turned by its own steadying, and timed by its sound
where there is an audio output to play it on.

The shader covers the whole window, so there is no sphere mesh to draw inside
out or mirror.  Directions are golblick's: longitude from the middle of the
panorama, rising to the right, latitude up from the horizon.
"""

from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QSize, Qt, QTimer, Signal
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

from . import fling as flings
from . import playback
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
#extension GL_OES_standard_derivatives : enable
precision highp float;
#endif
uniform sampler2D lens0;                    // RGB, or a video frame's luma
uniform sampler2D lens1;
uniform int nv12;                           // 1: a video frame, chroma in chroma0/1
uniform sampler2D chroma0;
uniform sampler2D chroma1;
uniform vec3 yuvLow;                        // subtracted from (Y, Cb, Cr): the range's black and grey
uniform vec3 yuvGain;                       // then scaled to full range
uniform vec3 yuvR, yuvG, yuvB;              // the colour matrix, by rows
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
uniform float coarse;                       // 0, or the blurred lenses' wider cross-fade
uniform float coarseLevel;                  // the mip level that blurs them, lens texture pixels
uniform float radial[64];
uniform int radialCount;
uniform float seam[256];
uniform int routed;
uniform int aimed;                          // 1: a video's seam aims the lenses at a parallax
uniform float parallax[256];                // degrees per column round the lens axis
uniform vec3 baseline;                      // lens 0 to lens 1, camera frame
uniform int shutterCount;                   // 0: no rolling shutter to undo
uniform vec4 shutter[5];                    // the frame's turns across its readout, (x, y, z, w)
varying vec2 ndc;
const float PI = 3.14159265358979;
const float DEPTH_INNER = 4.0;                // render._DEPTH_INNER
const float DEPTH_OUTER = 12.0;               // render._DEPTH_OUTER

float corrected(float theta) {
    if (radialCount < 2) return theta;
    float f = degrees(theta) / 2.0;
    float i = clamp(floor(f), 0.0, float(radialCount - 2));
    float t = clamp(f - i, 0.0, 1.0);
    int k = int(i);
    return theta + radians(mix(radial[k], radial[k + 1], t));
}

vec3 colourAt(sampler2D luma, sampler2D chroma, vec2 at) {
    if (nv12 == 0) return texture2D(luma, at).rgb;
    vec3 yuv = (vec3(texture2D(luma, at).r, texture2D(chroma, at).rg) - yuvLow) * yuvGain;
    return clamp(vec3(dot(yuvR, yuv), dot(yuvG, yuv), dot(yuvB, yuv)), 0.0, 1.0);
}

vec3 blurredAt(sampler2D luma, sampler2D chroma, vec2 at, float bias) {
    if (nv12 == 0) return texture2D(luma, at, bias).rgb;
    vec3 yuv = (vec3(texture2D(luma, at, bias).r, texture2D(chroma, at, bias).rg) - yuvLow) * yuvGain;
    return clamp(vec3(dot(yuvR, yuv), dot(yuvG, yuv), dot(yuvB, yuv)), 0.0, 1.0);
}

// The level the GPU would pick here, so a bias can land on coarseLevel at any zoom.
float level(vec2 at) {
    vec2 x = dFdx(at * cell), y = dFdy(at * cell);
    return max(0.0, 0.5 * log2(max(dot(x, x), dot(y, y))));
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

vec3 turn(vec4 q, vec3 v) { return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }

// render._aimed: lens 0 looks half the parallax along the baseline (side
// +0.5), lens 1 half against it (-0.5), tapered off away from the seam
// (render._depth_taper, DEPTH_INNER to DEPTH_OUTER degrees of d).
vec3 aim(vec3 ray, float side) {
    if (aimed == 0) return ray;
    float dz = 2.0 * acos(clamp(ray.z, -1.0, 1.0)) - PI;
    float position = mod((atan(ray.y, ray.x) + PI) / (2.0 * PI) * 256.0, 256.0);
    float low = floor(position);
    int lo = int(low);
    int hi = lo == 255 ? 0 : lo + 1;
    float taper = clamp((radians(DEPTH_OUTER) - abs(dz)) / radians(DEPTH_OUTER - DEPTH_INNER), 0.0, 1.0);
    float p = radians(mix(parallax[lo], parallax[hi], position - low)) * taper;
    return normalize(ray + side * p * baseline);
}

// render._project_read: the ray turned by the camera's turn to the moment
// its row was read, between the two nearest, projected again; twice.
vec3 projectRead(vec3 ray, vec3 r0, vec3 r1, vec3 r2, vec2 centre, float radius, float spin, float left) {
    vec3 p = project(ray, r0, r1, r2, centre, radius, spin, left);
    if (shutterCount < 2) return p;
    float steps = float(shutterCount - 1);
    for (int n = 0; n < 2; n++) {
        float at = clamp(p.y - 0.5 / cell.y, 0.0, 1.0) * steps;
        float low = min(floor(at), steps - 1.0);
        int j = int(low);
        vec3 mixed = mix(turn(shutter[j], ray), turn(shutter[j + 1], ray), at - low);
        p = project(normalize(mixed), r0, r1, r2, centre, radius, spin, left);
    }
    return p;
}

void main() {
    vec3 d = normalize(vec3(ndc * halfTan, 1.0));
    d = vec3(d.x, d.y * cos(pitch) + d.z * sin(pitch), -d.y * sin(pitch) + d.z * cos(pitch));
    d = vec3(d.x * cos(yaw) + d.z * sin(yaw), d.y, -d.x * sin(yaw) + d.z * cos(yaw));
    vec3 ray = vec3(dot(world0, d), dot(world1, d), dot(world2, d));

    vec3 a = projectRead(aim(ray, 0.5), m00, m01, m02, centres.xy, radii.x, 0.0, 0.0);
    vec3 b = projectRead(aim(ray, -0.5), m10, m11, m12, centres.zw, radii.y, spin1, cell.x);
    float va = a.z <= thetaMax ? 1.0 : 0.0;
    float vb = b.z <= thetaMax ? 1.0 : 0.0;
    float ta = va > 0.0 ? a.z : thetaMax + feather;
    float tb = vb > 0.0 ? b.z : thetaMax + feather;

    float levelA = level(a.xy), levelB = level(b.xy);   // outside any branch: derivatives need every pixel
    float wa, wb;
    float across = ta - tb;                     // how far past the hand-over, as d = theta0 - theta1
    if (routed == 1) {
        float dz = 2.0 * acos(clamp(ray.z, -1.0, 1.0)) - PI;
        float position = mod((atan(ray.y, ray.x) + PI) / (2.0 * PI) * 256.0, 256.0);
        float low = floor(position);
        int lo = int(low);
        int hi = lo == 255 ? 0 : lo + 1;
        float offset = mix(seam[lo], seam[hi], position - low);
        across = dz - offset;
        float share = clamp((feather - across) / (2.0 * feather), 0.0, 1.0);
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
    if (wa > 0.0) colour += colourAt(lens0, chroma0, a.xy) * wa;
    if (wb > 0.0) colour += colourAt(lens1, chroma1, b.xy) * wb;
    float total = wa + wb;
    colour = total > 0.0 ? colour / total : vec3(0.0);
    // Two bands: what both lenses show blurred hands over across the wide
    // band, so a difference in brightness has room to fade, while detail
    // keeps the narrow one, so a near subject is cut rather than doubled.
    if (coarse > 0.0 && va * vb > 0.0 && total > 0.0) {
        float fine = wb / total;
        float wide = 1.0 - clamp((coarse - across) / (2.0 * coarse), 0.0, 1.0);
        vec3 lowA = blurredAt(lens0, chroma0, a.xy, coarseLevel - levelA);
        vec3 lowB = blurredAt(lens1, chroma1, b.xy, coarseLevel - levelB);
        float rim = clamp((thetaMax - max(ta, tb)) / feather, 0.0, 1.0);
        colour = clamp(colour + (fine - wide) * (lowA - lowB) * rim, 0.0, 1.0);
    }
    gl_FragColor = vec4(colour, 1.0);
}
"""


class SphereView(QOpenGLWidget):
    """A photo's lens pair as a sphere: drag or swipe to look, scroll or pinch to zoom.

    A drag let go while still moving coasts on and slows to a stop
    (:mod:`golblick.fling`); pressing again stops it.
    """

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
        self._samples: list[tuple[float, float, float]] = []
        self._fling: flings.Fling | None = None
        self._fling_clock = QElapsedTimer()
        self._fling_done = (0.0, 0.0)
        self._fling_timer = QTimer(self)
        self._fling_timer.setInterval(16)
        self._fling_timer.timeout.connect(self._coast)
        self.setMinimumSize(320, 200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grabGesture(Qt.GestureType.PinchGesture)
        # Pinches through a filter, not an event() override: Qt paints inside
        # event(), and an override holds the GIL through the wait for the
        # screen, starving the decoder's thread while a drag repaints.
        self.installEventFilter(self)

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
        if scene is None or program is None or len(self._textures) not in (2, 4):
            return
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        gl.glViewport(0, 0, width, height)
        program.bind()
        for unit, texture in enumerate(self._textures):
            texture.bind(unit)
        uniform = program.uniformLocation
        program.setUniformValue1i(uniform("lens0"), 0)
        program.setUniformValue1i(uniform("lens1"), 1)
        program.setUniformValue1i(uniform("nv12"), 1 if len(self._textures) == 4 else 0)
        program.setUniformValue1i(uniform("chroma0"), 2 if len(self._textures) == 4 else 0)
        program.setUniformValue1i(uniform("chroma1"), 3 if len(self._textures) == 4 else 1)
        if len(self._textures) == 4:
            low, gain, rows = self._colour
            program.setUniformValue(uniform("yuvLow"), *low)
            program.setUniformValue(uniform("yuvGain"), *gain)
            for name, row in zip(("yuvR", "yuvG", "yuvB"), rows, strict=True):
                program.setUniformValue(uniform(name), *row)
        half = math.tan(math.radians(self.fov) / 2)
        program.setUniformValue(uniform("halfTan"), half * width / height, half)
        program.setUniformValue1f(uniform("yaw"), math.radians(self.longitude))
        program.setUniformValue1f(uniform("pitch"), math.radians(self.latitude))
        for k, row in enumerate(self._world()):
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
        program.setUniformValue1f(uniform("coarse"), scene.coarse)
        # A blur about half the wide band across, in the lens texture's pixels.
        program.setUniformValue1f(uniform("coarseLevel"), math.log2(max(
            1.0, scene.coarse / 2 * scene.lenses[0].radius / scene.theta_max)))
        radial = list(scene.radial[:64])
        for k, value in enumerate(radial):
            program.setUniformValue1f(uniform(f"radial[{k}]"), value)
        program.setUniformValue1i(uniform("radialCount"), len(radial))
        if scene.seam is not None:
            for k, value in enumerate(scene.seam):
                program.setUniformValue1f(uniform(f"seam[{k}]"), value)
        program.setUniformValue1i(uniform("routed"), 1 if scene.seam is not None else 0)
        if scene.parallax is not None:
            for k, value in enumerate(scene.parallax):
                program.setUniformValue1f(uniform(f"parallax[{k}]"), value)
            program.setUniformValue(uniform("baseline"), *scene.baseline)
        program.setUniformValue1i(uniform("aimed"), 1 if scene.parallax is not None else 0)
        turns = self._shutter() or ()
        for k, (w, x, y, z) in enumerate(turns):
            program.setUniformValue(uniform(f"shutter[{k}]"), x, y, z, w)
        program.setUniformValue1i(uniform("shutterCount"), len(turns))
        self._vao.bind()
        gl.glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._vao.release()

    def _world(self):
        """Rows of the rotation from the viewer's world to the camera frame, for what's drawn now."""
        return self._scene.camera_from_world

    def _shutter(self):
        """The turns across the readout of what's drawn now, or None: a photo has none."""
        return None

    def closeEvent(self, event) -> None:
        self._release()
        super().closeEvent(event)

    # -- Looking around --------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        if watched is self and event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                if pinch.state() == Qt.GestureState.GestureStarted:
                    self._pinch_fov = self.fov
                if self._pinch_fov is not None and pinch.totalScaleFactor() > 0:
                    self.look(self.longitude, self.latitude, self._pinch_fov / pinch.totalScaleFactor())
                if pinch.state() in (Qt.GestureState.GestureFinished, Qt.GestureState.GestureCanceled):
                    self._pinch_fov = None
                return True
        if (watched is self and event.type() == QEvent.Type.NativeGesture
                and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture):
            # A touchpad's pinch: Qt sends it as steps of scale, not as a QPinchGesture.
            self.turn(zoom=1.0 / (1.0 + event.value()))
            return True
        return super().eventFilter(watched, event)

    def _sample(self, event) -> None:
        position = event.position()
        self._samples.append((event.timestamp() / 1000.0, position.x(), position.y()))
        del self._samples[:-32]

    def _drag(self, dx: float, dy: float) -> None:
        # The scene follows the pointer, at the speed it appears to move.
        per_pixel = self.fov / max(1, self.height())
        self.turn(-dx * per_pixel, dy * per_pixel)

    def stop_fling(self) -> None:
        self._fling_timer.stop()
        self._fling = None

    def _coast(self) -> None:
        if self._fling is None:
            self._fling_timer.stop()
            return
        t = self._fling_clock.elapsed() / 1000.0
        x, y = self._fling.offset(t)
        self._drag(x - self._fling_done[0], y - self._fling_done[1])
        self._fling_done = (x, y)
        if self._fling.done(t):
            self.stop_fling()

    def mousePressEvent(self, event) -> None:
        self.stop_fling()
        self._last = event.position()
        self._samples = []
        self._sample(event)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._last is None or self._pinch_fov is not None:
            return
        delta = event.position() - self._last
        self._last = event.position()
        self._sample(event)
        self._drag(delta.x(), delta.y())

    def mouseReleaseEvent(self, event) -> None:
        if self._last is not None and self._pinch_fov is None:
            self._sample(event)
            vx, vy = flings.release_velocity(self._samples)
            fling = flings.Fling(vx, vy, self.logicalDpiX())
            if fling.duration > 0:
                self._fling, self._fling_done = fling, (0.0, 0.0)
                self._fling_clock.start()
                self._fling_timer.start()
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


#: How each range maps code values to full range: (black, grey, grey), then the gain.
_RANGES = {
    "pc": ((0.0, 128 / 255, 128 / 255), (1.0, 1.0, 1.0)),
    "tv": ((16 / 255, 128 / 255, 128 / 255), (255 / 219, 255 / 224, 255 / 224)),
}
#: (Y, Cb, Cr) to RGB, by rows, per colour matrix as ffprobe names it.
_MATRICES = {
    "bt709": ((1.0, 0.0, 1.5748), (1.0, -0.18733, -0.46813), (1.0, 1.8556, 0.0)),
    "smpte170m": ((1.0, 0.0, 1.402), (1.0, -0.344136, -0.714136), (1.0, 1.772, 0.0)),
}
_MATRICES["bt470bg"] = _MATRICES["smpte170m"]


class _Speaker:
    """A clip's sound through the desktop's audio output, from one frame on.

    Qt's count of what it has played moves in steps of about 20 ms and
    starts late, so the player keeps its own smooth clock and only
    corrects it to this one (:meth:`VideoView._now`).
    """

    def __init__(self, clip, start: int, volume: float):
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        wanted = QAudioFormat()
        wanted.setSampleRate(playback.SAMPLE_RATE)
        wanted.setChannelCount(playback.CHANNELS)
        wanted.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull() or not device.isFormatSupported(wanted):
            raise OSError("no audio output for 16-bit stereo at 48 kHz")
        self._sink = QAudioSink(device, wanted)
        self._sink.setVolume(volume)
        self._sound = playback.Sound(clip, start)
        self._from = start / float(clip.rate)
        self._out = None
        self._since = QElapsedTimer()

    @property
    def begun(self) -> bool:
        return self._out is not None

    @property
    def starting(self) -> bool:
        """Begun, and the output hasn't started moving yet; an output that hasn't in a second won't."""
        return (self._out is not None and self._sink.processedUSecs() == 0 and not self._sound.finished
                and self._since.elapsed() < 1000)

    def begin(self) -> None:
        self._out = self._sink.start()
        self._since.start()
        self.feed()

    def feed(self) -> None:
        if self._out is not None:
            free = self._sink.bytesFree()
            if free:
                self._out.write(self._sound.read(free))

    def heard(self) -> float | None:
        """Seconds into the clip the sound has reached; None before it starts moving and once it has run out."""
        played = self._sink.processedUSecs()
        if self._out is None or played == 0:
            return None
        if self._sound.finished and self._sink.bytesFree() == self._sink.bufferSize():
            return None
        return self._from + played / 1e6

    def pause(self) -> None:
        if self._out is not None:
            self._sink.suspend()

    def resume(self) -> None:
        if self._out is not None:
            self._sink.resume()

    def set_volume(self, volume: float) -> None:
        self._sink.setVolume(volume)

    def close(self) -> None:
        self._sink.stop()
        self._sound.close()


class VideoView(SphereView):
    """A clip's lens pair as a playing sphere, each frame turned by its own steadying."""

    position = Signal(int)       # the frame on screen
    ended = Signal(str)          # at the end of the clip; the decoder's error, if it failed
    seeking = Signal(int)        # a seek was asked for, to this frame
    sound_changed = Signal()     # muted or the volume changed
    playing_changed = Signal(bool)   # started or stopped, by a request or at the end
    notice = Signal(str)         # something the viewer should be told once, such as decoding on the CPU

    #: How far the picture may drift from the sound before it's put back in step, in seconds.
    DRIFT = 0.05

    #: How far the picture may fall behind the clock, in seconds, before decoding starts again
    #: further on: a decoder slower than the clip skips frames instead of drifting away from the sound.
    BEHIND = 0.5

    def __init__(self, longitude: float = 0.0, latitude: float = 0.0, fov: float = 75.0):
        super().__init__(longitude, latitude, fov)
        self.video: scenes.VideoScene | None = None
        self._decoder: playback.Decoder | None = None
        self._speaker: _Speaker | None = None
        settings = _settings()
        self.muted = False
        self.volume = _number(settings.value("player/volume", 1.0), 1.0)
        # Direction Lock is on unless turned off: a view that follows the
        # camera's turns keeps moving, which can be disorienting.
        self.steady = _flag(settings.value("player/steady", True))
        self.lock = _flag(settings.value("player/lock", True))
        self._target = 0                              # the frame the last seek asked for
        self._pending: int | None = None              # a seek asked for while another was starting
        self._frame: playback.Frame | None = None   # waiting to be uploaded
        self._shown = 0                               # index of the frame on screen
        self._held: playback.Frame | None = None      # a catch-up's first frame, early for the clock
        self._method: str | None = None               # how to decode once the card has failed on this clip
        self._startup = 0.5                           # how long decoding last took to start, seconds
        self._restarted = 0.0                         # when it last started, by time.monotonic()
        self._timing = False                          # its first frame hasn't come yet
        self._skipping_said = False
        self._keyframes: tuple[float, float] | None = None   # playback.keyframe_spacing, once read
        self.playing = False
        self._clock = QElapsedTimer()
        self._running = False                         # the clock is counting
        self._anchor = 0.0                            # seconds into the clip when it started
        self._waiting = False                         # a seek's first frame hasn't arrived yet
        self._tick = QTimer(self)
        self._tick.setInterval(4)
        self._tick.timeout.connect(self._advance)

    def refine(self, video: scenes.VideoScene) -> None:
        """The same clip with what its frames decided (``scene.refine_video``), without stopping it."""
        if self.video is None or video.clip is not self.video.clip:
            return
        self.video = video
        self.show_scene(video.scene)

    def show_video(self, video: scenes.VideoScene) -> None:
        self.video = video
        self._keyframes = None
        threading.Thread(target=self._read_keyframes, args=(video.clip,), daemon=True).start()
        low, gain = _RANGES.get(video.clip.colour_range, _RANGES["pc"])
        self._colour = (low, gain, _MATRICES.get(video.clip.colour_space, _MATRICES["bt709"]))
        self.show_scene(video.scene)
        self.seek(0)
        self.play()

    @property
    def frames(self) -> int:
        return self.video.clip.frames if self.video else 0

    @property
    def rate(self) -> float:
        return float(self.video.clip.rate) if self.video else 30.0

    def play(self) -> None:
        if self.video is None:
            return
        if self._shown >= self.frames - 1:
            self.seek(0)
        self.playing = True
        self.playing_changed.emit(True)
        if self._speaker is not None:
            if self._speaker.begun:
                self._speaker.resume()
            elif not self._waiting:
                self._speaker.begin()
        self._tick.start()

    def pause(self) -> None:
        self.playing = False
        self._running = False
        self.playing_changed.emit(False)
        if self._speaker is not None:
            self._speaker.pause()

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def mute(self, muted: bool | None = None) -> None:
        """Turn the sound off or on; with no argument, the other way from now."""
        self.muted = not self.muted if muted is None else muted
        if not self.muted and self.volume == 0:
            self.volume = 1.0
        self._apply_volume()

    def set_volume(self, volume: float) -> None:
        """0 to 1; at 0 the sound is muted, as in the Nextcloud player."""
        self.volume = max(0.0, min(1.0, volume))
        self.muted = self.volume == 0
        _settings().setValue("player/volume", self.volume)
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._speaker is not None:
            self._speaker.set_volume(0.0 if self.muted else self.volume)
        self.sound_changed.emit()

    def set_steady(self, on: bool) -> None:
        self.steady = on
        _settings().setValue("player/steady", on)
        self.update()

    def set_lock(self, on: bool) -> None:
        self.lock = on
        _settings().setValue("player/lock", on)
        self.update()

    @property
    def target(self) -> int:
        """Where playback is heading: the frame a seek asked for until it arrives, then the frame on screen."""
        if self._pending is not None:
            return self._pending
        return self._target if self._waiting else max(self._shown, 0)

    def seek(self, frame: int) -> None:
        """Start decoding at ``frame``; it's shown as soon as it arrives, playing or not."""
        if self.video is None:
            return
        frame = max(0, min(self.frames - 1, frame))
        self.seeking.emit(frame)
        if self._waiting and self._decoder is not None:
            # One is starting already: go on from its first frame, so a drag
            # along the bar doesn't start an ffmpeg for every step.
            self._pending = frame
            return
        self._target = frame
        self._stop_decoding()
        self._held = None
        self._restarted = time.monotonic()
        self._timing = True
        self._decoder = playback.Decoder(self.video.clip, self.video.size, frame, self._method)
        if self.video.clip.audio:
            try:
                self._speaker = _Speaker(self.video.clip, frame, 0.0 if self.muted else self.volume)
            except OSError:
                self._speaker = None   # no audio output: the picture keeps its own time
        self._shown = frame - 1
        # Nothing counts until the first frame is here: ffmpeg takes a moment
        # to produce it, and a clock started at the request would rush to catch up.
        self._waiting = True
        self._running = False
        self._tick.start()

    def _now(self) -> float | None:
        """Seconds into the clip by the playback clock; None while it isn't running."""
        if not self.playing or self._waiting:
            return None
        speaker = self._speaker
        heard = speaker.heard() if speaker is not None else None
        if not self._running:
            # With sound, the picture waits for it: the output takes a moment to start.
            if speaker is not None and speaker.starting:
                return None
            self._anchor = heard if heard is not None else max(self._shown, 0) / self.rate
            self._clock.start()
            self._running = True
        now = self._anchor + self._clock.elapsed() / 1000.0
        if heard is not None and abs(now - heard) > self.DRIFT:
            self._anchor, now = heard, heard
            self._clock.start()
        return now

    def _advance(self) -> None:
        decoder = self._decoder
        if decoder is None:
            return
        if self._speaker is not None:
            self._speaker.feed()
        now = self._now()
        if now is not None:
            due = int(now * self.rate)
        else:
            due = self._shown + 1 if self._waiting else self._shown   # a seek's first frame, playing or not
        latest = None
        while self._shown < due:
            if self._held is not None:
                frame, self._held = self._held, None
            else:
                try:
                    frame = decoder.next(timeout=0)
                except queue.Empty:
                    break
                if self._timing:
                    self._startup, self._timing = time.monotonic() - self._restarted, False
            if frame is not None and frame.index > due and not self._waiting:
                self._held = frame   # a catch-up started ahead: wait for the clock
                break
            if frame is None:
                self._tick.stop()
                self.playing = False
                self._running = False
                self.playing_changed.emit(False)
                self.ended.emit(decoder.error or "")
                break
            # Behind the clock, frames are skipped rather than shown late.
            latest, self._shown = frame, frame.index
        if latest is not None:
            if decoder.fell_back and self._method is None:
                self._method = decoder.method
                if decoder.method == "cpu":
                    self.notice.emit("Decoding on the CPU: the graphics card couldn't decode this clip")
            if self._waiting:
                self._waiting = False
                if self._pending is not None:
                    pending, self._pending = self._pending, None
                    self._frame = latest
                    self.update()
                    self.seek(pending)
                    return
                if self.playing and self._speaker is not None:
                    self._speaker.begin()
            self._frame = latest
            self.update()
            self.position.emit(latest.index)
        if not self.playing and self._shown >= due:
            self._tick.stop()
        elif (now is not None and self._held is None and not self._timing
              and due - self._shown > self.BEHIND * self.rate):
            self._catch_up(due)

    def _read_keyframes(self, clip) -> None:
        spacing = playback.keyframe_spacing(clip)
        if self.video is not None and self.video.clip is clip:
            self._keyframes = spacing

    def _catch_up(self, due: int) -> None:
        """Decoding has fallen behind the clock: start it again far enough ahead to be there in time.

        The sound plays on untouched; only the picture skips.  Far enough is
        what the last start took, and a little more; the one before has to
        have started, or every tick would start another.
        """
        target = due + int(round((1.25 * self._startup + 0.2) * self.rate))
        if self._keyframes is not None:
            # On to the next keyframe, at or just after it: started there, decoding needn't go back for one.
            first, spacing = self._keyframes
            at = first + math.ceil(max(0.0, target / self.rate - first) / spacing) * spacing
            target = math.ceil(at * self.rate - 1e-6)
        if target >= self.frames - 1:
            return
        if not self._skipping_said:
            self._skipping_said = True
            self.notice.emit("This clip decodes slower than it plays here, so frames are skipped to keep up with the sound")
        self._stop_decoding()
        self._restarted = time.monotonic()
        self._timing = True
        self._decoder = playback.Decoder(self.video.clip, self.video.size, target, self._method)

    def _stop_decoding(self) -> None:
        if self._decoder is not None:
            self._decoder.close()
            self._decoder = None
        if self._speaker is not None:
            self._speaker.close()
            self._speaker = None

    def _upload(self) -> None:
        frame, self._frame = self._frame, None
        size = frame.size
        if len(self._textures) != 4:
            for texture in self._textures:
                texture.destroy()
            self._textures = []
            for side, kind in ((size, "luma"), (size, "luma"), (size // 2, "chroma"), (size // 2, "chroma")):
                texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
                texture.setSize(side, side)
                texture.setFormat(QOpenGLTexture.TextureFormat.R8_UNorm if kind == "luma"
                                  else QOpenGLTexture.TextureFormat.RG8_UNorm)
                # Mipmapped for the seam's blurred band (setData makes the levels).
                texture.setMipLevels(texture.maximumMipLevels())
                texture.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
                texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
                texture.allocateStorage()
                self._textures.append(texture)
        for lens in (0, 1):
            luma, chroma = frame.planes(lens)
            self._textures[lens].setData(QOpenGLTexture.PixelFormat.Red, QOpenGLTexture.PixelType.UInt8,
                                         bytes(luma))
            self._textures[2 + lens].setData(QOpenGLTexture.PixelFormat.RG, QOpenGLTexture.PixelType.UInt8,
                                             bytes(chroma))

    def paintGL(self) -> None:
        if self._frame is not None:
            self.makeCurrent()
            self._upload()
        super().paintGL()

    def _world(self):
        if self.video is None:
            return super()._world()
        return self.video.camera_from_world(max(0, self._shown), self.steady, self.lock)

    def _shutter(self):
        if self.video is None:
            return None
        return self.video.frame_shutter(max(0, self._shown))

    def keyPressEvent(self, event) -> None:
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle()
        elif shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.seek(self.target + round((5 if key == Qt.Key.Key_Right else -5) * self.rate))
        elif key == Qt.Key.Key_Home:
            self.seek(0)
        elif key == Qt.Key.Key_M:
            self.mute()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._tick.stop()
        self._stop_decoding()
        super().closeEvent(event)


# -- Opening views -----------------------------------------------------------------


def _settings():
    """The player's remembered choices, in ``~/.config/golblick/viewer.conf``."""
    from PySide6.QtCore import QSettings

    return QSettings("golblick", "viewer")


def _flag(value) -> bool:
    # QSettings hands back what it read from the file as text.
    return value if isinstance(value, bool) else str(value).lower() in ("true", "1")


def _number(value, fallback: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return fallback


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
    video = Signal(object)
    refined_video = Signal(object)
    failed = Signal(str)


def _icon(name: str, colour: str = "white") -> QIcon:
    """One of :data:`golblick.icons.PATHS` in ``colour``: white for the dark bar."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    from .icons import PATHS

    icon = QIcon()
    # Greyed out the way the Nextcloud app greys a button, at 40%, not in the style's own way.
    for mode, opacity in ((QIcon.Mode.Normal, 1.0), (QIcon.Mode.Disabled, 0.4)):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
               f'<path fill="{colour}" fill-opacity="{opacity}" d="{PATHS[name]}"/></svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        for scale in (1, 2, 3):
            pixmap = QPixmap(24 * scale, 24 * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap, mode)
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
    # Styled as the bar it opens from, not in the desktop's theme: translucent
    # black with round corners, as the Nextcloud app's menu is.
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint
                        | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setStyleSheet(
        "QMenu { background: rgba(0, 0, 0, 150); border-radius: 16px; padding: 6px; color: white; }"
        "QMenu::item { padding: 9px 16px 9px 8px; border-radius: 10px; background: transparent; }"
        "QMenu::item:selected { background: rgba(255, 255, 255, 30); }"
        "QMenu::item:disabled { color: rgba(255, 255, 255, 102); }"
        "QMenu::icon { padding-left: 10px; }")
    here = menu.addAction(_icon("open_here"), "Open facing this way")
    reset = menu.addAction(_icon("open_default"), "Reset point of view")
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


def _video_controls(view: VideoView) -> QWidget:
    """Play and pause, the time, a seek bar, steadying, and the sound, along the bottom edge.

    The same controls, icons, labels and order as the Nextcloud app's player
    (videoControls in nextcloud-app/src/overlay.ts), so the two work alike.
    """
    from PySide6.QtWidgets import QProxyStyle, QSlider, QStyle

    class _Jump(QProxyStyle):
        # A click on a slider's track goes there, as a browser's range input does, not a page along.
        def styleHint(self, hint, option=None, widget=None, returned=None):
            if hint == QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
                return Qt.MouseButton.LeftButton.value
            return super().styleHint(hint, option, widget, returned)

    bar = QWidget(view)
    bar.setObjectName("player")
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    bar.setStyleSheet(
        "#player { background: rgba(0, 0, 0, 140); border-radius: 22px; }"
        "QLabel { color: white; }"
        "QToolButton { color: white; background: transparent; border: 0; border-radius: 18px; }"
        "QToolButton:hover { background: rgba(255, 255, 255, 30); }"
        "QToolButton:checked { background: rgba(255, 255, 255, 64); }"
        "QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: rgba(255, 255, 255, 80); }"
        "QSlider::sub-page:horizontal { border-radius: 2px; background: white; }"
        "QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: white; }")
    row = QHBoxLayout(bar)
    row.setContentsMargins(10, 4, 10, 4)
    row.setSpacing(8)
    jump = _Jump()
    jump.setParent(bar)

    def small(name: str, tip: str) -> QToolButton:
        button = _button(name, tip, bar)
        button.setMinimumSize(36, 36)
        button.setIconSize(QSize(22, 22))
        return button

    def slider() -> QSlider:
        made = QSlider(Qt.Orientation.Horizontal, bar)
        made.setStyle(jump)
        made.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        made.setCursor(Qt.CursorShape.PointingHandCursor)
        return made

    play = small("pause", "Pause")
    time = QLabel(bar)
    seek = slider()
    seek.setRange(0, max(0, view.frames - 1))
    seek.setAccessibleName("Position")
    mute = small("sound_on", "Mute")
    volume = slider()
    volume.setRange(0, 100)
    volume.setFixedWidth(72)
    volume.setAccessibleName("Volume")

    def clock(frame: int) -> str:
        seconds = int(frame / view.rate)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def playing_changed(*_) -> None:
        on = view.playing
        if play.property("on") == on:
            return
        play.setProperty("on", on)
        play.setIcon(_icon("pause" if on else "play"))
        play.setToolTip("Pause" if on else "Play")
        play.setAccessibleName(play.toolTip())

    def moved(frame: int) -> None:
        if not seek.isSliderDown():
            seek.setValue(frame)
        time.setText(f"{clock(frame)} / {clock(view.frames)}")
        playing_changed()

    def sound_changed() -> None:
        mute.setIcon(_icon("sound_off" if view.muted else "sound_on"))
        mute.setToolTip("Unmute" if view.muted else "Mute")
        mute.setAccessibleName(mute.toolTip())
        if not volume.isSliderDown():
            volume.blockSignals(True)
            volume.setValue(0 if view.muted else round(view.volume * 100))
            volume.blockSignals(False)

    play.clicked.connect(lambda: (view.toggle(), playing_changed()))
    view.position.connect(moved)
    view.seeking.connect(moved)
    view.playing_changed.connect(playing_changed)
    seek.sliderPressed.connect(lambda: view.seek(seek.value()))
    seek.sliderMoved.connect(view.seek)
    mute.clicked.connect(lambda: view.mute())
    volume.valueChanged.connect(lambda value: view.set_volume(value / 100))
    view.sound_changed.connect(sound_changed)
    # The time takes its widest text, so the seek bar doesn't shift as it counts.
    time.setText(f"{clock(view.frames)} / {clock(view.frames)}")
    time.setMinimumWidth(time.sizeHint().width() + 8)
    moved(max(view._shown, 0))
    sound_changed()

    row.addWidget(play)
    row.addWidget(time)
    row.addWidget(seek, 1)
    if view.video is not None and view.video.turns:
        steady = small("steady", "")
        lock = small("lock_direction", "")
        for button in (steady, lock):
            button.setCheckable(True)

        def steadying_changed() -> None:
            steady.setChecked(view.steady)
            steady.setToolTip("Steadied: click for the camera's own movement" if view.steady
                              else "Not steadied: click to steady")
            lock.setChecked(view.lock)
            lock.setToolTip("Direction locked: click to follow the camera's turns" if view.lock
                            else "Following the camera's turns: click to lock the direction")
            # Direction Lock only means something while the video is steadied.
            lock.setEnabled(view.steady)
            for button in (steady, lock):
                button.setAccessibleName(button.toolTip())

        steady.clicked.connect(lambda: (view.set_steady(not view.steady), steadying_changed()))
        lock.clicked.connect(lambda: (view.set_lock(not view.lock), steadying_changed()))
        steadying_changed()
        row.addWidget(steady)
        row.addWidget(lock)
    row.addWidget(mute)
    row.addWidget(volume)
    return bar


class _Follow(QObject):
    """Keeps the control bars along the bottom as the window is resized.

    The navigation bar is centred; a video's bar takes the bottom edge, and
    the navigation bar sits above it, as in the Nextcloud app.
    """

    def __init__(self, view: QWidget, bar: QWidget):
        super().__init__(view)
        self._view, self.bar = view, bar
        self._player: QWidget | None = None
        view.installEventFilter(self)
        self.place()

    def add_player(self, player: QWidget) -> None:
        self._player = player
        player.show()
        self.place()

    def place(self) -> None:
        view, bar, player = self._view, self.bar, self._player
        bottom = 16
        if player is not None:
            player.setGeometry(12, view.height() - player.sizeHint().height() - 12, view.width() - 24,
                               player.sizeHint().height())
            bottom = player.height() + 24
        bar.move((view.width() - bar.width()) // 2, view.height() - bar.height() - bottom)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False


class _AutoHide(QObject):
    """Fades a playing clip's controls and the pointer out when nobody is reaching for them.

    Moving the pointer into the bottom of the picture, where the controls are,
    brings them back.  Moving it anywhere else doesn't: that is usually a hand
    on its way to drag the view around, and it would bring them back before
    every drag.  A click or tap without a drag shows or hides them, which is
    all a touchscreen has.  They stay while the clip is paused, the pointer is
    on them, or their menu or a slider is in use.  The Nextcloud app's player
    does the same (autoHide in nextcloud-app/src/overlay.ts).
    """

    IDLE = 3000      # ms without reaching for them before they fade
    CLICK = 6        # pixels a press may move and still be a click
    REACH = 160      # pixels from the bottom edge, at least, where moving brings them back

    def __init__(self, view: VideoView, bars: list[QWidget]):
        from PySide6.QtCore import QPropertyAnimation
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        super().__init__(view)
        self._view, self._bars = view, bars
        self.shown = True
        self._pressed = None
        self._pointer = None
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(self.IDLE)
        self._idle.timeout.connect(self._expire)
        self._fades = []
        for bar in bars:
            effect = QGraphicsOpacityEffect(bar)
            effect.setOpacity(1.0)
            bar.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", self)
            fade.setDuration(200)
            # Hidden once faded, so it doesn't catch clicks meant for the picture.
            fade.finished.connect(lambda bar=bar, effect=effect: effect.opacity() == 0 and bar.hide())
            self._fades.append(fade)
        view.setMouseTracking(True)
        view.installEventFilter(self)
        view.playing_changed.connect(lambda on: self._idle.start() if on else self.show())
        if view.playing:
            self._idle.start()

    def show(self) -> None:
        if not self.shown:
            self.shown = True
            for bar, fade in zip(self._bars, self._fades, strict=True):
                bar.show()
                self._fade(fade, 1.0)
        self._view.setCursor(Qt.CursorShape.OpenHandCursor)
        self._idle.start()

    def hide(self) -> None:
        if self.shown:
            self.shown = False
            for fade in self._fades:
                self._fade(fade, 0.0)
        # Not mid-drag: the pointer is what's being dragged.
        if QApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self._view.setCursor(Qt.CursorShape.BlankCursor)
        self._idle.stop()

    @staticmethod
    def _fade(fade, to: float) -> None:
        fade.stop()
        fade.setStartValue(fade.targetObject().opacity())
        fade.setEndValue(to)
        fade.start()

    def _busy(self) -> bool:
        from PySide6.QtWidgets import QSlider

        if QApplication.activePopupWidget() is not None:
            return True
        return any(bar.underMouse() or any(s.isSliderDown() for s in bar.findChildren(QSlider))
                   for bar in self._bars)

    def _expire(self) -> None:
        if not self._view.playing:
            return
        if self._busy():
            self._idle.start()
        else:
            self.hide()

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            self._pressed = event.position()
        elif kind == QEvent.Type.MouseButtonRelease and self._pressed is not None:
            moved = (event.position() - self._pressed).manhattanLength()
            self._pressed = None
            if moved <= self.CLICK:
                self.hide() if self.shown else self.show()
            elif self._view.playing:
                self._idle.start()   # the pointer, back after the drag, fades again
        elif kind == QEvent.Type.MouseMove and event.buttons() == Qt.MouseButton.NoButton:
            # Qt also sends moves when what's under a still pointer changes;
            # only the pointer itself moving counts.
            where = event.globalPosition()
            still = self._pointer is not None and (where - self._pointer).manhattanLength() < 2
            self._pointer = where
            if still:
                return False
            if event.position().y() > self._view.height() - max(self.REACH, self._view.height() / 4):
                self.show()
        elif kind == QEvent.Type.Leave:
            self._expire()
        elif kind == QEvent.Type.KeyPress:
            shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            key = event.key()
            # What the time or the sound answers; turning the view doesn't need them.
            if key in (Qt.Key.Key_Space, Qt.Key.Key_Home, Qt.Key.Key_M) or (
                    shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right)):
                self.show()
        return False


def open_window(path: str | Path) -> SphereView:
    """A viewer window for the photo or clip at ``path``; it loads in the background."""
    path = Path(path)
    from .cli import _is_mp4

    is_video = _is_mp4(path)   # by content: an .insv is an MP4
    start = load_view(path) or {}
    kind = VideoView if is_video else SphereView
    view = kind(start.get("longitude", 0.0), start.get("latitude", 0.0), start.get("fov", 75.0))
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

    say("Loading…", None)
    follow = _Follow(view, _controls(view, path, say))
    QShortcut(QKeySequence(QKeySequence.StandardKey.Close), view, view.close)
    QShortcut(QKeySequence("Ctrl+Q"), view, view.close)

    loaded = _Loaded(view)
    loaded.scene.connect(lambda scene, halves: (view.show_scene(scene, halves),
                                                say("Drag to look around · scroll or pinch to zoom")))
    loaded.refined.connect(view.show_scene)
    what = "clip" if is_video else "photo"
    loaded.failed.connect(lambda message: say(f"Couldn't show this {what}: {message}", None))
    if is_video:
        def playable(video: scenes.VideoScene) -> None:
            view.show_video(video)
            player = _video_controls(view)
            follow.add_player(player)
            _AutoHide(view, [follow.bar, player])
            say("Space plays and pauses · Shift+arrows skip 5 s · M mutes · drag to look around")

        loaded.video.connect(playable)
        loaded.refined_video.connect(view.refine)
        view.ended.connect(lambda error: say(f"Couldn't play this clip: {error}", None) if error else None)
        view.notice.connect(lambda text: say(text, 6.0))

    def work() -> None:
        if is_video:
            try:
                quick = scenes.video_scene(path)
                loaded.video.emit(quick)
            except Exception as exc:  # shown in the window; there may be no terminal
                loaded.failed.emit(str(exc))
                return
            try:
                loaded.refined_video.emit(scenes.refine_video(path, quick))
            except Exception:  # noqa: BLE001 - the clip plays on with the bisector seam
                pass
            return
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


#: Qt refuses to decode an image that would take more than this, in MB. Its
#: default, 256, is just short of a high-resolution X5 or X3 frame (11904 x
#: 5952 and 11968 x 5984, about 270 MB decoded), which it then reported as
#: undecodable.
IMAGE_LIMIT_MB = 1024


def run(path: str | Path) -> int:
    """Open the window and run until it is closed."""
    from PySide6.QtGui import QImageReader

    QImageReader.setAllocationLimit(IMAGE_LIMIT_MB)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("golblick")
    app.setDesktopFileName("golblick-open")
    window = open_window(path)  # noqa: F841 - kept alive until exec returns
    return app.exec()
