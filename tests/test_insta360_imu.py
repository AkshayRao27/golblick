"""The inertial record, both encodings of it, and what it refuses.

Fixtures are synthesised, as everywhere else in this suite.  The values are
chosen so that a wrong stride cannot accidentally produce a valid-looking read.
"""

import math
import re
import struct
from pathlib import Path

import pytest
from conftest import write_file

from golblick.errors import FormatError
from golblick.vendors.insta360 import imu
from golblick.vendors.insta360.trailer import IMU, METADATA


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


def test_a_rare_repeated_timecode_is_the_clock_not_a_wrong_stride(tmp_path):
    """Two OneR clips repeat a timecode a few times in 100,000 samples."""
    times = list(range(2, 4002, 2))
    times[1000] = times[999]
    payload = b"".join(doubles(t, LEVEL_X5) for t in times)
    path = write_file(tmp_path / "r.insv", [(IMU, payload)])

    assert len(imu.entries(path)) == 2000


def test_frequent_repeated_timecodes_are_refused(tmp_path):
    payload = b"".join(doubles(t // 2 * 2, LEVEL_X5) for t in range(2, 2002))
    path = write_file(tmp_path / "s.insv", [(IMU, payload)])

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

    agreement = sum(a * b for a, b in zip(*ups, strict=True))
    assert abs(agreement) < 0.01, (
        f"the two mappings should send the same reading somewhere different, got {ups}"
    )


def test_gravity_up_refuses_a_camera_whose_axes_are_unmeasured(tmp_path):
    """Refusing is the point: a borrowed mapping produces a confident, wrong
    horizon, so an unknown model must raise rather than guess.

    An invented model name, so measuring a real camera can't make it stale.
    """
    path = write_file(tmp_path / "i.insp", [
        (METADATA, model_record("Insta360 Nonesuch")),
        (IMU, biased(1000, (-0.614, -0.789, 0.022, 0.0, 0.0, 0.0))),
    ])

    with pytest.raises(FormatError, match="has not been measured"):
        imu.gravity_up(path)


def test_both_measured_maps_are_reflections():
    """Guards a finding that looks exactly like a bug.

    Both maps have determinant -1: the stored triple, as this module labels
    it, is not right-handed on either camera.  Flipping a sign back to make
    one a proper rotation would restore the mirrored tilt azimuth that cost
    tilted X5 frames 0.16 of correlation against the camera's own stitch.  A
    candidate map with determinant +1 should be treated as suspect.
    """
    def determinant(rows):
        (a, b, c), (d, e, f), (g, h, i) = rows
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)

    assert determinant(imu._AXES["Insta360 X5"]) == pytest.approx(-1.0)
    assert determinant(imu._AXES["Insta360 OneR"]) == pytest.approx(-1.0)


def test_gravity_up_is_still_vertical_for_a_level_x5(tmp_path):
    """The sign correction must not disturb the upright case -- it did not,
    measured: 0.877 to 0.874 against the stitch, where tilted frames moved
    0.674 to 0.832."""
    path = write_file(tmp_path / "m.insp", [
        (METADATA, model_record("Insta360 X5")),
        (IMU, biased(1000, LEVEL_X5)),
    ])

    up = imu.gravity_up(path)

    assert up[1] > 0.999, f"a level X5 should still point straight up, got {up}"


LEVEL_ONER = (-0.02, -1.01, 0.03, 0.0, 0.0, 0.0)


def burst(tmp_path, stamp, sequence, *, record=True):
    """One frame of a burst: same timestamp, different sequence number."""
    records = [(METADATA, model_record("Insta360 OneR"))]
    if record:
        records.append((IMU, doubles(1000, LEVEL_ONER) + doubles(2000, LEVEL_ONER)))
    return write_file(tmp_path / f"IMG_{stamp}_00_{sequence:03d}.insp", records)


def test_a_frame_with_no_record_takes_one_from_its_burst(tmp_path):
    """The camera writes one inertial reading per shutter press and puts it on
    some frames and not others, so the frame beside it has the answer."""
    donor = burst(tmp_path, "20230913_142237", 1, record=True)
    bare = burst(tmp_path, "20230913_142237", 2, record=False)

    with pytest.raises(FormatError, match="no inertial record"):
        imu.gravity_up(bare)

    assert imu.gravity_up_nearby(bare) == pytest.approx(imu.gravity_up(donor))


def test_it_does_not_reach_into_a_different_shutter_press(tmp_path):
    """A different timestamp is a different moment and a different attitude.
    Borrowing across one would be a confident, wrong horizon."""
    burst(tmp_path, "20230913_142237", 1, record=True)
    bare = burst(tmp_path, "20230913_150000", 2, record=False)

    with pytest.raises(FormatError, match="no inertial record here or in the rest"):
        imu.gravity_up_nearby(bare)


def test_an_unmeasured_camera_is_refused_without_consulting_siblings(tmp_path):
    """Siblings are the same camera by construction, so one cannot supply a
    mapping the camera does not have -- and the error has to say so, rather
    than blaming a missing record."""
    write_file(
        tmp_path / "IMG_20240513_191435_00_001.insp",
        [(METADATA, model_record("Insta360 Nonesuch")),
         (IMU, doubles(1000, LEVEL_ONER) + doubles(2000, LEVEL_ONER))],
    )
    bare = write_file(
        tmp_path / "IMG_20240513_191435_00_002.insp",
        [(METADATA, model_record("Insta360 Nonesuch"))],
    )

    with pytest.raises(FormatError, match="has not been measured"):
        imu.gravity_up_nearby(bare)


def test_the_donor_is_deterministic(tmp_path):
    """Two runs must pick the same frame, or a cached preview and a fresh one
    disagree about the horizon."""
    burst(tmp_path, "20230913_142237", 3, record=True)
    burst(tmp_path, "20230913_142237", 1, record=True)
    bare = burst(tmp_path, "20230913_142237", 2, record=False)

    assert imu.gravity_up_nearby(bare) == imu.gravity_up_nearby(bare)


def test_a_video_levels_its_opening_frame_from_the_start_of_the_record(tmp_path):
    """A video's record covers the whole clip; its opening frame is at the start."""
    held, turned = (-1.0, 0.0, 0.0, 0.0, 0.0, 0.0), (0.0, -1.0, 0.0, 0.0, 0.0, 0.0)
    count = imu.OPENING_SAMPLES
    payload = b"".join(biased(i, held) for i in range(1, count + 1))
    payload += b"".join(biased(i, turned) for i in range(count + 1, 3 * count + 1))
    keyframe = b"\x00" * 22 + b"\x00\x00\x00\x01\x40\x01"
    video = write_file(tmp_path / "VID_20200809_163437_00_026.insv",
                       [(IMU, payload), (0x0200, keyframe + b"0"), (0x0500, keyframe + b"1")],
                       leading=b"\x00\x00\x00\x18ftypisom")
    still = write_file(tmp_path / "IMG_20200809_163437_00_026.insp", [(IMU, payload)])

    assert imu.gravity(video) == pytest.approx((-1.0, 0.0, 0.0))
    assert imu.gravity(still) == pytest.approx((0.0, -1.0, 0.0))


def test_an_x5_video_has_its_own_axes(tmp_path):
    """Its record is stated in a frame turned half way round from its stills'."""
    payload = b"".join(biased(i, LEVEL_X5) for i in range(1, 6))
    records = [(METADATA, model_record("Insta360 X5")), (IMU, payload)]
    still = write_file(tmp_path / "IMG_20260126_115034_00_011.insp", records)
    video = write_file(tmp_path / "VID_20260126_115034_00_011.insv", records,
                       leading=b"\x00\x00\x00\x18ftypisom")

    up_still, up_video = imu.gravity_up(still), imu.gravity_up(video)

    assert up_still[1] == pytest.approx(up_video[1])
    assert up_still[0] == pytest.approx(-up_video[0]) and up_still[2] == pytest.approx(-up_video[2])


def video_metadata(model, first_frame=None, readout=None, offset=None, full_scale=None):
    """Model string, plus fields 24 (frame 0's timecode), 25 (the readout, ms), 28 (frame offset, ms) and 65 (g, degrees per second) when given."""
    out = model_record(model)
    if full_scale is not None:
        g, degrees = full_scale
        inner = b"\x08" + bytes([g]) + b"\x10" + bytes([0x80 | degrees & 0x7F, degrees >> 7])
        out += b"\x8a\x04" + bytes([len(inner)]) + inner
    if readout is not None:
        out += b"\xc9\x01" + struct.pack("<d", readout)
    if offset is not None:
        out += b"\xe1\x01" + struct.pack("<d", offset)
    if first_frame is not None:
        value, varint = first_frame, b""
        while True:
            byte = value & 0x7F
            value >>= 7
            varint += bytes([byte | (0x80 if value else 0)])
            if not value:
                break
        out += b"\xc0\x01" + varint
    return out


def x5_clip(tmp_path, *, first_frame=1_100_000, gyro=(0.1, 0.0, 0.0), log_start=1_000_000, full_scale=(32, 2000)):
    """One second of X5 record at 1 kHz on a microsecond clock, a frame log at
    30 fps starting before the first frame, and fields 24 and 65."""
    samples = b"".join(biased(1_000_000 + i * 1000, LEVEL_X5[:3] + gyro) for i in range(1000))
    log = b"".join(struct.pack("<qd", log_start + i * 33_367, 0.001) for i in range(30))
    records = [(METADATA, video_metadata("Insta360 X5", first_frame, full_scale=full_scale)), (IMU, samples), (0x0400, log)]
    return write_file(tmp_path / "VID_20260126_115034_00_011.insv", records,
                      leading=b"\x00\x00\x00\x18ftypisom")


def test_motion_puts_samples_and_frames_on_one_clock_in_seconds(tmp_path):
    first = 1_000_000 + 3 * 33_367          # the log's fourth entry
    motion = imu.motion(x5_clip(tmp_path, first_frame=first))

    assert motion.sample_times[1] == pytest.approx(0.001)
    assert motion.frame_times[0] == pytest.approx(3 * 0.033367)
    assert motion.frame_times[1] - motion.frame_times[0] == pytest.approx(0.033367)
    assert len(motion.frame_times) == 27


def oner_clip(tmp_path, *, first_frame, readout=None, offset=-12.0, stamps=None, model="Insta360 OneR"):
    """One second of the 56-byte form at 500 Hz on a millisecond clock, and a
    25 fps frame log from 1,000 ms whose exposures alternate, 10 ms and 2 ms."""
    level = (0.0, -1.0, 0.0, 0.0, 0.0, 0.0)
    samples = b"".join(doubles(1000 + 2 * i, level) for i in range(500))
    stamps = stamps or [1000 + 40 * i for i in range(25)]
    log = b"".join(struct.pack("<qd", stamp, 0.010 if i % 2 == 0 else 0.002) for i, stamp in enumerate(stamps))
    records = [(METADATA, video_metadata(model, first_frame, readout, offset)), (IMU, samples), (0x0400, log)]
    return write_file(tmp_path / "VID_20200710_181901_00_001.insv", records,
                      leading=b"\x00\x00\x00\x18ftypisom")


def test_the_56_byte_form_counts_frames_off_from_field_24(tmp_path):
    """Field 24, then the log's own spacing, plus field 28, less half each frame's exposure; the stamps themselves only space the frames."""
    # Stamps 7 ms after field 24's frames and 1 ms of jitter on one of them, as the camera writes them.
    stamps = [1000 + 40 * i + (1 if i == 5 else 0) for i in range(25)]
    motion = imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7, offset=-12.0, stamps=stamps))

    assert len(motion.frame_times) == 22
    assert motion.frame_times[0] == pytest.approx(0.113 - 0.012 - 0.002 / 2)
    assert motion.frame_times[1] == pytest.approx(0.153 - 0.012 - 0.010 / 2)
    assert motion.frame_times[2] == pytest.approx(0.193 - 0.012 - 0.002 / 2)


