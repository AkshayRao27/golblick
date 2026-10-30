"""Stitching a whole video: the per-frame tables, checked without ffmpeg, and the 360 tag with it."""

import dataclasses
import shutil
import subprocess
import types
from fractions import Fraction
from pathlib import Path

import pytest

numpy = pytest.importorskip("numpy")

from test_render import synthetic_pair  # noqa: E402

from golblick import render, scene, stabilise, video  # noqa: E402

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


def test_a_frame_s_rolling_shutter_reaches_its_own_tables():
    """Frame k's tables use frame k's turns across the readout; a frame with none matches the plain tables."""
    _, lenses = synthetic_pair(size=SIZE)
    still = (1.0, 0.0, 0.0, 0.0)
    turned = stabilise._quaternion(render.rotation(3.0, 0.0, 0.0))
    plan = _plan(lenses, None, numpy.eye(3))
    plain = video.frame_tables(plan, plan.orientation)
    read = dataclasses.replace(plan, shutter=[(still,) * 5, (turned,) + (still,) * 4])

    assert video.frame_tables(read, read.orientation, video.frame_shutter(read, 0)) == plain
    assert video.frame_tables(read, read.orientation, video.frame_shutter(read, 1)) != plain
    assert numpy.allclose(video.frame_shutter(read, 9), video.frame_shutter(read, 1))


def test_tables_made_in_bands_are_the_tables_made_whole(monkeypatch):
    _, lenses = synthetic_pair(size=SIZE)
    plan = _plan(lenses, None, render.rotation(20.0, 10.0, -5.0))

    monkeypatch.setattr(video, "BAND", 7)   # uneven, so the last band is short
    banded = video.frame_tables(plan, plan.orientation)
    monkeypatch.setattr(video, "BAND", 10_000)
    whole = video.frame_tables(plan, plan.orientation)

    assert banded == whole
    width, height = video.layout(SIZE)
    assert len(whole) == 2 * width * height


