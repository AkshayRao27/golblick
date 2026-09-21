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


def test_relative_spin_is_taken_modulo_180():
    """A OneR puts the back-to-back flip in its yaw; an X5 does not.

    Both must reduce to the same thing -- a fraction of a degree of relative
    sensor rotation -- or one of the two cameras projects with a 180-degree
    error.
    """
    x5 = build(X5, width=5888)
    oner = build(ONER, width=6080)

    assert numpy.rad2deg(x5[0].spin) == 0.0
    assert numpy.rad2deg(x5[1].spin) == pytest.approx(-0.333, abs=0.01)

    # Stored difference is +179.108, which is -0.892 once the flip is removed.
    assert numpy.rad2deg(oner[1].spin) == pytest.approx(-0.892, abs=0.01)


def test_two_lenses_are_required():
    text = "1_2650.989_2691.500_2693.820_-0.873_0.140_90.047_10752_5376_1137"
    with pytest.raises(ValueError):
        build(text)


def synthetic_pair(size=256, field_of_view=194.0):
    """Render a known pattern into two fisheye circles.

    The inverse of the projection under test, so a round trip should return
    what went in.
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
        phi = numpy.arctan2(dy, dx)

        x = numpy.sin(theta) * numpy.cos(phi)
        y = numpy.sin(theta) * numpy.sin(phi)
        z = numpy.cos(theta)
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
        render.Lens(radius, (cell - 1) / 2, (cell - 1) / 2),
        render.Lens(radius, cell + (cell - 1) / 2, (cell - 1) / 2),
    )
    return image, lenses


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
