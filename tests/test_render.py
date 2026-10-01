"""Projection geometry, checked without any real media.

A synthetic pair of fisheye circles is built from a known equirectangular
source, projected back, and compared.  That exercises the geometry end to end
while keeping fixtures synthesised, as the rest of the suite does.
"""

import pytest

numpy = pytest.importorskip("numpy")

from kugelblick import render
from kugelblick.vendors.insta360 import calibration, metadata

# An X5 and a OneR string, verbatim from real files; neither carries anything
# identifying.  The OneR is here because it encodes the 180-degree flip in its
# yaw while the X5 does not, and that difference is the whole point.
X5 = (
    "2_2650.989_2691.500_2693.820_-0.873_0.140_90.047"
    "_2644.985_8069.050_2693.770_1.015_0.005_89.714_10752_5376_1137"
)
ONER = (
    "2_1478.32_1515.09_1518.95_-0.170038_0.734073_-178.89"
    "_1481.11_4563.81_1515.97_0.742285_0.733425_0.21768_6080_3040_3105"
)


def build(text, field=metadata.CALIBRATION_EQUIDISTANT, width=5888):
    return render.lenses_from_calibration(calibration.parse(text, field), width)


def test_lenses_are_scaled_into_the_actual_image():
    lenses = build(X5, width=5888)

    # 2650.989 * 5888/10752 = 1451.7, just inside the 1472 px half-cell.
    assert lenses[0].radius == pytest.approx(1451.7, abs=0.5)
    assert lenses[0].centre_x == pytest.approx(2691.5 * 5888 / 10752, abs=0.5)
    assert lenses[1].centre_x > lenses[0].centre_x


def test_relative_spin_reads_each_yaw_in_its_own_lens_frame():
    """The relative spin is -(yaw0 + yaw1) modulo 180, not the difference.

    Lens 1 faces the other way, so a rotation about the shared axis that it
    states in its own frame has the opposite sense in lens 0's.  Measured
    against the vendor's own stitch, a OneR's lens 1 sits at -1.328 degrees,
    which is what the sum gives; the difference gives -0.892.  The difference
    broke every horizon that crossed the seam.
    """
    x5 = build(X5, width=5888)
    oner = build(ONER, width=6080)

    assert numpy.rad2deg(x5[0].spin) == 0.0
    # -(90.047 + 89.714) = -179.761, i.e. +0.239 once the flip is removed.
    assert numpy.rad2deg(x5[1].spin) == pytest.approx(0.239, abs=0.01)
    # -(-178.89 + 0.21768) = +178.672, i.e. -1.328.
    assert numpy.rad2deg(oner[1].spin) == pytest.approx(-1.328, abs=0.01)


def test_the_fourth_and_fifth_values_are_carried_as_tilts():
    oner = build(ONER, width=6080)
    assert numpy.rad2deg(oner[0].tilt) == pytest.approx((-0.170038, 0.734073))
    assert numpy.rad2deg(oner[1].tilt) == pytest.approx((0.742285, 0.733425))


def test_two_lenses_are_required():
    text = "1_2650.989_2691.500_2693.820_-0.873_0.140_90.047_10752_5376_1137"
    with pytest.raises(ValueError):
        build(text)


