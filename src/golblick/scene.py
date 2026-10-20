"""A photo as a GPU viewer projects it: the lens pair and how to map it, without rendering.

:func:`golblick.render.equirectangular` projects every output pixel on the
CPU, which takes 10 to 25 seconds for a full-size photo.  A viewer doesn't need
a panorama file: it needs, for each direction on screen, where in which lens
to look, and the GPU works that out per pixel as it draws.  This module
supplies the numbers for that, in the same conventions and with the same
measured corrections as :mod:`golblick.render`, which owns them:

* :func:`photo_scene` is quick, about as long as reading the file: the lens
  pair as the camera stored it, the calibration, the measured lens
  correction, and levelling from gravity, turned to face the middle of
  Insta360 Studio's export of the photo (render.face).
* :func:`refine` is what takes the CPU longer, so a viewer runs it in the
  background and updates the view when it returns: whether an X5 wore lens
  guards, alignment to an X5's own stitch, and the routed seam.  It works on a
  half-size decode, which is plenty for all three.

Needs the ``render`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

#: Output width the background seam is decided at; see render.seam_columns.
SEAM_WIDTH = 2048

#: Frames a lens balance is averaged over, and the most it moves a channel in
#: 8-bit levels: the stitch's own (``video._balance``), so a clip looks the
#: same played as stitched.
BALANCE_FRAMES = 9
BALANCE_LIMIT = 20.0
#: Strip columns a lens balance is box-blurred over round the seam, either
#: side, twice: ``video._balance``'s avgblur.
BALANCE_BLUR = 12


@dataclass(frozen=True)
class Lens:
    """One fisheye circle, as the shader takes it.  Pixels of the full frame."""

    centre_x: float
    centre_y: float
    radius: float
    spin: float
    #: Rows of the rotation from the camera frame to this lens's own frame:
    #: lens 1's back-to-back flip, then its stated tilt (render._project).
    matrix: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class Scene:
    """Everything a GPU viewer needs to show a photo as a sphere."""

    jpeg: bytes
    width: int
    height: int
    lenses: tuple[Lens, Lens]
    #: Correction to the equidistant model, degrees, every render.RADIAL_STEP degrees.
    radial: tuple[float, ...]
    #: Half the field of view, radians.
    theta_max: float
    #: Width of the cross-fade between the lenses, radians.
    feather: float
    #: Rows of the rotation from the viewer's world to the camera frame.
    camera_from_world: tuple[tuple[float, float, float], ...]
    #: render._seam_columns offsets, or None for the bisector.
    seam: tuple[float, ...] | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: A video's seam aim (render.SeamPlan.parallax, degrees per column), or None.
    parallax: tuple[float, ...] | None = None
    #: The unit vector from lens 0 to lens 1 the aim pushes along, camera frame.
    baseline: tuple[float, float, float] | None = None


def photo_scene(path: str | Path) -> Scene:
    """The quick part: what to project, and how, before anything is decided from the picture."""
    import numpy

    from . import cli, render
    from .vendors import detect

    path = str(path)
    vendor = detect(path)
    if vendor is None or not hasattr(vendor, "extract_source"):
        from .errors import UnsupportedFile

        raise UnsupportedFile(f"{path}: not a photo golblick can project")
    model = vendor.describe(path)["calibrations"].get(5)
    if model is None:
        from .errors import UnsupportedFile

        raise UnsupportedFile(f"{path}: no equidistant calibration, so the lens geometry is unknown")
    source = vendor.extract_source(path)
    profile = vendor.lens_profile(path) if hasattr(vendor, "lens_profile") else None
    radial = profile.radial if profile is not None else ()
    field_of_view = profile.field_of_view_for() if profile is not None else 194.0
    built = render.lenses_from_calibration(model, source.width, radial)

    orientation, levelling = cli._levelling(render, vendor, path, model, "auto")
    if orientation is None:
        orientation = numpy.eye(3)
    forward = getattr(vendor, "PHOTO_FORWARD", None)
    if forward is not None:
        orientation = render.face(orientation, forward)

    return Scene(
        jpeg=source.data, width=source.width, height=source.height,
        lenses=tuple(_shader_lens(lens, index, render) for index, lens in enumerate(built)),
        radial=tuple(radial), theta_max=float(numpy.deg2rad(field_of_view / 2)),
        feather=float(numpy.deg2rad(1.5)),
        camera_from_world=_rows(numpy.asarray(orientation, numpy.float64).T),
        notes=(f"levelling {levelling}",),
    )


def refine(path: str | Path, scene: Scene) -> Scene:
    """The slow part, for a background thread: ``scene`` with what the picture decides."""
    import io

    import numpy
    from PIL import Image

    from . import cli, render
    from .vendors import detect

    path = str(path)
    vendor = detect(path)
    model = vendor.describe(path)["calibrations"].get(5)
    profile = vendor.lens_profile(path) if hasattr(vendor, "lens_profile") else None

    # Half size, decoded that way by the JPEG decoder itself: quick, and
    # finer than any of these decisions needs.
    picture = Image.open(io.BytesIO(scene.jpeg))
    picture.draft("RGB", (scene.width // 2, scene.height // 2))
    image = numpy.asarray(picture.convert("RGB"))
    lenses = render.lenses_from_calibration(model, image.shape[1], profile.radial if profile else ())
    orientation = numpy.asarray(scene.camera_from_world).T
    field_of_view = float(numpy.rad2deg(scene.theta_max * 2))
    notes = list(scene.notes)

    if profile is not None and profile.guard_factor:
        guarded = profile.field_of_view_for(guards=True)
        if render.pick_field_of_view([image], lenses, (guarded, field_of_view)) == guarded:
            field_of_view = guarded
            notes.append(f"lens guards detected: {guarded:.1f} degrees")
    try:
        orientation, levelling = cli._level_to_stitch(
            render, vendor, path, image, lenses, field_of_view, orientation)
        notes[0] = f"levelling {levelling}"
    except Exception:  # noqa: BLE001 - no stitch, or one that won't align: gravity stays
        pass

    seam = render.seam_columns(image, lenses, field_of_view, orientation, SEAM_WIDTH)
    if seam is not None:
        notes.append("seam routed round what the lenses disagree on")
    return replace(
        scene, theta_max=float(numpy.deg2rad(field_of_view / 2)),
        camera_from_world=_rows(orientation.T),
        seam=None if seam is None else tuple(float(v) for v in seam), notes=tuple(notes),
    )


@dataclass(frozen=True)
class VideoScene:
    """A clip as a GPU viewer plays it: the lens geometry, and per frame how to turn it."""

    scene: Scene
    clip: object                 # video.Clip
    size: int                    # each lens's decoded square, pixels
    orientation: tuple[tuple[float, float, float], ...]
    #: Per frame the following view's steadying turn (w, x, y, z), applied after ``orientation``; None, unsteadied.
    turns: tuple[tuple[float, float, float, float], ...] | None
    #: Per frame how far the following view's heading has turned, radians; turning back by it locks the direction.
    headings: tuple[float, ...] | None = None
    #: Per frame the turns across its readout, stabilise.shutter's; None, rolling shutter not corrected.
    shutter: tuple | None = None
    #: Where each lens sees the strip round the seam that the lenses are evened out from (render.balance_strips).
    strips: dict | None = field(default=None, compare=False)

    def camera_from_world(self, k: int, steady: bool = True, lock: bool = False) -> tuple[tuple[float, float, float], ...]:
        """The shader's rows for frame ``k``: the turn after the levelled, faced opening."""
        import numpy

        from . import stabilise, video

        orientation = numpy.asarray(self.orientation)
        if steady and self.turns:
            k = min(k, len(self.turns) - 1)
            turn = self.turns[k]
            if lock and self.headings:
                turn = stabilise.locked([turn], [self.headings[k]])[0]
            orientation = video.quaternion_matrix(turn) @ orientation
        return _rows(orientation.T)

    def frame_shutter(self, k: int):
        """Frame ``k``'s turns across its readout, unit quaternions ``(w, x, y, z)``, or None.

        The same steadied or not: they turn the camera's frame, which the
        steadying doesn't move.
        """
        if not self.shutter:
            return None
        return self.shutter[min(k, len(self.shutter) - 1)]


