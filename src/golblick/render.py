"""Equirectangular projection from a dual-fisheye pair, and how to score it.

This is the only module that needs numpy, which is why it sits behind the
``render`` extra.  Everything else in the package stays dependency-free.

The geometry is built from the *equidistant* calibration model, the only one
every camera carries and the only one whose interior is confirmed.
``docs/formats/insta360-agent-notes.md`` (the format notes, below) has the
measurements under "Calibration".

Conventions the code relies on:

* Each lens maps angle from its axis to radius in its image circle,
  ``r = radius * theta / theta_max``, plus a measured per-model correction
  that is not in the file (:attr:`Lens.radial`).
* The two lenses sit back to back.  Each states its angles in its own frame,
  and lens 1's frame is lens 0's turned 180 degrees, so the relative spin is
  ``-(yaw0 + yaw1)`` modulo 180, not the difference.  The fourth and fifth
  values are small rotations about the lens's own x and y, in the same sense.
* The absolute yaw is the sensor's mounting angle in the body; rolling by
  ``90 - yaw`` lands the render in the body frame (:func:`body_orientation`).
* Image rows run downward while world Y runs up, so the azimuth is negated;
  without that the panorama comes out mirrored.

Not in the file, and so supplied or fitted: ``theta_max``, the angle the rim
corresponds to (:func:`fit_field_of_view`, :func:`pick_field_of_view` for lens
guards), and the camera's attitude when the shutter fired
(:func:`fit_orientation`, or the IMU).
"""

from __future__ import annotations

from dataclasses import dataclass


def _numpy():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised by the extra
        raise ImportError(
            "rendering needs numpy: install the 'render' extra"
        ) from exc
    return numpy


@dataclass(frozen=True)
class Lens:
    """One fisheye circle, in pixels of the actual image."""

    radius: float
    centre_x: float
    centre_y: float
    #: Rotation of the sensor within its own image circle, radians.
    spin: float = 0.0
    #: Small rotation about the lens's own x and y axes, radians -- the fourth
    #: and fifth calibration values.  Applied after lens 1's back-to-back flip,
    #: because that is the frame the camera states them in.
    tilt: tuple[float, float] = (0.0, 0.0)
    #: Correction to the equidistant model, degrees, sampled every
    #: :data:`RADIAL_STEP` degrees out from the axis: a direction at angle
    #: theta off the axis is recorded where the equidistant model would put
    #: ``theta + radial(theta)``.  Not in the file -- a vendor supplies it per
    #: camera model, measured, or leaves it empty for the plain model.
    radial: tuple[float, ...] = ()


#: Spacing of :attr:`Lens.radial`, degrees.
RADIAL_STEP = 2.0


def lenses_from_calibration(calibration, width: int, radial: tuple[float, ...] = ()):
    """Build the lens pair from an equidistant calibration string.

    ``radial`` is a measured correction to the equidistant model, applied to
    both lenses; see :attr:`Lens.radial`.  The file does not carry it.

    Only the relative spin between the lenses is used here, so lens 0 is taken
    as the reference and lens 1 carries the difference.  That renders in lens
    0's sensor frame, which is not the camera body's; :func:`body_orientation`
    reads the absolute yaw and supplies the rotation between the two.
    """
    numpy = _numpy()
    if len(calibration.lenses) != 2:
        raise ValueError(f"expected 2 lenses, got {len(calibration.lenses)}")

    scale = calibration.scale_for(width)
    yaws = [lens[5] for lens in calibration.lenses]
    # A SUM, not a difference: lens 1 faces the other way, so its yaw reads with
    # the opposite sign in lens 0's frame.  Modulo 180, signed the short way.
    # The difference is 0.44 degrees out on a OneR, along the whole seam.  See
    # the format notes, "Lens orientation differs between cameras — do not
    # assume 0/180".
    relative = (-(yaws[0] + yaws[1]) + 90.0) % 180.0 - 90.0

    built = []
    for index, (radius, cx, cy, tilt_x, tilt_y, _yaw) in enumerate(calibration.lenses):
        built.append(Lens(
            radius=radius * scale,
            centre_x=cx * scale,
            centre_y=cy * scale,
            spin=numpy.deg2rad(relative) if index == 1 else 0.0,
            tilt=(float(numpy.deg2rad(tilt_x)), float(numpy.deg2rad(tilt_y))),
            radial=tuple(radial),
        ))
    return tuple(built)


def _rays(width: int, height: int, rows=None):
    """Unit vectors for every pixel of an equirectangular frame, or of a range of its rows."""
    numpy = _numpy()
    lon = (numpy.arange(width) + 0.5) / width * 2 * numpy.pi - numpy.pi
    index = numpy.arange(height)[rows if rows is not None else slice(None)]
    lat = numpy.pi / 2 - (index + 0.5) / height * numpy.pi
    lon, lat = numpy.meshgrid(lon, lat)
    cos_lat = numpy.cos(lat)
    return numpy.stack(
        [cos_lat * numpy.sin(lon), numpy.sin(lat), cos_lat * numpy.cos(lon)], -1
    )


def _tilt_matrix(about_x: float, about_y: float):
    """Rotation by the vector (about_x, about_y, 0), radians, column convention."""
    numpy = _numpy()
    w = numpy.array([about_x, about_y, 0.0])
    angle = float(numpy.linalg.norm(w))
    if angle == 0.0:
        return numpy.eye(3)
    k = w / angle
    cross = numpy.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return numpy.eye(3) + numpy.sin(angle) * cross + (1 - numpy.cos(angle)) * cross @ cross


def _project(rays, lens: Lens, index: int, theta_max: float):
    """Where each ray lands in one lens, and how far off axis it is."""
    numpy = _numpy()
    x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
    if index == 1:
        # Lens 1 faces the other way: rotate 180 degrees about the vertical.
        x, z = -x, -z
    if lens.tilt != (0.0, 0.0):
        # In the lens's own frame, after the flip.  Rows are vectors, so this
        # is R.T applied to each ray: for an output direction, the lens ray
        # that the tilted lens actually recorded there.
        t = _tilt_matrix(*lens.tilt)
        x, y, z = (x * t[0, 0] + y * t[1, 0] + z * t[2, 0],
                   x * t[0, 1] + y * t[1, 1] + z * t[2, 1],
                   x * t[0, 2] + y * t[1, 2] + z * t[2, 2])

    theta = numpy.arccos(numpy.clip(z, -1, 1))
    if lens.radial:
        # Where the lens actually recorded this direction.  The returned angle
        # is the corrected one, so validity and the rim taper are judged
        # against the image circle; the hand-over does not move, because both
        # lenses share one increasing curve and so still match at the bisector.
        grid = numpy.arange(len(lens.radial)) * RADIAL_STEP
        theta = theta + numpy.deg2rad(
            numpy.interp(numpy.rad2deg(theta), grid, numpy.asarray(lens.radial)))
    phi = numpy.arctan2(y, x) - lens.spin
    r = lens.radius * theta / theta_max
    # Rows run downward while world Y runs up, hence the minus on sin.
    return lens.centre_x + r * numpy.cos(phi), lens.centre_y - r * numpy.sin(phi), theta