def synthetic_pair(size=256, field_of_view=194.0, tilts=((0.0, 0.0), (0.0, 0.0)), radial=()):
    """Render a known pattern into two fisheye circles.

    The inverse of the projection under test, so a round trip should return
    what went in.  ``tilts`` rotates each lens about its OWN x and y axes, in
    radians, before lens 1 is turned to face backwards -- the frame the camera
    states them in.
    """
    cell = size
    image = numpy.zeros((cell, 2 * cell, 3), numpy.uint8)
    theta_max = numpy.deg2rad(field_of_view / 2)
    radius = cell / 2 - 2

    ys, xs = numpy.mgrid[0:cell, 0:cell]
    for index in range(2):
        dx = xs - (cell - 1) / 2
        dy = -(ys - (cell - 1) / 2)
        r = numpy.hypot(dx, dy)
        inside = r <= radius
        theta = numpy.clip(r / radius * theta_max, 0, numpy.pi)
        if radial:
            # The pixel at equidistant angle theta saw the TRUE angle t with
            # t + E(t) = theta; invert the table to build it.
            grid = numpy.arange(len(radial)) * render.RADIAL_STEP
            mapped = grid + numpy.asarray(radial)
            theta = numpy.deg2rad(numpy.interp(numpy.rad2deg(theta), mapped, grid))
        phi = numpy.arctan2(dy, dx)

        x = numpy.sin(theta) * numpy.cos(phi)
        y = numpy.sin(theta) * numpy.sin(phi)
        z = numpy.cos(theta)
        # What the tilted lens recorded at this pixel is the direction R q.
        t = render._tilt_matrix(*tilts[index])
        x, y, z = (t[0, 0] * x + t[0, 1] * y + t[0, 2] * z,
                   t[1, 0] * x + t[1, 1] * y + t[1, 2] * z,
                   t[2, 0] * x + t[2, 1] * y + t[2, 2] * z)
        if index == 1:
            x, z = -x, -z

        # A smooth pattern that varies over the whole sphere, so any rotation
        # error shows up as a mismatch rather than cancelling out.
        lon = numpy.arctan2(x, z)
        lat = numpy.arcsin(numpy.clip(y, -1, 1))
        red = (numpy.sin(lon * 2) * 0.5 + 0.5) * 255
        green = (numpy.sin(lat * 3) * 0.5 + 0.5) * 255
        blue = (numpy.cos(lon + lat) * 0.5 + 0.5) * 255

        cellpix = numpy.stack([red, green, blue], -1).astype(numpy.uint8)
        cellpix[~inside] = 0
        image[:, index * cell : (index + 1) * cell] = cellpix

    lenses = (
        render.Lens(radius, (cell - 1) / 2, (cell - 1) / 2, tilt=tuple(tilts[0]),
                    radial=tuple(radial)),
        render.Lens(radius, cell + (cell - 1) / 2, (cell - 1) / 2, tilt=tuple(tilts[1]),
                    radial=tuple(radial)),
    )
    return image, lenses


def flat_coloured_pair(cell=128):
    """A pair whose two lenses carry flat, different colours.

    Nothing here varies with direction, so any pixel that comes out neither
    red nor blue is the renderer mixing the two lenses -- which is exactly the
    thing a correlation over the overlap cannot see.
    """
    radius = cell / 2 - 1
    image = numpy.zeros((cell, cell * 2, 3), numpy.uint8)
    ys, xs = numpy.mgrid[0:cell, 0:cell]
    inside = numpy.hypot(xs - (cell - 1) / 2, ys - (cell - 1) / 2) <= radius
    for index, colour in enumerate(((255, 0, 0), (0, 0, 255))):
        cellpix = numpy.zeros((cell, cell, 3), numpy.uint8)
        cellpix[inside] = colour
        image[:, index * cell : (index + 1) * cell] = cellpix
    lenses = (
        render.Lens(radius, (cell - 1) / 2, (cell - 1) / 2),
        render.Lens(radius, cell + (cell - 1) / 2, (cell - 1) / 2),
    )
    return image, lenses


