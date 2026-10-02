"""Record ``0x0300`` -- the inertial log, and the gravity vector in it.

This is what makes levelling possible on a camera that embeds no stitch of its
own, which is most of them: the accelerometer says which way is down, and a
panorama that ignores it comes out at whatever angle the camera happened to be
held.  See ``docs/formats/insta360-agent-notes.md``.

⚠️ **Two encodings, and the camera does not announce which.**  The entry is a
64-bit millisecond timecode followed by six values -- three accelerometer axes
in g, then three angular velocities -- but how those six are stored varies:

=========  =========================  ==========================================
Stride     Payload                    Where it was seen
=========  =========================  ==========================================
20 bytes   6 x uint16, biased 0x8000  value = (raw - 32768) / 1000
56 bytes   6 x float64                value as stored
=========  =========================  ==========================================

🔴 **The stride is not a property of the camera model.**  The 20-byte form was
measured first, on an X5, and written down as the format's layout.  It is not:
of the 379 OneR stills in one library that carry this record, 285 use the
56-byte form and 94 use the 20-byte one -- the *same camera model* on both
sides.  So :func:`entries` searches the candidate strides and keeps only one
that divides the record exactly and whose timecodes rise monotonically,
refusing when none fits or more than one does; the trailer's padding search
works the same way and for the same reason.  Both decodes were checked against
exiftool's, value for value, over files from all three cameras.

⚠️ **Most files do not carry this record at all.**  Over all 1,415 ``.insp`` in
that library: 442 decode, 965 have no ``0x0300`` (all of them OneR -- 72% of
that camera's stills), 6 have no trailer, and 2 carry a zero-length record.  Of
the 442 that decode, 404 belong to a camera whose axis mapping is measured, so
an IMU-derived horizon serves a little under a third of the library and any
levelling that has to work everywhere needs a second route --
:func:`golblick.render.body_orientation`, which reaches all 1,409 files that
carry a trailer but corrects roll only.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ...errors import FormatError
from .trailer import IMU, read_trailer

_TIMECODE = struct.Struct("<q")

#: Stride in bytes -> how to read the six values that follow the timecode.
_LAYOUTS = {
    20: ("<6H", lambda raw: tuple((v - 0x8000) / 1000 for v in raw)),
    56: ("<6d", lambda raw: tuple(raw)),
}


@dataclass(frozen=True)
class Sample:
    """One inertial sample.  ``time`` is seconds; ``acceleration`` is in g."""

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
    for offset in range(0, len(data), stride):
        (timecode,) = _TIMECODE.unpack_from(data, offset)
        # A stride that is wrong slices the payload of one entry as the
        # timecode of the next, which does not stay ordered for long.
        if previous is not None and timecode <= previous:
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
            f"{path}: inertial record of {len(record.data)} bytes matches no known "
            f"entry stride {sorted(_LAYOUTS)}"
        )
    if len(fits) > 1:
        raise FormatError(
            f"{path}: inertial record is ambiguous -- strides {sorted(fits)} both fit"
        )
    return next(iter(fits.values()))


def gravity(path) -> tuple[float, float, float]:
    """The accelerometer's median reading over the whole record, in g.

    The median rather than the mean, and over every sample rather than the one
    nearest the shutter, because a still's log is short and a hand shake at one
    end of it should not tilt the horizon.

    ⚠️ This is the direction of gravity **in the IMU's own axes**, which are
    not the render's axes.  :func:`golblick.render.level` holds the rotation
    between them, which was measured rather than assumed.
    """
    samples = entries(path)
    if not samples:
        raise FormatError(f"{path}: inertial record is empty")
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
#: 🔴 **The X5's map is a reflection, not a rotation** -- its determinant is
#: -1.  That is not a mistake and must not be "fixed" by flipping a sign back:
#: it says the stored triple, *as this module labels it*, is not a right-handed
#: (x, y, z) on that camera.  Two components transposed or one inverted in the
#: camera's own convention would both produce it, and nothing measured
#: distinguishes those, so the composite is recorded rather than a story about
#: which axis is which.  The OneR's map is a proper rotation, and the
#: difference is per camera rather than per encoding -- both of the OneR's two
#: entry encodings were checked.
#:
#: 🔴 **Measured per camera, never borrowed.**  Upright, an X5 reads gravity
#: along -x and a OneR along +x, so applying one camera's mapping to another
#: hangs the panorama upside down.  Refusing an unmeasured model is the point:
#: a guessed axis mapping produces a confident, wrong horizon.
#:
#: The X5 was measured directly, against the levelled stitch it embeds.  No
#: other camera embeds one, so the OneR was measured a second way: over enough
#: shots the camera is upright *on average*, so the signed permutation that
#: carries the population's median reading to vertical is the mapping.  That
#: estimator was validated by running it on the X5 first, where it recovers the
#: directly-measured answer.  ``docs/formats/insta360-agent-notes.md`` has the evidence and
#: the failure case.
_AXES = {
    # up_render = (-az, -ax, -ay).  Determinant -1; see above.  The sign on
    # the first component was wrong until 2026-09-24, which left the tilt
    # *magnitude* right and its *azimuth* mirrored -- the reason no constant
    # offset ever reconciled the two.  Against the camera's own stitch the
    # correction moves tilted frames from 0.674 to 0.832 and leaves upright
    # ones alone, and it cuts the disagreement with the solved rotation from
    # 13.97 degrees median to 1.69.
    "Insta360 X5": ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    # up_render = (-ax, -az, ay).
    #
    # 🔴 Corrected 2026-09-29, against Insta360 Studio's own levelled exports.
    # The previous map, (-ax, ay, -az), was chosen by matching the body-up that
    # ``Calibration.body_roll`` derives from the calibration string -- a PROXY,
    # and for this camera a systematically misleading one.  Measured against a
    # real horizon instead, over 358 stills with a Studio export to score
    # against, rendered through this module and matched by feature
    # correspondence:
    #
    #     encoding   old map   this map   p90    within 5 deg    n
    #     56-byte      9.6       1.16     3.4        92%         285
    #     20-byte     42.9       1.06     2.4       100%          94
    #
    # That is EVERY OneR still in the library carrying an inertial record, not
    # a sample, and both encodings pick this map independently.
    #
    # 🔴 The X5 is the control twice over: its map was measured directly years
    # earlier, and the same search run against Studio returns it unchanged with
    # the runner-up 4.5 degrees away. The search moves a map only where it is
    # wrong. ⚠️ Studio is not a second opinion -- on X5 files it reproduces the
    # camera's own on-device stitch to 0.03 degrees -- so the residual degree
    # here is this renderer's and not a floor.
    #
    # ⚠️ It resolves what looked like two separate defects.  The "residual
    # wobble" recorded as a property of the OneR -- 10.8 degrees median -- was
    # this map, not the camera.  So was the 43-degree disagreement on the
    # 20-byte encoding, which is why no signed permutation ever reconciled it:
    # the search was scored against the same misleading proxy that chose the
    # wrong map in the first place.  history/08_IMU_AXES.md.
    "Insta360 OneR": ((-1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    # up_render = (-az, -ax, -ay) -- the same map as the X5, which is what the
    # two cameras sharing a product line would suggest.
    #
    # 🔴 Measured 2026-09-29 against Insta360 Studio's levelled exports, after
    # this camera had been REFUSED since it was first looked at.  38 stills over
    # five sessions: 0.83 degrees median, p90 1.67, every file within 5.  The
    # mounting-angle fallback it replaces leaves 46 to 53 degrees.
    #
    # ⚠️ The refusal was reasoned from the same calibration-zenith proxy that
    # gave the OneR a wrong map.  The recorded objection was that two sessions
    # which both render level give median readings 26 degrees apart, so "no
    # fixed mapping can level both".  The readings do differ -- that part was
    # observed correctly -- but it is how the camera was HELD on those days, not
    # how it reports.  Per session, against a real horizon, this one fixed map
    # gives 0.96, 0.68, 0.78 and 1.00 degrees.  history/08_IMU_AXES.md.
    "Insta360 X3": ((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
}


def gravity_up_nearby(path) -> tuple[float, float, float]:
    """Which way is up, from this file or from the frame beside it.

    🔴 Most stills carry no inertial record: 965 of 1,438 in one library, all
    OneR.  Every one of them sits in a burst or HDR bracket where another frame
    does — 100%, no exceptions — and the record is not merely *similar* between
    those frames, it is **identical**.  Measured on the 13 capture instants that
    carry three records apiece: the gravity vectors agree to 0.00 degrees, max
    0.00, over 36 frames.  The camera takes one reading per shutter press and
    writes it to some frames and not others.

    So this borrows bytes rather than interpolating an attitude, and it is why
    Insta360's own Studio levels these files while reading the record alone does
    not.  Scored against Studio's exports on 291 frames that carry no record:
    1.09 degrees median, p90 1.94, 98% within 5 — against 10.43 and 52.99 for
    the mounting-angle fallback.  ``history/08_IMU_AXES.md``.

    ⚠️ Unlike :func:`gravity_up` this reads the **directory**, not just the
    file.  Keep the two apart: the vendor contract is that a reader is handed a
    path and reports what is in it, and this deliberately does more.

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
            f"{path}: the inertial axis mapping for {model!r} has not been measured, "
            f"only {sorted(_AXES)}; levelling it would be a guess"
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
    axes = _AXES.get(model)
    if axes is None:
        raise FormatError(
            f"{path}: the inertial axis mapping for {model!r} has not been measured, "
            f"only {sorted(_AXES)}; levelling it would be a guess"
        )

    vector = gravity(path)
    length = sum(component * component for component in vector) ** 0.5
    if length < 0.5:
        raise FormatError(f"{path}: accelerometer reads {length:.3f} g, too little to be gravity")

    unit = [component / length for component in vector]
    return tuple(sum(row[i] * unit[i] for i in range(3)) for row in axes)
