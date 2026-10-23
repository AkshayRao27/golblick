"""What the file does not say about the lenses, per camera model, measured.

The equidistant calibration gives each image circle's radius and centre but not
the angle its rim corresponds to, and it describes an exactly equidistant lens,
which no real lens is.  Both have to come from measurement, and both are
constants of the camera model, so they live here as a table -- the same kind of
thing as the inertial axis maps in :mod:`.imu`.

``field_of_view`` is the full angle each lens sees, fitted by how well the two
lenses agree where they overlap.

``radial`` is the correction to the equidistant model, sampled every
``render.RADIAL_STEP`` degrees out from the axis (see ``render.Lens.radial``),
measured against the vendor's own stitch.  Empty where that has not been
measured well enough.  Where ``radial_from_file`` is set, each file's own MEI
calibration gives it instead (``Calibration.radial_correction``): it is per
camera body, and on the X5 it beats any table measured here.

How each value was measured: ``docs/formats/insta360-agent-notes.md``, "The
equidistant model is close, but not exact" and "Lens guards narrow the field
of view (X5)".

Stdlib only: this is read by the dependency-free CLI as well as the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class LensProfile:
    field_of_view: float
    radial: tuple[float, ...] = ()
    #: Where the numbers came from, for anyone deciding whether to trust them.
    basis: str = ""
    #: How much a clip-on lens guard narrows the field of view, as a divisor,
    #: where measured.  None means guards are not modelled for this camera.
    guard_factor: float | None = None
    #: Take ``radial`` from the file's MEI calibration (field 54) where it carries one.
    radial_from_file: bool = False

    def field_of_view_for(self, guards: bool = False) -> float:
        """The angle to render with, with or without guards.

        The same for a still and a video: a video differs only by the sensor
        crop, which ``Calibration.for_video`` applies to the geometry.
        """
        return self.field_of_view / self.guard_factor if guards and self.guard_factor else self.field_of_view


PROFILES: dict[str, LensProfile] = {
    "Insta360 OneR": LensProfile(
        field_of_view=194.0,
        # Fitted against Insta360 Studio exports, 14 scenes, out to 86 degrees;
        # continued straight beyond that.
        radial=(
            0.000, 0.030, 0.039, 0.031, 0.010, -0.021, -0.058, -0.100, -0.144, -0.187,
            -0.227, -0.262, -0.290, -0.311, -0.321, -0.322, -0.311, -0.289, -0.254, -0.207,
            -0.148, -0.077, 0.005, 0.097, 0.199, 0.309, 0.425, 0.547, 0.670, 0.795,
            0.917, 1.034, 1.144, 1.242, 1.326, 1.392, 1.435, 1.451, 1.436, 1.385,
            1.293, 1.155, 0.965, 0.717, 0.438, 0.159, -0.119, -0.398, -0.677, -0.956,
            -1.235,
        ),
        basis="field of view fitted by lens agreement; radial measured against Insta360 Studio exports, 14 scenes",
    ),
    "Insta360 X3": LensProfile(
        field_of_view=192.0,
        # Fitted at 192 degrees against Insta360 Studio exports, two scenes;
        # continued straight past 86 degrees.  The table only holds at the field
        # of view it was fitted at: used at another it double-counts the
        # difference.
        radial=(
            0.000, -0.171, -0.328, -0.474, -0.609, -0.736, -0.856, -0.969, -1.076, -1.177,
            -1.273, -1.361, -1.443, -1.518, -1.584, -1.640, -1.687, -1.722, -1.745, -1.754,
            -1.750, -1.731, -1.697, -1.647, -1.580, -1.498, -1.400, -1.286, -1.159, -1.018,
            -0.865, -0.704, -0.536, -0.364, -0.192, -0.024, 0.135, 0.279, 0.403, 0.500,
            0.562, 0.580, 0.547, 0.452, 0.322, 0.193, 0.063, -0.067, -0.197, -0.326,
            -0.456,
        ),
        basis="field of view fitted by lens agreement; radial measured against Insta360 Studio exports, 2 scenes",
    ),
    "Insta360 X5": LensProfile(
        # Without lens guards, which narrow it by guard_factor.  Fitted by lens
        # agreement per file and checked against Insta360 Studio exports at the
        # seam.
        field_of_view=197.5,
        # Studio's "Standard lens guards" setting against its "off": a pure
        # radial scale of 2.25%.
        guard_factor=1.0225,
        # Against the camera's own stitch, 43 of 45 photos: a median 11 px of
        # error at 2048 wide without it, 2 px with it.
        radial_from_file=True,
        basis="field of view fitted by lens agreement per file, checked against Insta360 Studio exports; lens guard factor measured from Studio's own setting; radial from the file's MEI calibration, checked against the camera's own stitch",
    ),
}


def lens_profile(path: str | Path) -> LensProfile | None:
    """The measured profile for the camera that wrote ``path``, or None."""
    from ... import render
    from . import describe  # circular at import time, fine at call time
    from .calibration import CalibrationError
    from .metadata import CALIBRATION_MEI

    info = describe(path)
    profile = PROFILES.get(info["model"])
    if profile is None or not profile.radial_from_file:
        return profile
    mei = info["calibrations"].get(CALIBRATION_MEI)
    if mei is None:
        return profile
    try:
        radial = mei.radial_correction(render.RADIAL_STEP, int(100 / render.RADIAL_STEP) + 1)
    except CalibrationError:
        return profile   # equidistant, as before the curve was read
    return replace(profile, radial=radial)
