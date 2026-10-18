"""Parsing of the calibration models, using strings measured from real files.

These are verbatim.  They carry no identifying information -- the serial number
lives in a different protobuf field and is deliberately not reproduced here.

Two cameras appear, on purpose: an X5, which carries all four models, and a
OneR, which carries only the equidistant one and quotes it against a completely
different reference frame, so X5-specific values can't pass as properties of
the format.
"""

import pytest

from golblick.errors import FormatError
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
    # Field 53's angles are not identified (only its lens offset is), so
    # nothing may read a yaw out of them by position.
    model = parse(POLYNOMIAL, metadata.CALIBRATION_POLY)

    with pytest.raises(CalibrationError):
        model.body_roll  # noqa: B018 -- the access is what raises


def test_the_lens_offset_is_lens_one_less_lens_zero():
    """The seventh to ninth values of field 53's lens blocks place the lenses.

    On this X5 lens 1 sits 0.0325 along the lens axis behind lens 0, which is
    the direction that lines near subjects up across the seam.
    """
    model = parse(POLYNOMIAL, metadata.CALIBRATION_POLY)

    assert model.lens_offset == pytest.approx((-0.000868, 0.000085, -0.032509))


def test_the_lens_offset_is_only_read_where_it_is_stored():
    model = parse(EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)

    with pytest.raises(CalibrationError):
        model.lens_offset  # noqa: B018 -- the access is what raises


# What a OneR video records in metadata field 27: each lens's 3040-pixel sensor
# square, of which the frame keeps the central 2880.  It writes no x or y.
ONER_VIDEO_CROP = (3040, 3040, 2880, 2880, 0, 0)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _submessage(number: int, values: dict[int, int]) -> bytes:
    inner = b"".join(_varint(key << 3) + _varint(value) for key, value in values.items())
    return _varint(number << 3 | 2) + _varint(len(inner)) + inner


def test_sensor_crop_reads_missing_offsets_as_zero():
    """A OneR or X3 leaves x and y out; an X5 writes the zeros.  Both read the same."""
    oner = metadata.by_number(_submessage(27, {1: 3040, 2: 3040, 3: 2880, 4: 2880}))
    x5 = metadata.by_number(_submessage(27, {1: 5376, 2: 5376, 3: 5312, 4: 5312, 5: 0, 6: 0}))

    assert metadata.sensor_crop(oner) == ONER_VIDEO_CROP
    assert metadata.sensor_crop(x5) == (5376, 5376, 5312, 5312, 0, 0)
    assert metadata.sensor_crop(metadata.by_number(_submessage(27, {1: 3040}))) is None
    assert metadata.sensor_crop({}) is None


def test_a_video_crops_the_still_calibration_and_keeps_its_radius():
    """Lens 0's centre moves in by the margin, lens 1's by three margins, the radius not at all.

    Scaling the still string to the video frame instead puts both centres
    within half a pixel of these, which is why it looks right, and makes the
    radius 5.3% too small on a OneR.
    """
    still = parse(ONER_EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT)
    video = still.for_video(ONER_VIDEO_CROP)

    assert video.reference_frame == (5760, 2880)
    assert video.scale_for(5760) == 1.0
    (r0, x0, y0, *rest0), (r1, x1, y1, *rest1) = video.lenses
    assert (r0, x0, y0) == pytest.approx((1478.32, 1515.09 - 80, 1518.95 - 80))
    assert (r1, x1, y1) == pytest.approx((1481.11, 4563.81 - 240, 1515.97 - 80))
    assert (rest0, rest1) == (list(still.lenses[0][3:]), list(still.lenses[1][3:]))
    assert video.lenses[0][0] / (still.lenses[0][0] * still.scale_for(5760)) == pytest.approx(6080 / 5760)


@pytest.mark.parametrize("crop", [
    (3040, 3040, 2880, 2880, 16, 0),     # an offset window: never seen, not understood
    (3040, 3040, 2880, 2860, 0, 0),      # not square
    (2976, 2976, 2880, 2880, 0, 0),      # a source that isn't this string's lens
    (3040, 3040, 3200, 3200, 0, 0),      # keeps more than there is
])
def test_a_crop_that_is_not_understood_is_refused(crop):
    with pytest.raises(FormatError):
        parse(ONER_EQUIDISTANT, metadata.CALIBRATION_EQUIDISTANT).for_video(crop)