def test_the_56_byte_form_needs_field_28(tmp_path):
    with pytest.raises(FormatError, match="field 28"):
        imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7, offset=None))


def test_a_56_byte_log_with_a_frame_missing_is_refused(tmp_path):
    """Counting frames off at one spacing is only right if none is missing."""
    stamps = [1000 + 40 * i for i in range(12)] + [1000 + 40 * i for i in range(13, 26)]
    with pytest.raises(FormatError, match="evenly spaced"):
        imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7, stamps=stamps))


def test_the_readout_comes_from_field_25_in_seconds(tmp_path):
    motion = imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7, readout=35.223))

    assert motion.readout == pytest.approx(0.035223)


def test_no_readout_without_field_25(tmp_path):
    assert imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7)).readout == 0.0


def test_a_readout_longer_than_a_frame_is_not_taken(tmp_path):
    """At 25 fps a frame is read within 40 ms; anything longer isn't a readout time."""
    assert imu.motion(oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7, readout=45.0)).readout == 0.0


def _x5_with_readout(tmp_path):
    samples = b"".join(biased(1_000_000 + i * 1000, LEVEL_X5) for i in range(1000))
    log = b"".join(struct.pack("<qd", 1_000_000 + i * 33_367, 0.001) for i in range(30))
    records = [(METADATA, video_metadata("Insta360 X5", 1_000_000, 21.2, full_scale=(32, 2000))), (IMU, samples), (0x0400, log)]
    return write_file(tmp_path / "VID_20260126_115034_00_011.insv", records, leading=b"\x00\x00\x00\x18ftypisom")


