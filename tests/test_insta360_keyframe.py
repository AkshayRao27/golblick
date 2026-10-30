import shutil
import subprocess

import pytest
from conftest import write_file

from golblick.errors import FormatError, ThumbnailError
from golblick.vendors.insta360 import extract_keyframes, extract_preview
from golblick.vendors.insta360.keyframe import DUAL_FISHEYE, LENS_PAIR, parse

HEADER = b"\x00\x00\x01\x34" + b"\x00" * 12 + b"\x00\x02\x00\x01\x10\x10"  # 22 bytes, as a OneR writes it
HEVC = b"\x00\x00\x00\x01\x40\x01" + b"lens"  # starts with a video parameter set
H264 = b"\x00\x00\x00\x01\x67\x4d" + b"lens"  # starts with a sequence parameter set


def test_a_master_carries_one_keyframe_per_lens(tmp_path):
    path = write_file(tmp_path / "VID_20200809_163437_00_026.insv",
                      [(0x0200, HEADER + HEVC + b"0"), (0x0500, HEADER + HEVC + b"1")], leading=b"mp4")

    frames = extract_keyframes(path)

    assert (frames.codec, frames.layout) == ("hevc", LENS_PAIR)
    assert frames.streams == (HEVC + b"0", HEVC + b"1")


def test_a_proxy_stores_one_dual_fisheye_frame_twice():
    frames = parse(HEADER + H264, HEADER + H264)

    assert (frames.codec, frames.layout, frames.streams) == ("h264", DUAL_FISHEYE, (H264,))


@pytest.mark.parametrize("lens0, lens1, message", [
    (b"\x01" * 40 + b"nv12", None, "not a video keyframe"),       # an X5's NV12 stitch
    (HEADER + HEVC, None, "missing"),
    (HEADER + HEVC, HEADER + H264, "different codecs"),
    (HEADER + b"\x00\x00\x00\x01\x26\x01", HEADER + HEVC, "not a parameter set"),
])
def test_anything_else_is_refused(lens0, lens1, message):
    with pytest.raises(FormatError, match=message):
        parse(lens0, lens1)


def test_the_preview_reader_says_what_a_keyframe_record_is(tmp_path):
    path = write_file(tmp_path / "v.insv", [(0x0200, HEADER + HEVC + b"\x00" * 40)], leading=b"mp4")

    with pytest.raises(ThumbnailError, match="video keyframe"):
        extract_preview(path)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_cli_decodes_both_lenses_and_puts_lens_0_on_the_left():
    numpy = pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    from golblick import cli

    def encode(colour):
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color={colour}:size=64x64:duration=0.04",
             "-frames:v", "1", "-c:v", "libx264", "-f", "h264", "pipe:1"],
            capture_output=True, check=True).stdout

    image = cli._decode_keyframes(parse(HEADER + encode("red"), HEADER + encode("blue")))

    assert image.shape == (64, 128, 3)
    left, right = image[:, :64].mean(axis=(0, 1)), image[:, 64:].mean(axis=(0, 1))
    assert left[0] > 200 > left[2] and right[2] > 200 > right[0]
    assert numpy.all(image[:, :64, 0] > image[:, :64, 2])


def _master(path, layout=LENS_PAIR):
    second = HEADER + HEVC + (b"1" if layout == LENS_PAIR else b"0")
    return write_file(path, [(0x0200, HEADER + HEVC + b"0"), (0x0500, second)], leading=b"mp4")


def test_a_oner_or_x3_clip_finds_its_second_lens_beside_it(tmp_path):
    from golblick.vendors.insta360 import lens_streams

    master = _master(tmp_path / "VID_20200809_163437_00_026.insv")
    partner = tmp_path / "VID_20200809_163437_10_026.insv"
    partner.write_bytes(b"mp4")

    assert lens_streams(master) == [(master, 0), (partner, 0)]


def test_a_missing_second_lens_file_is_refused_not_stitched_from_one_lens(tmp_path):
    from golblick.vendors.insta360 import lens_streams

    master = _master(tmp_path / "VID_20200809_163437_00_026.insv")
    with pytest.raises(FormatError, match="_10_026.insv, is not next to it"):
        lens_streams(master)
    renamed = _master(tmp_path / "holiday.insv")
    with pytest.raises(FormatError, match="can't be found"):
        lens_streams(renamed)


def test_an_x5_clip_has_both_lenses_in_one_file_in_the_order_it_states_and_a_proxy_is_refused(tmp_path):
    from golblick.vendors.insta360 import lens_streams

    stitch = (0x0200, b"\x01" * 40 + b"nv12")
    x5 = write_file(tmp_path / "VID_20260126_115034_00_011.insv", [stitch, (0x0101, b"\x80\x05\x01")],
                    leading=b"mp4")
    assert lens_streams(x5) == [(x5, 1), (x5, 0)]   # field 80 = 1: track 0 holds lens 1
    unstated = write_file(tmp_path / "VID_20260126_115034_00_012.insv", [stitch, (0x0101, b"\x10\x02")],
                          leading=b"mp4")
    with pytest.raises(FormatError, match="field 80 is None"):
        lens_streams(unstated)
    proxy = _master(tmp_path / "LRV_20200809_163437_01_026.lrv", layout=DUAL_FISHEYE)
    with pytest.raises(FormatError, match="low-resolution copy"):
        lens_streams(proxy)
