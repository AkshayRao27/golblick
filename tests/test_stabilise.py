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


def views(motion, lock=False):
    """Per frame, body to steadied view: the track composed with the reference."""
    reference = reference_for(motion)
    level = stabilise._quaternion(reference)
    return [multiply(c, level) for c in stabilise.track(motion, reference, lock=lock)]


def view_headings(motion, lock=False):
    """Where the world's forward appears in the view, per frame, in degrees."""
    out = []
    for k, view in enumerate(views(motion, lock)):
        world_to_view = multiply(view, conjugate(attitude(motion.frame_times[k])))
        out.append(2 * math.atan2(world_to_view[2], world_to_view[0]))
    return [math.degrees(h) for h in stabilise._unwrap(out)]


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


def test_a_locked_view_keeps_its_direction_through_the_pan():
    """Like Studio's Direction Lock: the 40-degree pan doesn't turn the view."""
    headings = view_headings(camera(), lock=True)
    assert max(headings) - min(headings) < 0.5


def test_locked_and_following_views_open_the_same_and_share_the_horizon():
    motion = camera()
    follow, locked = views(motion), views(motion, lock=True)
    assert all(a == pytest.approx(b) for a, b in zip(follow[0], locked[0], strict=True))
    for k, view in enumerate(locked):
        body_up = rotate(conjugate(attitude(motion.frame_times[k])), (0.0, 1.0, 0.0))
        assert math.degrees(math.acos(min(1.0, rotate(view, body_up)[1]))) < 0.5


def test_a_track_turned_with_the_render_draws_the_same_picture_turned():
    """Turning the copy to face forward must turn every frame alike, not just the first.

    Frame k is drawn with q_k @ reference; turned by Y it must become Y q_k @ reference.
    The rotations here are lopsided on purpose: a turn about the vertical alone
    commutes with Y and would pass even if the conjugation were the wrong way round.
    """
    numpy = pytest.importorskip("numpy")
    from golblick import video

    rng = numpy.random.default_rng(3)
    track = [stabilise._normalise(tuple(rng.normal(size=4))) for _ in range(6)]
    reference = video.quaternion_matrix(stabilise._normalise((0.9, 0.2, -0.3, 0.1)))
    angle = 2.1
    c, s = math.cos(angle), math.sin(angle)
    turn = numpy.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])   # about +y, column convention

    for q, q_turned in zip(track, stabilise.turned(track, angle), strict=True):
        before = video.quaternion_matrix(q) @ reference
        after = video.quaternion_matrix(q_turned) @ (turn @ reference)
        assert after == pytest.approx(turn @ before, abs=1e-12)


def test_locking_a_turned_track_is_turning_a_locked_one():
    """The player turns the following track to face forward and locks it after; the stitch did it the other way round."""
    import random

    rng = random.Random(5)
    track = [stabilise._normalise(tuple(rng.gauss(0, 1) for _ in range(4))) for _ in range(6)]
    headings = [rng.uniform(-3, 3) for _ in track]
    one = stabilise.locked(stabilise.turned(track, 2.1), headings)
    other = stabilise.turned(stabilise.locked(track, headings), 2.1)
    for a, b in zip(one, other, strict=True):
        assert a == pytest.approx(b, abs=1e-12) or a == pytest.approx(tuple(-v for v in b), abs=1e-12)


def test_the_shutter_turns_are_the_camera_s_own_turn_across_the_readout():
    """Each turn takes a ray as the camera saw it at the frame's time to the same ray at that moment."""
    motion = camera()
    motion.readout = 0.03
    turns = stabilise.shutter(motion)

    assert len(turns) == len(motion.frame_times)
    v = (0.3, -0.5, 0.81)
    for k in (0, 57, 140):
        t = motion.frame_times[k]
        assert len(turns[k]) == stabilise.SHUTTER_SAMPLES
        for j, turn in enumerate(turns[k]):
            moment = t + 0.03 * (j / (stabilise.SHUTTER_SAMPLES - 1) - 0.5)
            # A world direction d is seen as R(q)^T d; so then = R(q_then)^T R(q_now) now.
            expected = rotate(multiply(conjugate(attitude(moment)), attitude(t)), v)
            assert rotate(turn, v) == pytest.approx(expected, abs=2e-4)
        middle = turns[k][stabilise.SHUTTER_SAMPLES // 2]
        assert rotate(middle, v) == pytest.approx(v, abs=1e-9)


def test_the_shutter_turns_between_samples_not_at_them():
    """A moment between two gyro samples gets the turn so far, not the next sample's."""
    motion = camera()
    motion.readout = 0.0005                   # half a sample apart at 1 kHz
    turns = stabilise.shutter(motion, samples=2)
    t = motion.frame_times[30]
    expected = rotate(multiply(conjugate(attitude(t - 0.00025)), attitude(t)), (0.0, 0.0, 1.0))
    got = rotate(turns[30][0], (0.0, 0.0, 1.0))
    # Holding a sample would give no turn or a whole sample's; this is a quarter of one, to 5%.
    assert abs(expected[0]) > 1e-4
    assert got == pytest.approx(expected, abs=0.05 * abs(expected[0]))


def test_no_readout_no_shutter():
    motion = camera()
    assert stabilise.shutter(motion) is None
    motion.readout = 0.0
    assert stabilise.shutter(motion) is None


def test_a_frame_between_two_samples_gets_the_attitude_at_its_own_time():
    """Not the next sample's: at 500 Hz that would put a frame up to 2 ms late."""
    motion = camera()
    t = motion.sample_times[3000] + 0.00025
    motion.frame_times = array("d", (t, t + 0.0005))
    first, second = stabilise._attitudes(motion, stabilise.UP_WINDOW)
    got = rotate(multiply(conjugate(first), second), (0.0, 0.0, 1.0))
    expected = rotate(multiply(conjugate(attitude(t)), attitude(t + 0.0005)), (0.0, 0.0, 1.0))
    assert abs(expected[0]) > 1e-4
    assert got == pytest.approx(expected, abs=0.05 * abs(expected[0]))


def test_numpy_steadies_and_undoes_the_shutter_as_the_standard_library_does(monkeypatch):
    """numpy, where installed, takes the running product as a prefix scan; that may only differ by rounding."""
    pytest.importorskip("numpy")
    motion = camera(jolt=(1.0, 1.4))
    motion.readout = 0.03
    reference = reference_for(motion)
    fast_track, fast_turns = stabilise.steady(motion, reference), stabilise.shutter(motion)
    monkeypatch.setattr(stabilise, "_numpy", lambda: None)
    slow_track, slow_turns = stabilise.steady(motion, reference), stabilise.shutter(motion)

    for a, b in zip(fast_track[0], slow_track[0], strict=True):
        assert a == pytest.approx(b, abs=1e-9)
    assert fast_track[1] == pytest.approx(slow_track[1], abs=1e-9)
    for row_a, row_b in zip(fast_turns, slow_turns, strict=True):
        for a, b in zip(row_a, row_b, strict=True):
            assert a == pytest.approx(b, abs=1e-9)
