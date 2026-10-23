"""Per-model lens profiles: read from the right camera, sane, and identical in the port."""

import re
from itertools import pairwise
from pathlib import Path

import pytest
from conftest import write_file

from golblick.vendors.insta360 import lens
from golblick.vendors.insta360.trailer import METADATA

STEP = 2.0  # render.RADIAL_STEP, restated so this test needs no numpy


def model_record(name):
    text = name.encode()
    return b"\x12" + bytes([len(text)]) + text


@pytest.mark.parametrize("model, field_of_view", [
    ("Insta360 OneR", 194.0), ("Insta360 X3", 192.0), ("Insta360 X5", 197.5),
])
def test_the_profile_follows_the_camera_that_wrote_the_file(tmp_path, model, field_of_view):
    path = write_file(tmp_path / "a.insp", [(METADATA, model_record(model))])
    assert lens.lens_profile(path).field_of_view == field_of_view


def test_an_unmeasured_camera_gets_no_profile(tmp_path):
    path = write_file(tmp_path / "a.insp", [(METADATA, model_record("Insta360 Nonesuch"))])
    assert lens.lens_profile(path) is None


@pytest.mark.parametrize("model", sorted(lens.PROFILES))
def test_a_radial_correction_keeps_the_lens_monotone(model):
    """A correction that folded the mapping back would send two directions to
    one pixel, and one on the axis cannot move at all."""
    table = lens.PROFILES[model].radial
    if not table:
        pytest.skip(f"{model} has no measured correction")
    assert table[0] == 0.0
    mapped = [i * STEP + e for i, e in enumerate(table)]
    assert all(b > a for a, b in pairwise(mapped))


def test_the_preview_provider_carries_the_same_table():
    """The PHP port restates the table; a drift between the two is a silent
    difference between the CLI and every preview."""
    php = Path(__file__).parents[1] / "nextcloud-app/lib/Insta360/LensProfile.php"
    text = php.read_text()
    for model, profile in lens.PROFILES.items():
        match = re.search(re.escape(f"'{model}' => [")
                          + r"([\d.]+), \[([^\]]*)\](?:, ([\d.]+))?\]", text)
        assert match, f"{model} missing from {php.name}"
        assert float(match.group(1)) == profile.field_of_view
        values = tuple(float(v) for v in match.group(2).split(",") if v.strip())
        assert values == profile.radial
        guard = float(match.group(3)) if match.group(3) else None
        assert guard == profile.guard_factor


def test_the_preview_provider_faces_the_same_way():
    """Where a still opens is restated in PHP too, and the two must agree."""
    from golblick.vendors import insta360

    php = Path(__file__).parents[1] / "nextcloud-app/lib/Insta360/LensProfile.php"
    match = re.search(r"PHOTO_FORWARD = \[([^\]]*)\]", php.read_text())
    assert match, f"PHOTO_FORWARD missing from {php.name}"
    assert tuple(float(v) for v in match.group(1).split(",")) == insta360.PHOTO_FORWARD


def test_lens_guards_change_the_angle_only_where_measured():
    x5 = lens.PROFILES["Insta360 X5"]
    assert x5.field_of_view_for() == 197.5
    assert x5.field_of_view_for(guards=True) == pytest.approx(197.5 / 1.0225)
    oner = lens.PROFILES["Insta360 OneR"]
    assert oner.field_of_view_for(guards=True) == oner.field_of_view


def test_the_preview_provider_opens_videos_the_same_way():
    """Where a clip opens is restated in PHP for the Nextcloud player."""
    from golblick.vendors import insta360

    php = (Path(__file__).parents[1] / "nextcloud-app/lib/Insta360/LensProfile.php").read_text()
    match = re.search(r"VIDEO_FORWARD = \[(.*)\];", php)
    assert match, "VIDEO_FORWARD missing from LensProfile.php"
    restated = {model: tuple(float(v) for v in values.split(","))
                for model, values in re.findall(r"'([^']+)' => \[([^\]]*)\]", match.group(1))}
    assert restated == insta360.VIDEO_FORWARD


# A two-lens MEI string shaped like an X5's: xi fx fy cx cy yaw pitch roll tx ty tz k1 k2 k3 p1 p2 w h type per lens,
# then one global.  Synthesised, not a camera's.
MEI = "_".join(["2"] + [f"{v:g}" for v in (2.0, 4275, 4275, 2690, 2690, -0.9, 0.1, 90.0, 0, 0, 0, 0.18, 2.1, -3.25,
                                            0, 0, 10752, 5376, 113)]
                + [f"{v:g}" for v in (2.0, 4265, 4265, 8070, 2690, 1.0, 0.0, 89.7, 0, 0, -0.03, 0.18, 2.08, -3.2,
                                      0, 0, 10752, 5376, 113)] + ["198144"])


def mei_record(model):
    text = MEI.encode()
    return model_record(model) + b"\xb2\x03" + bytes([len(text) & 0x7F | 0x80, len(text) >> 7]) + text


def test_the_mei_curve_is_anchored_on_the_axis_and_at_ninety_degrees():
    from golblick.vendors.insta360 import calibration, metadata

    curve = calibration.parse(MEI, metadata.CALIBRATION_MEI).radial_correction(STEP, 51)
    assert curve[0] == 0.0 and curve[45] == 0.0
    # The X5's shape: content sits further out than an equidistant lens puts it, most around 50 degrees.
    assert min(curve[:45]) < -1.0 and 40 <= curve.index(min(curve[:45])) * STEP <= 60
    assert all(b > a for a, b in pairwise(i * STEP + e for i, e in enumerate(curve)))


def test_the_mei_curve_is_read_from_the_mei_model_only():
    from golblick.vendors.insta360 import calibration, metadata

    equidistant = calibration.parse("2_2650_2690_2690_-0.9_0.1_90_2645_8070_2690_1_0_89.7_10752_5376_196864",
                                    metadata.CALIBRATION_EQUIDISTANT)
    with pytest.raises(calibration.CalibrationError):
        equidistant.radial_correction(STEP, 51)


def test_an_x5_takes_its_curve_from_its_own_file(tmp_path):
    with_mei = write_file(tmp_path / "a.insp", [(METADATA, mei_record("Insta360 X5"))])
    without = write_file(tmp_path / "b.insp", [(METADATA, model_record("Insta360 X5"))])
    assert len(lens.lens_profile(with_mei).radial) == 51
    assert lens.lens_profile(without).radial == ()
    # The X3 keeps its measured table, which beats its own MEI curve against Studio's exports.
    x3 = write_file(tmp_path / "c.insp", [(METADATA, mei_record("Insta360 X3"))])
    assert lens.lens_profile(x3).radial == lens.PROFILES["Insta360 X3"].radial


def test_the_preview_provider_takes_the_curve_from_the_file_for_the_same_cameras():
    php = (Path(__file__).parents[1] / "nextcloud-app/lib/Insta360/LensProfile.php").read_text()
    match = re.search(r"RADIAL_FROM_FILE = \[([^\]]*)\]", php)
    assert match, "RADIAL_FROM_FILE missing from LensProfile.php"
    assert set(re.findall(r"'([^']+)'", match.group(1))) == {m for m, p in lens.PROFILES.items() if p.radial_from_file}