def _sample(image, u, v, valid):
    """Bilinear, because the projection lands between source pixels everywhere.

    Measured against nearest-neighbour in the format notes, "Sampling".

    ``u`` and ``v`` are in source-pixel index space, so the integer part is the
    texel and the fraction is the weight; there is no half-pixel offset to add.
    """
    numpy = _numpy()
    height, width = image.shape[:2]
    x0 = numpy.floor(u)
    y0 = numpy.floor(v)
    fx = (u - x0)[..., None].astype(numpy.float32)
    fy = (v - y0)[..., None].astype(numpy.float32)
    x0 = numpy.clip(x0.astype(numpy.int32), 0, width - 1)
    y0 = numpy.clip(y0.astype(numpy.int32), 0, height - 1)
    x1 = numpy.clip(x0 + 1, 0, width - 1)
    y1 = numpy.clip(y0 + 1, 0, height - 1)

    out = image[y0, x0].astype(numpy.float32)
    out *= (1.0 - fx) * (1.0 - fy)
    out += image[y0, x1] * (fx * (1.0 - fy))
    out += image[y1, x0] * ((1.0 - fx) * fy)
    out += image[y1, x1] * (fx * fy)
    out[~valid] = 0
    return out


#: Grid the seam is chosen on: azimuth columns by offset rows.  Finer buys
#: nothing measurable, and the PHP port, which decides from a small probe
#: render, needs enough samples per bin.  Format notes, "Routing the seam".
_SEAM_COLUMNS = 256
_SEAM_ROWS = 48

#: Do not route below this output width: a thinner grid picks a path by noise
#: (format notes, "Routing the seam").
_SEAM_MIN_WIDTH = 2048

#: Below this mean disagreement (0-255) the lenses already agree along the
#: bisector, so there is nothing to route around and the straight seam is the
#: better answer for being the simpler one.
_SEAM_FLOOR = 2.0

#: Route only for a material gain, not for a rounding difference.
_SEAM_MARGIN = 0.9


def _seam_cost(a, b, both, d, phi, room):
    """Mean |lensA - lensB| binned by (offset from the bisector, azimuth)."""
    numpy = _numpy()
    keep = both & (numpy.abs(d) < room)
    if keep.sum() < 1000:
        return None
    row = ((d[keep] + room) / (2 * room) * (_SEAM_ROWS - 1)).astype(numpy.int32)
    column = (((phi[keep] + numpy.pi) / (2 * numpy.pi) * _SEAM_COLUMNS)
              .astype(numpy.int32) % _SEAM_COLUMNS)
    flat = row * _SEAM_COLUMNS + column
    size = _SEAM_ROWS * _SEAM_COLUMNS
    difference = numpy.abs(a[keep] - b[keep])
    total = numpy.bincount(flat, weights=difference, minlength=size)
    count = numpy.bincount(flat, minlength=size)
    total = total.reshape(_SEAM_ROWS, _SEAM_COLUMNS)
    count = count.reshape(_SEAM_ROWS, _SEAM_COLUMNS)
    return numpy.where(count > 0, total / numpy.maximum(count, 1), numpy.inf)


def _widen(grid, feather, room):
    """Cost each candidate over the width the CROSS-FADE averages, not one row.

    Otherwise the search minimises a slice far thinner than the blend, so the
    path dodges a near object and the blend drags it straight back in.
    """
    numpy = _numpy()
    rows = grid.shape[0]
    step = 2 * room / (rows - 1)
    span = max(1, int(round(2 * feather / step)))
    finite = numpy.isfinite(grid)
    pad = span // 2
    def boxed(values):
        padded = numpy.pad(values, ((pad, span - 1 - pad), (0, 0)), mode="edge")
        stacked = numpy.cumsum(padded, axis=0)
        stacked = numpy.concatenate([numpy.zeros((1, grid.shape[1])), stacked])
        return stacked[span:] - stacked[:-span]
    total = boxed(numpy.where(finite, grid, 0.0))
    count = boxed(finite.astype(numpy.float64))
    widened = numpy.where(count > 0, total / numpy.maximum(count, 1e-9), numpy.inf)
    return numpy.where(finite, widened, numpy.inf)


def _cheapest_cycle(grid):
    """Minimum-cost closed path, one row per column, steps of at most one row.

    The path is cyclic because the azimuth wraps, and connected because a seam
    that jumps is a tear.  Two passes (a free start, then re-solved pinned to
    where that landed) rather than every start exactly, which the PHP port
    can't afford; both implementations run this same algorithm, and the format
    notes, "Routing the seam", measure what it gives up.
    """
    numpy = _numpy()
    rows, columns = grid.shape
    work = numpy.where(numpy.isfinite(grid), grid, 1e9)
    index = numpy.arange(rows)

    def sweep(initial):
        cost = initial.copy()
        back = numpy.zeros((columns, rows), numpy.int32)
        for column in range(1, columns):
            up = numpy.concatenate(([numpy.inf], cost[:-1]))
            down = numpy.concatenate((cost[1:], [numpy.inf]))
            stacked = numpy.stack([up, cost, down])
            choice = numpy.argmin(stacked, axis=0)
            cost = stacked[choice, index] + work[:, column]
            back[column] = index + (choice - 1)
        return cost, back

    def unwind(back, end):
        path = numpy.empty(columns, numpy.int32)
        path[-1] = end
        for column in range(columns - 1, 0, -1):
            path[column - 1] = back[column][path[column]]
        return path

    cost, back = sweep(work[:, 0])
    if not numpy.isfinite(cost).any():
        return None
    first = unwind(back, int(numpy.argmin(cost)))

    start = int(first[0])
    pinned = numpy.full(rows, numpy.inf)
    pinned[start] = work[start, 0]
    cost, back = sweep(pinned)
    ends = [e for e in (start - 1, start, start + 1)
            if 0 <= e < rows and numpy.isfinite(cost[e])]
    if not ends:
        return None
    return unwind(back, min(ends, key=lambda e: cost[e]))


def _seam_offset(a, b, both, d, phi, feather, half):
    """Where the two lenses should hand over, as an offset per azimuth.

    Returns ``None`` -- meaning hand over on the bisector -- whenever routing
    cannot be shown to beat it.
    """
    numpy = _numpy()
    columns = _seam_columns(a, b, both, d, phi, feather, half)
    if columns is None:
        return None
    position = ((phi + numpy.pi) / (2 * numpy.pi) * _SEAM_COLUMNS) % _SEAM_COLUMNS
    low = numpy.floor(position).astype(numpy.int32) % _SEAM_COLUMNS
    high = (low + 1) % _SEAM_COLUMNS
    fraction = position - numpy.floor(position)
    return columns[low] * (1 - fraction) + columns[high] * fraction


def _seam_columns(a, b, both, d, phi, feather, half):
    """:func:`_seam_offset` as :data:`_SEAM_COLUMNS` values round the lens axis, radians of ``d``.

    Column ``k`` is at azimuth ``-pi + 2 pi k / _SEAM_COLUMNS``, read linearly
    and wrapping, which is how a viewer that projects on the GPU takes it.
    """
    numpy = _numpy()
    room = half - 2 * feather
    if room <= 0:
        return None
    grid = _seam_cost(a, b, both, d, phi, room)
    if grid is None:
        return None
    widened = _widen(grid, feather, room)
    path = _cheapest_cycle(widened)
    if path is None:
        return None

    columns = numpy.arange(_SEAM_COLUMNS)
    middle = (_SEAM_ROWS - 1) // 2
    routed = widened[path, columns]
    straight = widened[middle, columns]
    routed = routed[numpy.isfinite(routed)]
    straight = straight[numpy.isfinite(straight)]
    if routed.size == 0 or straight.size == 0:
        return None

    # Needs both the floor and the MARGIN: a bare "is the route cheaper" can
    # never decline, because the bisector is one of the paths the search
    # minimises over.  Format notes, "Routing the seam".
    if straight.mean() < _SEAM_FLOOR:
        return None
    if routed.mean() >= _SEAM_MARGIN * straight.mean():
        return None

    # Smooth a little: the grid is coarse and a jagged seam is its own artefact.
    extended = numpy.concatenate([path[-8:], path, path[:8]]).astype(numpy.float64)
    smoothed = numpy.convolve(extended, numpy.ones(9) / 9, mode="same")[8:-8]
    return smoothed / (_SEAM_ROWS - 1) * (2 * room) - room