def video_scene(path: str | Path, size: int | None = None) -> VideoScene:
    """What a player needs before the first frame: geometry, colour and the steadying tracks.

    ``size`` is each lens's decoded square; None means half the camera's, as
    Insta360's own player decodes, which a screen rarely needs more than.
    """
    import numpy

    from . import render, video
    from .errors import GolblickError, UnsupportedFile
    from .vendors import detect

    path = str(path)
    vendor = detect(path)
    if vendor is None:
        raise UnsupportedFile(f"{path}: not a file golblick knows")
    clip = video.open_clip(vendor, path)
    size = size or clip.size // 2
    info = vendor.describe(path)
    calibration = info["calibrations"].get(5)
    if calibration is None:
        raise UnsupportedFile(f"{path}: no equidistant calibration, so the lens geometry is unknown")
    calibration, cropped = video.video_calibration(calibration, info.get("sensor_crop"))
    profile = vendor.lens_profile(path) if hasattr(vendor, "lens_profile") else None
    radial = profile.radial if profile is not None else ()
    field_of_view = profile.field_of_view_for() if profile is not None else 194.0
    built = render.lenses_from_calibration(calibration, 2 * size, radial)
    level, orientation, heading, notes = video.opening(vendor, path, calibration)
    turns = headings = None
    # Read once for both: a half-hour record is 1.8 million samples.  Where
    # it can't be read, each asks again and says why in its own note.
    try:
        motion = vendor.motion(path)
    except (GolblickError, ValueError, AttributeError):
        motion = None
    try:
        turns, headings = video.steadying(vendor, path, level, heading, motion)
        notes.append(f"steadying      {len(turns)} frames from the motion record")
    except (GolblickError, ValueError, AttributeError) as exc:
        notes.append(f"steadying      not steadied: {exc}")
    read, line = video.shutter(vendor, path, motion)
    notes.append(line)
    strips = render.balance_strips(built, size, field_of_view)
    scene = Scene(
        jpeg=b"", width=2 * size, height=size,
        lenses=tuple(_shader_lens(lens, index, render) for index, lens in enumerate(built)),
        radial=tuple(radial), theta_max=float(numpy.deg2rad(field_of_view / 2)),
        feather=float(numpy.deg2rad(1.5)),
        camera_from_world=_rows(numpy.asarray(orientation).T),
        notes=(cropped, *notes),
    )
    return VideoScene(scene, clip, size, _rows(orientation),
                      None if turns is None else tuple(tuple(float(v) for v in q) for q in turns),
                      None if headings is None else tuple(float(h) for h in headings),
                      None if read is None else tuple(read), strips)


