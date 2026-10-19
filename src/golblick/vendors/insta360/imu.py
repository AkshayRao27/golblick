"""Record ``0x0300`` -- the inertial log, and the gravity vector in it.

This is what makes levelling possible on a camera that embeds no stitch of its
own, which is most of them: the accelerometer says which way is down, and a
panorama that ignores it comes out at whatever angle the camera happened to be
held.  ``docs/formats/insta360-agent-notes.md`` ("the format notes") has the
measurements, under "Record `0x0300` — IMU" and "Levelling".

Two encodings, and the camera does not announce which.  The entry is a
64-bit millisecond timecode followed by six values -- three accelerometer axes
in g, then three angular velocities -- but how those six are stored varies:

=========  =========================  ==========================================
Stride     Payload                    Where it was seen
=========  =========================  ==========================================
20 bytes   6 x uint16, biased 0x8000  value = (raw - 32768) / 1000
56 bytes   6 x float64                value as stored
=========  =========================  ==========================================

The stride is not a property of the camera model: one OneR writes both forms.
So :func:`entries` searches the candidate strides and keeps only one that
divides the record exactly and whose timecodes rise monotonically, refusing
when none fits or more than one does, as the trailer's padding search does.

Most stills carry no record of their own; :func:`gravity_up_nearby` borrows
one from the same shutter press, and :func:`golblick.render.body_orientation`
corrects the roll of every file that carries a trailer.
"""

from __future__ import annotations

import struct
from array import array
from dataclasses import dataclass

from ...errors import FormatError
from .trailer import IMU, read_trailer

_TIMECODE = struct.Struct("<q")

#: Stride in bytes -> how to read the six values that follow the timecode.
_LAYOUTS = {
    20: ("<6H", lambda raw: tuple((v - 0x8000) / 1000 for v in raw)),
    56: ("<6d", lambda raw: tuple(raw)),
}


#: The share of timecodes that may repeat the one before.  See :func:`_decode`.
_REPEATS_ALLOWED = 0.001


@dataclass(frozen=True)
class Sample:
    """One inertial sample.  ``acceleration`` is in g.

    ``time`` is the raw timecode over 1000, not converted, so its unit depends
    on the encoding: seconds on the 56-byte form and milliseconds on the
    20-byte form, which counts microseconds (see :data:`_CLOCK`).  Nothing in
    the package uses ``time``; :func:`motion` converts with :data:`_CLOCK`.
    """

    time: float
    acceleration: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]


