"""Exceptions shared by every vendor reader."""


class KugelblickError(Exception):
    """Base class for every error this package raises."""


class UnsupportedFile(KugelblickError):
    """No registered vendor recognises this file."""


class FormatError(KugelblickError):
    """The file was recognised but could not be parsed.

    Raised in preference to returning a partial or guessed result: a reader that
    cannot prove it understood the layout should say so rather than hand back
    plausible-looking nonsense.
    """


class ThumbnailError(KugelblickError):
    """No embedded preview image could be extracted."""