def _box_down(values, factor):
    height, width = values.shape[:2]
    height, width = height // factor * factor, width // factor * factor
    block = values[:height, :width].reshape(
        height // factor, factor, width // factor, factor, 3)
    return block.mean(axis=(1, 3))


def textured_pair(cell=128, period=4.0):
    """A pair carrying detail near the sampling limit.

    ⚠️ The smooth pattern in :func:`synthetic_pair` cannot detect a sampling
    error: nearest-neighbour reproduces a slow gradient about as well as
    bilinear does, and a first version of the test below passed under both.
    Aliasing needs something to alias.
    """
    radius = cell / 2 - 1
    image = numpy.zeros((cell, cell * 2, 3), numpy.uint8)
    ys, xs = numpy.mgrid[0:cell, 0:cell]
    inside = numpy.hypot(xs - (cell - 1) / 2, ys - (cell - 1) / 2) <= radius
    fine = (numpy.sin(2 * numpy.pi * xs / period)
            * numpy.sin(2 * numpy.pi * ys / period) * 0.5 + 0.5) * 255
    for index in range(2):
        cellpix = numpy.repeat(fine[..., None], 3, axis=-1).astype(numpy.uint8)
        cellpix[~inside] = 0
        image[:, index * cell : (index + 1) * cell] = cellpix
    lenses = (
        render.Lens(radius, (cell - 1) / 2, (cell - 1) / 2),
        render.Lens(radius, cell + (cell - 1) / 2, (cell - 1) / 2),
    )
    return image, lenses


def test_the_projection_samples_between_source_pixels():
    """🔴 Nearest-neighbour sampling costs more resolution than the output size.

    Render the same scene three times larger and box it back down; that is what
    the pixels ought to be, so a sampler that aliases disagrees with itself
    across scales.

    ⚠️ Do NOT score this with high-frequency energy. Nearest-neighbour *adds*
    high frequencies, because its jaggies are aliasing, so that metric rewards
    the worse sampler. On real media the RMSE at 2048 fell from 5.28 to 3.26 --
    62% of what quadrupling the pixel count buys, for none of the pixels.
    """
    image, lenses = textured_pair()
    size = (256, 128)

    reference = _box_down(
        render.equirectangular(image, lenses, (size[0] * 3, size[1] * 3), 194.0)[0], 3)
    got = render.equirectangular(image, lenses, size, 194.0)[0]
    got = got[: reference.shape[0], : reference.shape[1]]
    inside = reference.max(axis=-1) > 8
    error = numpy.sqrt((((got - reference) ** 2).mean(axis=-1))[inside].mean())

    assert error < 15.0, (
        f"RMSE {error:.2f} against a 3x reference; nearest-neighbour sampling "
        "scores 32.6 on this fixture and bilinear 8.5"
    )


def test_the_lenses_hand_over_rather_than_averaging():
    """🔴 The overlap must not come out as a 50/50 average of both lenses.

    The lenses see 194 degrees and so overlap by 14, and they are separated by
    a baseline, so a near object sits in different places in the two views.
    Averaging across that band makes it semi-transparent -- you could see the
    scene through a person standing near the seam.  The first weighting shipped
    tapered each lens from its own rim, which leaves both weights saturated at
    one across the middle of the band; 17.9 per cent of every sphere was a
    50/50 mix and no metric in the suite could see it, because a correlation
    between the two lenses is blindest exactly where they are averaged.
    """
    image, lenses = flat_coloured_pair()
    pixels, _ = render.equirectangular(image, lenses, (512, 256), 194.0)

    red, blue = pixels[..., 0], pixels[..., 2]
    lit = numpy.maximum(red, blue) > 8
    mixed = (numpy.minimum(red, blue) / numpy.maximum(numpy.maximum(red, blue), 1e-6))
    share = float((lit & (mixed > 0.4)).sum()) / lit.sum()

    assert share < 0.05, (
        f"{share:.1%} of the sphere is a blend of both lenses, which is where "
        "near objects turn transparent; the rim-taper weighting scored 0.179"
    )


def _band_disagreement(hemispheres, half_degrees=6.0, size=(512, 256)):
    rays = render._rays(*size)
    d = 2 * numpy.arccos(numpy.clip(rays[..., 2], -1, 1)) - numpy.pi
    (a, va), (b, vb) = hemispheres
    band = va & vb & (numpy.abs(d) < numpy.deg2rad(half_degrees))
    return float(numpy.abs(a.astype(float) - b.astype(float))[band].mean())


def test_the_tilt_is_applied_in_the_lens_own_frame():
    """A tilt on lens 1 about x is where frames matter: turning the lens round
    reverses x, so applying it in lens 0's frame gets its sign wrong.  Lopsided
    on purpose -- a tilt about y, or the same tilt on both lenses, would pass
    either way.
    """
    tilts = ((0.0, 0.0), (numpy.deg2rad(3.0), 0.0))
    image, lenses = synthetic_pair(size=512, tilts=tilts)
    untilted = tuple(render.Lens(l.radius, l.centre_x, l.centre_y) for l in lenses)
    wrong_frame = (lenses[0], render.Lens(lenses[1].radius, lenses[1].centre_x,
                                          lenses[1].centre_y, tilt=(-tilts[1][0], 0.0)))

    def score(pair):
        _, hemispheres = render.equirectangular(image, pair, (512, 256), 194.0)
        return _band_disagreement(hemispheres)

    right, ignored, flipped = score(lenses), score(untilted), score(wrong_frame)
    assert right < 0.5 * ignored, (right, ignored)
    assert ignored < flipped, (ignored, flipped)


def test_a_radial_correction_is_applied_where_the_lens_recorded_it():
    """A lens that departs from the equidistant model by a known curve.

    The curve is lopsided on purpose -- zero at the axis, a bump at 60 degrees,
    and a different value at the rim -- so it cannot pass by cancelling.
    Rendering with it must restore agreement; ignoring it, or applying it with
    the wrong sign, must not.
    """
    grid = numpy.arange(0, 101, render.RADIAL_STEP)
    curve = 2.5 * numpy.sin(numpy.pi * grid / 120.0) ** 2 * numpy.exp(-((grid - 60) / 40) ** 2)
    curve = tuple(float(v) for v in curve)
    image, lenses = synthetic_pair(size=512, radial=curve)
    plain = tuple(render.Lens(l.radius, l.centre_x, l.centre_y) for l in lenses)
    reversed_ = tuple(render.Lens(l.radius, l.centre_x, l.centre_y,
                                  radial=tuple(-v for v in curve)) for l in lenses)

    def score(pair):
        _, hemispheres = render.equirectangular(image, pair, (512, 256), 194.0)
        return _band_disagreement(hemispheres, half_degrees=12.0)

    right, ignored, wrong = score(lenses), score(plain), score(reversed_)
    assert right < 0.5 * ignored, (right, ignored)
    assert ignored < wrong, (ignored, wrong)


def test_round_trip_recovers_the_pattern():
    """Project a synthetic pair back out and the two lenses must agree."""
    image, lenses = synthetic_pair()

    _, hemispheres = render.equirectangular(image, lenses, (256, 128), 194.0)
    score = render.overlap_agreement(hemispheres)

    assert score is not None
    assert score > 0.95, f"a correct projection should agree with itself, got {score}"


def test_a_wrong_spin_destroys_the_agreement():
    """The harness has to be able to tell right from wrong, or it is useless."""
    image, lenses = synthetic_pair()
    wrong = (lenses[0], render.Lens(lenses[1].radius, lenses[1].centre_x,
                                    lenses[1].centre_y, spin=numpy.deg2rad(90)))

    _, good = render.equirectangular(image, lenses, (256, 128), 194.0)
    _, bad = render.equirectangular(image, wrong, (256, 128), 194.0)

    assert render.overlap_agreement(good) > render.overlap_agreement(bad) + 0.3


def test_overlap_is_blind_to_a_global_rotation():
    """Documented limitation, pinned so it is not mistaken for a full check.

    Because lens 1 faces backwards, a rotation of the *world* about the lens
    axis appears as +a in lens 0 and -a in lens 1.  That leaves the two lenses
    agreeing exactly as before, which is why absolute orientation cannot come
    from this metric -- it compares the lenses to each other, not to gravity.
    """
    image, lenses = synthetic_pair()
    angle = numpy.deg2rad(30)
    rotated_world = (
        render.Lens(lenses[0].radius, lenses[0].centre_x, lenses[0].centre_y,
                    spin=lenses[0].spin + angle),
        render.Lens(lenses[1].radius, lenses[1].centre_x, lenses[1].centre_y,
                    spin=lenses[1].spin - angle),
    )

    _, plain = render.equirectangular(image, lenses, (256, 128), 194.0)
    _, turned = render.equirectangular(image, rotated_world, (256, 128), 194.0)

    # The tolerance absorbs nearest-neighbour resampling drift, which is small
    # next to the ~1.9 swing the wrong convention produces in the next test.
    assert render.overlap_agreement(plain) == pytest.approx(
        render.overlap_agreement(turned), abs=0.05
    )


def test_spinning_both_lenses_the_same_way_is_not_a_rotation():
    """It turns them in opposite world senses, so agreement collapses.

    This is what made the stored yaw identifiable: applying it to both lenses
    alike scored ~0.02 on real files, while the relative reading scored ~0.8.
    """
    image, lenses = synthetic_pair()
    both = tuple(
        render.Lens(l.radius, l.centre_x, l.centre_y, spin=l.spin + numpy.deg2rad(30))
        for l in lenses
    )

    _, plain = render.equirectangular(image, lenses, (256, 128), 194.0)
    _, spun = render.equirectangular(image, both, (256, 128), 194.0)

    assert render.overlap_agreement(plain) > render.overlap_agreement(spun) + 0.5


def test_field_of_view_is_fitted_not_assumed():
    image, lenses = synthetic_pair(field_of_view=194.0)

    best, scored = render.fit_field_of_view(
        image, lenses, candidates=range(188, 201, 2), size=(256, 128)
    )

    assert len(scored) > 3
    assert best == pytest.approx(194.0, abs=2.0)


def test_no_overlap_reports_none():
    """Below 180 degrees the lenses cannot see the same thing at all."""
    image, lenses = synthetic_pair()

    _, hemispheres = render.equirectangular(image, lenses, (256, 128), 170.0)

    assert render.overlap_agreement(hemispheres) is None


def test_rotation_is_a_rotation():
    matrix = render.rotation(31.0, -12.0, 57.0)

    assert numpy.allclose(matrix @ matrix.T, numpy.eye(3), atol=1e-12)
    assert numpy.linalg.det(matrix) == pytest.approx(1.0)


def test_rendering_with_an_orientation_matches_turning_the_render():
    """Two routes to the same panorama, and they have to agree.

    The fitter leans on the cheap one -- it turns a small equirectangular
    frame instead of re-projecting a 70-megapixel fisheye pair for every
    candidate -- so if these two ever disagreed, every solved rotation would
    be wrong by however much they differ.
    """
    image, lenses = synthetic_pair()
    matrix = render.rotation(37.0, 12.0, -8.0)

    direct, _ = render.equirectangular(image, lenses, (256, 128), 194.0, orientation=matrix)
    plain, _ = render.equirectangular(image, lenses, (256, 128), 194.0)
    turned = render.rotate(plain, matrix)

    both = (direct > 2).all(-1) & (turned > 2).all(-1)
    assert both.sum() > 10000
    assert numpy.abs(direct[both] - turned[both]).mean() < 3.0


def test_level_puts_the_given_direction_at_the_top():
    for up in ([0, 1, 0], [1, 0, 0], [0, -1, 0], [0.3, 0.9, -0.2]):
        vector = numpy.array(up, float)
        vector /= numpy.linalg.norm(vector)

        lifted = render.level(vector) @ vector

        assert lifted == pytest.approx([0, 1, 0], abs=1e-9)


def test_level_yaw_turns_the_panorama_without_tipping_it():
    """Gravity fixes two axes of three; which way the result faces is free."""
    up = numpy.array([0.3, 0.9, -0.2])
    up /= numpy.linalg.norm(up)

    plain = render.level(up)
    turned = render.level(up, yaw=90.0)

    assert (turned @ up) == pytest.approx([0, 1, 0], abs=1e-9)
    assert not numpy.allclose(plain, turned)


def test_fit_orientation_recovers_a_known_rotation():
    image, lenses = synthetic_pair()
    reference, _ = render.equirectangular(image, lenses, (128, 64), 194.0)
    truth = render.rotation(23.0, 14.0, -7.0)
    tilted = render.rotate(reference, truth.T)

    angles, score = render.fit_orientation(tilted, reference, coarse_degrees=15.0)

    assert score > 0.9, f"a recoverable rotation should align well, got {score}"
    recovered = render.rotation(*angles)
    # Compare the rotations themselves: the angles are one parameterisation of
    # many, but the matrix they build is not.
    error = numpy.degrees(numpy.arccos(numpy.clip((numpy.trace(recovered.T @ truth) - 1) / 2, -1, 1)))
    assert error < 3.0, f"recovered rotation is {error:.1f} degrees off"


def test_fit_orientation_refuses_a_blank_frame():
    """One X5 still in the library is an all-black exposure.

    Before this check it aligned to a confident-looking nonsense rotation.
    """
    blank = numpy.zeros((64, 128, 3), numpy.float32) + 5

    with pytest.raises(ValueError, match="no structure"):
        render.fit_orientation(blank, blank)


def test_fit_orientation_refuses_frames_of_different_sizes():
    image, lenses = synthetic_pair()
    small, _ = render.equirectangular(image, lenses, (64, 32), 194.0)
    large, _ = render.equirectangular(image, lenses, (128, 64), 194.0)

    with pytest.raises(ValueError, match="differ in size"):
        render.fit_orientation(small, large)


def test_body_orientation_undoes_the_sensor_mounting_angle():
    """A OneR's sensor sits 90 degrees round from an X5's.

    Without this rotation a OneR render comes out on its side, which is how
    1,344 of the 1,415 files in one library looked.
    """
    from kugelblick.vendors.insta360 import calibration, metadata

    oner = calibration.parse(
        "2_1478.32_1515.09_1518.95_-0.17_0.73_-178.89"
        "_1481.11_4563.81_1515.97_0.74_0.73_0.21768_6080_3040_3105",
        metadata.CALIBRATION_EQUIDISTANT,
    )
    matrix = render.body_orientation(oner)

    # Rolling about the lens axis leaves that axis alone and swings the
    # vertical onto the horizontal.
    assert (matrix @ numpy.array([0.0, 0.0, 1.0])) == pytest.approx([0, 0, 1], abs=1e-9)
    assert abs((matrix @ numpy.array([0.0, 1.0, 0.0]))[0]) == pytest.approx(1.0, abs=0.02)
    assert render.rotation(0.0, 0.0, oner.body_roll) == pytest.approx(matrix)


def test_body_orientation_is_a_near_identity_for_an_x5():
    from kugelblick.vendors.insta360 import calibration, metadata

    x5 = calibration.parse(
        "2_2650.989_2691.500_2693.820_-0.873_0.140_90.047"
        "_2644.985_8069.050_2693.770_1.015_0.005_89.714_10752_5376_1137",
        metadata.CALIBRATION_EQUIDISTANT,
    )

    assert render.body_orientation(x5) == pytest.approx(numpy.eye(3), abs=1e-3)


# ---------------------------------------------- levelling selection in the CLI


class _Vendor:
    """A stand-in vendor, so the choice is tested without needing real media."""

    NAME = "stub"

    def __init__(self, up=None, error=None):
        self._up, self._error = up, error

    def gravity_up(self, path):
        if self._error is not None:
            raise self._error
        return self._up


class _Calibration:
    body_roll = -91.11


def test_levelling_prefers_the_inertial_record():
    import numpy

    from kugelblick import cli, render

    matrix, note = cli._levelling(render, _Vendor(up=(0.0, 0.0, 1.0)), "x", _Calibration(), "auto")

    assert "gravity" in note
    assert (matrix @ numpy.array([0.0, 0.0, 1.0])) == pytest.approx([0, 1, 0], abs=1e-9)


def test_levelling_falls_back_to_the_calibration():
    """Most files carry no usable inertial record, so the fallback is the
    common path rather than an edge case."""
    from kugelblick import cli, render
    from kugelblick.errors import FormatError

    vendor = _Vendor(error=FormatError("not measured for this camera"))
    matrix, note = cli._levelling(render, vendor, "x", _Calibration(), "auto")

    assert "calibration" in note and "no usable inertial record" in note
    assert matrix == pytest.approx(render.body_orientation(_Calibration()))


def test_forcing_the_inertial_route_refuses_rather_than_falling_back():
    """--level imu means 'fail if you cannot', so a silent downgrade to a
    worse horizon is not possible."""
    from kugelblick import cli, render
    from kugelblick.errors import FormatError

    vendor = _Vendor(error=FormatError("not measured for this camera"))

    with pytest.raises(FormatError):
        cli._levelling(render, vendor, "x", _Calibration(), "imu")


def test_levelling_can_be_turned_off():
    from kugelblick import cli, render

    matrix, note = cli._levelling(render, _Vendor(up=(0.0, 0.0, 1.0)), "x", _Calibration(), "none")

    assert matrix is None and "none" in note


def test_the_seam_path_is_closed_and_connected():
    """A seam that jumps is a tear, and the azimuth wraps.

    Both properties are structural, so they are checked on the search directly
    rather than inferred from a rendered frame.
    """
    rows, columns = 32, 128
    grid = numpy.full((rows, columns), 10.0)
    path = render._cheapest_cycle(grid)

    assert path is not None
    assert path.shape == (columns,)
    assert numpy.abs(numpy.diff(path)).max() <= 1, "the seam steps more than one row"
    assert abs(int(path[0]) - int(path[-1])) <= 1, "the seam does not close"


def test_the_seam_follows_the_cheap_corridor():
    """It has to actually route, not merely return something well-formed."""
    rows, columns = 32, 256
    corridor = (rows / 2 + numpy.sin(numpy.arange(columns) / columns * 2 * numpy.pi)
                * (rows / 2 - 3)).astype(int)
    grid = numpy.full((rows, columns), 50.0)
    grid[corridor, numpy.arange(columns)] = 1.0

    path = render._cheapest_cycle(grid)

    assert path is not None
    assert numpy.abs(path - corridor).max() <= 1, (
        f"the seam strayed from the corridor by {numpy.abs(path - corridor).max()} rows"
    )


def test_routing_declines_when_there_is_nothing_to_route_around():
    """🔴 The decline has to be reachable, and once was not.

    The first guard asked only whether the routed path was cheaper than the
    straight one.  It can never fail: the search minimises over connected paths
    and the bisector is one of them, so its optimum is always at least as good.
    Comparing an optimum against a feasible solution of the same problem has
    one possible answer.  A featureless pair got a seam that wandered after
    noise, and the test that would have caught it is this one.
    """
    image, lenses = flat_coloured_pair()
    theta_max = numpy.deg2rad(97.0)
    feather = numpy.deg2rad(2.0)
    rays = render._rays(256, 128)

    sampled = []
    for index, lens in enumerate(lenses):
        u, v, theta = render._project(rays, lens, index, theta_max)
        sampled.append((render._sample(image, u, v, theta <= theta_max), theta <= theta_max))
    grey = lambda p: p[..., 0] * 0.299 + p[..., 1] * 0.587 + p[..., 2] * 0.114
    z = numpy.clip(rays[..., 2], -1, 1)

    offset = render._seam_offset(
        grey(sampled[0][0]), grey(sampled[1][0]), sampled[0][1] & sampled[1][1],
        2 * numpy.arccos(z) - numpy.pi,
        numpy.arctan2(rays[..., 1], rays[..., 0]),
        feather, 2 * theta_max - numpy.pi,
    )

    assert offset is None, "routed a seam through a scene with nothing to route around"
