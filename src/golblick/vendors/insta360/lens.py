"""What the file does not say about the lenses, per camera model, measured.

The equidistant calibration gives each image circle's radius and centre but not
the angle its rim corresponds to, and it describes an exactly equidistant lens,
which no real lens is.  Both have to come from measurement, and both are
constants of the camera model, so they live here as a table -- the same kind of
thing as the inertial axis maps in :mod:`.imu`.

``field_of_view`` is the full angle each lens sees, fitted by how well the two
lenses agree where they overlap.

``radial`` is the correction to the equidistant model, sampled every
``render.RADIAL_STEP`` degrees out from the axis (see ``render.Lens.radial``).
It is measured against the vendor's own stitch: blocks of one of our lenses,
away from the seam where that lens appears alone in the reference, matched to
their place there.  Empty where that has not been measured well enough.

Stdlib only: this is read by the dependency-free CLI as well as the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LensProfile:
    field_of_view: float
    radial: tuple[float, ...] = ()
    #: Where the numbers came from, for anyone deciding whether to trust them.
    basis: str = ""


PROFILES: dict[str, LensProfile] = {
    "Insta360 OneR": LensProfile(
        field_of_view=194.0,
        # Peaks at +1.45 degrees 74 degrees off the axis.  Fitted over 14
        # scenes against Insta360 Studio exports (0.017 degrees RMS on the
        # binned medians), up to 86 degrees, where Studio still shows one lens alone;
        # continued straight beyond that, which held-out lens agreement chose
        # over any bend.
        radial=(
            0.000, 0.030, 0.039, 0.031, 0.010, -0.021, -0.058, -0.100, -0.144, -0.187,
            -0.227, -0.262, -0.290, -0.311, -0.321, -0.322, -0.311, -0.289, -0.254, -0.207,
            -0.148, -0.077, 0.005, 0.097, 0.199, 0.309, 0.425, 0.547, 0.670, 0.795,
            0.917, 1.034, 1.144, 1.242, 1.326, 1.392, 1.435, 1.451, 1.436, 1.385,
            1.293, 1.155, 0.965, 0.717, 0.438, 0.159, -0.119, -0.398, -0.677, -0.956,
            -1.235,
        ),
        basis="field of view fitted by lens agreement; radial measured against "
        "Insta360 Studio exports, 14 scenes",
    ),
    "Insta360 X3": LensProfile(
        field_of_view=192.0,
        # Peaks at -1.75 degrees 40 degrees off the axis, the other way from a
        # OneR.  Fitted at 192 -- a table fitted at one field of view and used
        # at another double-counts the difference -- to two scenes against
        # Insta360 Studio exports, which agree to within 0.2 degrees; fitted on either
        # scene it takes the other from 3.95 px to 1.02 px and 2.89 to 1.10.
        # Continued straight past 86 degrees, as on the OneR: every one of 40
        # frames then agrees better across the seam.  ⚠️ Two scenes is thin.
        radial=(
            0.000, -0.171, -0.328, -0.474, -0.609, -0.736, -0.856, -0.969, -1.076, -1.177,
            -1.273, -1.361, -1.443, -1.518, -1.584, -1.640, -1.687, -1.722, -1.745, -1.754,
            -1.750, -1.731, -1.697, -1.647, -1.580, -1.498, -1.400, -1.286, -1.159, -1.018,
            -0.865, -0.704, -0.536, -0.364, -0.192, -0.024, 0.135, 0.279, 0.403, 0.500,
            0.562, 0.580, 0.547, 0.452, 0.322, 0.193, 0.063, -0.067, -0.197, -0.326,
            -0.456,
        ),
        basis="field of view fitted by lens agreement; radial measured against "
        "Insta360 Studio exports, 2 scenes",
    ),
    "Insta360 X5": LensProfile(
        field_of_view=194.0,
        basis="field of view fitted by overlap_agreement; lens agreement prefers "
        "198 and the embedded stitch puts the rim at 194, unresolved",
    ),
}


def lens_profile(path: str | Path) -> LensProfile | None:
    """The measured profile for the camera that wrote ``path``, or None."""
    from . import describe  # circular at import time, fine at call time

    return PROFILES.get(describe(path)["model"])
