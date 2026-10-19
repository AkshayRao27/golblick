"""Stabilising a 360 video from its inertial record.  Standard library only.

A 360 video can be stabilised without cropping anything: the whole sphere is
there, so turning it back against the camera's motion loses nothing.  What
this computes is that turn for every frame, as a rotation from a frame as it
was rendered to the steadied view.  A player applies it while it plays, or a
renderer bakes it in.

The steadied view keeps the horizon level and lets its heading follow the
camera's, smoothed over a couple of seconds, so a turn comes through as a turn
and the shake doesn't.  The horizon and the shake were scored against
Insta360 Studio's FlowState; the heading was not, and FlowState follows turns
much more slowly, so where the view points after a turn is a choice here, not
a match.  ``docs/formats/insta360-agent-notes.md``, "Stabilising video from
the record".

How the camera's attitude is found, and why offline:

1. Integrate the gyroscope.  That is exact over short spans and drifts over
   long ones.
2. Express each accelerometer reading in that drifting frame.  Over a span of
   seconds it averages to up, because the camera's velocity is bounded, so its
   acceleration averages to nothing; a moment-to-moment reading can be 10
   degrees out while the camera is carried.
3. Average it with a window centred on each moment, and turn the attitude so
   that the average is straight up.

A filter that only looks back has to start from a guess and lags behind it;
having the whole clip, this does neither.

Frames: the render's own (``golblick.render``: y up, z forward), and every
rotation in the column convention, ``v_out = R @ v_in``.
"""

from __future__ import annotations

import math

#: Seconds over which the accelerometer is averaged into up (a Gaussian's
#: sigma).  Tuned on one X5 clip only; 1 and 2 seconds scored alike there and
#: 2 was the better of the two on the clips held out.
UP_WINDOW = 2.0

#: Seconds over which the heading is smoothed (a Gaussian's sigma).  On the
#: tuning clip the yaw left over against FlowState fell to 0.27 degrees rms at
#: 2 seconds and stayed flat beyond.
FOLLOW = 2.0

#: Accelerometer readings further than this from 1 g are left out of up.
STILL = 0.1

#: Readings are averaged in bins of this many seconds before smoothing.
BIN = 0.01

#: Orientations per frame across the readout, for :func:`shutter`.  A
#: renderer interpolates between them linearly.
SHUTTER_SAMPLES = 5


def track(motion, reference, up_window: float = UP_WINDOW, follow: float = FOLLOW, lock: bool = False):
    """Per video frame, the rotation from a frame rendered at ``reference`` to the steadied view.

    ``motion`` is what a vendor's ``motion(path)`` returns.  ``reference`` is
    the 3x3 orientation the frames were rendered with (``render.level`` of the
    opening's gravity, for a video), and the result starts close to the
    identity, so the steadied view opens facing where the render does.

    With ``lock``, the view keeps the direction it opens in instead of
    following the camera's turns, like Insta360 Studio's Direction Lock.

    Returns a list of unit quaternions ``(w, x, y, z)``, one per frame time.
    Raises ``ValueError`` if the accelerometer never reads close to 1 g, since
    then there is nothing to find up from.
    """
    rotations, turns = steady(motion, reference, up_window, follow)
    return locked(rotations, turns) if lock else rotations


def locked(rotations, turns):
    """The locked view from the following one and each frame's heading turn, both from :func:`steady`.

    Holds for a track that :func:`turned` has turned as well, since turns
    about the vertical commute.
    """
    return [_normalise(_multiply(_yaw(turn), q)) for q, turn in zip(rotations, turns, strict=True)]


def turned(rotations, angle: float):
    """The same track for a render turned ``angle`` radians about the vertical afterwards.

    A frame drawn with ``q @ reference`` and the whole picture then turned by
    ``Y`` is ``Y q Y^-1 @ (Y reference)``, so each rotation is conjugated by
    the turn.  This is exact; building the track again from the turned
    reference is not, because its first frame is aligned by a twist that
    doesn't simply add.
    """
    yaw, back = _yaw(angle), _yaw(-angle)
    return [_normalise(_multiply(_multiply(yaw, q), back)) for q in rotations]


