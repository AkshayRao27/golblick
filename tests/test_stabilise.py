"""Stabilising from an inertial record, on a synthesised camera.

The camera is held tilted 20 degrees forward and 7 to the side (lopsided on
purpose), pans slowly through 40 degrees and shakes at 3 Hz by 5 degrees.  The
accelerometer reads gravity alone, except where a test adds a jolt.  Pure
Python: the core has to pass without numpy.
"""

import math
from array import array
from types import SimpleNamespace

import pytest

from golblick import stabilise

RATE = 1000
SECONDS = 8.0
FPS = 30.0


def multiply(a, b):
    return stabilise._multiply(a, b)


def about(axis, degrees):
    half = math.radians(degrees) / 2
    x, y, z = axis
    return (math.cos(half), x * math.sin(half), y * math.sin(half), z * math.sin(half))


def rotate(q, v):
    w, x, y, z = q
    vx, vy, vz = v
    return ((1 - 2 * (y * y + z * z)) * vx + 2 * (x * y - w * z) * vy + 2 * (x * z + w * y) * vz,
            2 * (x * y + w * z) * vx + (1 - 2 * (x * x + z * z)) * vy + 2 * (y * z - w * x) * vz,
            2 * (x * z - w * y) * vx + 2 * (y * z + w * x) * vy + (1 - 2 * (x * x + y * y)) * vz)


def conjugate(q):
    return (q[0], -q[1], -q[2], -q[3])


def matrix(q):
    """Column convention: the rotated basis vectors are the columns."""
    columns = [rotate(q, e) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return [[columns[j][i] for j in range(3)] for i in range(3)]


def pan(t):
    return 40.0 * t / SECONDS


def shake(t):
    return 5.0 * math.sin(2 * math.pi * 3.0 * t)


def attitude(t):
    """Body to world: heading (pan plus shake) after a fixed lopsided tilt."""
    tilt = multiply(about((1, 0, 0), 20.0), about((0, 0, 1), 7.0))
    return multiply(about((0, 1, 0), pan(t) + shake(t)), tilt)


def camera(jolt=None):
    """The record such a camera would write, in the shape a vendor's motion() returns."""
    count = int(SECONDS * RATE)
    times = array("d", (i / RATE for i in range(count)))
    angular, up, gravity = array("d"), array("d"), array("d")
    for i in range(count):
        q = attitude(times[i])
        nxt = attitude(times[i] + 1.0 / RATE)
        # Body-frame rate: the turn from this attitude to the next, in the body.
        d = multiply(conjugate(attitude(times[i] - 1.0 / RATE)), q) if i else multiply(conjugate(q), nxt)
        angle = 2 * math.atan2(math.sqrt(d[1] ** 2 + d[2] ** 2 + d[3] ** 2), d[0])
        norm = math.sqrt(d[1] ** 2 + d[2] ** 2 + d[3] ** 2) or 1.0
        angular.extend(c / norm * angle * RATE for c in d[1:])
        u = rotate(conjugate(q), (0.0, 1.0, 0.0))
        g = 1.0
        if jolt is not None and jolt[0] <= times[i] < jolt[1]:
            g = 1.6                          # carried, not still: left out of up
            u = rotate(about((1, 0, 0), 30.0), u)
        up.extend(u)
        gravity.append(g)
    frames = array("d", (0.2 + k / FPS for k in range(int((SECONDS - 0.4) * FPS))))
    return SimpleNamespace(sample_times=times, angular_velocity=angular, up=up,
                           gravity=gravity, frame_times=frames)


def reference_for(motion):
    """What a renderer levels a video's frames with: the opening's up, shortest turn to +y."""
    return matrix(stabilise._level_quaternion(tuple(motion.up[:3])))


def views(motion):
    """Per frame, body to steadied view: the track composed with the reference."""
    reference = reference_for(motion)
    level = stabilise._quaternion(reference)
    return [multiply(c, level) for c in stabilise.track(motion, reference)]


def test_the_steadied_view_keeps_the_horizon_level():
    motion = camera()
    for k, view in enumerate(views(motion)):
        body_up = rotate(conjugate(attitude(motion.frame_times[k])), (0.0, 1.0, 0.0))
        shown = rotate(view, body_up)
        assert math.degrees(math.acos(min(1.0, shown[1]))) < 0.5


def test_the_shake_goes_and_the_pan_stays():
    motion = camera()
    headings = []
    for k, view in enumerate(views(motion)):
        world_to_view = multiply(view, conjugate(attitude(motion.frame_times[k])))
        headings.append(math.degrees(2 * math.atan2(world_to_view[2], world_to_view[0])))
    headings = stabilise._unwrap([math.radians(h) for h in headings])
    headings = [math.degrees(h) for h in headings]
    # What is left, about the pan's straight line, against a 3.5-degree rms shake.
    n = len(headings)
    mean_t = sum(range(n)) / n
    slope = sum((k - mean_t) * h for k, h in enumerate(headings)) / sum((k - mean_t) ** 2 for k in range(n))
    residual = [h - slope * (k - mean_t) for k, h in enumerate(headings)]
    centre = sum(residual) / n
    rms = math.sqrt(sum((r - centre) ** 2 for r in residual) / n)
    assert rms < 0.5
    # The view turns with the pan, the other way round: 5 degrees a second.
    assert abs(slope * FPS) == pytest.approx(40.0 / SECONDS, rel=0.05)


def test_the_first_frame_faces_where_the_render_does():
    first = stabilise.track(camera(), reference_for(camera()))[0]
    assert math.degrees(2 * math.atan2(abs(first[2]), first[0])) < 0.5


def test_a_jolt_does_not_tip_the_horizon():
    """Readings well away from 1 g are the camera being carried, not gravity."""
    motion = camera(jolt=(3.0, 4.0))
    for k, view in enumerate(views(motion)):
        body_up = rotate(conjugate(attitude(motion.frame_times[k])), (0.0, 1.0, 0.0))
        assert math.degrees(math.acos(min(1.0, rotate(view, body_up)[1]))) < 0.5


def test_without_a_still_moment_it_declines():
    motion = camera()
    motion.gravity = array("d", [1.5] * len(motion.gravity))
    with pytest.raises(ValueError, match="1 g"):
        stabilise.track(motion, reference_for(motion))