def test_the_wide_band_reaches_further_and_only_where_both_lenses_see():
    _, lenses = synthetic_pair(size=SIZE)
    coarse = numpy.deg2rad(scene.SEAM_COARSE)
    maps, share, wide = render.remap_tables(lenses, (1024, 512), 194.0, lens_size=SIZE, coarse=coarse)
    both = maps[0][2] & maps[1][2]

    assert ((wide >= 0) & (wide <= 1)).all()
    assert numpy.array_equal(wide[~both], share[~both])
    handing = lambda weight: ((weight > 0.05) & (weight < 0.95)).sum()   # noqa: E731
    assert handing(wide) > 2.5 * handing(share)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_copy_hands_a_brightness_step_over_across_the_wide_band(tmp_path):
    """Two flat lenses blur to themselves, so the graph has to give exactly the wide band's blend."""
    _, lenses = synthetic_pair(size=SIZE)
    plan = _plan(lenses, None, render.rotation(20.0, 10.0, -5.0))
    tables = video.frame_tables(plan, plan.orientation)
    (tmp_path / "tables.raw").write_bytes(tables)
    clip = types.SimpleNamespace(rate=Fraction(10), lenses=[(None, 0), (None, 0)])
    graph = video._graph(clip, plan, {"lens0": 0, "lens1": 1, "tables": 2})
    width, height = video.layout(SIZE)
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x646464:s={SIZE}x{SIZE}:r=10:d=0.1",
         "-f", "lavfi", "-i", f"color=c=0x8c8c8c:s={SIZE}x{SIZE}:r=10:d=0.1",
         "-f", "rawvideo", "-pix_fmt", "gray16le", "-s", f"{width}x{height}", "-framerate", "10",
         "-i", str(tmp_path / "tables.raw"), "-filter_complex", graph, "-map", "[out]", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    luma = numpy.frombuffer(out, numpy.uint8)[:SIZE * SIZE // 2].reshape(SIZE // 2, SIZE).astype(float)
    stack = numpy.frombuffer(tables, "<u2").reshape(-1, SIZE)
    share, wide = ((stack[k * SIZE // 2:(k + 1) * SIZE // 2] // 257) / 255.0 for k in (4, 5))
    low, high = numpy.percentile(luma, [0.5, 99.5])

    seen = (luma - low) / (high - low)

    assert high - low > 30
    assert numpy.abs(seen - wide).max() < 0.06
    assert numpy.abs(seen - share).max() > 3 * numpy.abs(seen - wide).max()   # not the one-band blend


def test_the_two_bands_match_the_nextcloud_app():
    """The app restates these numbers; a change to one side has to reach the other."""
    php = (Path(__file__).parents[1] / "nextcloud-app/lib/Render/RemapTables.php").read_text()
    assert f"COARSE_DEGREES = {scene.SEAM_COARSE};" in php
    renderer = (Path(__file__).parents[1] / "nextcloud-app/lib/Service/VideoRenderer.php").read_text()
    assert f"BLUR_DEGREES = {video.BLUR};" in renderer
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


def _pattern(direction):
    """synthetic_pair's scene, by camera-frame direction: what each output pixel ought to show."""
    x, y, z = direction[..., 0], direction[..., 1], direction[..., 2]
    lon, lat = numpy.arctan2(x, z), numpy.arcsin(numpy.clip(y, -1, 1))
    return numpy.stack([(numpy.sin(lon * 2) * 0.5 + 0.5) * 255, (numpy.sin(lat * 3) * 0.5 + 0.5) * 255,
                        (numpy.cos(lon + lat) * 0.5 + 0.5) * 255], -1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
def test_a_whole_clip_stitches_to_the_scene_its_lenses_recorded(tmp_path):
    """The whole video path, file to file: a synthetic X5-style clip (both
    lenses as streams of one MP4, lens 1 first as field 80 says, a trailer
    with the calibration), through video.stitch, compared with the scene the
    lenses were painted from -- the pattern's own formula, not anything the
    renderer computes."""
    from conftest import build_trailer
    from PIL import Image

    from golblick.vendors import detect
    from golblick.vendors.insta360 import METADATA

    image, _ = synthetic_pair(SIZE)
    for index in range(2):
        Image.fromarray(image[:, index * SIZE:(index + 1) * SIZE]).save(tmp_path / f"lens{index}.png")
    clip = tmp_path / "VID_20260101_120000_00_001.insv"
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-loop", "1", "-framerate", "10", "-t", "1", "-i", str(tmp_path / "lens1.png"),
                    "-loop", "1", "-framerate", "10", "-t", "1", "-i", str(tmp_path / "lens0.png"),
                    "-map", "0:v", "-map", "1:v", "-c:v", "libx264", "-crf", "4", "-pix_fmt", "yuv444p",
                    "-f", "mp4", str(clip)], check=True)

    def text(number, value):
        def varint(n):
            out = b""
            while True:
                out += bytes([n & 0x7F | (0x80 if n > 0x7F else 0)])
                n >>= 7
                if not n:
                    return out
        return varint(number << 3 | 2) + varint(len(value)) + value

    c = (SIZE - 1) / 2
    calibration = (f"2_{SIZE / 2 - 2}_{c}_{c}_0_0_90_{SIZE / 2 - 2}_{SIZE + c}_{c}_0_0_90"
                   f"_{2 * SIZE}_{SIZE}_100").encode()
    with clip.open("ab") as handle:
        track_order = b"\x80\x05\x01"   # field 80 = 1, as on every X5 clip
        handle.write(build_trailer([(METADATA, text(2, b"Insta360 Test") + text(5, calibration) + track_order)]))

    vendor = detect(str(clip))
    output = tmp_path / "stitched.360.mp4"
    plan = video.stitch(vendor, str(clip), output, width=2 * SIZE, steady=False, say=lambda _line: None)

    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,nb_read_frames", "-of", "csv=p=0",
                            str(output)], capture_output=True, text=True, check=True)
    probe = probe.stdout.strip().strip(",")
    assert probe == f"{2 * SIZE},{SIZE},10"
    assert b"<GSpherical:ProjectionType>equirectangular" in output.read_bytes()

    frame = tmp_path / "frame.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(output), "-frames:v", "1", str(frame)],
                   check=True)
    got = numpy.asarray(Image.open(frame).convert("RGB"), float)
    height, width = got.shape[:2]
    # Each output pixel's direction in the camera frame, which is where the pattern is defined.
    rays = render._rays(width, height) @ numpy.asarray(plan.orientation, float)
    keep = slice(0, height - 12)   # the frame-number strip along the bottom is the player's, not the scene
    error = numpy.abs(got - _pattern(rays))[keep]
    assert error.mean() < 6, error.mean()
    # And a mirror of the scene doesn't pass: the test can tell.
    mirrored = numpy.abs(got - _pattern(rays * numpy.array([-1.0, 1.0, 1.0])))[keep]
    assert mirrored.mean() > 4 * error.mean()


def test_planning_frames_move_to_keyframes_but_stay_distinct():
    keyframes = [0.0, 2.0, 4.0, 6.0]

    assert video.probe_times([0.3, 2.4, 5.1], keyframes) == [0.0, 2.0, 6.0]
    # Two moments nearest the same keyframe: the second keeps its own time.
    assert video.probe_times([1.9, 2.1, 6.5], keyframes) == [2.0, 2.1, 6.0]
    # No index to go by: the moments as asked.
    assert video.probe_times([1.0, 3.0], []) == [1.0, 3.0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_lenses_and_tables_stay_on_the_same_frame():
    """Two streams with the stitch's two time bases, paired by a filter that syncs on time, frame k with frame k.

    The lens comes from a file at time base 1/30000, the tables from a pipe at 30000/1001, and each frame's grey is
    its number, so a pairing one frame out shows as a difference.
    """
    from fractions import Fraction

    rate = Fraction(30000, 1001)
    frames = 60
    clock = video.frame_clock(rate)
    tables = b"".join(bytes([4 * k]) * 64 for k in range(frames))
    graph = (f"[0:v]{clock},format=gray[lens];[1:v]{clock},format=gray[tables];"
             f"[lens][tables]blend=all_mode=difference,format=gray[out]")
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"nullsrc=s=8x8:r={rate}:d={float(frames / rate):.6f},format=gray,geq=lum='4*N',settb=1/30000",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", "8x8", "-framerate", str(rate), "-i", "pipe:0",
         "-filter_complex", graph, "-map", "[out]", "-f", "rawvideo", "-"],
        input=tables, capture_output=True, check=True)
    differences = [max(result.stdout[k * 64:(k + 1) * 64]) for k in range(len(result.stdout) // 64)]
    assert len(differences) >= frames - 1
    assert max(differences) == 0