def steady(motion, reference, up_window: float = UP_WINDOW, follow: float = FOLLOW):
    """The following view's rotations, and per frame how far its heading has turned since frame 0.

    Turning a frame's rotation back by its turn about the vertical (radians,
    applied on the left) gives the locked view: both views are the same
    attitude with different headings, and turns about the vertical commute.
    A player can offer both from this one track.
    """
    attitudes = _attitudes(motion, up_window)
    times = motion.frame_times
    step = _median([b - a for a, b in zip(times, times[1:], strict=False)]) if len(times) > 1 else 1.0

    # The heading is the attitude's twist about the vertical, which stays
    # defined however the camera is tilted.
    headings = _unwrap([2.0 * math.atan2(q[2], q[0]) for q in attitudes])
    smooth = _smooth_trend(headings, follow / step)
    ref = _quaternion(reference)
    inverse_ref = (ref[0], -ref[1], -ref[2], -ref[3])

    out = []
    for q, heading in zip(attitudes, smooth, strict=True):
        out.append(_multiply(_multiply(_yaw(-heading), q), inverse_ref))

    # Turn the steadied view so that its first frame faces where the render's
    # does: no twist about the vertical at frame 0.
    first = out[0]
    align = _yaw(-2.0 * math.atan2(first[2], first[0]))
    rotations = [_normalise(_multiply(align, q)) for q in out]
    return rotations, [heading - smooth[0] for heading in smooth]


def shutter(motion, samples: int = SHUTTER_SAMPLES):
    """Per video frame, how the camera turned while the frame was being read, for undoing rolling shutter.

    Returns, per frame time, ``samples`` unit quaternions ``(w, x, y, z)`` at
    even steps from half the readout before the frame's time to half after.
    Each takes a ray in the camera's frame as the camera pointed at the
    frame's time to the same ray as it pointed at that moment, so the middle
    one is the identity.  A renderer turns each ray by the one for the moment
    its row was read (``Motion.readout``), projects it again, and samples
    there.  Returns None when the readout is 0.

    The turn comes from the gyroscope alone, rate held over each sample as
    :func:`_attitudes` holds it.  Levelling moves over seconds, not within a
    frame, so it is left out; and the turn is the same with or without
    steadying, so an unsteadied view is corrected too.
    """
    readout = getattr(motion, "readout", 0.0)
    if not readout or samples < 2:
        return None
    t = motion.sample_times
    w = motion.angular_velocity
    frames = motion.frame_times
    offsets = [readout * (j / (samples - 1) - 0.5) for j in range(samples)]
    wanted = sorted((time + offset, k, j) for k, time in enumerate(frames) for j, offset in enumerate(offsets))
    centres = sorted((time, k) for k, time in enumerate(frames))

    # The attitude at every wanted moment and at every frame's time, in one
    # pass: the rate w[i] holds over (t[i-1], t[i]], so within a step the
    # attitude is the step's start turned by w[i] for the time since.
    at = [[None] * samples for _ in frames]
    centre = [None] * len(frames)
    q = (1.0, 0.0, 0.0, 0.0)
    a = c = 0
    count = len(t)
    for i in range(count + 1):
        end = t[i] if i < count else math.inf
        while a < len(wanted) or c < len(centres):
            nxt_a = wanted[a][0] if a < len(wanted) else math.inf
            nxt_c = centres[c][0] if c < len(centres) else math.inf
            moment = min(nxt_a, nxt_c)
            if moment > end:
                break
            here = q if i == 0 or i == count else _turned(q, w, i, moment - t[i - 1])
            if nxt_a <= nxt_c:
                at[wanted[a][1]][wanted[a][2]] = here
                a += 1
            else:
                centre[centres[c][1]] = here
                c += 1
        if 0 < i < count:
            q = _turned(q, w, i, t[i] - t[i - 1])
    # ray then = R(q_then)^T R(q_frame) ray: the quaternion conj(q_then) q_frame.
    return [tuple(_normalise(_multiply((p[0], -p[1], -p[2], -p[3]), centre[k])) for p in row)
            for k, row in enumerate(at)]


def _turned(q, w, i, dt):
    """``q`` turned by the body rate ``w[i]`` held for ``dt`` seconds."""
    wx, wy, wz = w[3 * i], w[3 * i + 1], w[3 * i + 2]
    rate = math.sqrt(wx * wx + wy * wy + wz * wz)
    if rate == 0 or dt <= 0:
        return q
    half = rate * dt / 2.0
    s = math.sin(half) / rate
    return _normalise(_multiply(q, (math.cos(half), wx * s, wy * s, wz * s)))


def _yaw(angle):
    """A turn about the vertical (+y) by ``angle`` radians, as a quaternion."""
    return (math.cos(angle / 2.0), 0.0, math.sin(angle / 2.0), 0.0)