def _decode(data: bytes, stride: int) -> list[Sample] | None:
    """Read the record at one candidate stride, or None if it does not fit."""
    if stride > len(data) or len(data) % stride:
        return None
    layout, convert = _LAYOUTS[stride]
    values = struct.Struct(layout)

    samples = []
    previous = None
    repeats = 0
    for offset in range(0, len(data), stride):
        (timecode,) = _TIMECODE.unpack_from(data, offset)
        # A wrong stride reads one entry's payload as the next timecode, which
        # does not stay ordered for long.  A rare repeat is the camera's clock
        # (format notes, "Record `0x0300` — IMU"); going backwards, or
        # repeating often, refuses.
        if previous is not None and timecode < previous:
            return None
        if previous is not None and timecode == previous:
            repeats += 1
            if repeats > _REPEATS_ALLOWED * (len(data) // stride):
                return None
        previous = timecode
        six = convert(values.unpack_from(data, offset + _TIMECODE.size))
        samples.append(Sample(timecode / 1000.0, six[:3], six[3:]))
    return samples


def entries(path) -> list[Sample]:
    """Every inertial sample in ``path``, whichever encoding it uses."""
    record = read_trailer(path).get(IMU)
    if record is None:
        raise FormatError(f"{path}: no inertial record (0x0300) in the trailer")

    fits = {stride: _decode(record.data, stride) for stride in _LAYOUTS}
    fits = {stride: samples for stride, samples in fits.items() if samples}
    if not fits:
        raise FormatError(
            f"{path}: inertial record of {len(record.data)} bytes matches no known entry stride {sorted(_LAYOUTS)}"
        )
    if len(fits) > 1:
        raise FormatError(
            f"{path}: inertial record is ambiguous -- strides {sorted(fits)} both fit"
        )
    return next(iter(fits.values()))


#: How much of a video's record levels its opening frame.  See :func:`gravity`.
OPENING_SAMPLES = 1500


def gravity(path) -> tuple[float, float, float]:
    """The accelerometer's median reading over the whole record, in g.

    The median rather than the mean, and over every sample rather than the one
    nearest the shutter, because a still's log is short and a hand shake at one
    end of it should not tilt the horizon.

    Except for a video, which is levelled for its opening frame: there the
    record covers the whole clip, so only its first ``OPENING_SAMPLES`` are
    used.  That also bounds memory in the Nextcloud port, which has to stay
    identical, and it levels frame 0 better than the whole record or a shorter
    window (format notes, "Route 2 — the gravity vector from the IMU").

    This is the direction of gravity in the IMU's own axes, not the render's;
    :func:`gravity_up` applies the measured mapping between them.
    """
    samples = entries(path)
    if not samples:
        raise FormatError(f"{path}: inertial record is empty")
    if is_video(path):
        samples = samples[:OPENING_SAMPLES]
    axes = []
    for axis in range(3):
        ordered = sorted(sample.acceleration[axis] for sample in samples)
        middle = len(ordered) // 2
        axes.append(ordered[middle] if len(ordered) % 2
                    else (ordered[middle - 1] + ordered[middle]) / 2)
    return tuple(axes)


#: How each camera's inertial axes sit relative to the render's, as rows of a
#: linear map applied to the acceleration vector.
#:
#: Every map here is a reflection (determinant -1), and that is measured, not a
#: slip: do not "fix" one by flipping a sign.  It matters beyond gravity, since
#: the gyroscope shares these axes and an angular velocity changes sign under a
#: reflection (see :func:`motion`).
#:
#: Measured per camera, never borrowed: upright, an X5 reads gravity along -x
#: and a OneR along +x, so one camera's map hangs another's panorama upside
#: down.  An unmeasured model is refused.  Each map's measurement is in the
#: format notes, "Route 2 — the gravity vector from the IMU" and the sections
#: after it.
_AXES = {
    # up_render = (-az, -ax, -ay); measured against the stitch the X5 embeds.
    "Insta360 X5": ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    # up_render = (-ax, -az, ay); measured against Insta360 Studio's levelled
    # exports of every OneR still that carries a record.  Not against the
    # body-up that Calibration.body_roll gives, which misled an earlier fit.
    "Insta360 OneR": ((-1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    # up_render = (-az, -ax, -ay), the X5's map; measured against Insta360
    # Studio's levelled exports, 38 stills.
    "Insta360 X3": ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
}

#: Where a camera's VIDEO record differs from its stills'.  Others use _AXES.
_VIDEO_AXES = {
    # up_render = (az, -ax, ay): the still map turned 180 degrees about the
    # vertical.  Measured on 44 X5 videos against the camera's own stitch of
    # frame 0; OneR and X3 videos keep their still maps.
    "Insta360 X5": ((0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}


def is_video(path) -> bool:
    """By content: an MP4 (.insv, .lrv) has ``ftyp`` at byte 4; a still is a JPEG."""
    with open(path, "rb") as handle:
        return handle.read(8)[4:8] == b"ftyp"


def gravity_up_nearby(path) -> tuple[float, float, float]:
    """Which way is up, from this file or from the frame beside it.

    Most stills carry no inertial record, but each sits in a burst or bracket
    where another frame does, and the camera writes the same reading to every
    frame of one shutter press.  So this borrows the record from a frame with
    the same timestamp.  Format notes, "Borrowing the record from the same
    shutter press".

    Unlike :func:`gravity_up` this reads the DIRECTORY, not just the file.
    Keep the two apart: the vendor contract is that a reader is handed a path
    and reports what is in it, and this deliberately does more.

    Raises :class:`FormatError` if neither this file nor any sibling yields a
    reading.
    """
    from pathlib import Path

    from . import describe, naming

    # A sibling is the same camera by construction, so an unmeasured axis
    # mapping cannot be rescued by looking at one -- fail with the real reason
    # rather than the misleading "no record anywhere" further down.
    model = describe(path)["model"]
    if model not in _AXES:
        raise FormatError(
            f"{path}: the inertial axis mapping for {model!r} has not been measured, only {sorted(_AXES)}; levelling it would be a guess"
        )

    try:
        return gravity_up(path)
    except FormatError:
        pass

    path = Path(path)
    stamp = naming.burst(path)
    if stamp is None:
        raise FormatError(f"{path}: no inertial record, and the name is not one we can group")

    # Sorted so the choice is deterministic: two runs over the same bracket must
    # pick the same donor, or a cached preview and a fresh one disagree.
    for sibling in sorted(path.parent.glob("*")):
        if sibling == path or naming.burst(sibling) != stamp:
            continue
        try:
            return gravity_up(sibling)
        except (FormatError, OSError):
            continue

    raise FormatError(f"{path}: no inertial record here or in the rest of the burst")


def gravity_up(path) -> tuple[float, float, float]:
    """Which way is up, as a unit vector in the render's own frame.

    Feed it to :func:`golblick.render.level` to build the rotation, and that
    to :func:`golblick.render.equirectangular` as its ``orientation``.

    Raises :class:`FormatError` for a camera whose axis mapping has not been
    measured, rather than borrowing another camera's.
    """
    from . import describe  # circular at import time, fine at call time

    model = describe(path)["model"]
    axes = (_VIDEO_AXES.get(model) if is_video(path) else None) or _AXES.get(model)
    if axes is None:
        raise FormatError(
            f"{path}: the inertial axis mapping for {model!r} has not been measured, only {sorted(_AXES)}; levelling it would be a guess"
        )

    vector = gravity(path)
    length = sum(component * component for component in vector) ** 0.5
    if length < 0.5:
        raise FormatError(f"{path}: accelerometer reads {length:.3f} g, too little to be gravity")

    unit = [component / length for component in vector]
    return tuple(sum(row[i] * unit[i] for i in range(3)) for row in axes)


#: Seconds per raw timecode unit, by entry stride: milliseconds on the 56-byte
#: form, microseconds on the 20-byte one.  Measured by each video record's span
#: against the clip's length (format notes, "Record `0x0300` — IMU").
_CLOCK = {20: 1e-6, 56: 1e-3}

#: A frame log entry: the frame's timecode on the inertial clock, then a
#: double that reads as the exposure time in seconds (1/1144 s on a bright
#: X3 clip).
_FRAME_ENTRY = struct.Struct("<qd")

#: How late the 56-byte form's frame log stamps a frame, in seconds, beyond
#: half its exposure: the picture matches the gyroscope at the stamp less half
#: the exposure less this.  Fitted against the picture on 17 clips; the 20-byte
#: form needs nothing (format notes, "Frame stamps in the 56-byte form come late").
_STAMPED_LATE = {56: 0.0186}

#: Models whose rolling shutter has been measured: each lens image is read
#: down its rows, both lenses alike, over metadata field 25's time.  Other
#: models get no correction until their direction is measured (format notes,
#: "Rolling shutter").
_READS_DOWN = {"Insta360 OneR"}


@dataclass(frozen=True)
class Motion:
    """A video's inertial record, ready to stabilise it with.

    Everything is in the render's own frame and in seconds on one clock, whose
    zero is the record's first sample.  Vectors are flat, three values per
    sample, to keep a half-hour clip (some 1.8 million samples) in memory.

    ``angular_velocity`` is in radians per second.  ``up`` is the unit vector
    the accelerometer reads as up, and ``gravity`` the reading's length in g,
    which is near 1 only when the camera isn't accelerating.  ``frame_times``
    is when each video frame was captured; there can be a few more of them
    than the video has frames, at the end.

    ``readout`` is how long the sensor took to read a frame, in seconds: a
    pixel in row ``y`` of a lens image ``h`` rows high was seen at its frame's
    time plus ``(y / h - 1/2) * readout``.  0 means don't correct for it,
    because the file doesn't say or the camera hasn't been measured.
    """

    sample_times: array
    angular_velocity: array
    up: array
    gravity: array
    frame_times: array
    readout: float = 0.0


def _columns(data: bytes, stride: int):
    """Timecodes and the six values, as arrays; the same ordering rule as _decode."""
    layout, convert = _LAYOUTS[stride]
    times = array("q")
    values = array("d")
    previous = None
    repeats = 0
    allowed = _REPEATS_ALLOWED * (len(data) // stride)
    for entry in struct.iter_unpack("<q" + layout[1:], data):
        timecode = entry[0]
        if previous is not None and timecode < previous:
            return None
        if previous is not None and timecode == previous:
            repeats += 1
            if repeats > allowed:
                return None
        previous = timecode
        times.append(timecode)
        values.extend(convert(entry[1:]))
    return times, values


def motion(path) -> Motion:
    """The inertial record of a video, with the time of each of its frames.

    The gyroscope shares the accelerometer's axes, so the axis map measured
    for gravity serves for rotation too, with one twist: an angular velocity
    is an axial vector, so where that map is a reflection (determinant -1:
    every map measured so far) it changes sign.  Angular velocity is in radians per second.

    Frame 0 is the frame log's entry nearest metadata field 24, a timecode on
    the same clock, and the entries from it on are the frames.  The 20-byte
    form's frames were captured at field 24's time and the log's spacing; the
    56-byte form's, half an exposure and a little more before each stamp
    (:data:`_STAMPED_LATE`).  Format notes, "The gyroscope shares the
    accelerometer's axes", "When each frame was captured" and "Frame stamps in
    the 56-byte form come late".

    The readout time is metadata field 25, in milliseconds, for the models in
    :data:`_READS_DOWN`.

    Raises :class:`FormatError` for a still, an unmeasured camera, a missing
    or unreadable record, and a first frame that falls outside the inertial
    record or the frame log.
    """
    from . import describe, metadata  # circular at import time, fine at call time
    from .trailer import FRAMES, METADATA

    if not is_video(path):
        raise FormatError(f"{path}: not a video")
    model = describe(path)["model"]
    axes = _VIDEO_AXES.get(model) or _AXES.get(model)
    if axes is None:
        raise FormatError(
            f"{path}: the inertial axis mapping for {model!r} has not been measured, only {sorted(_AXES)}; stabilising it would be a guess"
        )

    trailer = read_trailer(path)
    record = trailer.get(IMU)
    if record is None or not record.data:
        raise FormatError(f"{path}: no inertial record (0x0300) in the trailer")
    fits = {}
    for stride in _LAYOUTS:
        if len(record.data) % stride == 0:
            columns = _columns(record.data, stride)
            if columns is not None:
                fits[stride] = columns
    if len(fits) != 1:
        raise FormatError(f"{path}: inertial record of {len(record.data)} bytes fits {len(fits)} of the known strides, not one")
    ((stride, (timecodes, values)),) = fits.items()
    unit = _CLOCK[stride]
    start = timecodes[0]

    grouped = metadata.by_number(trailer.get(METADATA).data) if trailer.get(METADATA) else {}
    first = [f.value for f in grouped.get(metadata.FIRST_FRAME, ()) if isinstance(f.value, int)]
    if not first:
        raise FormatError(f"{path}: no first-frame time (metadata field 24)")
    first = first[0]
    if not start <= first <= timecodes[-1]:
        raise FormatError(f"{path}: the first frame's time falls outside the inertial record")

    log = trailer.get(FRAMES)
    if log is None or len(log.data) < 2 * _FRAME_ENTRY.size or len(log.data) % _FRAME_ENTRY.size:
        raise FormatError(f"{path}: no readable frame log (0x0400)")
    entries = list(_FRAME_ENTRY.iter_unpack(log.data))
    stamps = [entry[0] for entry in entries]
    if any(b <= a for a, b in zip(stamps, stamps[1:], strict=False)):
        raise FormatError(f"{path}: the frame log's timecodes do not rise")
    nearest = min(range(len(stamps)), key=lambda i: abs(stamps[i] - first))
    steps = sorted(b - a for a, b in zip(stamps, stamps[1:], strict=False))
    spacing = steps[len(steps) // 2]
    if abs(stamps[nearest] - first) > spacing / 2:
        raise FormatError(f"{path}: the first frame's time is not in the frame log")
    late = _STAMPED_LATE.get(stride)
    if late is None:
        shift = first - stamps[nearest]
        frame_times = array("d", ((stamp + shift - start) * unit for stamp in stamps[nearest:]))
    else:
        if any(not 0.0 <= exposure < 1.0 for _, exposure in entries[nearest:]):
            raise FormatError(f"{path}: the frame log has an exposure that isn't a fraction of a second")
        frame_times = array("d", ((stamp - start) * unit - exposure / 2 - late for stamp, exposure in entries[nearest:]))

    sign = -1.0 if _determinant(axes) < 0 else 1.0
    count = len(timecodes)
    sample_times = array("d", ((t - start) * unit for t in timecodes))
    angular = array("d", bytes(8 * 3 * count))
    up = array("d", bytes(8 * 3 * count))
    gravity = array("d", bytes(8 * count))
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = axes
    for i in range(count):
        o = 6 * i
        ax, ay, az, gx, gy, gz = values[o:o + 6]
        angular[3 * i] = sign * (a0 * gx + a1 * gy + a2 * gz)
        angular[3 * i + 1] = sign * (b0 * gx + b1 * gy + b2 * gz)
        angular[3 * i + 2] = sign * (c0 * gx + c1 * gy + c2 * gz)
        length = (ax * ax + ay * ay + az * az) ** 0.5
        gravity[i] = length
        if length > 0:
            up[3 * i] = (a0 * ax + a1 * ay + a2 * az) / length
            up[3 * i + 1] = (b0 * ax + b1 * ay + b2 * az) / length
            up[3 * i + 2] = (c0 * ax + c1 * ay + c2 * az) / length
    readout = 0.0
    if model in _READS_DOWN:
        given = [f.value for f in grouped.get(metadata.READOUT, ()) if isinstance(f.value, float)]
        # A frame is read within its own period; anything else isn't a readout time.
        if given and 0.0 < given[0] < 1000.0 * spacing * unit:
            readout = given[0] / 1000.0
    return Motion(sample_times, angular, up, gravity, frame_times, readout)


def _determinant(m) -> float:
    (a, b, c), (d, e, f), (g, h, i) = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
