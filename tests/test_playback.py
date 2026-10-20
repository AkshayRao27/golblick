"""The player's decoder: frames labelled with their index, both lenses in step and in order."""

import shutil
import subprocess
import time
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


def test_ffmpeg_built_with_cuda_but_without_a_card_decodes_on_the_processor(monkeypatch):
    """Most packaged ffmpeg builds list cuda whether or not there is a card."""
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "-1")
    assert playback.hardware.__wrapped__() is False


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


@pytest.fixture(scope="module")
def sounding(tmp_path_factory):
    """A clip whose sound rises steadily, a tenth of full scale a second, so a sample says when it is."""
    path = tmp_path_factory.mktemp("sound") / "sound.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"nullsrc=s={SIZE}x{SIZE}:r=10:d={FRAMES / 10}",
         "-f", "lavfi", "-i", f"aevalsrc=0.1*t|0.1*t:s=48000:d={FRAMES / 10}",
         "-map", "0:v", "-map", "1:a", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(path)],
        check=True)
    return video.Clip(((path, 0), (path, 0)), SIZE, Fraction(10), FRAMES, FRAMES / 10, True, None)


def _first_sample(sound):
    for _ in range(200):
        data = sound.read(4)
        if data:
            return int.from_bytes(data[:2], "little", signed=True)
        time.sleep(0.01)
    raise AssertionError("no sound decoded")


def test_the_sound_starts_where_the_picture_does(sounding):
    sound = playback.Sound(sounding, 17)
    try:
        assert _first_sample(sound) / 32767 == pytest.approx(0.17, abs=0.002)
    finally:
        sound.close()


def test_the_sound_comes_in_whole_samples_and_ends(sounding):
    sound = playback.Sound(sounding, FRAMES - 5)
    try:
        total = 0
        while not sound.finished:
            data = sound.read(1001)
            assert len(data) % 4 == 0 and len(data) <= 1000
            total += len(data)
            if not data:
                time.sleep(0.01)
        assert total == pytest.approx(0.5 * playback.BYTES_PER_SECOND, abs=4 * 1024)
    finally:
        sound.close()


def test_a_video_scene_locks_by_turning_back_each_frame_heading():
    numpy = pytest.importorskip("numpy")
    from golblick import scene, stabilise

    opening = numpy.eye(3)
    turn = tuple((0.8, -0.2, 0.5, 0.1) / numpy.linalg.norm((0.8, -0.2, 0.5, 0.1)))
    played = scene.VideoScene(None, None, 64, tuple(map(tuple, opening)), ((1.0, 0.0, 0.0, 0.0), turn), (0.0, 0.7))
    locked = stabilise.locked([turn], [0.7])[0]
    assert numpy.asarray(played.camera_from_world(1, lock=True)) == pytest.approx(video.quaternion_matrix(locked).T)
    assert played.camera_from_world(1, steady=False) == played.camera_from_world(0)


def test_the_end_still_arrives_when_the_player_is_slow(clip):
    """The decoder fills its queue and finishes before anything is read; the end must not be dropped."""
    decoder = playback.Decoder(clip, SIZE, FRAMES - playback.AHEAD, gpu=False)
    try:
        time.sleep(1.0)
        got = [decoder.next(timeout=20) for _ in range(playback.AHEAD + 1)]
        assert [frame.index for frame in got[:-1]] == list(range(FRAMES - playback.AHEAD, FRAMES))
        assert got[-1] is None
    finally:
        decoder.close()


def test_a_card_that_fails_on_the_clip_hands_it_to_the_cpu(clip, monkeypatch):
    """Before its first frame: the same frames, from the CPU, and the card's error kept to say why."""
    real = playback.command

    def card_fails(clip, size, start, gpu):
        if gpu:
            return [playback.binaries()[0], "-v", "error", "-nostdin", "-init_hw_device", "nosuchdevice", "-f", "null", "-"]
        return real(clip, size, start, gpu)

    monkeypatch.setattr(playback, "command", card_fails)
    decoder = playback.Decoder(clip, SIZE, 5, gpu=True)
    try:
        first = decoder.next(timeout=30)
    finally:
        decoder.close()
    assert first is not None and first.index == 5
    assert decoder.gpu is False and decoder.fell_back and decoder.error is None


