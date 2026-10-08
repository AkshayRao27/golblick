"""Read, inspect and triage 360 camera files on Linux.

360 cameras wrap their footage in vendor-specific containers that standard tools
open but do not understand -- a dual-fisheye still looks like two circles, and
everything describing how to turn it into a viewable panorama lives in a
proprietary trailer the decoder skipped.

This package reads those containers.  Support is organised per vendor behind a
small contract; see :mod:`golblick.vendors`.
"""

from .errors import FormatError, GolblickError, ThumbnailError, UnsupportedFile
from .vendors import VENDORS, detect

__all__ = [
    "FormatError",
    "GolblickError",
    "ThumbnailError",
    "UnsupportedFile",
    "VENDORS",
    "detect",
]

__version__ = "0.4.0"
