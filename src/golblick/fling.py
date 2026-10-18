"""The coast after a drag is let go: how far and how long, from how fast.

Android's fling model (``OverScroller`` in the Android Open Source Project,
Apache-2.0), because it has the feel people expect from a touch screen: the
coast grows faster than the speed, as speed to the power D/(D-1), about 1.74,
so a slow drag barely carries on and a quick flick keeps turning.  With
``r = ln(INFLEXION * speed / (FRICTION * k))`` the coast covers
``FRICTION * k * exp(D / (D - 1) * r)`` pixels in ``exp(r / (D - 1))`` seconds,
``k`` being a deceleration in pixels per second squared for the screen's
density.  Android eases over that time along a precomputed spline; this uses
``1 - (1 - t/T) ** (1 / INFLEXION)``, which covers the same distance in the
same time and starts at exactly the release speed, so there is no jolt on
letting go.

Qt-free, so it can be tested without the desktop extra.
"""

from __future__ import annotations

import math

#: Android's ``DECELERATION_RATE``, ln 0.78 / ln 0.9.
DECELERATION = math.log(0.78) / math.log(0.9)
#: Android's ``INFLEXION``.
INFLEXION = 0.35
#: Scroll friction: 1.5 times Android's default, so a coast is about a quarter
#: shorter.  Turning a sphere, Android's carried on further than felt right.
FRICTION = 0.0225
#: Faster releases are treated as this fast, in pixels a second.
MAX_SPEED = 3000.0
#: Below this a release is a stop, not a fling, so an unhurried drag ends where it's let go.
MIN_SPEED = 250.0
#: How much of the drag's end the release speed is read from, in seconds.
WINDOW = 0.08


def deceleration(dpi: float) -> float:
    """Android's physical deceleration, in pixels a second squared, at ``dpi``."""
    return 9.80665 * 39.37 * dpi * 0.84   # gravity, in inches, at the screen's density


def release_velocity(samples: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Pixels a second in x and y, from ``(seconds, x, y)`` pointer samples ending at the release.

    A straight-line fit over the last :data:`WINDOW` seconds, not the last two
    events: two samples a few milliseconds apart make a noisy speed, and a slow
    drag that ends with a twitch would fling.  A pointer that stopped before
    it was let go leaves fewer than two samples in the window, which is no fling.
    """
    if not samples:
        return 0.0, 0.0
    end = samples[-1][0]
    recent = [s for s in samples if end - s[0] <= WINDOW]
    if len(recent) < 2:
        return 0.0, 0.0
    mean_t = sum(s[0] for s in recent) / len(recent)
    spread = sum((s[0] - mean_t) ** 2 for s in recent)
    if spread <= 0:
        return 0.0, 0.0
    slopes = []
    for axis in (1, 2):
        mean = sum(s[axis] for s in recent) / len(recent)
        slopes.append(sum((s[0] - mean_t) * (s[axis] - mean) for s in recent) / spread)
    return slopes[0], slopes[1]


class Fling:
    """One coast along a straight line, in pixels; ``offset(t)`` is how far it has gone at ``t`` seconds."""

    def __init__(self, vx: float, vy: float, dpi: float = 96.0):
        # Only the main direction carries on: a sideways flick that drifted the
        # view up or down for a second afterwards would tip the horizon.
        if abs(vx) >= abs(vy):
            vy = 0.0
        else:
            vx = 0.0
        speed = min(math.hypot(vx, vy), MAX_SPEED)
        self.direction = (math.copysign(1.0, vx) if vx else 0.0, math.copysign(1.0, vy) if vy else 0.0)
        if speed < MIN_SPEED:
            self.distance = self.duration = 0.0
            return
        k = FRICTION * deceleration(dpi)
        r = math.log(INFLEXION * speed / k)
        self.duration = math.exp(r / (DECELERATION - 1))
        self.distance = k * math.exp(DECELERATION / (DECELERATION - 1) * r)

    def offset(self, t: float) -> tuple[float, float]:
        """Pixels covered after ``t`` seconds, along x and y."""
        if self.duration <= 0:
            return 0.0, 0.0
        share = 1.0 - (1.0 - min(t, self.duration) / self.duration) ** (1 / INFLEXION)
        return self.direction[0] * self.distance * share, self.direction[1] * self.distance * share

    def done(self, t: float) -> bool:
        return t >= self.duration