#: Parallax the depth search tries, degrees: how far apart the two lenses see a
#: point on the seam.  0 is the far scene; a point at distance r behind a
#: baseline b shows about b/r radians, so with the lenses 30 mm apart the last
#: level is about 15 cm.  Searching in parallax rather than distance means only
#: the baseline's DIRECTION is needed, never its length or unit.
DEPTH_LEVELS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 11.0)

#: The warp is full strength this close to the bisector and gone by the
#: second, degrees of ``d``: it bends single-lens content between them, so it
#: is kept to about the band the vendor's own stitcher reworks.
_DEPTH_INNER = 4.0
_DEPTH_OUTER = 12.0

#: How close to the bisector agreement is judged at each parallax, degrees.
_DEPTH_BAND = 3.0

#: Grey levels per degree of parallax change between neighbouring columns.
_DEPTH_JUMP = 0.65

#: A column leaves the far scene only to cut its own disagreement by this much.
_DEPTH_GAIN = 0.10

#: Narrowest stretch of seam, in columns of :data:`_SEAM_COLUMNS`, that keeps
#: a parallax of its own (about 11 degrees).
_DEPTH_RUN = 8

#: Grey at or above which a sample says nothing about alignment.
_NEAR_WHITE = 245.0

#: Steps of the ring the seam is chosen on: round the lens axis per column, and
#: across the band in degrees of ``d``.
_RING_PER_COLUMN = 2
_RING_STEP = 0.25


@dataclass(frozen=True)
class SeamPlan:
    """Where and how two lenses hand over, chosen once for a whole clip.

    ``direction`` is the unit vector from lens 0 to lens 1 in the camera frame.
    ``parallax`` holds degrees per column of :data:`_SEAM_COLUMNS` round the
    lens axis (see :data:`DEPTH_LEVELS`), and ``offset`` radians of ``d`` by
    which the hand-over moves off the bisector; either may be None.
    """

    direction: tuple[float, float, float]
    parallax: object = None
    offset: object = None


def _around(values, phi):
    """Per-column values read at azimuth ``phi``, linearly, wrapping."""
    numpy = _numpy()
    columns = len(values)
    position = ((phi + numpy.pi) / (2 * numpy.pi) * columns) % columns
    low = numpy.floor(position).astype(numpy.int32) % columns
    fraction = position - numpy.floor(position)
    return values[low] * (1 - fraction) + values[(low + 1) % columns] * fraction


def _depth_taper(d):
    numpy = _numpy()
    inner, outer = numpy.deg2rad(_DEPTH_INNER), numpy.deg2rad(_DEPTH_OUTER)
    return numpy.clip((outer - numpy.abs(d)) / (outer - inner), 0, 1)


def _aimed(rays, d, parallax, direction, index):
    """Lens ``index``'s ray for output rays aimed at a point with that parallax.

    A point at distance r from the midpoint of the lenses is seen by lens i
    along ``r*w + m - c_i``; scaled by 1/r that is ``w + (m - c_i)/r``, and
    ``|c_1 - c_0|/r`` is the parallax.  So lens 0 looks half the parallax along
    the baseline and lens 1 half against it, and at zero parallax both look
    along ``w``.  ``parallax`` is radians per ray, already tapered.
    """
    numpy = _numpy()
    sign = 0.5 if index == 0 else -0.5
    aimed = rays + (sign * parallax)[..., None] * numpy.asarray(direction, numpy.float64)
    return aimed / numpy.linalg.norm(aimed, axis=-1, keepdims=True)


def _ring(half):
    """Directions round the seam, evenly in azimuth and in ``d`` out to ``half``."""
    numpy = _numpy()
    phi = (numpy.arange(_SEAM_COLUMNS * _RING_PER_COLUMN) + 0.5) * (
        2 * numpy.pi / (_SEAM_COLUMNS * _RING_PER_COLUMN)) - numpy.pi
    steps = int(numpy.floor(numpy.rad2deg(half) / _RING_STEP))
    d = numpy.deg2rad(numpy.arange(-steps, steps + 1) * _RING_STEP)
    phi, d = numpy.meshgrid(phi, d)
    rays = numpy.stack([numpy.cos(d / 2) * numpy.cos(phi), numpy.cos(d / 2) * numpy.sin(phi),
                        -numpy.sin(d / 2)], axis=-1)
    return rays, d, phi


def _grey_pair(image, lenses, rays, d, theta_max, parallax=None, direction=None):
    """Both lenses' grey at ``rays``, aimed at ``parallax`` if given, and validity."""
    out = []
    for index, lens in enumerate(lenses):
        aimed = rays if parallax is None else _aimed(rays, d, parallax, direction, index)
        u, v, theta = _project(aimed, lens, index, theta_max)
        valid = theta <= theta_max
        p = _sample(image, u, v, valid)
        out.append((p[..., 0] * 0.299 + p[..., 1] * 0.587 + p[..., 2] * 0.114, valid))
    return out


def _mean_finite(grids):
    numpy = _numpy()
    stacked = numpy.stack(grids)
    finite = numpy.isfinite(stacked)
    total = numpy.where(finite, stacked, 0).sum(axis=0)
    count = finite.sum(axis=0)
    return numpy.where(count > 0, total / numpy.maximum(count, 1), numpy.inf)


def _parallax_cost(a, b, both, d, phi):
    """Mean |a - b| per column, within :data:`_DEPTH_BAND` of the bisector."""
    numpy = _numpy()
    keep = both & (numpy.abs(d) < numpy.deg2rad(_DEPTH_BAND)) & (a < _NEAR_WHITE) & (b < _NEAR_WHITE)
    column = (((phi[keep] + numpy.pi) / (2 * numpy.pi) * _SEAM_COLUMNS)
              .astype(numpy.int32) % _SEAM_COLUMNS)
    total = numpy.bincount(column, weights=numpy.abs(a[keep] - b[keep]), minlength=_SEAM_COLUMNS)
    count = numpy.bincount(column, minlength=_SEAM_COLUMNS)
    return numpy.where(count >= _RING_PER_COLUMN * 4, total / numpy.maximum(count, 1), numpy.inf)


