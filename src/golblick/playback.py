"""Decoding a clip's two lenses for a player, frame by frame, in step.

One ffmpeg decodes both lens streams and stacks them, lens 0 above lens 1,
so the pair can't drift apart: the filter graph only emits a frame when it
has both.  Frames come out as NV12, which the player's shader turns into
colour, so each lens is two contiguous slices of the buffer (luma, then
chroma at half size) and uploads without a copy.  The decoder runs on the
graphics card when ffmpeg can, which is what makes full-size playback
possible: NVDEC on an NVIDIA card, VA-API on AMD and Intel.  On a desktop
NVIDIA card both 2880-pixel lenses of an X5 clip decode at about 5x real
time, on an 8-core CPU at about 0.6x.

Each frame is handed over with its index, so the player knows exactly which
frame it is drawing and steadies it with that frame's turn.

The sound comes from a second ffmpeg, as raw PCM from the same moment, for
the player to hand to the desktop's audio output and keep time by.

Qt-free; needs ffmpeg.
"""

from __future__ import annotations

import functools
import os
import queue
import subprocess
import threading
from dataclasses import dataclass

from .video import Clip, binaries

#: Frames decoded ahead of the one on screen.
AHEAD = 4

#: Seconds a graphics card has to produce a clip's first frame.  Some drivers
#: hang on a clip they can't decode instead of failing (NVIDIA's VA-API driver
#: does on small test clips), and the decoder falls back only from a failure.
STALL = 15.0

#: The sound as handed to a player, whatever the clip recorded: 16-bit stereo at 48 kHz.
SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2


@dataclass(frozen=True)
class Frame:
    """One decoded lens pair: its index in the clip, and NV12 planes per lens."""

    index: int
    size: int
    data: bytes

    def planes(self, lens: int) -> tuple[memoryview, memoryview]:
        """Lens ``lens``'s luma (size x size) and interleaved chroma (size/2 x size/2, two bytes a texel)."""
        view = memoryview(self.data)
        luma = self.size * self.size
        chroma = luma // 2
        return (view[lens * luma:(lens + 1) * luma],
                view[2 * luma + lens * chroma:2 * luma + (lens + 1) * chroma])


#: Ways to decode, best first.  "vaapi" decodes and scales on the card; "vaapi-decode" decodes there and
#: scales on the CPU, for a VA-API driver that can't scale (NVIDIA's, which only decodes).
METHODS = ("cuda", "vaapi", "vaapi-decode", "cpu")

#: What a decoder tries next when ``method`` fails on a clip before its first frame.
FALLBACK = {"cuda": "cpu", "vaapi": "vaapi-decode", "vaapi-decode": "cpu"}


@functools.cache
def hardware() -> str:
    """The best of :data:`METHODS` that works here, or the one ``GOLBLICK_DECODE`` names.

    Opens each device rather than reading ``-hwaccels``, which lists what
    ffmpeg was built with whether or not there is a card to use it.  Whether
    the card takes a clip's codec is only known from the clip, so a decoder
    falls back from there (:data:`FALLBACK`).
    """
    chosen = os.environ.get("GOLBLICK_DECODE", "").strip().lower()
    if chosen in METHODS:
        return chosen
    if _runs(["-init_hw_device", "cuda"]):
        return "cuda"
    if _runs(["-init_hw_device", "vaapi=va", "-filter_hw_device", "va"],
             "format=nv12,hwupload,scale_vaapi=w=32:h=32:format=nv12,hwdownload,format=nv12"):
        return "vaapi"
    if _runs(["-init_hw_device", "vaapi"]):
        return "vaapi-decode"
    return "cpu"


