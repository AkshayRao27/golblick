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
                          + r"([\d.]+), \[([^\]]*)\](?:, ([\d.]+))?(?:, ([\d.]+))?\]", text)
        assert match, f"{model} missing from {php.name}"
        assert float(match.group(1)) == profile.field_of_view
        values = tuple(float(v) for v in match.group(2).split(",") if v.strip())
        assert values == profile.radial
        video = float(match.group(3)) if match.group(3) else None
        guard = float(match.group(4)) if match.group(4) else None
        assert (video, guard) == (profile.video_field_of_view, profile.guard_factor)


def test_video_and_lens_guards_change_the_angle_only_where_measured():
    x5 = lens.PROFILES["Insta360 X5"]
    assert x5.field_of_view_for() == 197.5
    assert x5.field_of_view_for(video=True) == 195.3
    assert x5.field_of_view_for(video=True, guards=True) == pytest.approx(195.3 / 1.0225)
    oner = lens.PROFILES["Insta360 OneR"]
    assert oner.field_of_view_for(video=True, guards=True) == oner.field_of_view
