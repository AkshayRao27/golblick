"""The player's decoder: frames labelled with their index, both lenses in step and in order."""

import shutil
import subprocess
from fractions import Fraction

import pytest

from golblick import playback, video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

SIZE = 64
FRAMES = 30


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """Two streams in one file, as an X5 records them: frame k is grey 8k on lens 0 and 255 - 8k on lens 1."""
    path = tmp_path_factory.mktemp("clip") / "pair.mkv"
    lens = f"nullsrc=s={SIZE}x{SIZE}:r=10:d={FRAMES / 10},format=gray,geq=lum='8*N'"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", lens, "-f", "lavfi", "-i", lens,
         "-filter_complex", "[0:v]format=yuv420p[a];[1:v]negate,format=yuv420p[b]",
         "-map", "[a]", "-map", "[b]", "-c:v", "ffv1", str(path)],
        check=True)
    return video.Clip(((path, 0), (path, 1)), SIZE, Fraction(10), FRAMES, FRAMES / 10, False, None)


def _tv(grey):
    """Where yuv420p, limited range, stores a grey: black at 16, white at 235."""
    return 16 + grey * 219 / 255


def _greys(frame):
    luma0, _ = frame.planes(0)
    luma1, _ = frame.planes(1)
    return sum(luma0) / len(luma0), sum(luma1) / len(luma1)


def test_frames_come_in_order_with_both_lenses_from_the_same_moment(clip):
    decoder = playback.Decoder(clip, SIZE, 0, gpu=False)
    try:
        for k in range(10):
            frame = decoder.next(timeout=20)
            first, second = _greys(frame)
            assert frame.index == k
            assert first == pytest.approx(_tv(8 * k), abs=2)
            assert second == pytest.approx(_tv(255 - 8 * k), abs=2)
    finally:
        decoder.close()


def test_a_seek_lands_on_the_frame_it_is_labelled_with(clip):
    """Steadying turns each frame by its own index, so a label one off tilts the picture."""
    decoder = playback.Decoder(clip, SIZE, 17, gpu=False)
    try:
        frame = decoder.next(timeout=20)
        assert frame.index == 17
        assert _greys(frame)[0] == pytest.approx(_tv(8 * 17), abs=2)
    finally:
        decoder.close()


def test_the_end_of_the_clip_is_a_none(clip):
    decoder = playback.Decoder(clip, SIZE, FRAMES - 2, gpu=False)
    try:
        assert decoder.next(timeout=20).index == FRAMES - 2
        assert decoder.next(timeout=20).index == FRAMES - 1
        assert decoder.next(timeout=20) is None
        assert decoder.error is None
    finally:
        decoder.close()


def test_the_gpu_command_scales_on_the_gpu_and_stacks_lens_0_on_top(clip):
    command = playback.command(clip, 1440, 30, gpu=True)
    graph = command[command.index("-filter_complex") + 1]
    assert command.count("-hwaccel") == 1           # one file holds both lenses
    assert "[0:v:0]scale_cuda=1440:1440" in graph and "[0:v:1]scale_cuda=1440:1440" in graph
    assert "[a][b]vstack" in graph
    assert command[command.index("-ss") + 1] == "3.000000"


def test_a_video_scene_turns_each_frame_after_the_opening():
    """The player's per-frame rotation is the stitch's: the frame's turn after the faced opening."""
    numpy = pytest.importorskip("numpy")
    from golblick import scene

    opening = video.quaternion_matrix((0.9, 0.1, -0.3, 0.2) / numpy.linalg.norm((0.9, 0.1, -0.3, 0.2)))
    turn = tuple((0.8, -0.2, 0.5, 0.1) / numpy.linalg.norm((0.8, -0.2, 0.5, 0.1)))
    played = scene.VideoScene(None, None, 64, tuple(map(tuple, opening)), ((1.0, 0.0, 0.0, 0.0), turn))
    assert numpy.asarray(played.camera_from_world(0)) == pytest.approx(opening.T)
    assert numpy.asarray(played.camera_from_world(1)) == pytest.approx((video.quaternion_matrix(turn) @ opening).T)
    # Past the end of the record, the last turn holds.
    assert played.camera_from_world(9) == played.camera_from_world(1)
