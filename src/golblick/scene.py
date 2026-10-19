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
    try:
        turns, headings = video.steadying(vendor, path, level, heading)
        notes.append(f"steadying      {len(turns)} frames from the motion record")
    except (GolblickError, ValueError, AttributeError) as exc:
        notes.append(f"steadying      not steadied: {exc}")
    read, line = video.shutter(vendor, path)
    notes.append(line)
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
                      None if read is None else tuple(read))


def _shader_lens(lens, index: int, render) -> Lens:
    import numpy

    flip = numpy.diag([-1.0, 1.0, -1.0]) if index == 1 else numpy.eye(3)
    tilt = render._tilt_matrix(*lens.tilt) if lens.tilt != (0.0, 0.0) else numpy.eye(3)
    return Lens(lens.centre_x, lens.centre_y, lens.radius, float(lens.spin), _rows(tilt.T @ flip))


def _rows(matrix) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(float(v) for v in row) for row in matrix)
