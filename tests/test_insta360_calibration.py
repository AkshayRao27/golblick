"""Parsing of the calibration models, using strings measured from real files.

These are verbatim.  They carry no identifying information -- the serial number
lives in a different protobuf field and is deliberately not reproduced here.

Two cameras appear, on purpose: an X5, which carries all four models, and a
OneR, which carries only the equidistant one and quotes it against a completely
different reference frame.  Testing against one camera is what let a handful of
X5-specific values get recorded as properties of the format.
"""

import pytest

from golblick.vendors.insta360 import metadata
from golblick.vendors.insta360.calibration import CalibrationError, best, parse

EQUIDISTANT = (
    "2_2650.989_2691.500_2693.820_-0.873_0.140_90.047"
    "_2644.985_8069.050_2693.770_1.015_0.005_89.714_10752_5376_1137"
)
# A OneR carries only field 5, and quotes it against 6080x3040 -- which is also
# its image size, so the scale factor is exactly 1.0 there.
ONER_EQUIDISTANT = (
    "2_1478.32_1515.09_1518.95_-0.170038_0.734073_-178.89"
    "_1481.11_4563.81_1515.97_0.742285_0.733425_0.21768_6080_3040_3105"
)

X5_REFERENCE_FRAME = (10752, 5376)

POLYNOMIAL = (
    "2_2659.375_2691.500_2693.820_-0.873_0.140_90.047_0.000000_0.000000_0.000000"
    "_1.00000000_-0.18948607_0.27191675_-0.08897080_10752_5376_113"
    "_2654.540_8069.050_2693.770_1.015_0.005_89.714_-0.000868_0.000085_-0.032509"
    "_1.00000000_-0.18783575_0.26932722_-0.08787999_10752_5376_113_132096"
)


def test_equidistant_shape():
    model = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    assert model.kind == "equidistant"
    assert model.lens_count == 2
    assert all(len(lens) == 6 for lens in model.lenses)
    assert model.reference_frame == X5_REFERENCE_FRAME


def test_equidistant_values():
    model = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    radius, centre_x, centre_y, roll, pitch, yaw = model.lenses[0]

    assert radius == pytest.approx(2650.989)
    assert (centre_x, centre_y) == pytest.approx((2691.5, 2693.82))
    # Both lens axes sit near 90 degrees, which is why a naive dual-fisheye
    # stitch that assumes 0/180 comes out rotated.
    assert yaw == pytest.approx(90.047, abs=0.1)
    assert model.lenses[1][5] == pytest.approx(89.714, abs=0.1)


def test_polynomial_repeats_reference_frame_per_lens():
    model = parse(POLYNOMIAL, metadata.CALIBRATION_POLY)

    assert model.lens_count == 2
    assert all(len(lens) == 16 for lens in model.lenses)
    assert model.reference_frame == X5_REFERENCE_FRAME


def test_lens_circle_lands_inside_its_half_cell():
    """The scaling rule, checked geometrically rather than asserted."""
    model = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    width, height = 5888, 2944
    scale = model.scale_for(width)

    radius = model.lenses[0][0] * scale
    half_cell = width / 2 / 2  # two square fisheye cells side by side

    assert radius < half_cell
    assert radius > half_cell * 0.95, "circle should very nearly fill its cell"
    assert radius == pytest.approx(1451.7, abs=0.5)
    assert height == width // 2


def test_wrong_part_count_is_rejected():
    with pytest.raises(CalibrationError):
        parse("2_1.0_2.0_3.0", metadata.CALIBRATION_EQUIDISTANT)


def test_non_numeric_is_rejected():
    with pytest.raises(CalibrationError):
        parse("2_nope_2.0", metadata.CALIBRATION_EQUIDISTANT)


def test_best_prefers_the_richest_model():
    models = {
        metadata.CALIBRATION_EQUIDISTANT: parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT),
        metadata.CALIBRATION_POLY: parse(POLYNOMIAL, metadata.CALIBRATION_POLY),
    }

    assert best(models).field == metadata.CALIBRATION_POLY
    assert best({}) is None


def test_reference_frame_is_read_from_the_string_not_assumed():
    """It is per camera: 10752x5376 on an X5, 6080x3040 on a OneR.

    Hard-coding the X5's value would misplace every lens circle on a OneR, which
    is 1,344 of the 1,415 files measured.
    """
    x5 = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    oner = parse(ONER_EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    assert x5.reference_frame == (10752, 5376)
    assert oner.reference_frame == (6080, 3040)
    assert oner.scale_for(6080) == pytest.approx(1.0)
    assert x5.scale_for(5888) == pytest.approx(0.547619, abs=1e-6)


def test_scale_can_exceed_one():
    """The X5's high-resolution still mode is wider than its own reference frame."""
    model = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    assert model.scale_for(11904) == pytest.approx(1.107143, abs=1e-6)


def test_lens_orientation_is_not_assumed_to_be_front_back():
    """A OneR uses 0/180; an X3 and X5 do not.  Neither may be hard-coded."""
    x5 = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    oner = parse(ONER_EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    assert oner.lenses[0][5] == pytest.approx(-178.89, abs=0.01)
    assert oner.lenses[1][5] == pytest.approx(0.22, abs=0.01)
    assert x5.lenses[0][5] == pytest.approx(90.05, abs=0.01)
    assert x5.lenses[1][5] == pytest.approx(89.71, abs=0.01)


def test_body_roll_is_the_complement_of_the_stored_yaw():
    x5 = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    oner = parse(ONER_EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    # The X5's sensor sits at the reference angle, so it needs no correction.
    assert x5.body_roll == pytest.approx(-0.047, abs=0.01)
    # The OneR's sits 90 degrees round, which is why an uncorrected OneR render
    # comes out on its side.
    assert oner.body_roll == pytest.approx(-91.11, abs=0.01)


def test_body_roll_stays_in_the_short_half_turn():
    # A yaw just past the wrap must not produce a 269-degree roll.
    model = parse(
        "2_100_100_100_0_0_-179.5_100_300_100_0_0_0.5_1000_500_1",
        metadata.CALIBRATION_EQUIDISTANT,
    )

    assert -180.0 < model.body_roll <= 180.0
    assert model.body_roll == pytest.approx(-90.5)


def test_body_roll_refuses_a_model_whose_interior_is_unknown():
    # Field 53's parameters are not identified, so nothing may read a yaw out
    # of them by position.
    model = parse(POLYNOMIAL, metadata.CALIBRATION_POLY)

    with pytest.raises(CalibrationError):
        model.body_roll
