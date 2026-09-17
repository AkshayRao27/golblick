"""Read, inspect and triage Insta360 ``.insp`` and ``.insv`` files on Linux."""

from .calibration import Calibration
from .trailer import Insta360Error, NotInsta360, Record, Trailer, TrailerError, read_trailer

__all__ = [
    "Calibration",
    "Insta360Error",
    "NotInsta360",
    "Record",
    "Trailer",
    "TrailerError",
    "read_trailer",
]

__version__ = "0.1.0"
