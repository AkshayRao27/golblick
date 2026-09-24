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


class MissingDependency(KugelblickError):
    """An optional extra is needed for this operation and is not installed.

    The library and CLI are dependency-free on purpose, so the one thing that
    is not -- rendering -- has to fail with an instruction rather than a
    traceback from somewhere deep in an import.
    """
