"""Stitching a whole video: the per-frame tables, checked without ffmpeg, and the 360 tag with it."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

numpy = pytest.importorskip("numpy")

from test_render import synthetic_pair  # noqa: E402

from golblick import render, stabilise, video  # noqa: E402

SIZE = 256   # the synthetic pair's lens size; the output is SIZE x SIZE / 2


def _plan(lenses, turns, orientation):
    return video.Plan(lenses, SIZE, SIZE, 194.0, None, numpy.asarray(orientation, float), turns, [])


def _apply(tables: bytes, image, width):
    """What ffmpeg's remap and maskedmerge do with a frame's tables: nearest pixel, then the mask."""
    height = width // 2
    stack = numpy.frombuffer(tables, "<u2").reshape(-1, width)
    x0, y0, x1, y1, mask = (stack[k * height:(k + 1) * height].astype(int) for k in range(5))
    lens0, lens1 = image[:, :SIZE].astype(float), image[:, SIZE:].astype(float)
    share = ((mask // 257) / 255.0)[..., None]
    return (1 - share) * lens0[y0, x0] + share * lens1[y1, x1]


def test_quaternion_matrix_is_the_rotation_stabilise_means():
    q = stabilise._normalise((0.9, 0.2, -0.3, 0.25))
    matrix = video.quaternion_matrix(q)

    assert numpy.allclose(matrix @ matrix.T, numpy.eye(3), atol=1e-12)
    back = stabilise._quaternion(matrix)
    assert numpy.allclose(back, q, atol=1e-9) or numpy.allclose(back, [-c for c in q], atol=1e-9)


def test_a_frame_rendered_with_its_turn_is_the_levelled_frame_turned():
    """The one-pass claim: tables made with R @ O give the levelled render seen through R.

    Built from the frame's own tables as ffmpeg would apply them, and compared
    with the library's independent route (render, then rotate).  The wrong
    composition, Rᵀ, has to come out far worse, or the test can't tell them apart.
    """
    image, lenses = synthetic_pair(size=SIZE)
    level = render.rotation(10.0, 5.0, 0.0)
    turn = stabilise._quaternion(render.rotation(25.0, -10.0, 8.0))
    plan = _plan(lenses, [turn], level)

    one_pass = _apply(video.frame_tables(plan, video.frame_orientation(plan, 0)), image, SIZE)
    levelled, _ = render.equirectangular(image, lenses, (SIZE, SIZE // 2), 194.0, orientation=level)
    two_pass = render.rotate(levelled, video.quaternion_matrix(turn)).astype(float)
    wrong = render.rotate(levelled, video.quaternion_matrix(turn).T).astype(float)

    seen = (two_pass > 2).all(-1)
    assert seen.sum() > 10000
    right_error = numpy.abs(one_pass - two_pass)[seen].mean()
    assert right_error < 6.0
    assert numpy.abs(one_pass - wrong)[seen].mean() > 4 * right_error


def test_a_frame_beyond_the_motion_record_keeps_the_last_turn():
    image, lenses = synthetic_pair(size=SIZE)
    turns = [stabilise._quaternion(render.rotation(a, 0.0, 0.0)) for a in (0.0, 30.0)]
    plan = _plan(lenses, turns, numpy.eye(3))

    assert numpy.allclose(video.frame_orientation(plan, 5), video.frame_orientation(plan, 1))
    assert numpy.allclose(video.frame_orientation(_plan(lenses, None, numpy.eye(3)), 5), numpy.eye(3))


def test_tables_made_in_bands_are_the_tables_made_whole(monkeypatch):
    _, lenses = synthetic_pair(size=SIZE)
    plan = _plan(lenses, None, render.rotation(20.0, 10.0, -5.0))

    monkeypatch.setattr(video, "BAND", 7)   # uneven, so the last band is short
    banded = video.frame_tables(plan, plan.orientation)
    monkeypatch.setattr(video, "BAND", 10_000)
    whole = video.frame_tables(plan, plan.orientation)

    assert banded == whole
    width, height, _, _ = video.layout(SIZE)
    assert len(whole) == 2 * width * height


def test_the_balance_matches_the_nextcloud_app():
    """The app restates these numbers; a change to one side has to reach the other."""
    php = (Path(__file__).parents[1] / "nextcloud-app/lib/Render/RemapTables.php").read_text()
    constants = dict(re.findall(r"const (STRIP_AROUND|STRIP_ACROSS|LADDER|BALANCE_REACH) = ([\d.]+);", php))

    assert int(constants["STRIP_AROUND"]) == render.STRIP_AROUND
    assert int(constants["STRIP_ACROSS"]) == render.STRIP_ACROSS
    assert int(constants["LADDER"]) == render.LADDER
    assert float(constants["BALANCE_REACH"]) == render.BALANCE_REACH
    renderer = (Path(__file__).parents[1] / "nextcloud-app/lib/Service/VideoRenderer.php").read_text()
    assert "BITS_PER_PIXEL_SECOND = 20e6 / (3840 * 1920)" in renderer
    assert video.BITS_PER_PIXEL_SECOND == 20e6 / (3840 * 1920)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
@pytest.mark.parametrize("faststart", [True, False])
def test_the_copy_is_marked_as_360_and_still_plays(tmp_path, faststart):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x32:rate=10:duration=1",
                    "-c:v", "libx264", *(["-movflags", "+faststart"] if faststart else []), str(clip)],
                   check=True)

    assert video.tag_spherical(clip)
    assert video.tag_spherical(clip)   # once only
    data = clip.read_bytes()
    assert data.count(b"uuid" + video._UUID) == 1
    assert b"<GSpherical:ProjectionType>equirectangular" in data
    decoded = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                              "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(clip)],
                             capture_output=True, text=True, check=True)
    assert decoded.stdout.strip().strip(",") == "10"