def refine_video(path: str | Path, video: VideoScene) -> VideoScene:
    """The slow part for a clip, for a background thread while it plays: lens guards and the seam.

    The same decision the stitch makes (``video.decide``), from a few frames
    decoded on their own, so the player and a stitched copy hand over between
    the lenses in the same place.
    """
    import numpy

    from . import render
    from . import video as videos
    from .vendors import detect

    path = str(path)
    vendor = detect(path)
    info = vendor.describe(path)
    calibration, _ = videos.video_calibration(info["calibrations"][5], info.get("sensor_crop"))
    field_of_view, seam, notes = videos.decide(vendor, path, video.clip, calibration)
    profile = vendor.lens_profile(path) if hasattr(vendor, "lens_profile") else None
    built = render.lenses_from_calibration(calibration, 2 * video.size, profile.radial if profile is not None else ())
    scene = replace(
        video.scene, theta_max=float(numpy.deg2rad(field_of_view / 2)),
        seam=None if seam is None or seam.offset is None else tuple(float(v) for v in seam.offset),
        parallax=None if seam is None or seam.parallax is None else tuple(float(v) for v in seam.parallax),
        baseline=None if seam is None or seam.parallax is None else tuple(float(v) for v in seam.direction),
        notes=(*video.scene.notes, *notes),
    )
    return replace(video, scene=scene, strips=render.balance_strips(built, video.size, field_of_view))