def _nv12_pair(index, size, lens0, lens1):
    """A playback.Frame whose two lenses are flat grey at luma ``lens0`` and ``lens1``, chroma neutral."""
    luma = size * size
    data = bytes([lens0]) * luma + bytes([lens1]) * luma + bytes([128]) * (luma // 2) * 2
    return playback.Frame(index, size, data)


def _strips(size):
    numpy = pytest.importorskip("numpy")
    rows, columns = numpy.mgrid[0:16, 0:720]
    at = (rows * 3 % size).astype(numpy.uint16), (columns % size).astype(numpy.uint16)
    return {"s0y": at[0], "s0x": at[1], "s1y": at[0], "s1x": at[1]}


def _balance(size=64):
    from golblick import scene

    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return scene.LensBalance(_strips(size), size, (0.0, 0.5, 0.5), (1.0, 1.0, 1.0), identity)


def test_the_lens_balance_moves_each_lens_half_way_to_the_other():
    numpy = pytest.importorskip("numpy")
    correction = _balance().update(_nv12_pair(0, 64, 100, 110))

    assert correction.shape == (720, 3)
    assert numpy.allclose(correction[:, 0], 5.0)   # luma reads straight through the identity matrix


def test_the_lens_balance_leaves_out_white_and_stops_at_its_limit():
    numpy = pytest.importorskip("numpy")
    from golblick import scene

    assert numpy.allclose(_balance().update(_nv12_pair(0, 64, 100, 252))[:, 0], 0.0)
    assert numpy.allclose(_balance().update(_nv12_pair(0, 64, 20, 200))[:, 0], scene.BALANCE_LIMIT)


def test_the_lens_balance_averages_over_frames_and_starts_again_after_a_seek():
    numpy = pytest.importorskip("numpy")
    balance = _balance()
    balance.update(_nv12_pair(10, 64, 100, 120))
    # A skipped frame keeps the average: (10 + 0) / 2.
    assert numpy.allclose(balance.update(_nv12_pair(12, 64, 100, 100))[:, 0], 5.0)
    # A seek back starts it again.
    assert numpy.allclose(balance.update(_nv12_pair(3, 64, 100, 100))[:, 0], 0.0)


def test_the_player_s_shader_fades_the_balance_as_the_stitch_does():
    """viewer.py states render's balance reach and its own texture scale in GLSL; they have to agree."""
    import re
    from pathlib import Path

    pytest.importorskip("numpy")
    from golblick import render

    source = (Path(__file__).parents[1] / "src/golblick/viewer.py").read_text()
    reach = re.search(r"const float BALANCE_REACH = ([\d.]+);", source)
    scale = re.search(r"const float BALANCE_SCALE = ([\d.]+);", source)
    python_scale = re.search(r"^_BALANCE_SCALE = ([\d.]+)$", source, re.M)
    assert reach and scale and python_scale
    assert float(reach.group(1)) == render.BALANCE_REACH
    assert float(scale.group(1)) == float(python_scale.group(1))


def test_the_blurred_band_stays_inside_every_camera_s_overlap():
    """Past the overlap one lens has nothing to blur; the rim taper (1.5 degrees) needs room too."""
    from golblick import scene
    from golblick.vendors.insta360.lens import PROFILES

    for profile in PROFILES.values():
        for guards in (False, True):
            past = profile.field_of_view_for(guards) / 2 - 90
            assert scene.SEAM_COARSE / 2 + 1.5 <= past, profile


def _probed_keyframes(path, index):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"v:{index}", "-show_entries",
                          "packet=pts_time,flags", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return sorted(float(stamp) for stamp, _, flags in (line.partition(",") for line in out.splitlines()) if "K" in flags)


def test_keyframes_read_from_the_movie_header_are_the_ones_ffprobe_lists(tmp_path):
    """B-frames give the tracks composition offsets and an edit list; the two streams keyframe at different spacings."""
    path = tmp_path / "pair.mp4"
    lens = f"testsrc=s={SIZE}x{SIZE}:r=30:d=3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", lens, "-f", "lavfi", "-i", lens,
                    "-map", "0", "-map", "1", "-c:v", "mpeg4", "-bf", "2", "-g:v:0", "7", "-g:v:1", "11", str(path)],
                   check=True)
    first, second = video._indexed_keyframes(path, 0), video._indexed_keyframes(path, 1)
    assert first == pytest.approx(_probed_keyframes(path, 0), abs=1e-6)
    assert second == pytest.approx(_probed_keyframes(path, 1), abs=1e-6)
    assert len(first) != len(second)


def test_keyframes_come_from_ffprobe_where_there_is_no_movie_header(clip):
    assert video._indexed_keyframes(clip.lenses[0][0], 0) is None
    assert video.keyframe_times(clip) == pytest.approx(_probed_keyframes(clip.lenses[0][0], 0))
