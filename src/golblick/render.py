"""Equirectangular projection from a dual-fisheye pair, and how to score it.

This is the only module that needs numpy, which is why it sits behind the
``render`` extra.  Everything else in the package stays dependency-free.

WHAT IS MEASURED, AND WHAT IS NOT
---------------------------------
The geometry here is built from the *equidistant* calibration model, because it
is the only one every camera carries and the only one whose interior is
confirmed.  See ``docs/formats/insta360-agent-notes.md``.

Confirmed by measurement across three cameras:

* Each lens maps angle from its axis nearly linearly to radius in its image
  circle, ``r = radius * theta / theta_max`` -- the equidistant model.  Nearly:
  measured against the vendor's own stitch, a OneR departs from it by up to
  1.45 degrees and an X3 by up to 1.75, the same curve in every scene.  That
  curve is not in the file; a vendor supplies it per camera model, and
  :attr:`Lens.radial` applies it.
* The two lenses sit back to back, and the stored yaw is the sensor's rotation
  *within* its image circle, not the direction the lens points.  Each lens
  states its angles in its **own** frame, and lens 1's frame is lens 0's turned
  180 degrees, which reverses the sense of a rotation about the lens axis.  So
  the relative spin is ``-(yaw0 + yaw1)`` modulo 180 -- not the difference.
  Measured against the vendor's own stitch on all three cameras, to within
  0.04 degrees.
* The fourth and fifth values are small rotations about the lens's own x and y
  axes, in the same own-frame sense.  Confirmed on both axes on a OneR against
  the vendor's stitch; on an X3 and X5 only about x, with an unexplained
  ~0.3 degree residual about y that the stored values do not predict.
* The *absolute* yaw is the sensor's mounting angle in the camera body, and it
  is a constant of the body -- zero spread over 1,409 files from three of them.
  Rolling the render by ``90 - yaw`` lands it in the body frame, which levels a
  OneR that would otherwise come out 90 degrees on its side.  See
  :func:`body_orientation`.
* Image rows run downward while world Y runs up, so the azimuth is negated.
  Without that the panorama comes out mirrored.

⚠️ **Not** established, and therefore not applied:

* ``theta_max``, the angle the image circle's rim corresponds to.  It is not in
  the file.  :func:`fit_field_of_view` recovers it by scoring, and it differs
  per camera (194 degrees on an X5 and a OneR, 192 on an X3).
* The camera's attitude when the shutter fired.  :func:`body_orientation`
  removes the mounting angle, but a camera that was genuinely tilted stays
  tilted; that needs :func:`fit_orientation` or the IMU.  See
  :func:`overlap_agreement` for why the projection alone cannot tell.
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
    # 🔴 A SUM, not a difference.  Each lens states its yaw in its own frame,
    # and lens 1 faces the other way, so its rotation about the shared axis
    # reads with the opposite sign in lens 0's frame.  Modulo 180, signed the
    # short way.  The difference, used until 2026-09-30, was 0.44 degrees out
    # on a OneR -- about 5 px at 4096 wide, along the whole seam -- and broke
    # every horizon that crossed it.  Measured against the vendor's stitch:
    # OneR -1.328 (sum -1.328, difference -0.892), X3 and X5 within 0.04.
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


def _rays(width: int, height: int):
    """Unit vectors for every pixel of an equirectangular frame."""
    numpy = _numpy()
    lon = (numpy.arange(width) + 0.5) / width * 2 * numpy.pi - numpy.pi
    lat = numpy.pi / 2 - (numpy.arange(height) + 0.5) / height * numpy.pi
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

    Nearest-neighbour was measurably the larger of the two resolution losses.
    Scored against a 3x render box-downsampled to the target -- which is what
    the pixels ought to be, and the comparison to make, since high-frequency
    energy would reward nearest-neighbour for its own aliasing -- the RMSE at
    2048 falls from 5.28 to 3.26.  That is 62 per cent of what quadrupling the
    pixel count buys, for none of the pixels.

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
#: nothing measurable -- 512x64 scores 28% and 192x32 scores 25% -- and it has
#: to stay coarse enough that the PHP port, which decides the seam from a small
#: probe render rather than the full frame, gets enough samples per bin to fill
#: it.  At 512x64 the port saw about 0.5 samples per bin and declined outright.
_SEAM_COLUMNS = 256
_SEAM_ROWS = 48

#: Do not route below this output width; see the note where it is used.
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

    🔴 Without this the search minimises a slice far thinner than the blend, so
    the path dodges a near object and the blend drags it straight back in.  On
    the first frame tried that was the whole of the difference between routing
    looking worthless (16.86 -> 17.51) and worthwhile.
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

    ⚠️ The path has to be CYCLIC because the azimuth wraps, and it has to be
    CONNECTED because a seam that jumps is a tear.  The connectivity is what
    limits the gain: the per-column minima are scattered, jumping as much as 62
    of 64 rows between neighbours, so a seam cannot visit them.

    Two passes -- solve with a free start, then re-solve pinned to where that
    landed -- rather than solving every start exactly.  Measured against the
    exact answer on five frames the difference is 0.0% median and 3.9% worst,
    and the exact version needs a back-pointer table for every start, which the
    PHP port cannot afford.  Both implementations run this same algorithm.
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
    cannot be shown to beat it.  An estimator that cannot decline has no place
    here; the image-only horizon fit is the cautionary tale.
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

    # 🔴 The test has to carry a MARGIN, and has to ask whether there is a
    # problem at all.  A bare "is the route cheaper" cannot ever decline: the
    # search minimises over connected paths and the bisector is itself one of
    # them, so its optimum is always at least as good.  Comparing an optimum
    # against a feasible solution of the same problem has one possible answer.
    # Without both tests a featureless scene still gets a seam that wanders
    # after noise, for nothing.
    if straight.mean() < _SEAM_FLOOR:
        return None
    if routed.mean() >= _SEAM_MARGIN * straight.mean():
        return None

    # Smooth a little: the grid is coarse and a jagged seam is its own artefact.
    extended = numpy.concatenate([path[-8:], path, path[:8]]).astype(numpy.float64)
    smoothed = numpy.convolve(extended, numpy.ones(9) / 9, mode="same")[8:-8]
    position = ((phi + numpy.pi) / (2 * numpy.pi) * _SEAM_COLUMNS) % _SEAM_COLUMNS
    low = numpy.floor(position).astype(numpy.int32) % _SEAM_COLUMNS
    high = (low + 1) % _SEAM_COLUMNS
    fraction = position - numpy.floor(position)
    rowwise = smoothed[low] * (1 - fraction) + smoothed[high] * fraction
    return rowwise / (_SEAM_ROWS - 1) * (2 * room) - room


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
    with :func:`fit_orientation`, or eventually from the gravity vector in the
    IMU record, which is still undecoded.
    """
    numpy = _numpy()
    width, height = size
    theta_max = numpy.deg2rad(field_of_view / 2)
    if feather_degrees is None:
        # Two requirements, and they pull opposite ways.
        #
        # A few PIXELS, so the hand-over does not alias into a stair-step at
        # small output sizes -- and a wide blend drags back the content a
        # routed seam was routed around, so wider is not free.
        #
        # 🔴 But also a minimum ANGLE, because hiding the photometric step
        # between two lenses is a question about angle, not pixels.  Treating
        # it as pixels alone makes the cross-fade NARROWER as resolution rises,
        # which is backwards: at 4096 wide it came to 0.35 degrees and the seam
        # showed as a hard line across a boat deck.  Measured as the gradient at
        # the seam over the gradient just outside it, over nine frames: 1.16 at
        # 0.35 degrees and 1.11 at 0.70 -- i.e. sharper than its own
        # surroundings -- against 1.01 at 1.5, which still keeps 17% of the
        # routing gain.  Above 2 degrees routing stops paying at all.
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

    # 🔴 Cross-fade on how far each lens is from the BEST-PLACED lens, not on
    # how far it is from its own rim.  Tapering from the rim looks right and is
    # not: with a 194 degree lens the taper only starts at 92 degrees, so both
    # lenses carry full weight across the middle of the 14 degree overlap and
    # the result is a straight 50/50 average of two views separated by
    # parallax.  Near objects then appear as ghosts -- you can see the scene
    # through a person standing near the seam -- and the mix stays visible for
    # about 12 degrees whatever ``feather_degrees`` is set to.  Narrowing the
    # feather makes it worse, not better, because it widens the plateau where
    # both weights saturate at one.
    #
    # Relative to the closest lens, the hand-over happens in a band of width
    # ``feather_degrees`` about the bisector, and the weights never both
    # saturate away from it.  Objects near the seam are cut rather than made
    # transparent, which is the trade the vendor's own stitcher makes too.
    #
    # Three degrees rather than one: narrower is measurably cleaner and carries
    # no photometric penalty, but the cross-fade has to stay several pixels
    # wide at the smallest size anything renders at.  One degree is about 1.4
    # rows of a 256-row preview, which aliases into a hard cut; three is about
    # four rows.
    # With exactly two lenses the hand-over can be ROUTED rather than left on
    # the bisector: parametrise it by d = theta_0 - theta_1 against the azimuth
    # about the lens axis, and put it where the two lenses already agree -- i.e.
    # where nothing is close enough for parallax to separate the views.  A near
    # subject is then walked around instead of cut through.  Median 25% less
    # disagreement across nine frames, 10% to 57%.
    # 🔴 Only decide a seam when there is enough of the frame to decide it on.
    # Measured across nine frames, a grid built at 2048 wide is positive on all
    # of them and never worse than +7%; at 1024 one frame loses 25% and at 512
    # two lose up to 30%.  The cost landscape has many near-equal paths, so a
    # thin grid picks one by noise, and a badly placed seam is worse than the
    # bisector.  Below this the seam is not visible anyway.
    offset = None
    if len(lenses) == 2 and width >= _SEAM_MIN_WIDTH:
        grey = lambda p: p[..., 0] * 0.299 + p[..., 1] * 0.587 + p[..., 2] * 0.114
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
        for index, ((pixels, valid), theta) in enumerate(zip(sampled, thetas)):
            weight = (share if index == 0 else 1.0 - share)
            weight = weight * numpy.clip((theta_max - theta) / feather, 0, 1) * valid
            total += pixels * weight[..., None]
            weights += weight[..., None]
        blended = numpy.where(weights > 0, total / numpy.maximum(weights, 1e-6), 0)
        return blended.astype(numpy.float32), hemispheres

    closest = numpy.minimum.reduce(thetas)
    for (pixels, valid), theta in zip(sampled, thetas):
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


