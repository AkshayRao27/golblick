"""Equirectangular projection from a dual-fisheye pair, and how to score it.

This is the only module that needs numpy, which is why it sits behind the
``render`` extra.  Everything else in the package stays dependency-free.

WHAT IS MEASURED, AND WHAT IS NOT
---------------------------------
The geometry here is built from the *equidistant* calibration model, because it
is the only one every camera carries and the only one whose interior is
confirmed.  See ``docs/formats/insta360.md``.

Confirmed by measurement across three cameras:

* Each lens maps angle from its axis linearly to radius in its image circle,
  ``r = radius * theta / theta_max`` -- the equidistant model.
* The two lenses sit back to back, and the stored yaw is the sensor's rotation
  *within* its image circle, not the direction the lens points.  The relative
  rotation between the lenses is the stored yaw difference taken modulo 180
  degrees; a OneR states that 180 explicitly, an X3 and X5 leave it implicit.
* Image rows run downward while world Y runs up, so the azimuth is negated.
  Without that the panorama comes out mirrored.

⚠️ **Not** established, and therefore not applied:

* What ``roll`` and ``pitch`` mean.  They are under one degree on every camera
  measured, and applying them as tilts about X and Y scores slightly *worse*
  than ignoring them, so the convention is wrong rather than the values useless.
* ``theta_max``, the angle the image circle's rim corresponds to.  It is not in
  the file.  :func:`fit_field_of_view` recovers it by scoring, and it differs
  per camera (194 degrees on an X5 and a OneR, 192 on an X3).
* The absolute orientation of the result.  See :func:`overlap_agreement`.
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


def lenses_from_calibration(calibration, width: int):
    """Build the lens pair from an equidistant calibration string.

    Only the relative spin between the lenses is used.  The absolute value is
    not recoverable from the file alone -- see :func:`overlap_agreement` -- so
    lens 0 is taken as the reference and lens 1 carries the difference.
    """
    numpy = _numpy()
    if len(calibration.lenses) != 2:
        raise ValueError(f"expected 2 lenses, got {len(calibration.lenses)}")

    scale = calibration.scale_for(width)
    yaws = [lens[5] for lens in calibration.lenses]
    # Modulo 180, signed the short way: lens 1 is physically 180 degrees round,
    # and a OneR encodes that in the yaw while an X3 and X5 do not.
    relative = ((yaws[1] - yaws[0]) + 90.0) % 180.0 - 90.0

    built = []
    for index, (radius, cx, cy, _roll, _pitch, _yaw) in enumerate(calibration.lenses):
        built.append(Lens(
            radius=radius * scale,
            centre_x=cx * scale,
            centre_y=cy * scale,
            spin=numpy.deg2rad(relative) if index == 1 else 0.0,
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


def _project(rays, lens: Lens, index: int, theta_max: float):
    """Where each ray lands in one lens, and how far off axis it is."""
    numpy = _numpy()
    x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
    if index == 1:
        # Lens 1 faces the other way: rotate 180 degrees about the vertical.
        x, z = -x, -z

    theta = numpy.arccos(numpy.clip(z, -1, 1))
    phi = numpy.arctan2(y, x) - lens.spin
    r = lens.radius * theta / theta_max
    # Rows run downward while world Y runs up, hence the minus on sin.
    return lens.centre_x + r * numpy.cos(phi), lens.centre_y - r * numpy.sin(phi), theta


def _sample(image, u, v, valid):
    numpy = _numpy()
    height, width = image.shape[:2]
    x = numpy.clip(numpy.rint(u).astype(numpy.int32), 0, width - 1)
    y = numpy.clip(numpy.rint(v).astype(numpy.int32), 0, height - 1)
    out = image[y, x].astype(numpy.float32)
    out[~valid] = 0
    return out


def equirectangular(image, lenses, size, field_of_view, feather_degrees=5.0):
    """Project a dual-fisheye ``image`` into an equirectangular frame.

    ``field_of_view`` is the full angle each lens sees, in degrees; it is not
    carried in the file, so fit it with :func:`fit_field_of_view`.

    ⚠️ The result's absolute orientation is arbitrary: the calibration fixes
    the lenses relative to each other, not relative to the world.  Levelling it
    needs the camera's own stitch or the gravity vector from the IMU.
    """
    numpy = _numpy()
    width, height = size
    theta_max = numpy.deg2rad(field_of_view / 2)
    feather = numpy.deg2rad(feather_degrees)
    rays = _rays(width, height)

    total = numpy.zeros((height, width, 3), numpy.float32)
    weights = numpy.zeros((height, width, 1), numpy.float32)
    hemispheres = []
    for index, lens in enumerate(lenses):
        u, v, theta = _project(rays, lens, index, theta_max)
        valid = theta <= theta_max
        pixels = _sample(image, u, v, valid)
        # Taper to nothing at the rim so the hemispheres cross-fade rather than
        # meeting at a hard edge.  This is a blend, not a parallax fix.
        weight = numpy.clip((theta_max - theta) / feather, 0, 1) * valid
        total += pixels * weight[..., None]
        weights += weight[..., None]
        hemispheres.append((pixels, valid))

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
