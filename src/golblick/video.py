"""Stitching a whole 360 video, steadied as it is stitched.

Needs the ``render`` extra (numpy) and ffmpeg.  ffmpeg decodes the lenses,
remaps them and encodes the result; nothing per pixel goes through Python.
The projection is the one the Nextcloud app renders videos with:
:func:`render.remap_tables` with one :func:`render.plan_seam` hand-over for
the whole clip, in two bands as the desktop player hands over: detail across
the narrow one, the lenses blurred across ``scene.SEAM_COARSE``.

The difference is the steadying.  The app writes one set of tables per clip
and turns the picture afterwards, in its player or on a GPU.  Here every
frame gets its own tables, already turned by that frame's rotation from
:mod:`golblick.stabilise`, and ffmpeg's ``remap`` takes them as a stream, so
the picture is resampled once: turning a stitched frame again, as a second
bilinear pass, kept 0.66 of its detail on a OneR clip, and stitching a frame
in numpy took 3.5 to 4.7 s at 2880 wide against 0.13 to 0.21 s for ffmpeg's
``remap``.  The tables take about 1.1 s a frame at 2880 on one core, so a pool
of processes makes them, several frames ahead.

Frames: the render's own, and rotations in the column convention.  A frame's
tables use ``R @ O``: ``O`` levels the opening and ``R`` is that frame's
steadying turn, and :func:`render.remap_tables` samples the camera at
``(R O)ᵀ r`` for each output direction ``r`` -- which is ``Oᵀ (Rᵀ r)``, the
levelled render seen through the turn.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from . import render, scene, stabilise
from .errors import FormatError, GolblickError, MissingDependency, UnsupportedFile

#: Output bitrate, per pixel per second: the Nextcloud app's, 20 Mbit/s at 3840 x 1920.
BITS_PER_PIXEL_SECOND = 20e6 / (3840 * 1920)

#: Frames, and the lens size, the seam plan is chosen and checked on (the app's).
SEAM_FRAMES = 8
SEAM_SIZE = 720

#: Rows of the tables made at a time.  The whole frame at once streams
#: gigabytes of temporaries through memory, and stopped scaling at 1.6 frames
#: a second from four processes up on a 16-core machine.
BAND = 32

#: Lens size the lens-guard check decodes at, and when in the clip (the app's).
GUARD_SIZE = 1440
GUARD_AT = (0.2, 0.5, 0.8)


def binaries() -> tuple[str, str]:
    """ffmpeg and ffprobe, from the PATH."""
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise MissingDependency("stitching a video needs ffmpeg and ffprobe on the PATH")
    return ffmpeg, ffprobe


@dataclass(frozen=True)
class Clip:
    """What ffprobe says about a clip's lens streams."""

    lenses: tuple[tuple[Path, int], tuple[Path, int]]   # (file, video stream index) per lens
    size: int            # each lens's square frame, in pixels
    rate: Fraction       # frames per second
    frames: int
    duration: float
    audio: bool
    created: str | None  # when it was recorded, for the copy's own metadata
    colour_range: str = "pc"         # ffprobe's color_range: pc (full) or tv (limited)
    colour_space: str = "bt709"      # ffprobe's color_space: bt709, smpte170m, bt470bg
    codec: str = ""                  # ffprobe's codec_name for the lens streams: h264, hevc


def open_clip(vendor, path) -> Clip:
    """Find both lenses of the clip at ``path`` and check ffmpeg can read them."""
    _, ffprobe = binaries()
    reader = getattr(vendor, "lens_streams", None)
    if reader is None:
        raise UnsupportedFile(f"{vendor.NAME} can't say where a video's lenses are")
    lenses = reader(path)
    probes = {file: _probe(ffprobe, file) for file in {file for file, _ in lenses}}
    streams = []
    for file, index in lenses:
        video = probes[file]["video"]
        if index >= len(video):
            raise FormatError(f"{file}: no video stream {index} for the second lens")
        streams.append(video[index])
    sizes = {(stream["width"], stream["height"]) for stream in streams}
    if len(sizes) != 1 or streams[0]["width"] != streams[0]["height"]:
        raise FormatError(f"{path}: the lens streams are not square and alike ({sorted(sizes)})")
    rate = Fraction(streams[0]["r_frame_rate"])
    if rate <= 0 or any(Fraction(stream["r_frame_rate"]) != rate for stream in streams):
        raise FormatError(f"{path}: the lens streams don't share one frame rate")
    first = probes[lenses[0][0]]
    counts = [int(stream["nb_frames"]) for stream in streams if str(stream.get("nb_frames", "")).isdigit()]
    frames = min(counts) if counts else int(first["duration"] * rate)
    return Clip((lenses[0], lenses[1]), streams[0]["width"], rate, frames, first["duration"], first["audio"],
                first["created"], streams[0].get("color_range") or "pc", streams[0].get("color_space") or "bt709",
                streams[0].get("codec_name") or "")