def overlap_agreement(hemispheres):
    """How well the two lenses agree where both of them see the scene.

    This is the accuracy harness for cameras that embed no stitch of their own,
    which is most of them: the lenses see past 180 degrees, so there is a band
    where both observe the same thing, and a correct projection makes the two
    views of it coincide.  Every file carries this evidence.

    Returns Pearson correlation over the overlap band, or None if the lenses do
    not overlap.  Measured on correctly-projected stills: 0.75 to 0.90.  A wrong
    rotation convention drops it to about 0.02.

    🔴 It compares the lenses to each other, not to the world, so it is blind to
    the absolute orientation of the result: because lens 1 faces backwards, a
    world rotation about the lens axis appears as +a in one lens and -a in the
    other and leaves the score untouched.  Levelling has to come from somewhere
    else -- the camera's own stitch, or gravity from the IMU.

    Note that adding the same spin to *both* lenses is not a rotation at all;
    it turns them in opposite world senses and the score collapses.  That
    asymmetry is what made the stored yaw identifiable.

    🔴 It is also blind to the QUALITY of a stitch that is basically correct,
    so do not rank files by it.  A correlation over the band is dominated by
    large-scale luminance: across a 1,432-file corpus the highest score in the
    library, 0.985, is a visibly misregistered sky-against-trees frame, the
    lowest, 0.096, is a blank white room that stitches cleanly, and a file
    verified against the vendor's own export sits below the median.  This
    separates a correct projection from a wrong convention -- 0.75 to 0.90
    against 0.02, one file at a time -- and nothing finer.
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

    ⚠️ This is ground truth only where a levelled reference exists, which is
    25 files in 1,415 of one library -- X5 only.  A OneR or X3 embeds the
    fisheye pair instead, so for those the rotation has to come from the IMU.

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
    # happen to score highest on noise.  One X5 still in the library is an
    # all-black exposure, and it aligned to a confident-looking nonsense
    # rotation before this check existed: it reads 0.3 to 0.6 grey levels of
    # deviation where a real frame reads 50 to 65.
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
    ⚠️ Matching an X5's own stitch takes ``yaw=180``: measured at 180.3 degrees,
    sd 1.8, over the 24 files in one library that embed a stitch to measure
    against.  For a camera that embeds none, nothing fixes the yaw at all.
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