def level(up):
    """The shortest rotation taking ``up`` to straight up, as a 3x3 orientation.

    The same rotation as :func:`golblick.render.level` with no yaw, without
    numpy, so that a reference can be built where the render extra isn't
    installed.  ``test_render`` checks the two agree.
    """
    w, x, y, z = _level_quaternion(up)
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def _attitudes(motion, up_window):
    """The camera's attitude at each frame time, body to world, as quaternions."""
    t = motion.sample_times
    w = motion.angular_velocity
    up = motion.up
    gravity = motion.gravity
    frames = motion.frame_times
    count = len(t)

    bins = int(t[-1] / BIN) + 1
    sx = [0.0] * bins
    sy = [0.0] * bins
    sz = [0.0] * bins
    weight = [0.0] * bins

    q0, q1, q2, q3 = 1.0, 0.0, 0.0, 0.0
    at_frames = []
    k = 0
    for i in range(count):
        # A frame between two samples gets the attitude at its own time, the
        # rate held since the last sample, not the next sample's: at 500 Hz
        # that is up to 2 ms, which on a fast turn is a visible jerk.
        while k < len(frames) and frames[k] <= t[i]:
            at_frames.append(_turned((q0, q1, q2, q3), w, i, frames[k] - t[i - 1]) if i else (q0, q1, q2, q3))
            k += 1
        if i:
            dt = t[i] - t[i - 1]
            if dt > 0:
                wx, wy, wz = w[3 * i], w[3 * i + 1], w[3 * i + 2]
                rate = math.sqrt(wx * wx + wy * wy + wz * wz)
                if rate > 0:
                    half = rate * dt / 2.0
                    s = math.sin(half) / rate
                    d0, d1, d2, d3 = math.cos(half), wx * s, wy * s, wz * s
                    q0, q1, q2, q3 = (q0 * d0 - q1 * d1 - q2 * d2 - q3 * d3,
                                      q0 * d1 + q1 * d0 + q2 * d3 - q3 * d2,
                                      q0 * d2 - q1 * d3 + q2 * d0 + q3 * d1,
                                      q0 * d3 + q1 * d2 - q2 * d1 + q3 * d0)
                    n = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
                    q0, q1, q2, q3 = q0 / n, q1 / n, q2 / n, q3 / n
        if abs(gravity[i] - 1.0) < STILL:
            ux, uy, uz = up[3 * i], up[3 * i + 1], up[3 * i + 2]
            # The reading, turned into the integrated frame: R(q) @ u.
            vx = ((1 - 2 * (q2 * q2 + q3 * q3)) * ux + 2 * (q1 * q2 - q0 * q3) * uy
                  + 2 * (q1 * q3 + q0 * q2) * uz)
            vy = (2 * (q1 * q2 + q0 * q3) * ux + (1 - 2 * (q1 * q1 + q3 * q3)) * uy
                  + 2 * (q2 * q3 - q0 * q1) * uz)
            vz = (2 * (q1 * q3 - q0 * q2) * ux + 2 * (q2 * q3 + q0 * q1) * uy
                  + (1 - 2 * (q1 * q1 + q2 * q2)) * uz)
            b = int(t[i] / BIN)
            sx[b] += vx
            sy[b] += vy
            sz[b] += vz
            weight[b] += 1.0
    while k < len(frames):
        at_frames.append((q0, q1, q2, q3))
        k += 1

    if not any(weight):
        raise ValueError("the accelerometer never reads close to 1 g, so up can't be found")
    sigma = up_window / BIN
    mx = _smooth(sx, weight, sigma, presummed=True)
    my = _smooth(sy, weight, sigma, presummed=True)
    mz = _smooth(sz, weight, sigma, presummed=True)

    out = []
    for time, q in zip(frames, at_frames, strict=True):
        b = min(max(int(time / BIN), 0), bins - 1)
        level = _level_quaternion((mx[b], my[b], mz[b]))
        out.append(_normalise(_multiply(level, q)))
    return out