def test_the_x5_reads_down_its_rows_too(tmp_path):
    assert imu.motion(_x5_with_readout(tmp_path)).readout == pytest.approx(0.0212)


def test_a_camera_whose_readout_direction_is_unmeasured_is_not_corrected(tmp_path, monkeypatch):
    """The file gives the time, not which way the sensor reads, so only measured models get one."""
    monkeypatch.setattr(imu, "_READS_DOWN", imu._READS_DOWN - {"Insta360 X5"})
    assert imu.motion(_x5_with_readout(tmp_path)).readout == 0.0


def test_the_php_port_times_the_same_forms_by_field_28():
    php = (Path(__file__).parents[1] / "nextcloud-app/lib/Insta360/Imu.php").read_text()
    match = re.search(r"LATE_STAMPS = \[([\d, ]+)\]", php)
    assert match, "LATE_STAMPS missing from Imu.php"
    assert {int(v) for v in match.group(1).split(",")} == imu._LATE_STAMPS


def test_the_php_port_corrects_the_same_cameras_with_as_many_turns():
    app = Path(__file__).parents[1] / "nextcloud-app/lib"
    reads = re.search(r"READS_DOWN = \[([^\]]*)\]", (app / "Insta360/Imu.php").read_text())
    samples = re.search(r"SHUTTER_SAMPLES = (\d+);", (app / "Render/Stabilise.php").read_text())
    assert reads and samples, "READS_DOWN or SHUTTER_SAMPLES missing from the PHP port"
    assert set(re.findall(r"'([^']+)'", reads.group(1))) == imu._READS_DOWN
    from golblick import stabilise
    assert int(samples.group(1)) == stabilise.SHUTTER_SAMPLES