def _cheapest_parallax(grid):
    """Parallax level per column: a cyclic path with a cost per degree of change.

    Unlike the routing path, any jump is allowed, because distance is
    discontinuous at the edge of a near subject.  Two guards, each against an
    artefact the disagreement score can't see:

    * A column still improving at the last parallax the overlap can measure has
      its subject in the blind zone, so only a minimum INSIDE the range counts.
    * Runs narrower than :data:`_DEPTH_RUN` columns are removed afterwards: a
      sun flare can halve the disagreement, and a near subject worth stitching
      for spans far more.

    Format notes, "Aiming the lenses at a parallax (video)".
    """
    numpy = _numpy()
    levels = numpy.asarray(DEPTH_LEVELS)
    rows, columns = grid.shape
    finite = numpy.isfinite(grid)
    work = numpy.where(finite, grid, 1e3)
    base = numpy.where(finite[0], grid[0], 0.0)
    work = work + _DEPTH_GAIN * base[None, :] * (levels[:, None] > 0)
    last = numpy.where(finite.any(axis=0), rows - 1 - numpy.argmax(finite[::-1], axis=0), 0)
    best = numpy.argmin(numpy.where(finite, grid, numpy.inf), axis=0)
    work[1:, (best == last) & (last > 0)] = 1e3
    step = _DEPTH_JUMP * numpy.abs(levels[:, None] - levels[None, :])

    def sweep(initial):
        cost = initial.copy()
        back = numpy.zeros((columns, rows), numpy.int32)
        for column in range(1, columns):
            total = cost[:, None] + step
            back[column] = numpy.argmin(total, axis=0)
            cost = total[back[column], numpy.arange(rows)] + work[:, column]
        return cost, back

    def unwind(back, end):
        path = numpy.empty(columns, numpy.int32)
        path[-1] = end
        for column in range(columns - 1, 0, -1):
            path[column - 1] = back[column][path[column]]
        return path

    # The same two-pass treatment of the wrap as _cheapest_cycle.
    cost, back = sweep(work[:, 0])
    start = int(unwind(back, int(numpy.argmin(cost)))[0])
    pinned = numpy.full(rows, numpy.inf)
    pinned[start] = work[start, 0]
    cost, back = sweep(pinned)
    path = unwind(back, int(numpy.argmin(cost + step[:, start])))

    # Grey-scale opening, cyclic: erode then dilate over the run length.
    run = _DEPTH_RUN
    index = numpy.arange(columns)
    eroded = path[(index[:, None] + numpy.arange(run)[None, :]) % columns].min(axis=1)
    return eroded[(index[:, None] - numpy.arange(run)[None, :]) % columns].max(axis=1)


def plan_seam(images, lenses, field_of_view, direction):
    """Choose one hand-over for a whole clip from a few of its frames, or None.

    Two moves, in this order, each chosen on the disagreement averaged over the
    frames.  First a parallax per azimuth, so a subject near the camera lines
    up across the seam instead of breaking: the cut cannot be routed round
    something wider than the overlap, like the body of whoever holds the
    camera.  Then the cut is routed, on the lenses as aimed, round what still
    disagrees -- which also moves it off a flare that only one lens has.

    One plan per clip because a video's tables are written once.  It pays
    where the near subject stays put relative to the camera, and has to
    decline where nothing does.

    The plan is chosen on every other frame and checked on the rest, and
    declined unless it clears routing's margin THERE: checked on the frames it
    was chosen on, a plan always looks good.

    A wrong field of view also shifts the lenses across the seam, so this will
    "line up" an angle error with a warp that bends straight lines; a parallax
    that is the same everywhere means check the angle.  Format notes, "Aiming
    the lenses at a parallax (video)" and "Field 53 says where the two lenses
    sit".

    ``images`` are lens pairs side by side, as for :func:`equirectangular`;
    ``direction`` is the baseline from lens 0 to lens 1 in any unit, or None
    if the camera does not say, in which case only the route is planned.
    """
    numpy = _numpy()
    if len(lenses) != 2 or len(images) < 2:
        return None
    theta_max = numpy.deg2rad(field_of_view / 2)
    feather = numpy.deg2rad(1.5)
    half = 2 * theta_max - numpy.pi
    room = half - 2 * feather
    if room <= 0:
        return None
    rays, d, phi = _ring(half)
    if direction is not None:
        direction = numpy.asarray(direction, numpy.float64)
        norm = float(numpy.linalg.norm(direction))
        direction = direction / norm if norm > 0 else None
    columns = numpy.arange(_SEAM_COLUMNS)
    middle = (_SEAM_ROWS - 1) // 2

    def aimed_by(profile):
        if profile is None:
            return None
        return numpy.deg2rad(_around(numpy.asarray(profile, numpy.float64), phi)) * _depth_taper(d)

    def routed(frames, profile):
        """The widened routing grid over ``frames``, lenses aimed by ``profile``."""
        grids = []
        for image in frames:
            (a, va), (b, vb) = _grey_pair(image, lenses, rays, d, theta_max, aimed_by(profile), direction)
            grid = _seam_cost(a, b, va & vb, d, phi, room)
            if grid is not None:
                grids.append(_widen(grid, feather, room))
        return _mean_finite(grids) if grids else None

    def ratio(grid, straight, path):
        along = grid[middle] if path is None else grid[path, columns]
        ok = numpy.isfinite(along) & numpy.isfinite(straight)
        return along[ok].mean() / straight[ok].mean() if ok.any() else None

    choose, check = images[0::2], images[1::2]

    profile = None
    if direction is not None:
        grids = []
        for image in choose:
            grid = numpy.full((len(DEPTH_LEVELS), _SEAM_COLUMNS), numpy.inf)
            for row, level in enumerate(DEPTH_LEVELS):
                aimed = numpy.full(d.shape, numpy.deg2rad(level)) * _depth_taper(d)
                (a, va), (b, vb) = _grey_pair(image, lenses, rays, d, theta_max, aimed, direction)
                grid[row] = _parallax_cost(a, b, va & vb, d, phi)
            grids.append(grid)
        chosen = numpy.asarray(DEPTH_LEVELS)[_cheapest_parallax(_mean_finite(grids))]
        if chosen.any():
            profile = chosen

    flat = routed(choose, None)
    if flat is None:
        return None
    best = None
    for candidate in ([None, profile] if profile is not None else [None]):
        grid = flat if candidate is None else routed(choose, candidate)
        if grid is None:
            continue
        for path in (None, _cheapest_cycle(grid)):
            if candidate is None and path is None:
                continue
            score = ratio(grid, flat[middle], path)
            if score is not None and (best is None or score < best[0]):
                best = (score, candidate, path)
    if best is None:
        return None
    _, profile, path = best

    # The same margin and floor as a photo's routing, applied to frames the
    # choice never saw.
    straight = routed(check, None)
    if straight is None:
        return None
    finite = straight[middle][numpy.isfinite(straight[middle])]
    if finite.size == 0 or finite.mean() < _SEAM_FLOOR:
        return None
    verified = ratio(straight if profile is None else routed(check, profile), straight[middle], path)
    if verified is None or verified >= _SEAM_MARGIN:
        return None

    # Aimed but not routed still hands over on d, as it was scored.
    offset = numpy.zeros(_SEAM_COLUMNS)
    if path is not None:
        extended = numpy.concatenate([path[-8:], path, path[:8]]).astype(numpy.float64)
        smoothed = numpy.convolve(extended, numpy.ones(9) / 9, mode="same")[8:-8]
        offset = smoothed / (_SEAM_ROWS - 1) * (2 * room) - room
    return SeamPlan(tuple(float(x) for x in direction) if profile is not None else (0.0, 0.0, 0.0),
                    profile, offset)


