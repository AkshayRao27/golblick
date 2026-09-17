"""Exceptions shared by every vendor reader."""


class SphereKitError(Exception):
    """Base class for every error this package raises."""


class UnsupportedFile(SphereKitError):
    """No registered vendor recognises this file."""


class FormatError(SphereKitError):
    """The file was recognised but could not be parsed.

    Raised in preference to returning a partial or guessed result: a reader that
    cannot prove it understood the layout should say so rather than hand back
    plausible-looking nonsense.
    """


class ThumbnailError(SphereKitError):
    """No embedded preview image could be extracted."""