def test_motion_turns_the_gyroscope_with_the_gravity_axes_and_flips_it_for_a_reflection(tmp_path):
    """The X5's map is a reflection, and an angular velocity is an axial vector."""
    motion = imu.motion(x5_clip(tmp_path, first_frame=1_000_000, gyro=(0.1, 0.0, 0.0)))

    # The video map sends (x, y, z) to (z, -x, y); the reflection flips that.
    # 0.1 is 100 counts of 2000 / 32768 degrees per second.
    assert tuple(motion.angular_velocity[:3]) == pytest.approx((0.0, 100 * math.radians(2000) / 32768, 0.0))
    up = imu.gravity_up(x5_clip(tmp_path, first_frame=1_000_000))
    assert tuple(motion.up[:3]) == pytest.approx(up)


def test_the_20_byte_form_counts_in_field_65_s_full_scale(tmp_path):
    """1,024 counts of 32 g is 1 g, and 1,000 of them aren't; the gyroscope scales with its own range."""
    small = imu.motion(x5_clip(tmp_path, gyro=(0.1, 0.0, 0.0), full_scale=(32, 2000)))
    large = imu.motion(x5_clip(tmp_path, gyro=(0.1, 0.0, 0.0), full_scale=(32, 4000)))

    assert small.gravity[0] == pytest.approx(1.0, abs=1e-3)
    assert large.angular_velocity[1] == pytest.approx(2 * small.angular_velocity[1])