def _probe(ffprobe: str, file: Path) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,color_range,color_space:stream_tags=creation_time"
         ":format=duration:format_tags=creation_time", "-of", "json", str(file)],
        capture_output=True, text=True)
    try:
        info = json.loads(result.stdout)
    except ValueError:
        info = {}
    if result.returncode != 0 or not info.get("streams"):
        raise FormatError(f"{file}: ffprobe could not read it: {result.stderr.strip()[-200:]}")
    video = [stream for stream in info["streams"] if stream.get("codec_type") == "video"]
    # A OneR or X3 tags the container with when it was recorded, an X5 only each stream.
    created = (info.get("format", {}).get("tags", {}).get("creation_time")
               or (video[0].get("tags", {}).get("creation_time") if video else None))
    if not (isinstance(created, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z?", created)):
        created = None
    return {"video": video, "audio": any(stream.get("codec_type") == "audio" for stream in info["streams"]),
            "duration": float(info.get("format", {}).get("duration") or 0), "created": created}


def keyframe_times(clip: Clip) -> list[float]:
    """When lens 0 has a keyframe, in seconds, from the packet index: nothing is decoded."""
    _, ffprobe = binaries()
    file, index = clip.lenses[0]
    # The movie header lists them; asking ffprobe for packets reads the whole
    # file, a minute for a long clip on a slow disk.
    indexed = _indexed_keyframes(file, index)
    if indexed is not None:
        return indexed
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", f"v:{index}", "-show_entries", "packet=pts_time,flags",
         "-of", "csv=p=0", str(file)], capture_output=True, text=True)
    times = []
    for line in result.stdout.splitlines():
        stamp, _, flags = line.partition(",")
        if "K" in flags:
            try:
                times.append(float(stamp))
            except ValueError:
                continue
    return sorted(times)


def _indexed_keyframes(file, index: int) -> list[float] | None:
    """The ``index``-th video track's keyframe times from its sample tables, as ffprobe gives them.

    None for a layout this doesn't handle (no movie header, an edit list with
    more than one edit or an empty one), so the caller can ask ffprobe.
    """
    try:
        with open(file, "rb") as handle:
            handle.seek(0, 2)
            length, at, moov = handle.tell(), 0, None
            while at + 8 <= length and moov is None:
                handle.seek(at)
                head = handle.read(16)
                size, kind, body = int.from_bytes(head[:4], "big"), head[4:8], 8
                if size == 1:
                    size, body = int.from_bytes(head[8:16], "big"), 16
                elif size == 0:
                    size = length - at
                if size < body:
                    return None
                if kind == b"moov":
                    handle.seek(at)
                    moov = handle.read(size)
                at += size
    except OSError:
        return None
    if moov is None or len(moov) < 8 or moov[4:8] != b"moov":
        return None

    def u32(at):
        return int.from_bytes(moov[at:at + 4], "big")

    seen = 0
    for kind, start, size in _children(moov, 8, len(moov)):
        if kind != b"trak":
            continue
        boxes = {inner: inner_start for inner, inner_start, _ in _descend(moov, start, size)}
        handler = boxes.get(b"hdlr")
        if handler is None or moov[handler + 16:handler + 20] != b"vide":
            continue
        if seen != index:
            seen += 1
            continue
        if not {b"mdhd", b"stts", b"stss"} <= boxes.keys():
            return None
        mdhd = boxes[b"mdhd"]
        scale = u32(mdhd + 28) if moov[mdhd + 8] == 1 else u32(mdhd + 20)
        shift = 0
        for edts, edts_start, edts_size in _children(moov, start + 8, start + size):
            if edts != b"edts":
                continue
            edits = [child for child in _children(moov, edts_start + 8, edts_start + edts_size) if child[0] == b"elst"]
            if len(edits) != 1:
                return None
            elst = edits[0][1]
            wide = moov[elst + 8] == 1
            if u32(elst + 12) != 1:
                return None
            entry = elst + 16
            shift = int.from_bytes(moov[entry + 8:entry + 16] if wide else moov[entry + 4:entry + 8], "big", signed=True)
            if shift < 0:
                return None
        if scale <= 0:
            return None
        stts, stss = boxes[b"stts"], boxes[b"stss"]
        decode, number = [], 0
        for k in range(u32(stts + 12)):
            count, delta = u32(stts + 16 + 8 * k), u32(stts + 20 + 8 * k)
            for _ in range(count):
                decode.append(number)
                number += delta
        offsets = [0] * len(decode)
        if b"ctts" in boxes:
            ctts, sample = boxes[b"ctts"], 0
            for k in range(u32(ctts + 12)):
                count = u32(ctts + 16 + 8 * k)
                offset = int.from_bytes(moov[ctts + 20 + 8 * k:ctts + 24 + 8 * k], "big", signed=True)
                offsets[sample:sample + count] = [offset] * count
                sample += count
            if len(offsets) != len(decode):
                return None
        times = []
        for k in range(u32(stss + 12)):
            sample = u32(stss + 16 + 4 * k) - 1
            if not 0 <= sample < len(decode):
                return None
            times.append((decode[sample] + offsets[sample] - shift) / scale)
        return sorted(times)
    return None


