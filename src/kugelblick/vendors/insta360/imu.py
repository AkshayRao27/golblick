"""Record ``0x0300`` -- the inertial log, and the gravity vector in it.

This is what makes levelling possible on a camera that embeds no stitch of its
own, which is most of them: the accelerometer says which way is down, and a
panorama that ignores it comes out at whatever angle the camera happened to be
held.  See ``docs/formats/insta360.md``.

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
that camera's stills), 6 have no trailer, and 2 carry a zero-length record.  So
an IMU-derived horizon serves about a third of the library, and any levelling
that has to work everywhere needs a second route.
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
    not the render's axes.  :func:`kugelblick.render.level` holds the rotation
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
#: rotation applied to the acceleration vector.
#:
#: 🔴 Measured for the X5 only, and it does **not** generalise: with the camera
#: upright an X5 reads gravity along -x and a OneR along +x, so applying the X5
#: mapping to a OneR would hang the panorama upside down.  An X3's median
#: reading falls between two axes and matches neither.  The measurement needs a
#: levelled reference to score against, and only the X5 embeds one -- see
#: ``docs/formats/insta360.md``.  Refusing here is the point: a guessed axis
#: mapping produces a confident, wrong horizon.
_AXES = {
    # up_render = (az, -ax, -ay).  Fitted against 24 solved rotations, then
    # replaced by the exact signed permutation, which scored better: 2.3
    # degrees median against the camera's own levelling, versus 4.0.
    "Insta360 X5": ((0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
}


def gravity_up(path) -> tuple[float, float, float]:
    """Which way is up, as a unit vector in the render's own frame.

    Feed it to :func:`kugelblick.render.level` to build the rotation, and that
    to :func:`kugelblick.render.equirectangular` as its ``orientation``.

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
