"""Decoding a clip's two lenses for a player, frame by frame, in step.

One ffmpeg decodes both lens streams and stacks them, lens 0 above lens 1,
so the pair can't drift apart: the filter graph only emits a frame when it
has both.  Frames come out as NV12, which the player's shader turns into
colour, so each lens is two contiguous slices of the buffer (luma, then
chroma at half size) and uploads without a copy.  The decoder runs on the
GPU when ffmpeg can (NVDEC), which is what makes full-size playback possible:
on a desktop GPU both 2880-pixel lenses decode at about 4x real time, on the
CPU at about 0.6x.

Each frame is handed over with its index, so the player knows exactly which
frame it is drawing and steadies it with that frame's turn.

Qt-free; needs ffmpeg.
"""

from __future__ import annotations

import functools
import queue
import subprocess
import threading
from dataclasses import dataclass

from .video import Clip, binaries

#: Frames decoded ahead of the one on screen.
AHEAD = 4


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


@functools.cache
def hardware() -> bool:
    """Whether ffmpeg here can decode on an NVIDIA graphics card (NVDEC).

    Opens the device rather than reading ``-hwaccels``, which lists what
    ffmpeg was built with whether or not there is a card to use it.
    """
    ffmpeg, _ = binaries()
    try:
        probe = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-init_hw_device", "cuda", "-f", "lavfi",
                                "-i", "nullsrc=s=16x16", "-frames:v", "1", "-f", "null", "-"],
                               capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def command(clip: Clip, size: int, start: int, gpu: bool) -> list[str]:
    """The ffmpeg command that decodes ``clip`` from frame ``start``, each lens at ``size`` square."""
    ffmpeg, _ = binaries()
    at = f"{start / clip.rate:.6f}"
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    inputs: list = []
    for file, _ in clip.lenses:
        if file not in inputs:
            inputs.append(file)
            if gpu:
                cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
            cmd += ["-ss", at, "-i", str(file)]
    graph = []
    for name, (file, stream) in zip("ab", clip.lenses, strict=True):
        source = f"[{inputs.index(file)}:v:{stream}]"
        if gpu:
            graph.append(f"{source}scale_cuda={size}:{size},hwdownload,format=nv12[{name}]")
        else:
            graph.append(f"{source}scale={size}:{size}:flags=area,format=nv12[{name}]")
    graph.append("[a][b]vstack=inputs=2,format=nv12[out]")
    return cmd + ["-filter_complex", ";".join(graph), "-map", "[out]", "-an",
                  "-f", "rawvideo", "-pix_fmt", "nv12", "pipe:1"]


class Decoder:
    """Decodes ``clip`` from a frame onwards in a background thread, a few frames ahead."""

    def __init__(self, clip: Clip, size: int, start: int = 0, gpu: bool | None = None):
        self.clip, self.size, self.start = clip, size, start
        self.gpu = hardware() if gpu is None else gpu
        self.frames: queue.Queue[Frame | None] = queue.Queue(AHEAD)
        self.error: str | None = None
        self._stop = threading.Event()
        self._process = subprocess.Popen(command(clip, size, start, self.gpu), stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, bufsize=0)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        length = self.size * self.size * 3   # two lenses, NV12: 1.5 bytes a pixel each
        index = self.start
        stream = self._process.stdout
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
                frame = Frame(index, self.size, bytes(buffer))
                while not self._stop.is_set():
                    try:
                        self.frames.put(frame, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                index += 1
        finally:
            if not self._stop.is_set() and self._process.wait() not in (0, None):
                self.error = self._process.stderr.read().decode(errors="replace").strip()[-300:] or "ffmpeg failed"
            try:
                self.frames.put_nowait(None)   # the end of the clip, or a failure
            except queue.Full:
                pass

    def next(self, timeout: float | None = None) -> Frame | None:
        """The next frame, or None at the end; raises queue.Empty if none is ready in time."""
        return self.frames.get(timeout=timeout)

    def close(self) -> None:
        self._stop.set()
        self._process.kill()
        self._process.wait()
        self._thread.join(timeout=1)