def equirectangular(image, lenses, size, field_of_view, feather_degrees=None,
                    orientation=None):
    """Project a dual-fisheye ``image`` into an equirectangular frame.

    ``field_of_view`` is the full angle each lens sees, in degrees; it is not
    carried in the file, so fit it with :func:`fit_field_of_view`.

    ``orientation`` is an optional 3x3 rotation, from :func:`rotation`, that
    turns the scene before it is written out -- this is how a levelled render
    is produced.  Without it the result's orientation is whatever the camera
    body happened to be doing, because the calibration fixes the lenses
    relative to each other and not relative to the world.  Recover the rotation
    with :func:`fit_orientation`, or from the gravity vector in the IMU record
    (:func:`level`).
    """
    numpy = _numpy()
    width, height = size
    theta_max = numpy.deg2rad(field_of_view / 2)
    if feather_degrees is None:
        # A few pixels, so the hand-over doesn't alias at small sizes, but never
        # under 1.5 degrees: hiding the brightness step between the lenses is a
        # question of angle, and a width in pixels alone shows as a hard line at
        # large sizes.  Format notes, "Cross-fade width".
        feather_degrees = min(3.0, max(1.5, 4.0 * 180.0 / height))
    feather = numpy.deg2rad(feather_degrees)
    rays = _rays(width, height)
    if orientation is not None:
        # Rays are row vectors, so ``rays @ R`` is ``R.T @ ray`` -- for each
        # output direction, the camera-frame direction that should land there.
        rays = rays @ numpy.asarray(orientation, numpy.float64)

    sampled = []
    thetas = []
    hemispheres = []
    for index, lens in enumerate(lenses):
        u, v, theta = _project(rays, lens, index, theta_max)
        valid = theta <= theta_max
        pixels = _sample(image, u, v, valid)
        sampled.append((pixels, valid))
        # Lenses that cannot see this direction must not drag the minimum down.
        # Past the rim rather than infinite, so that a direction no lens sees
        # subtracts finite numbers instead of producing a NaN to mask later.
        thetas.append(numpy.where(valid, theta, theta_max + feather))
        hemispheres.append((pixels, valid))

    # Cross-fade on how far each lens is from the BEST-PLACED lens, never on how
    # far it is from its own rim: a rim taper leaves both lenses at full weight
    # across the overlap, a 50/50 average in which near objects turn
    # transparent.  Format notes, "Blend weights".
    #
    # With exactly two lenses the hand-over can be ROUTED: parametrise it by
    # d = theta_0 - theta_1 against the azimuth about the lens axis, and put it
    # where the lenses already agree, so a near subject is walked round instead
    # of cut through.  Only at _SEAM_MIN_WIDTH or more; below that the seam
    # isn't visible anyway.  Format notes, "Routing the seam".
    offset = None
    if len(lenses) == 2 and width >= _SEAM_MIN_WIDTH:
        def grey(p):
            return p[..., 0] * 0.299 + p[..., 1] * 0.587 + p[..., 2] * 0.114

        both = sampled[0][1] & sampled[1][1]
        z = numpy.clip(rays[..., 2], -1, 1)
        offset = _seam_offset(
            grey(sampled[0][0]), grey(sampled[1][0]), both,
            2 * numpy.arccos(z) - numpy.pi,
            numpy.arctan2(rays[..., 1], rays[..., 0]),
            feather, 2 * theta_max - numpy.pi,
        )

    total = numpy.zeros((height, width, 3), numpy.float32)
    weights = numpy.zeros((height, width, 1), numpy.float32)
    if offset is not None:
        share = numpy.clip(
            (feather - ((2 * numpy.arccos(numpy.clip(rays[..., 2], -1, 1)) - numpy.pi)
                        - offset)) / (2 * feather), 0, 1)
        for index, ((pixels, valid), theta) in enumerate(zip(sampled, thetas, strict=True)):
            weight = (share if index == 0 else 1.0 - share)
            weight = weight * numpy.clip((theta_max - theta) / feather, 0, 1) * valid
            total += pixels * weight[..., None]
            weights += weight[..., None]
        blended = numpy.where(weights > 0, total / numpy.maximum(weights, 1e-6), 0)
        return blended.astype(numpy.float32), hemispheres

    closest = numpy.minimum.reduce(thetas)
    for (pixels, valid), theta in zip(sampled, thetas, strict=True):
        weight = numpy.clip((closest + feather - theta) / feather, 0, 1)
        # Keep the rim taper as well.  Inside the overlap it is already 1
        # wherever the cross-fade is non-zero, so it changes nothing there; it
        # only matters if a lens has no partner, where dropping straight to
        # black at the rim would be a hard edge.
        weight = weight * numpy.clip((theta_max - theta) / feather, 0, 1) * valid
        total += pixels * weight[..., None]
        weights += weight[..., None]

    blended = numpy.where(weights > 0, total / numpy.maximum(weights, 1e-6), 0)
    return blended.astype(numpy.float32), hemispheres


def seam_columns(image, lenses, field_of_view: float, orientation=None, width: int = _SEAM_MIN_WIDTH):
    """The routed seam :func:`equirectangular` would use, for a viewer that projects on the GPU.

    :data:`_SEAM_COLUMNS` offsets round the lens axis, radians of
    ``d = theta_0 - theta_1``, or None for the bisector.  Decided on a
    ``width``-wide render, as :func:`equirectangular` decides it at that
    size: the grid needs at least :data:`_SEAM_MIN_WIDTH` to choose reliably.
    """
    numpy = _numpy()
    height = width // 2
    theta_max = numpy.deg2rad(field_of_view / 2)
    feather = numpy.deg2rad(min(3.0, max(1.5, 4.0 * 180.0 / height)))
    rays = _rays(width, height)
    if orientation is not None:
        rays = rays @ numpy.asarray(orientation, numpy.float64)
    grey = []
    for index, lens in enumerate(lenses):
        u, v, theta = _project(rays, lens, index, theta_max)
        valid = theta <= theta_max
        pixels = _sample(image, u, v, valid)
        grey.append((pixels[..., 0] * 0.299 + pixels[..., 1] * 0.587 + pixels[..., 2] * 0.114, valid))
    z = numpy.clip(rays[..., 2], -1, 1)
    return _seam_columns(grey[0][0], grey[1][0], grey[0][1] & grey[1][1], 2 * numpy.arccos(z) - numpy.pi,
                         numpy.arctan2(rays[..., 1], rays[..., 0]), feather, 2 * theta_max - numpy.pi)


def remap_tables(lenses, size, field_of_view, orientation=None, lens_size=None, plan=None,
                 feather_height=None, rows=None):
    """Where each output pixel comes from, for a video renderer that remaps every frame.

    A video is the same projection applied to every frame, so it is computed
    once, as tables a remapping filter (ffmpeg's ``remap``) can apply, and the
    frames never pass through Python.  Returns ``(maps, share)``: ``maps`` is
    one ``(x, y, valid)`` per lens, with ``x`` and ``y`` in that lens's OWN
    frame, ``lens_size`` square (the lenses of a OneR or X3 video are separate
    streams, not halves of one frame), and ``share`` is how much of each output
    pixel comes from lens 1, 0 to 1.

    The hand-over is the cross-fade about the bisector unless ``plan``, from
    :func:`plan_seam`, says otherwise: a seam chosen per frame would have to be
    re-chosen as the content moves, so a video gets one plan for the whole clip.
    ``lenses`` come from :func:`lenses_from_calibration` at twice
    ``lens_size``, as if the lenses sat side by side.  ``feather_height``
    sets the cross-fade as for an output that tall, so a table at a smaller
    size hands over where the full-size one does.  ``rows``, a slice, gives
    only those rows of the tables, the same values as the whole: every pixel
    depends on its own direction alone, and a band small enough to stay in
    the processor's cache is several times faster per pixel.
    """
    numpy = _numpy()
    width, height = size
    theta_max = numpy.deg2rad(field_of_view / 2)
    feather = numpy.deg2rad(min(3.0, max(1.5, 4.0 * 180.0 / (feather_height or height))))
    rays = _rays(width, height, rows)
    if orientation is not None:
        rays = rays @ numpy.asarray(orientation, numpy.float64)
    if lens_size is None:
        lens_size = int(round(lenses[0].centre_x * 2))

    # The plan is in the camera frame, where d and the azimuth are measured.
    z = numpy.clip(rays[..., 2], -1, 1)
    d = 2 * numpy.arccos(z) - numpy.pi
    phi = numpy.arctan2(rays[..., 1], rays[..., 0])
    aimed = None
    if plan is not None and plan.parallax is not None:
        aimed = numpy.deg2rad(_around(numpy.asarray(plan.parallax, numpy.float64), phi)) * _depth_taper(d)

    maps, thetas = [], []
    for index, lens in enumerate(lenses):
        looking = rays if aimed is None else _aimed(rays, d, aimed, plan.direction, index)
        u, v, theta = _project(looking, lens, index, theta_max)
        valid = theta <= theta_max
        maps.append((u - index * lens_size, v, valid))
        thetas.append(numpy.where(valid, theta, theta_max + feather))

    if plan is not None and plan.offset is not None:
        # The routed hand-over, weighted exactly as a photo's routed seam is.
        offset = _around(numpy.asarray(plan.offset, numpy.float64), phi)
        to_first = numpy.clip((feather - (d - offset)) / (2 * feather), 0, 1)
        weights = [(to_first if index == 0 else 1.0 - to_first)
                   * numpy.clip((theta_max - theta) / feather, 0, 1) * valid
                   for index, (theta, (_, _, valid)) in enumerate(zip(thetas, maps, strict=True))]
        total = weights[0] + weights[1]
        share = numpy.where(total > 0, weights[1] / numpy.maximum(total, 1e-9), 0.0)
        return maps, share

    closest = numpy.minimum.reduce(thetas)
    weights = [numpy.clip((closest + feather - theta) / feather, 0, 1)
               * numpy.clip((theta_max - theta) / feather, 0, 1) * valid
               for theta, (_, _, valid) in zip(thetas, maps, strict=True)]
    total = weights[0] + weights[1]
    share = numpy.where(total > 0, weights[1] / numpy.maximum(total, 1e-9), 0.0)
    return maps, share