def probe_times(wanted: list[float], keyframes: list[float]) -> list[float]:
    """``wanted`` moved to the nearest keyframe, where that's a frame not already taken.

    Planning wants frames spread through the clip, not at exact moments, and
    seeking to a moment means decoding forward from the keyframe before it (up
    to 60 full-size frames on an X5, which keyframes every 2 seconds).  At a
    keyframe it is one frame.  Both lenses are read at the same moment
    either way: the cameras measured keyframe their two streams together, and
    a seek to a moment is exact even if a stream didn't.  A moment whose
    nearest keyframe is already taken keeps its own time, so a short clip
    with few keyframes still gets as many different frames as were asked for.
    """
    taken: set[float] = set()
    out = []
    for at in wanted:
        nearest = min(keyframes, key=lambda k: abs(k - at), default=None)
        if nearest is not None and nearest not in taken:
            taken.add(nearest)
            out.append(nearest)
        else:
            out.append(at)
    return out


def lens_frames(clip: Clip, at: float, size: int):
    """The lens pair at ``at`` seconds, ``size`` square each, side by side as in a still."""
    numpy = render._numpy()
    ffmpeg, _ = binaries()
    halves = []
    for file, index in clip.lenses:
        result = subprocess.run(
            # One decoder thread: with several, the decoder reads frames ahead
            # before handing over the first, which triples the time for one.
            [ffmpeg, "-v", "error", "-nostdin", "-threads", "1", "-ss", f"{at:.6f}", "-i", str(file),
             "-map", f"0:v:{index}", "-frames:v", "1", "-vf", f"scale={size}:{size}",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True)
        if result.returncode != 0 or len(result.stdout) != size * size * 3:
            raise FormatError(f"{file}: ffmpeg gave no frame at {at:.1f} s")
        halves.append(numpy.frombuffer(result.stdout, numpy.uint8).reshape(size, size, 3))
    return numpy.hstack(halves)


def video_calibration(calibration, crop):
    """The calibration for a video's frames, and a line saying how it was made.

    The camera quotes the still sensor; a video keeps the centre of it, which
    the file records (see ``Calibration.for_video``).  Without that record the
    still calibration is scaled to the frame, which is what a video with no
    crop needs and is 1-5% off in radius on every camera measured so far.
    """
    if crop is None:
        return calibration, "sensor crop    none recorded, so the still calibration is scaled to the frame"
    kept, source = crop[2], crop[0]
    return calibration.for_video(crop), f"sensor crop    {kept} of {source} per lens, from the file"


@dataclass
class Plan:
    """Everything decided before the first frame: geometry, hand-over and steadying."""

    lenses: tuple            # render.Lens pair, at twice lens_size
    lens_size: int
    width: int
    field_of_view: float
    seam: object             # render.SeamPlan or None
    orientation: object      # 3x3, levels the opening
    turns: list | None       # per frame, the steadying quaternion (w, x, y, z), or None
    notes: list[str]         # one line each on what was decided and why
    shutter: list | None = None   # per frame, stabilise.shutter's turns, or None


def decide(vendor, path, clip: Clip, calibration, field_of_view: float | None = None, guards: str = "auto",
           keyframes=None):
    """What a few of the clip's frames decide: the field of view (lens guards or not) and the seam.

    Returns ``(field_of_view, seam, notes)``: degrees, a ``render.SeamPlan`` or
    None for the bisector, and a line on each decision.  Shared by the stitch
    and the desktop player, which runs it in the background while the clip
    plays.  ``keyframes`` is a function returning the clip's keyframe times,
    read only if a frame is needed.
    """
    notes = []
    if keyframes is None:
        cached: list[list[float]] = []

        def keyframes() -> list[float]:
            if not cached:
                cached.append(keyframe_times(clip))
            return cached[0]
    calibrations = vendor.describe(path)["calibrations"]
    reader = getattr(vendor, "lens_profile", None)
    profile = reader(path) if reader is not None else None
    radial = profile.radial if profile is not None else ()

    if field_of_view is not None:
        notes.append(f"field of view  {field_of_view:g} degrees (given)")
    elif profile is None:
        field_of_view = 194.0
        notes.append("field of view  194 degrees (this camera hasn't been measured)")
    else:
        field_of_view = profile.field_of_view_for()
        guarded = profile.field_of_view_for(guards=True) if profile.guard_factor else None
        if guarded is not None and guards == "on":
            field_of_view = guarded
            notes.append(f"lens guards    on (--lens-guards on), {guarded:.1f} degrees")
        elif guarded is not None and guards == "auto" and clip.duration > 0:
            images = []
            for at in probe_times([share * clip.duration for share in GUARD_AT], keyframes()):
                try:
                    images.append(lens_frames(clip, at, GUARD_SIZE))
                except FormatError:
                    continue
            probe = render.lenses_from_calibration(calibration, 2 * GUARD_SIZE, radial)
            if images and render.pick_field_of_view(images, probe, (guarded, field_of_view)) == guarded:
                notes.append(f"lens guards    detected: the lenses agree at {guarded:.1f} degrees, not {field_of_view:g}")
                field_of_view = guarded
            else:
                notes.append("lens guards    none detected")
        guarded_note = ", less for lens guards" if field_of_view != profile.field_of_view_for() else ""
        notes.append(f"field of view  {field_of_view:.1f} degrees (the camera's measured value{guarded_note})")

    seam, how = None, "bisector"
    if clip.duration > 0:
        images = []
        wanted = [clip.duration * (0.03 + 0.94 * k / (SEAM_FRAMES - 1)) for k in range(SEAM_FRAMES)]
        for at in probe_times(wanted, keyframes()):
            try:
                images.append(lens_frames(clip, at, SEAM_SIZE))
            except FormatError:
                continue
        direction = calibrations[53].lens_offset if 53 in calibrations else None
        try:
            probe = render.lenses_from_calibration(calibration, 2 * SEAM_SIZE, radial)
            seam = render.plan_seam(images, probe, field_of_view, direction)
            if seam is not None:
                how = "aimed and routed" if seam.parallax is not None else "routed"
        except (ValueError, FormatError) as exc:
            how = f"bisector (the seam plan failed: {exc})"
    notes.append(f"seam           {how}")
    return field_of_view, seam, notes


def plan(vendor, path, clip: Clip, width: int, steady: bool = True, lock: bool = False,
         field_of_view: float | None = None, guards: str = "auto") -> Plan:
    """Decide the geometry, the seam and the steadying, from the file and a few of its frames."""
    notes = []
    cached: list[list[float]] = []

    def keyframes() -> list[float]:
        # Read once, and only if a frame is needed at all.
        if not cached:
            cached.append(keyframe_times(clip))
        return cached[0]
    info = vendor.describe(path)
    calibrations = info["calibrations"]
    calibration = calibrations.get(5)
    if calibration is None:
        raise UnsupportedFile(f"{path}: no equidistant calibration, so the lens geometry is unknown")
    calibration, cropped = video_calibration(calibration, info.get("sensor_crop"))
    notes.append(cropped)
    field_of_view, seam, decided = decide(vendor, path, clip, calibration, field_of_view, guards, keyframes)
    notes.extend(decided)
    reader = getattr(vendor, "lens_profile", None)
    profile = reader(path) if reader is not None else None
    radial = profile.radial if profile is not None else ()

    native = render.lenses_from_calibration(calibration, 2 * clip.size, radial)
    lens_size = render.lens_size_for(native, clip.size, width, field_of_view)
    lenses = render.lenses_from_calibration(calibration, 2 * lens_size, radial)

    faced, turns, turned = orient(vendor, path, calibration, clip.frames, steady, lock)
    notes.extend(turned)
    read, line = shutter(vendor, path)
    notes.append(line)

    return Plan(lenses, lens_size, width, field_of_view, seam, faced,
                turns, notes, read)


def orient(vendor, path, calibration, frames: int, steady: bool = True, lock: bool = False):
    """How a clip is turned: its levelled opening facing the camera's forward, and the steadying.

    Returns ``(orientation, turns, notes)``: the 3x3 opening orientation, per
    frame a unit quaternion ``(w, x, y, z)`` applied after it (or None,
    unsteadied), and a line on each decision.  Shared by the stitch and the
    desktop player, so both turn a clip the same way.
    """
    level, faced, heading, notes = opening(vendor, path, calibration)
    turns = None
    if steady:
        try:
            follow, headings = steadying(vendor, path, level, heading)
            turns = stabilise.locked(follow, headings) if lock else follow
            notes.append("steadying      " + ("direction locked" if lock else "follows the camera's turns")
                         + f", {len(turns)} frames from the motion record")
            if len(turns) < frames:
                notes.append(f"               ⚠️ the video has {frames} frames; the last {frames - len(turns)} keep the record's last turn")
        except (GolblickError, ValueError, AttributeError) as exc:
            notes.append(f"steadying      not steadied: {exc}")
    else:
        notes.append("steadying      off (--no-steady)")
    return faced, turns, notes


def opening(vendor, path, calibration):
    """A clip's levelled opening, the same turned to face the camera's forward, the turn between, and notes.

    Returns ``(level, faced, heading, notes)``: two 3x3 orientations, the
    heading in radians, and a line on each decision.
    """
    numpy = render._numpy()
    notes = []
    try:
        orientation = render.level(vendor.gravity_up(path))
        notes.append("levelling      from gravity at the opening (inertial record)")
    except (GolblickError, AttributeError) as exc:
        orientation = render.body_orientation(calibration)
        notes.append(f"levelling      calibration only ({exc})")

    # Face the middle of the vendor's own exports, as a photo does.  The track
    # is built for the levelled render and turned with it (stabilise.turned).
    reader = getattr(vendor, "video_forward", None)
    forward = reader(path) if reader is not None else None
    faced = orientation if forward is None else render.face(orientation, forward)
    turn = numpy.asarray(faced, numpy.float64) @ numpy.asarray(orientation, numpy.float64).T
    heading = float(numpy.arctan2(turn[0][2], turn[0][0]))
    if forward is not None:
        notes.append(f"facing         the camera's forward, turned {numpy.degrees(heading):+.0f} degrees")
    return orientation, numpy.asarray(faced, numpy.float64), heading, notes


def steadying(vendor, path, level, heading, motion=None):
    """The following view's per-frame turns for a clip faced ``heading`` from ``level``, and each frame's heading.

    ``stabilise.locked`` makes the locked view from the two.  ``motion`` is
    ``vendor.motion(path)`` if the caller has it already.  Raises what
    ``vendor.motion`` and ``stabilise.steady`` raise.
    """
    follow, headings = stabilise.steady(motion or vendor.motion(path), level)
    return stabilise.turned(follow, heading), headings


def shutter(vendor, path, motion=None):
    """A clip's turns across each frame's readout, for undoing rolling shutter, and a note.

    Returns ``(turns, note)``: ``stabilise.shutter``'s quaternions per frame,
    or None where the camera's readout isn't known.  ``motion`` is
    ``vendor.motion(path)`` if the caller has it already.
    """
    try:
        motion = motion or vendor.motion(path)
    except (GolblickError, ValueError, AttributeError) as exc:
        return None, f"shutter        rolling shutter left in: {exc}"
    turns = stabilise.shutter(motion)
    if turns is None:
        return None, "shutter        rolling shutter left in: no readout time for this camera"
    return turns, f"shutter        rolling shutter undone, {1000 * motion.readout:.1f} ms readout"


def frame_shutter(plan: Plan, k: int):
    """Frame ``k``'s turns across its readout as 3x3 matrices, as the renderer takes them, or None."""
    if not plan.shutter:
        return None
    return [quaternion_matrix(q) for q in plan.shutter[min(k, len(plan.shutter) - 1)]]


def frame_orientation(plan: Plan, k: int):
    """The orientation frame ``k`` is rendered with: its steadying turn after the levelling."""
    if not plan.turns:
        return plan.orientation
    return quaternion_matrix(plan.turns[min(k, len(plan.turns) - 1)]) @ plan.orientation


def quaternion_matrix(q):
    """The 3x3 rotation of a unit quaternion ``(w, x, y, z)``, column convention."""
    numpy = render._numpy()
    w, x, y, z = q
    return numpy.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


# ---- the tables, made in worker processes ---------------------------------------------

_WORKER: Plan | None = None


def _start_worker(plan: Plan) -> None:
    global _WORKER
    _WORKER = plan


def _tables(k: int) -> bytes:
    """Frame ``k``'s tables, stacked into one 16-bit picture: see :func:`layout`."""
    return frame_tables(_WORKER, frame_orientation(_WORKER, k), frame_shutter(_WORKER, k))


#: The stacked tables, top to bottom: each lens's x and y, the narrow band's mask and the wide one's.
TABLES = ("x0", "y0", "x1", "y1", "mask", "wide")


def layout(width: int) -> tuple[int, int]:
    """The stacked tables' size, ``(width, height)``: :data:`TABLES` one above the other.

    So a frame's tables are one picture through one pipe, and ffmpeg crops them apart.
    """
    return width, len(TABLES) * (width // 2)


def frame_tables(plan: Plan, orientation, shutter=None) -> bytes:
    numpy = render._numpy()
    width, height = plan.width, plan.width // 2
    last = plan.lens_size - 1
    planes = [numpy.empty((height, width), "<u2") for _ in TABLES]
    coarse = float(numpy.deg2rad(scene.SEAM_COARSE))
    for top in range(0, height, BAND):
        rows = slice(top, min(height, top + BAND))
        maps, share, wide = render.remap_tables(plan.lenses, (width, height), plan.field_of_view, orientation,
                                                plan.lens_size, plan.seam, rows=rows, shutter=shutter,
                                                coarse=coarse)
        for index, (x, y, valid) in enumerate(maps):
            planes[2 * index][rows] = numpy.where(valid, numpy.clip(numpy.rint(x), 0, last), 0)
            planes[2 * index + 1][rows] = numpy.where(valid, numpy.clip(numpy.rint(y), 0, last), 0)
        # The masks are 8-bit in the app; as 16 bits, v * 257 converts back to exactly v.
        planes[4][rows] = numpy.rint(255.0 * share).astype("<u2") * 257
        planes[5][rows] = numpy.rint(255.0 * wide).astype("<u2") * 257
    return numpy.concatenate(planes).tobytes()


# ---- ffmpeg ---------------------------------------------------------------------------

def frame_clock(rate: Fraction) -> str:
    """A filter that times each frame by its number at ``rate``, whatever the stream's time base.

    Frame numbers, not the files' timestamps, line the lenses and the tables
    up.  ``round`` matters: ffmpeg evaluates the expression in floating point
    and truncates, so without it frame 3 at 30000/1001 is 3002 on a lens (time
    base 1/30000) and 2 on the tables (1001/30000), and a filter that pairs its
    inputs by time puts each frame with the next one's turn.  Format notes,
    "Stabilising video from the record".
    """
    return f"setpts=round(N*{rate.denominator}/{rate.numerator}/TB)"


#: How far the wide band's blur reaches, degrees: a box this wide, as the
#: player's mip level, and bilinear back up.  Fixed in degrees, so the blurred
#: picture is the same size at any width.
BLUR = scene.SEAM_COARSE / 2


def _graph(clip: Clip, plan: Plan, inputs: dict[str, int]) -> str:
    """The filter graph: the app's, with every table arriving per frame from input ``tables``.

    The copy is the narrow band's blend, plus the blurred lenses blended
    across the wide band, less the same blended across the narrow one: the
    shader's ``(fine - wide) * (lowA - lowB)``, written with what ffmpeg has
    (``maskedmerge`` takes no signed weight).
    """
    width, height = plan.width, plan.width // 2
    small_width = round(360 / BLUR)
    pts = frame_clock(clip.rate)
    lens = plan.lens_size
    graph = f"[{inputs['tables']}:v]{pts},split=6[t0][t1][t2][t3][t4][t5];"
    for index, name in enumerate(("x0", "y0", "x1", "y1")):
        graph += f"[t{index}]crop={width}:{height}:0:{index * height}[{name}];"
    graph += f"[t4]crop={width}:{height}:0:{4 * height},format=gray,format=gbrp,split[m][m2];"
    graph += f"[t5]crop={width}:{height}:0:{5 * height},format=gray,format=gbrp[w];"
    for index, (_, stream) in enumerate(clip.lenses):
        graph += f"[{inputs[f'lens{index}']}:v:{stream}]{pts},scale={lens}:{lens}:flags=area[l{index}];"
    blur = f"scale={small_width}:{small_width // 2}:flags=area,scale={width}:{height}:flags=bilinear"
    graph += ("[l0][x0][y0]remap,format=gbrp,split[a][a2];[l1][x1][y1]remap,format=gbrp,split[b][b2];"
              f"[a2]{blur},split[la][la2];[b2]{blur},split[lb][lb2];"
              "[a][b][m]maskedmerge[fine];[la][lb][w]maskedmerge[across];[la2][lb2][m2]maskedmerge[cut];"
              "[across][cut]blend=all_mode=grainextract[lift];"
              "[fine][lift]blend=all_mode=grainmerge,format=yuv420p[out]")
    return graph


def stitch(vendor, path, output, width: int = 2880, steady: bool = True, lock: bool = False,
           field_of_view: float | None = None, guards: str = "auto", jobs: int | None = None,
           say=print) -> Plan:
    """Stitch the clip at ``path`` into ``output``, a 360 MP4, and return what was decided."""
    render._numpy()   # fail now, not in a worker
    ffmpeg, _ = binaries()
    if width % 8:
        raise GolblickError(f"width {width} is not a multiple of 8")
    output = Path(output)
    clip = open_clip(vendor, path)
    decided = plan(vendor, path, clip, width, steady, lock, field_of_view, guards)
    for note in decided.notes:
        say(f"  {note}")

    jobs = jobs or default_jobs(width)
    stack_width, stack_height = layout(width)
    part = output.with_name(output.name + ".part")
    with tempfile.TemporaryDirectory(prefix="golblick-") as scratch:
        scratch = Path(scratch)
        command = [ffmpeg, "-v", "error", "-y"]
        inputs: dict[str, int] = {}
        files = []
        for index, (file, _) in enumerate(clip.lenses):
            if file not in files:
                files.append(file)
                command += ["-i", str(file)]
            inputs[f"lens{index}"] = files.index(file)
        inputs["tables"] = len(files)
        command += ["-f", "rawvideo", "-pix_fmt", "gray16le", "-s", f"{stack_width}x{stack_height}",
                    "-framerate", str(clip.rate), "-i", "pipe:0"]

        bitrate = round(BITS_PER_PIXEL_SECOND * width * (width // 2))
        command += ["-filter_complex", _graph(clip, decided, inputs), "-map", "[out]", "-map", "0:a:0?",
                    "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(bitrate),
                    "-maxrate", str(int(bitrate * 1.5)), "-bufsize", str(2 * bitrate),
                    "-c:a", "copy", "-movflags", "+faststart", "-frames:v", str(clip.frames)]
        if clip.created:
            command += ["-metadata", f"creation_time={clip.created}"]
        command += ["-f", "mp4", str(part)]

        log = scratch / "ffmpeg.log"
        say(f"  {clip.frames} frames at {width}x{width // 2}, tables made by {jobs} processes")
        with log.open("wb") as errors:
            encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
            try:
                _feed(encoder, decided, clip.frames, jobs)
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise GolblickError(f"ffmpeg failed: {log.read_text(errors='replace').strip()[-600:]}")
            except BaseException:
                encoder.kill()
                encoder.wait()
                part.unlink(missing_ok=True)
                if log.exists() and log.stat().st_size:
                    say(f"  ffmpeg said: {log.read_text(errors='replace').strip()[-600:]}")
                raise
    tagged = tag_spherical(part)
    part.replace(output)
    if not tagged:
        say("  ⚠️ not marked as 360 video: the MP4's layout wasn't one this can edit")
    return decided


def default_jobs(width: int) -> int:
    """Processes making tables: half the logical cores, and fewer if memory is short.

    Half, because the tables are arithmetic on long arrays: on a machine with
    16 logical cores, 8 processes made 4.7 frames a second and 15 made 2.8.
    """
    cores = os.cpu_count() or 2
    per_job = 0.6e9 if width > 2880 else 0.4e9
    return max(1, min(cores // 2, int(_available_memory() * 0.6 / per_job)))


def _available_memory() -> float:
    """Memory that can be had without swapping: MemAvailable counts reclaimable cache, free memory doesn't."""
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024.0
    except OSError:
        pass
    try:
        return float(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES"))
    except (ValueError, OSError, AttributeError):
        return 8e9


def _feed(encoder, decided: Plan, frames: int, jobs: int) -> None:
    """Write every frame's tables to ffmpeg in order, with a few in hand, and report progress."""
    if not decided.turns and not decided.shutter:
        # Unsteadied and with no rolling shutter to undo, every frame has the same tables.
        tables = frame_tables(decided, decided.orientation)
        try:
            for _ in range(frames):
                encoder.stdin.write(tables)
        except BrokenPipeError as exc:
            raise GolblickError("ffmpeg stopped reading") from exc
        return
    methods = multiprocessing.get_all_start_methods()
    context = multiprocessing.get_context("fork" if "fork" in methods else "spawn")
    started = time.monotonic()
    shown = 0.0
    terminal = sys.stderr.isatty()
    with context.Pool(jobs, initializer=_start_worker, initargs=(decided,)) as pool:
        pending: deque = deque()
        submitted = 0
        for written in range(frames):
            while submitted < frames and len(pending) < 2 * jobs:
                pending.append(pool.apply_async(_tables, (submitted,)))
                submitted += 1
            try:
                encoder.stdin.write(pending.popleft().get())
            except BrokenPipeError as exc:
                raise GolblickError("ffmpeg stopped reading") from exc
            now = time.monotonic()
            if now - shown >= (2 if terminal else 10) or written + 1 == frames:
                shown = now
                rate = (written + 1) / max(now - started, 1e-6)
                left = (frames - written - 1) / rate
                line = f"  frame {written + 1}/{frames}, {rate:.1f} a second, about {_clock(left)} left"
                sys.stderr.write("\r" + line + "   " if terminal else line + "\n")
                sys.stderr.flush()
    if terminal:
        sys.stderr.write("\n")


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


# ---- marking the result as 360 video ------------------------------------------------------

_UUID = bytes.fromhex("ffcc8263f8554a938814587a02521fdd")
_XMP = (b'<?xml version="1.0"?><rdf:SphericalVideo'
        b' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
        b' xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/">'
        b"<GSpherical:Spherical>true</GSpherical:Spherical>"
        b"<GSpherical:Stitched>true</GSpherical:Stitched>"
        b"<GSpherical:StitchingSoftware>golblick</GSpherical:StitchingSoftware>"
        b"<GSpherical:ProjectionType>equirectangular</GSpherical:ProjectionType>"
        b"<GSpherical:StereoMode>mono</GSpherical:StereoMode>"
        b"</rdf:SphericalVideo>")


def tag_spherical(path) -> bool:
    """Mark the MP4 at ``path`` as a 360 video, in place; True if it is marked afterwards.

    Google's spherical video metadata, version 1, as the Nextcloud app's
    ``SphericalTag`` writes it and Insta360 Studio's exports carry it: an XMP
    document in a ``uuid`` box at the end of the video track.  ffmpeg can
    carry one through but can't create one.  The movie header comes first
    (``+faststart``), so the box pushes the media back and every chunk offset
    moves with it.  Refuses, leaving the file as it was, on anything it
    doesn't fully understand.
    """
    path = Path(path)
    length = path.stat().st_size
    moov = mdat = None
    with path.open("rb") as handle:
        at = 0
        while at + 8 <= length:
            handle.seek(at)
            head = handle.read(8)
            size, kind = int.from_bytes(head[:4], "big"), head[4:8]
            if size == 1:
                size = int.from_bytes(handle.read(8), "big")
                if kind == b"moov":
                    return False
            elif size == 0:
                size = length - at
            if size < 8:
                return False
            if kind == b"moov":
                moov = (at, size)
            elif kind == b"mdat" and mdat is None:
                mdat = at
            at += size
        if moov is None or mdat is None:
            return False
        handle.seek(moov[0])
        box = bytearray(handle.read(moov[1]))

    tag = (8 + 16 + len(_XMP)).to_bytes(4, "big") + b"uuid" + _UUID + _XMP
    video, offsets = None, []
    for kind, start, size in _children(box, 8, len(box)):
        if kind != b"trak":
            continue
        is_video = False
        for inner, inner_start, _ in _descend(box, start, size):
            if inner == b"hdlr" and box[inner_start + 16:inner_start + 20] == b"vide":
                is_video = True
            elif inner in (b"stco", b"co64"):
                offsets.append((inner, inner_start))
            elif inner == b"uuid" and box[inner_start + 8:inner_start + 24] == _UUID:
                return True
        if is_video and video is None:
            video = (start, size)
    if video is None:
        return False

    shift = len(tag) if mdat > moov[0] else 0
    if shift:
        for kind, start in offsets:
            count = int.from_bytes(box[start + 12:start + 16], "big")
            step = 8 if kind == b"co64" else 4
            for i in range(count):
                at = start + 16 + i * step
                value = int.from_bytes(box[at:at + step], "big") + shift
                if step == 4 and value > 0xFFFFFFFF:
                    return False
                box[at:at + step] = value.to_bytes(step, "big")

    start, size = video
    box[start:start + 4] = (size + len(tag)).to_bytes(4, "big")
    box[start + size:start + size] = tag
    box[0:4] = len(box).to_bytes(4, "big")

    temporary = path.with_name(path.name + ".tagging")
    with path.open("rb") as source, temporary.open("wb") as out:
        shutil.copyfileobj(_limited(source, moov[0]), out)
        out.write(box)
        source.seek(moov[0] + moov[1])
        shutil.copyfileobj(source, out)
    temporary.replace(path)
    return True


def _limited(handle, count: int):
    """The first ``count`` bytes of ``handle``, as a file shutil can copy from."""
    import io
    handle.seek(0)
    return io.BytesIO(handle.read(count)) if count < 64 * 2**20 else _Chunks(handle, count)


class _Chunks:
    def __init__(self, handle, count: int):
        self.handle, self.left = handle, count

    def read(self, size: int = -1) -> bytes:
        size = self.left if size < 0 else min(size, self.left)
        data = self.handle.read(size)
        self.left -= len(data)
        return data


def _children(data, start: int, end: int):
    out, at = [], start
    while at + 8 <= end:
        size = int.from_bytes(data[at:at + 4], "big")
        if size < 8 or at + size > end:
            break
        out.append((bytes(data[at + 4:at + 8]), at, size))
        at += size
    return out


def _descend(data, start: int, size: int):
    out = []
    for child in _children(data, start + 8, start + size):
        out.append(child)
        if child[0] in (b"mdia", b"minf", b"stbl"):
            out.extend(_descend(data, child[1], child[2]))
    return out