def _smooth(values, weights, sigma, presummed=False):
    """A weighted, normalised Gaussian smoothing, as three passes of a running sum.

    With ``presummed``, ``values`` already hold value times weight per slot
    (sums over a bin).  Slots outside the sequence count as weight zero, so
    the ends are averaged over what there is rather than pulled to zero.
    Three boxes of width w have variance 3 (w^2 - 1) / 12, which sets w.
    """
    width = int(math.sqrt(4.0 * sigma * sigma + 1.0))
    width += 1 - width % 2
    numerator = list(values) if presummed else [v * w for v, w in zip(values, weights, strict=True)]
    denominator = list(weights)
    for _ in range(3):
        numerator = _box(numerator, width)
        denominator = _box(denominator, width)
    return [n / d if d > 0 else 0.0 for n, d in zip(numerator, denominator, strict=True)]


def _smooth_trend(values, sigma):
    """Gaussian smoothing that carries a trend through the ends.

    The sequence is extended past each end by point reflection, so a turn
    that is under way when the clip starts or stops is smoothed as a turn,
    not pulled towards the average of whatever lies on one side (which jumps
    ahead at the start of a clip that opens mid-pan).  The point it reflects
    through is a straight line fitted
    to the end, not the end value itself, which would pin the first and last
    frames to whatever the shake was doing at that instant.
    """
    width = int(math.sqrt(4.0 * sigma * sigma + 1.0))
    width += 1 - width % 2
    n = len(values)
    if n < 3:
        return list(values)
    pad = min(3 * width, n - 1)
    span = min(n, width)
    first = _line_at(values[:span], 0.0)
    last = _line_at(values[n - span:], span - 1.0)
    extended = ([2 * first - values[j] for j in range(pad, 0, -1)] + list(values)
                + [2 * last - values[n - 1 - j] for j in range(1, pad + 1)])
    ones = [1.0] * len(extended)
    smooth = extended
    count = ones
    for _ in range(3):
        smooth = _box(smooth, width)
        count = _box(count, width)
    return [smooth[pad + i] / count[pad + i] for i in range(n)]


def _line_at(values, x):
    """A least-squares straight line through ``values`` (at 0, 1, ...), evaluated at ``x``."""
    n = len(values)
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    spread = sum((i - mean_x) ** 2 for i in range(n))
    slope = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / spread if spread else 0.0
    return mean_y + slope * (x - mean_x)


def _box(values, width):
    """Centred running sum of ``width`` (odd) slots, by prefix sums."""
    half = width // 2
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    n = len(values)
    return [prefix[min(n, i + half + 1)] - prefix[max(0, i - half)] for i in range(n)]


def _level_quaternion(up):
    """The shortest rotation taking ``up`` to +y, as a quaternion."""
    x, y, z = up
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0:
        return (1.0, 0.0, 0.0, 0.0)
    x, y, z = x / n, y / n, z / n
    # Half-way vector trick: q = (1 + u.y, u x y) normalised.
    w = 1.0 + y
    if w < 1e-9:
        return (0.0, 1.0, 0.0, 0.0)   # straight down: half a turn about x
    return _normalise((w, -z, 0.0, x))


def _multiply(a, b):
    a0, a1, a2, a3 = a
    b0, b1, b2, b3 = b
    return (a0 * b0 - a1 * b1 - a2 * b2 - a3 * b3,
            a0 * b1 + a1 * b0 + a2 * b3 - a3 * b2,
            a0 * b2 - a1 * b3 + a2 * b0 + a3 * b1,
            a0 * b3 + a1 * b2 - a2 * b1 + a3 * b0)


def _normalise(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def _quaternion(m):
    """A 3x3 rotation (column convention) as a unit quaternion."""
    (a, b, c), (d, e, f), (g, h, i) = [[float(v) for v in row] for row in m]
    trace = a + e + i
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = (s / 4, (h - f) / s, (c - g) / s, (d - b) / s)
    elif a > e and a > i:
        s = math.sqrt(1.0 + a - e - i) * 2
        q = ((h - f) / s, s / 4, (b + d) / s, (c + g) / s)
    elif e > i:
        s = math.sqrt(1.0 + e - a - i) * 2
        q = ((c - g) / s, (b + d) / s, s / 4, (f + h) / s)
    else:
        s = math.sqrt(1.0 + i - a - e) * 2
        q = ((d - b) / s, (c + g) / s, (f + h) / s, s / 4)
    return _normalise(q)


def _unwrap(angles):
    out = []
    offset = 0.0
    previous = None
    for a in angles:
        if previous is not None:
            jump = a - previous
            if jump > math.pi:
                offset -= 2 * math.pi
            elif jump < -math.pi:
                offset += 2 * math.pi
        previous = a
        out.append(a + offset)
    return out


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