#: The lens balance's seam strip: samples round the seam and across the band
#: both lenses see, and the rungs of its ladder of correction weights.  The
#: Nextcloud app's RemapTables uses the same numbers.
STRIP_AROUND = 720
STRIP_ACROSS = 16
LADDER = 64

#: How far from the seam the balance correction reaches before it fades to nothing, degrees.
BALANCE_REACH = 60.0


def lens_size_for(lenses, native: int, width: int, field_of_view: float) -> int:
    """How big to scale each lens before remapping to ``width``.

    Matched to the output's angular density with 15% to spare, as the
    Nextcloud app does: more is aliasing that shimmers in motion, less is
    blur.  ``lenses`` at twice ``native``, as :func:`remap_tables` takes them.
    """
    wanted = 1.15 * (width / 360.0) * (field_of_view / 2.0) / lenses[0].radius * native
    size = int(min(native, -(-wanted // 1)))
    return max(64, size + size % 2)


def balance_strips(lenses, lens_size: int, field_of_view: float):
    """Where each lens sees a strip that runs once round the seam.

    The camera leaves a video's lenses unmatched, and not by one factor, so
    the renderer compares them where both see the same thing and evens them
    out from there; the Nextcloud app's ``RemapTables::writeBalance`` has the
    reasoning.  These are fixed in the camera's frame, whatever the output's
    orientation: ``s0x``, ``s0y``, ``s1x``, ``s1y`` as ``STRIP_ACROSS`` by
    ``STRIP_AROUND`` arrays of whole lens pixels.
    """
    numpy = _numpy()
    band = field_of_view / 2 - 91.0   # a degree inside each rim
    if band <= 0:
        raise ValueError("the lenses do not overlap, so there is nothing to compare")
    across = numpy.deg2rad(90.0 - band + (numpy.arange(STRIP_ACROSS) + 0.5) / STRIP_ACROSS * 2.0 * band)
    around = 2.0 * numpy.pi * (numpy.arange(STRIP_AROUND) + 0.5) / STRIP_AROUND
    polar, azimuth = numpy.meshgrid(across, around, indexing="ij")
    rays = numpy.stack([numpy.sin(polar) * numpy.cos(azimuth), numpy.sin(polar) * numpy.sin(azimuth),
                        numpy.cos(polar)], -1)
    theta_max = numpy.deg2rad(field_of_view / 2)
    strips = {}
    for index, lens in enumerate(lenses):
        u, v, _ = _project(rays, lens, index, theta_max)
        last = lens_size - 1
        strips[f"s{index}x"] = numpy.clip(numpy.rint(u - index * lens_size), 0, last).astype(numpy.uint16)
        strips[f"s{index}y"] = numpy.clip(numpy.rint(v), 0, last).astype(numpy.uint16)
    return strips


def balance_field(lenses, width: int, field_of_view: float, orientation=None, lens_size=None, plan=None):
    """For each pixel of a quarter-size output, which point of the strip it is level with, and how much.

    Returns ``(fx, fy)``: the strip column round the seam, and the ladder rung
    (``LADDER`` of them, from -1 to 1) that carries the correction's weight
    there, which fades from the seam to nothing ``BALANCE_REACH`` degrees in
    and changes sign with the hand-over: one lens moves up as the other moves
    down.  Unlike the strips this moves with ``orientation``.
    """
    numpy = _numpy()
    field_width = width // 4
    field_height = field_width // 2
    rays = _rays(field_width, field_height)
    if orientation is not None:
        rays = rays @ numpy.asarray(orientation, numpy.float64)
    azimuth = numpy.arctan2(rays[..., 1], rays[..., 0]) % (2 * numpy.pi)
    fx = numpy.minimum(STRIP_AROUND - 1, numpy.floor(azimuth / (2 * numpy.pi) * STRIP_AROUND))
    polar = numpy.arccos(numpy.clip(rays[..., 2], -1, 1))
    fade = numpy.maximum(0.0, 1.0 - numpy.abs(polar - numpy.pi / 2) / numpy.deg2rad(BALANCE_REACH))
    _, share = remap_tables(lenses, (field_width, field_height), field_of_view, orientation, lens_size, plan,
                            feather_height=width // 2)
    weight = fade * (1.0 - 2.0 * share)
    fy = numpy.clip(numpy.rint((weight + 1.0) / 2.0 * (LADDER - 1)), 0, LADDER - 1)
    return fx.astype(numpy.uint16), fy.astype(numpy.uint16)


def overlap_agreement(hemispheres):
    """How well the two lenses agree where both of them see the scene.

    This is the accuracy harness for cameras that embed no stitch of their own,
    which is most of them: the lenses see past 180 degrees, so there is a band
    where both observe the same thing, and a correct projection makes the two
    views of it coincide.  Every file carries this evidence.

    Returns Pearson correlation over the overlap band, or None if the lenses do
    not overlap: 0.75 to 0.90 on correctly projected stills, about 0.02 under a
    wrong rotation convention.

    Blind spots: it compares the lenses to each other, so it can't see the
    absolute orientation (a world rotation about the lens axis is +a in one
    lens and -a in the other), a mirror, or an error both lenses share.  And it
    is dominated by large-scale brightness, so it must not rank files by
    stitch quality.  Format notes, "Scoring without a reference".
    """
    numpy = _numpy()
    (pixels_a, valid_a), (pixels_b, valid_b) = hemispheres
    # For a back-to-back pair theta_b is about 180 degrees minus theta_a, so
    # "both lenses valid" is already exactly the overlap band.
    both = valid_a & valid_b
    if both.sum() < 1000:
        return None

    def grey(rgb):
        return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114

    a = grey(pixels_a)[both]
    b = grey(pixels_b)[both]
    a = a - a.mean()
    b = b - b.mean()
    denominator = numpy.sqrt((a * a).sum() * (b * b).sum())
    if denominator == 0:
        return None
    return float((a * b).sum() / denominator)


def fit_field_of_view(image, lenses, candidates=None, size=(1024, 512)):
    """Recover the rim angle by scoring, since the file does not carry it.

    Returns ``(best_degrees, [(degrees, score), ...])``.  Scoring at a small
    output size is enough: the optimum is broad and this runs many renders.
    """
    if candidates is None:
        candidates = range(186, 205, 2)

    scored = []
    for degrees in candidates:
        _, hemispheres = equirectangular(image, lenses, size, degrees)
        score = overlap_agreement(hemispheres)
        if score is not None:
            scored.append((float(degrees), score))
    if not scored:
        raise ValueError("no candidate field of view produced an overlap")
    best = max(scored, key=lambda pair: pair[1])
    return best[0], scored


#: How much better one field of view has to make the lenses agree before it is
#: chosen over the other.  See :func:`pick_field_of_view`.
PICK_MARGIN = 0.15


#: The ring :func:`_band_disagreement` samples: directions round the lens
#: axis, and offsets across the bisector within this many degrees of ``d``.
BAND_AROUND = 720
BAND_ACROSS = 13
BAND_DEGREES = 6.0


def _band_disagreement(image, lenses, field_of_view):
    """Mean |lens 0 - lens 1| in grey over a ring about the bisector.

    Sampled evenly round the lens axis and across the band, so every part of
    the seam counts the same; an equirectangular grid would crowd samples where
    the seam crosses its poles.  ``d = theta_0 - theta_1`` as in the seam
    routing, so a direction at ``d`` is ``-sin(d/2)`` along the lens axis.
    """
    numpy = _numpy()
    phi = numpy.arange(BAND_AROUND) * (2 * numpy.pi / BAND_AROUND)
    d = numpy.deg2rad(numpy.linspace(-BAND_DEGREES, BAND_DEGREES, BAND_ACROSS))
    phi, d = numpy.meshgrid(phi, d)
    rays = numpy.stack([numpy.cos(d / 2) * numpy.cos(phi), numpy.cos(d / 2) * numpy.sin(phi),
                        -numpy.sin(d / 2)], axis=-1)
    theta_max = numpy.deg2rad(field_of_view / 2)
    sampled = []
    for index, lens in enumerate(lenses):
        u, v, theta = _project(rays, lens, index, theta_max)
        valid = theta <= theta_max
        sampled.append((_sample(image, u, v, valid).mean(axis=-1), valid))
    both = sampled[0][1] & sampled[1][1]
    if both.sum() < both.size // 2:
        return None
    return float(numpy.abs(sampled[0][0] - sampled[1][0])[both].mean())


def pick_field_of_view(images, lenses, candidates, margin=PICK_MARGIN):
    """Which of two fields of view the lenses agree on, or None if neither clearly.

    For a choice between known states rather than a free fit -- a lens with or
    without a clip-on guard, which narrows what it sees by a measured factor.
    A wrong angle pulls the two lenses' copies of the overlap apart, so the
    right one leaves them agreeing better.  ``images`` are one or more lens
    pairs from the same file (frames of a video), scored at both candidates;
    the median ratio decides, and it has to clear ``margin`` either way.

    Lens agreement also rewards an angle that suits a near subject, which is
    why this picks between two values rather than fitting one: a free fit
    wanders with the scene.  Returns the chosen candidate, or None, and the
    caller then falls back to its default.
    """
    numpy = _numpy()
    first, second = candidates
    ratios = []
    for image in images:
        a = _band_disagreement(image, lenses, first)
        b = _band_disagreement(image, lenses, second)
        if a is not None and b is not None and b > 0:
            ratios.append(a / b)
    if not ratios:
        return None
    ratio = float(numpy.median(ratios))
    if ratio < 1.0 - margin:
        return first
    if ratio > 1.0 / (1.0 - margin):
        return second
    return None


def face(orientation, forward):
    """Turn ``orientation`` about the vertical so ``forward`` opens the panorama.

    ``forward`` is a direction in the render's own frame, such as a vendor's
    ``PHOTO_FORWARD``; afterwards its projection onto the horizon sits at the
    middle column, where a viewer starts.  Only the heading changes, so a
    level panorama stays level.  A ``forward`` within about 11 degrees of
    straight up or down has no reliable heading, and the orientation comes
    back unchanged.
    """
    numpy = _numpy()
    matrix = numpy.asarray(orientation, numpy.float64)
    # Rays are row vectors put through the orientation, so the world direction
    # of a render-frame vector f is matrix @ f.
    x, _, z = matrix @ numpy.asarray(forward, numpy.float64)
    if numpy.hypot(x, z) < 0.2:
        return matrix
    heading = numpy.arctan2(x, z)
    c, s = numpy.cos(heading), numpy.sin(heading)
    turn = numpy.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
    return turn @ matrix


def rotation(yaw: float, pitch: float, roll: float):
    """A rotation of the scene, in degrees, as ``Ry(yaw) @ Rx(pitch) @ Rz(roll)``.

    That order is not arbitrary.  Yaw is separable -- about the vertical axis it
    is exactly a horizontal shift of an equirectangular frame -- so putting it
    outermost lets :func:`fit_orientation` solve it by cross-correlation and
    search only the other two.
    """
    numpy = _numpy()
    y, p, r = numpy.deg2rad([yaw, pitch, roll])
    cy, sy, cp, sp, cr, sr = (numpy.cos(y), numpy.sin(y), numpy.cos(p),
                              numpy.sin(p), numpy.cos(r), numpy.sin(r))
    ry = numpy.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = numpy.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    rz = numpy.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return ry @ rx @ rz


def rotate(image, matrix):
    """Turn an existing equirectangular frame by ``matrix``, bilinearly.

    Equivalent to re-rendering with ``orientation=matrix``, and much cheaper,
    because it resamples a small panorama instead of a 70-megapixel fisheye
    pair.  :func:`fit_orientation` leans on that; a final render should still
    go back to the source, since this costs one resampling.
    """
    numpy = _numpy()
    height, width = image.shape[:2]
    directions = _rays(width, height) @ numpy.asarray(matrix, numpy.float64)
    lon = numpy.arctan2(directions[..., 0], directions[..., 2])
    lat = numpy.arcsin(numpy.clip(directions[..., 1], -1, 1))

    x = (lon + numpy.pi) / (2 * numpy.pi) * width - 0.5
    y = (numpy.pi / 2 - lat) / numpy.pi * height - 0.5
    x0 = numpy.floor(x).astype(numpy.int64)
    y0 = numpy.floor(y).astype(numpy.int64)
    fx, fy = x - x0, y - y0
    if image.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    # Longitude wraps; latitude does not.
    left, right = x0 % width, (x0 + 1) % width
    top, bottom = numpy.clip(y0, 0, height - 1), numpy.clip(y0 + 1, 0, height - 1)

    upper = image[top, left] * (1 - fx) + image[top, right] * fx
    lower = image[bottom, left] * (1 - fx) + image[bottom, right] * fx
    return (upper * (1 - fy) + lower * fy).astype(numpy.float32)


def _grey(image):
    numpy = _numpy()
    image = numpy.asarray(image, numpy.float32)
    if image.ndim == 2:
        return image
    return image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114


def _centred(values, weight):
    return (values - (values * weight).sum() / weight.sum()) * weight


def _correlate_yaw(turned, reference, weight):
    """Best horizontal shift of ``turned`` onto ``reference``, in degrees.

    A yaw is a horizontal shift and nothing else, so one FFT per candidate
    tilt replaces a whole third axis of the search.
    """
    numpy = _numpy()
    width = turned.shape[1]
    a, b = _centred(turned, weight), _centred(reference, weight)
    spectrum = numpy.fft.rfft(b, axis=1) * numpy.conj(numpy.fft.rfft(a, axis=1))
    correlation = numpy.fft.irfft(spectrum, n=width, axis=1).sum(0)
    shift = int(numpy.argmax(correlation))
    denominator = numpy.sqrt((a * a).sum() * (b * b).sum())
    if denominator == 0:
        return 0.0, 0.0
    return shift / width * 360.0, float(correlation[shift] / denominator)


def fit_orientation(image, reference, coarse_degrees=10.0, seed=None):
    """Recover the rotation that puts ``image`` into ``reference``'s frame.

    Both arguments are equirectangular frames of the same size and scene: the
    render to be levelled, and something already levelled to level it against.
    On an X5 that reference is the camera's own stitch, record ``0x0200``.

    Returns ``((yaw, pitch, roll), score)`` in degrees, where ``score`` is the
    correlation after alignment.  Feed the angles to :func:`rotation`.

    Only the X5 embeds a levelled reference; a OneR or X3 embeds the fisheye
    pair, so for those the rotation has to come from the IMU.

    ``seed`` skips the coarse grid and refines around a known answer, which is
    how a cheap low-resolution pass hands off to an accurate one.
    """
    numpy = _numpy()
    a, b = _grey(image), _grey(reference)
    if a.shape != b.shape:
        raise ValueError(f"frames differ in size: {a.shape} vs {b.shape}")
    # Score only where both frames have something to say: our render is blank
    # past the lens rim, and the camera paints out its own nadir.
    weight = ((a > 2) & (b > 2)).astype(numpy.float32)
    if weight.sum() < 1000:
        raise ValueError("frames have too little in common to align")

    # Refuse a frame with no structure rather than return the angles that
    # happen to score highest on noise: an all-black exposure reads 0.3 to 0.6
    # grey levels of deviation where a real frame reads 50 to 65.
    overlap = weight.astype(bool)
    if a[overlap].std() < 2.0 or b[overlap].std() < 2.0:
        raise ValueError("frames carry no structure to align: is one of them blank?")

    best = (0.0, 0.0, 0.0, -2.0)
    step = coarse_degrees
    if seed is None:
        for pitch in numpy.arange(-90.0, 90.1, step):
            for roll in numpy.arange(-180.0, 180.0, step):
                turned = rotate(a, rotation(0.0, pitch, roll))
                yaw, score = _correlate_yaw(turned, b, weight)
                if score > best[3]:
                    best = (yaw, float(pitch), float(roll), score)
    else:
        best = (float(seed[0]), float(seed[1]), float(seed[2]), -2.0)
        step = 2.0

    # Three quartering passes take the grid from 10 degrees to under 0.2.
    for _ in range(3):
        step /= 4
        _, pitch0, roll0, _ = best
        for pitch in numpy.arange(pitch0 - 2 * step, pitch0 + 2.01 * step, step):
            for roll in numpy.arange(roll0 - 2 * step, roll0 + 2.01 * step, step):
                turned = rotate(a, rotation(0.0, pitch, roll))
                yaw, score = _correlate_yaw(turned, b, weight)
                if score > best[3]:
                    best = (yaw, float(pitch), float(roll), score)

    yaw, pitch, roll, score = best
    return (yaw, pitch, roll), score


#: Below this, an alignment to a reference is declined rather than used.  Real
#: X5 renders against their own stitch score 0.78 to 0.86; a frame aligned to
#: an unrelated scene scores near 0.  ``test_render`` checks the decline fires.
REFERENCE_MIN_SCORE = 0.5


def orientation_from_reference(image, lenses, field_of_view, reference, start=None):
    """Level a render by aligning it to a panorama that is already level.

    On an X5 the reference is the camera's own stitch, which the camera
    levelled itself.  That is ground truth, so it beats the inertial record,
    whose median can be badly wrong when the record is long (format notes,
    "Route 1 — solve the rotation against the camera's own stitch").  It also fixes which way the panorama faces.

    ``reference`` is an equirectangular frame, any even 2:1 size; 512x256 is
    plenty, as the result is a rotation, not pixels.  ``start`` is the
    orientation to render from before aligning (a gravity or calibration
    guess); the search is global, so it only has to be a rotation.

    Returns ``(orientation, score)``.  Raises ``ValueError`` if the frames
    cannot be aligned or agree less than :data:`REFERENCE_MIN_SCORE`, so the
    caller falls back to another route rather than trusting a bad fit.

    The correction composes on the LEFT, ``rotation(...) @ start``; the other
    orders were measured and don't align.
    """
    numpy = _numpy()
    reference = numpy.asarray(reference, numpy.float32)
    height, width = reference.shape[:2]
    if width != 2 * height or height % 2:
        raise ValueError(f"reference must be an even 2:1 frame, not {width}x{height}")
    start = numpy.eye(3) if start is None else numpy.asarray(start, numpy.float64)

    pixels, _ = equirectangular(image, lenses, (width, height), field_of_view, orientation=start)

    # The global search runs on frames halved again, which is where its cost
    # is; the full-size pass only refines around the answer.
    def halve(frame):
        frame = numpy.asarray(frame, numpy.float32)
        return frame.reshape(height // 2, 2, width // 2, 2, -1).mean(axis=(1, 3))

    angles, _ = fit_orientation(halve(pixels), halve(reference))
    angles, score = fit_orientation(pixels, reference, seed=angles)
    if score < REFERENCE_MIN_SCORE:
        raise ValueError(f"the render agrees with the reference only {score:.2f}, below {REFERENCE_MIN_SCORE}")
    return rotation(*angles) @ start, score


def body_orientation(calibration):
    """Rotation putting a render into the camera-body frame, from the calibration.

    The cheapest levelling there is: it needs no IMU and no reference stitch,
    so unlike :func:`fit_orientation` and :func:`level` it works on every file.
    What it fixes is the sensor's mounting angle, which is a constant of the
    camera body -- so a shot taken with the camera genuinely tilted is still
    tilted afterwards.  Compose it with :func:`level` when a gravity vector is
    also available.

    See :attr:`~golblick.vendors.insta360.calibration.Calibration.body_roll`
    for what is measured and what is fitted.
    """
    return rotation(0.0, 0.0, calibration.body_roll)


def level(up, yaw: float = 0.0):
    """Rotation that lifts ``up`` to the top of the frame.

    ``up`` is which way is up expressed in the render's own frame -- from
    :func:`golblick.vendors.insta360.imu.gravity_up`, or from the ``pitch``
    and ``roll`` that :func:`fit_orientation` solved.  Pass the result to
    :func:`equirectangular` as its ``orientation``.

    The rotation is the shortest one that does the job, so it adds no spin of
    its own; ``yaw`` then turns the levelled panorama about the vertical.
    Which way it should face is a separate question that gravity cannot answer.
    Matching an X5's own stitch takes ``yaw=180`` (format notes, "Route 1 — solve the
    rotation against the camera's own stitch").
    For any camera, :func:`face` turns it to the vendor's measured forward.
    """
    numpy = _numpy()
    vector = numpy.asarray(up, numpy.float64)
    norm = numpy.linalg.norm(vector)
    if norm < 1e-9:
        raise ValueError("up vector has no direction")
    vector = vector / norm

    target = numpy.array([0.0, 1.0, 0.0])
    axis = numpy.cross(vector, target)
    sine = numpy.linalg.norm(axis)
    cosine = float(vector @ target)
    if sine < 1e-9:
        # Already vertical, one way or the other.
        upright = numpy.eye(3) if cosine > 0 else numpy.diag([1.0, -1.0, -1.0])
    else:
        cross = numpy.array([[0.0, -axis[2], axis[1]],
                             [axis[2], 0.0, -axis[0]],
                             [-axis[1], axis[0], 0.0]])
        upright = numpy.eye(3) + cross + cross @ cross * ((1 - cosine) / sine ** 2)
    return rotation(yaw, 0.0, 0.0) @ upright
