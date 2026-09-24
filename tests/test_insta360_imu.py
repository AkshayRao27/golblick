"""The inertial record, both encodings of it, and what it refuses.

Fixtures are synthesised, as everywhere else in this suite.  The values are
chosen so that a wrong stride cannot accidentally produce a valid-looking read.
"""

import struct

import pytest

from conftest import write_file
from kugelblick.errors import FormatError
from kugelblick.vendors.insta360 import imu
from kugelblick.vendors.insta360.trailer import IMU, METADATA


def biased(timecode, values):
    """One 20-byte entry: uint16 biased by 0x8000, a thousandth of a unit each."""
    return struct.pack("<q", timecode) + struct.pack(
        "<6H", *(round(v * 1000) + 0x8000 for v in values)
    )


def doubles(timecode, values):
    """One 56-byte entry: six float64."""
    return struct.pack("<q", timecode) + struct.pack("<6d", *values)


def model_record(name):
    """A metadata record carrying just the model string (protobuf field 2)."""
    text = name.encode()
    return b"\x12" + bytes([len(text)]) + text


LEVEL_X5 = (-1.024, 0.019, -0.008, 0.0, 0.0, 0.0)


def test_reads_the_biased_integer_encoding(tmp_path):
    payload = biased(1000, LEVEL_X5) + biased(2000, (0.5, -0.25, 1.0, 0.0, 0.0, 0.0))
    path = write_file(tmp_path / "a.insp", [(IMU, payload)])

    samples = imu.entries(path)

    assert [s.time for s in samples] == [1.0, 2.0]
    assert samples[0].acceleration == pytest.approx((-1.024, 0.019, -0.008))
    assert samples[1].acceleration == pytest.approx((0.5, -0.25, 1.0))
    assert samples[0].angular_velocity == pytest.approx((0.0, 0.0, 0.0))


def test_reads_the_float_encoding(tmp_path):
    payload = doubles(1432297, (0.995117, 0.016113, -0.015625, 0.000454, 0.003956, 0.002243))
    path = write_file(tmp_path / "b.insp", [(IMU, payload)])

    sample, = imu.entries(path)

    assert sample.time == pytest.approx(1432.297)
    assert sample.acceleration == pytest.approx((0.995117, 0.016113, -0.015625))
    assert sample.angular_velocity == pytest.approx((0.000454, 0.003956, 0.002243))


def test_the_stride_is_searched_not_assumed(tmp_path):
    """Both encodings are real, on the same camera model, so neither is default.

    A OneR writes the 56-byte form in some files and the 20-byte form in
    others, which is why nothing here may key off the model name.
    """
    short = write_file(tmp_path / "s.insp", [(IMU, biased(10, LEVEL_X5))])
    long = write_file(tmp_path / "l.insp", [(IMU, doubles(10, LEVEL_X5))])

    assert imu.entries(short)[0].acceleration == pytest.approx(imu.entries(long)[0].acceleration)


def test_a_record_of_no_known_stride_is_refused(tmp_path):
    path = write_file(tmp_path / "c.insp", [(IMU, b"\x01" * 37)])

    with pytest.raises(FormatError, match="no known entry stride"):
        imu.entries(path)


def test_an_empty_record_is_refused(tmp_path):
    """Two X3 files in one library carry a zero-length inertial record."""
    path = write_file(tmp_path / "d.insp", [(IMU, b"")])

    with pytest.raises(FormatError, match="no known entry stride"):
        imu.entries(path)


def test_unordered_timecodes_are_refused(tmp_path):
    """What a wrong stride looks like: the payload read as the next timecode."""
    payload = biased(5000, LEVEL_X5) + biased(1000, LEVEL_X5)
    path = write_file(tmp_path / "e.insp", [(IMU, payload)])

    with pytest.raises(FormatError, match="no known entry stride"):
        imu.entries(path)


def test_a_missing_record_is_refused(tmp_path):
    """965 OneR stills in one library have no inertial record at all."""
    path = write_file(tmp_path / "f.insp", [(METADATA, b"meta")])

    with pytest.raises(FormatError, match="no inertial record"):
        imu.entries(path)


def test_gravity_is_the_median_not_the_mean(tmp_path):
    """One jolt in a short log must not tilt the horizon."""
    payload = b"".join(
        biased(i * 1000, (-1.0, 0.0, 0.0, 0.0, 0.0, 0.0)) for i in range(1, 5)
    ) + biased(5000, (5.0, 5.0, 5.0, 0.0, 0.0, 0.0))
    path = write_file(tmp_path / "g.insp", [(IMU, payload)])

    assert imu.gravity(path) == pytest.approx((-1.0, 0.0, 0.0))


def test_gravity_up_is_vertical_for_a_level_x5(tmp_path):
    path = write_file(tmp_path / "h.insp", [
        (METADATA, model_record("Insta360 X5")),
        (IMU, biased(1000, LEVEL_X5)),
    ])

    up = imu.gravity_up(path)

    assert up[1] > 0.999, f"a level camera should point straight up, got {up}"


def test_gravity_up_for_a_level_oner_points_where_the_calibration_says(tmp_path):
    """Up is returned in the *render's* frame, not the camera body's.

    A OneR's sensor is mounted a quarter turn round, so a level OneR reads up
    along -x rather than +y -- which is exactly the direction that camera's
    ``Calibration.body_roll`` rotates to vertical.  Two independent sources,
    a calibration string and an accelerometer, agreeing on the same axis.
    """
    path = write_file(tmp_path / "j.insp", [
        (METADATA, model_record("Insta360 OneR")),
        (IMU, biased(1000, (0.995, 0.0, 0.0, 0.0, 0.0, 0.0))),
    ])

    up = imu.gravity_up(path)

    assert up == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6), (
        f"a level OneR should read up along -x, got {up}"
    )


def test_the_two_measured_cameras_read_the_same_thing_differently(tmp_path):
    """Guards the property that makes borrowing a mapping dangerous.

    The same accelerometer reading means a different up on each camera.  If an
    edit ever made them agree, the refusal below would quietly stop being
    load-bearing.
    """
    reading = (0.995, 0.0, 0.0, 0.0, 0.0, 0.0)
    ups = []
    for index, model in enumerate(("Insta360 OneR", "Insta360 X5")):
        path = write_file(tmp_path / f"k{index}.insp", [
            (METADATA, model_record(model)),
            (IMU, biased(1000, reading)),
        ])
        ups.append(imu.gravity_up(path))

    agreement = sum(a * b for a, b in zip(*ups))
    assert abs(agreement) < 0.01, (
        f"the two mappings should send the same reading somewhere different, got {ups}"
    )


def test_gravity_up_refuses_a_camera_whose_axes_are_unmeasured(tmp_path):
    """The X3 is deliberately absent: its readings cannot be reconciled with
    the camera's attitude, so the only honest answer is to refuse.
    """
    path = write_file(tmp_path / "i.insp", [
        (METADATA, model_record("Insta360 X3")),
        (IMU, biased(1000, (-0.614, -0.789, 0.022, 0.0, 0.0, 0.0))),
    ])

    with pytest.raises(FormatError, match="has not been measured"):
        imu.gravity_up(path)