@pytest.mark.parametrize("clip", ["x5", "oner"])
def test_reading_with_numpy_gives_the_same_numbers_as_without(tmp_path, monkeypatch, clip):
    pytest.importorskip("numpy")
    path = x5_clip(tmp_path, gyro=(0.1, -0.2, 0.03)) if clip == "x5" else oner_clip(tmp_path, first_frame=1000 + 3 * 40 - 7)
    fast, opening = imu.motion(path), imu.gravity(path)
    monkeypatch.setattr(imu, "_numpy", lambda: None)
    slow = imu.motion(path)

    for name in ("sample_times", "angular_velocity", "up", "gravity", "frame_times"):
        assert getattr(fast, name).tobytes() == getattr(slow, name).tobytes(), name
    assert opening == imu.gravity(path)


def test_the_20_byte_form_needs_field_65(tmp_path):
    with pytest.raises(FormatError, match="field 65"):
        imu.motion(x5_clip(tmp_path, full_scale=None))


def test_motion_refuses_a_still(tmp_path):
    path = write_file(tmp_path / "a.insp", [(METADATA, video_metadata("Insta360 X5", 1)),
                                            (IMU, biased(1, LEVEL_X5) + biased(2, LEVEL_X5))])

    with pytest.raises(FormatError, match="not a video"):
        imu.motion(path)


def test_motion_refuses_a_clip_without_the_first_frame_time(tmp_path):
    with pytest.raises(FormatError, match="field 24"):
        imu.motion(x5_clip(tmp_path, first_frame=None))


def test_motion_refuses_a_first_frame_outside_the_record(tmp_path):
    with pytest.raises(FormatError, match="outside the inertial record"):
        imu.motion(x5_clip(tmp_path, first_frame=5_000_000))


def test_motion_refuses_a_first_frame_the_log_does_not_hold(tmp_path):
    with pytest.raises(FormatError, match="not in the frame log"):
        imu.motion(x5_clip(tmp_path, first_frame=1_500_000, log_start=1_000_000 - 30 * 33_367))


def test_the_player_asks_for_the_current_steadying_track():
    """The browser keeps a track for a day, so its address carries MotionStore's version."""
    app = Path(__file__).parents[1] / "nextcloud-app"
    store = re.search(r"const VERSION = (\d+);", (app / "lib/Service/MotionStore.php").read_text())
    url = re.search(r"&v=(\d+)`", (app / "src/overlay.ts").read_text())
    assert store and url, "MotionStore::VERSION or motionUrl's v is missing"
    assert store.group(1) == url.group(1)