def _runs(device: list[str], filters: str = "null") -> bool:
    """Whether ffmpeg opens ``device`` and turns one blank frame through ``filters``."""
    ffmpeg, _ = binaries()
    try:
        probe = subprocess.run([ffmpeg, "-v", "error", "-nostdin", *device, "-f", "lavfi", "-i", "nullsrc=s=64x64",
                                "-vf", filters, "-frames:v", "1", "-f", "null", "-"], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


@functools.cache
def _decoders() -> frozenset[str]:
    ffmpeg, _ = binaries()
    try:
        listed = subprocess.run([ffmpeg, "-hide_banner", "-decoders"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    return frozenset(line.split()[1] for line in listed.stdout.splitlines() if len(line.split()) > 1)


def command(clip: Clip, size: int, start: int, method: str) -> list[str]:
    """The ffmpeg command that decodes ``clip`` from frame ``start`` by ``method``, each lens at ``size`` square."""
    ffmpeg, _ = binaries()
    at = f"{start / clip.rate:.6f}"
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    # NVIDIA's own decoder starts about 30% sooner than ffmpeg's with NVDEC
    # under it, which is most of what a seek waits for; the frames are the same.
    cuvid = f"{clip.codec}_cuvid"
    inputs: list = []
    for file, _ in clip.lenses:
        if file not in inputs:
            inputs.append(file)
            if method == "cuda":
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
                if cuvid in _decoders():
                    cmd += ["-c:v", cuvid]
            elif method in ("vaapi", "vaapi-decode"):
                # Frames stay on the card, so a codec it can't decode fails
                # here instead of ffmpeg quietly decoding it on the CPU.
                cmd += ["-hwaccel", "vaapi", "-hwaccel_output_format", "vaapi"]
            cmd += ["-ss", at, "-i", str(file)]
    scale = {"cuda": f"scale_cuda={size}:{size},hwdownload,format=nv12",
             "vaapi": f"scale_vaapi=w={size}:h={size}:format=nv12,hwdownload,format=nv12",
             "vaapi-decode": f"hwdownload,format=nv12,scale={size}:{size}:flags=area,format=nv12",
             }.get(method, f"scale={size}:{size}:flags=area,format=nv12")
    graph = [f"[{inputs.index(file)}:v:{stream}]{scale}[{name}]"
             for name, (file, stream) in zip("ab", clip.lenses, strict=True)]
    graph.append("[a][b]vstack=inputs=2:shortest=1,format=nv12[out]")   # a _00_ file can hold one frame more than its _10_
    return cmd + ["-filter_complex", ";".join(graph), "-map", "[out]", "-an",
                  "-f", "rawvideo", "-pix_fmt", "nv12", "pipe:1"]


def keyframe_spacing(clip: Clip, seconds: float = 7.0) -> tuple[float, float] | None:
    """Lens 0's first keyframe and the spacing after it, in seconds, from the opening's packets; None if irregular.

    A decoder started on a keyframe begins at once, and one started just past
    it decodes everything back to it first: on an X5 clip on the CPU, 1.4 s
    against 4.1.  Reads only the first ``seconds``, because listing every
    packet of a long clip reads the whole file; the cameras here space their
    keyframes evenly (every 2.002 s on an X5), and a spacing that isn't even
    over the opening gives None.
    """
    _, ffprobe = binaries()
    file, index = clip.lenses[0]
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", f"v:{index}", "-read_intervals", f"%+{seconds:g}",
             "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(file)],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    times = []
    for line in result.stdout.splitlines():
        stamp, _, flags = line.partition(",")
        if "K" in flags:
            try:
                times.append(float(stamp))
            except ValueError:
                continue
    times.sort()
    if len(times) < 3:
        return None
    steps = [b - a for a, b in zip(times, times[1:], strict=False)]
    if max(steps) - min(steps) > 0.5 / float(clip.rate):
        return None
    return times[0], sum(steps) / len(steps)


class Decoder:
    """Decodes ``clip`` from a frame onwards in a background thread, a few frames ahead.

    If the graphics card fails on the clip before its first frame (a codec or
    size its decoder doesn't take, a driver fault), it tries the next way down
    (:data:`FALLBACK`), ending on the CPU; ``method`` then reads where it
    landed and ``fell_back`` holds the card's error, so a player can start
    its later seeks there.
    """

    def __init__(self, clip: Clip, size: int, start: int = 0, method: str | None = None):
        self.clip, self.size, self.start = clip, size, start
        self.method = method or hardware()
        self.fell_back: str | None = None
        self.frames: queue.Queue[Frame | None] = queue.Queue(AHEAD)
        self.error: str | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._process = self._spawn()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _spawn(self) -> subprocess.Popen:
        return subprocess.Popen(command(self.clip, self.size, self.start, self.method), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)

    def _read(self) -> None:
        index = self._decode()
        while index == self.start and self.method in FALLBACK and self.error and not self._stop.is_set():
            with self._lock:
                if self._stop.is_set():
                    return
                self.fell_back = self.fell_back or self.error
                self.error, self.method = None, FALLBACK[self.method]
                self._process = self._spawn()
            index = self._decode()
        # The end of the clip, or a failure.  Waits for room: a full queue
        # at the end is the usual case when the player is keeping up.
        while not self._stop.is_set():
            try:
                self.frames.put(None, timeout=0.1)
                break
            except queue.Full:
                continue

    def _decode(self) -> int:
        """Hand over frames until ffmpeg stops; the index after the last one, with ``error`` set if it failed."""
        length = self.size * self.size * 3   # two lenses, NV12: 1.5 bytes a pixel each
        index = self.start
        process = self._process
        stream = process.stdout
        first, stalled = threading.Event(), threading.Event()

        def stall() -> None:
            if not first.is_set():
                stalled.set()
                process.kill()

        watch = threading.Timer(STALL, stall) if self.method in FALLBACK else None
        if watch is not None:
            watch.daemon = True
            watch.start()
        try:
            while not self._stop.is_set():
                buffer = bytearray(length)
                view, got = memoryview(buffer), 0
                while got < length:
                    read = stream.readinto(view[got:])
                    if not read:
                        break
                    got += read
                if got < length:
                    break
                first.set()
                frame = Frame(index, self.size, bytes(buffer))
                while not self._stop.is_set():
                    try:
                        self.frames.put(frame, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                index += 1
        finally:
            if watch is not None:
                watch.cancel()
            if not self._stop.is_set() and process.wait() not in (0, None):
                self.error = (f"the graphics card gave no frame in {STALL:g} s" if stalled.is_set() else
                              process.stderr.read().decode(errors="replace").strip()[-300:] or "ffmpeg failed")
        return index

    def next(self, timeout: float | None = None) -> Frame | None:
        """The next frame, or None at the end; raises queue.Empty if none is ready in time."""
        return self.frames.get(timeout=timeout)

    def close(self) -> None:
        with self._lock:
            self._stop.set()
            process = self._process
        process.kill()
        process.wait()
        self._thread.join(timeout=1)


def sound_command(clip: Clip, start: int) -> list[str]:
    """The ffmpeg command that decodes ``clip``'s sound from the start of frame ``start``."""
    ffmpeg, _ = binaries()
    return [ffmpeg, "-v", "error", "-nostdin", "-ss", f"{start / clip.rate:.6f}", "-i", str(clip.lenses[0][0]),
            "-map", "0:a:0", "-vn", "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "pipe:1"]


class Sound:
    """Decodes ``clip``'s sound from a frame onwards in a background thread, about two seconds ahead."""

    CHUNK = BYTES_PER_SECOND // 10

    def __init__(self, clip: Clip, start: int = 0):
        self.chunks: queue.Queue[bytes | None] = queue.Queue(20)
        self._left = b""
        self.finished = False
        self._stop = threading.Event()
        self._process = subprocess.Popen(sound_command(clip, start), stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, bufsize=0)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        stream = self._process.stdout
        try:
            while not self._stop.is_set():
                chunk = stream.read(self.CHUNK)
                if not chunk:
                    break
                while not self._stop.is_set():
                    try:
                        self.chunks.put(chunk, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        finally:
            while not self._stop.is_set():
                try:
                    self.chunks.put(None, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def read(self, limit: int) -> bytes:
        """Up to ``limit`` bytes of what's decoded so far, whole samples only; empty when none is ready."""
        limit -= limit % (CHANNELS * 2)
        out = bytearray(self._left[:limit])
        self._left = self._left[limit:]
        while len(out) < limit and not self.finished:
            try:
                chunk = self.chunks.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                self.finished = True
                break
            take = limit - len(out)
            out += chunk[:take]
            self._left = chunk[take:]
        # A pipe read can end mid-sample; keep the part for next time.
        whole = len(out) - len(out) % (CHANNELS * 2)
        self._left = bytes(out[whole:]) + self._left
        return bytes(out[:whole])

    def close(self) -> None:
        self._stop.set()
        self._process.kill()
        self._process.wait()
        self._thread.join(timeout=1)