class LensBalance:
    """Evens out a playing clip's two lenses the way its stitched copy does (``video._balance``).

    The camera leaves a video's lenses unmatched, and not by one factor, so
    each frame the strip round the seam is read from both lenses, turned into
    RGB as the shader does, and lens 1 less lens 0 averaged across it, leaving
    out a channel at white in either.  That is smoothed round the seam and over
    the last :data:`BALANCE_FRAMES` frames.  :meth:`update` gives half of it per
    strip column, clipped to :data:`BALANCE_LIMIT`, which the shader adds to
    lens 0 and takes from lens 1, fading out ``render.BALANCE_REACH`` degrees
    from the seam.
    """

    def __init__(self, strips: dict, size: int, low, gain, matrix):
        import numpy

        self._at = [(numpy.asarray(strips[f"s{lens}y"]), numpy.asarray(strips[f"s{lens}x"])) for lens in (0, 1)]
        self._size = size
        self._low = numpy.asarray(low, numpy.float32)
        self._gain = numpy.asarray(gain, numpy.float32)
        self._matrix = numpy.asarray(matrix, numpy.float32)
        self._recent: list = []
        self._last: int | None = None

    def _rgb(self, frame, lens: int):
        import numpy

        luma, chroma = frame.planes(lens)
        y, x = self._at[lens]
        luma = numpy.frombuffer(luma, numpy.uint8).reshape(self._size, self._size)
        chroma = numpy.frombuffer(chroma, numpy.uint8).reshape(self._size // 2, self._size // 2, 2)
        yuv = numpy.concatenate([luma[y, x][..., None], chroma[y // 2, x // 2]], -1) / numpy.float32(255)
        return numpy.clip((yuv - self._low) * self._gain @ self._matrix.T, 0.0, 1.0) * 255

    def update(self, frame):
        """Frame ``frame``'s correction, ``(columns, 3)`` levels; the average restarts after a seek."""
        import numpy

        # Skipped frames, as when the player catches up, don't matter; a seek does.
        if self._last is None or not 0 < frame.index - self._last <= BALANCE_FRAMES:
            self._recent = []
        self._last = frame.index
        first, second = self._rgb(frame, 0), self._rgb(frame, 1)
        difference = numpy.where((first >= 250) | (second >= 250), 0.0, second - first).mean(0)
        box = 2 * BALANCE_BLUR + 1
        for _ in range(2):
            wrapped = numpy.concatenate([difference[-BALANCE_BLUR:], difference, difference[:BALANCE_BLUR]])
            summed = numpy.cumsum(numpy.concatenate([numpy.zeros((1, 3)), wrapped]), 0)
            difference = (summed[box:] - summed[:-box]) / box
        self._recent = (self._recent + [difference])[-BALANCE_FRAMES:]
        return numpy.clip(numpy.mean(self._recent, 0) / 2, -BALANCE_LIMIT, BALANCE_LIMIT)


def _shader_lens(lens, index: int, render) -> Lens:
    import numpy

    flip = numpy.diag([-1.0, 1.0, -1.0]) if index == 1 else numpy.eye(3)
    tilt = render._tilt_matrix(*lens.tilt) if lens.tilt != (0.0, 0.0) else numpy.eye(3)
    return Lens(lens.centre_x, lens.centre_y, lens.radius, float(lens.spin), _rows(tilt.T @ flip))


def _rows(matrix) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(float(v) for v in row) for row in matrix)
