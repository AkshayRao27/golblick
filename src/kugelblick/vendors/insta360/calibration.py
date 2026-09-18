"""Lens calibration strings carried in the 0x0101 metadata record.

The camera stores calibration as underscore-delimited ASCII, not packed binary,
and the richer cameras store it several times at increasing fidelity: four
models on an X5, three on an X3, and only the equidistant one on a OneR, so
nothing may require the richest model to be present.  Every string starts with a
lens count and ends with one or more global values; between those sit one block
per lens::

    <lens_count> _ <lens 0 block> _ <lens 1 block> _ <globals>

Parameters are quoted against a reference frame carried in the string itself,
which is usually not the image size, so they must be scaled by
``actual_width / reference_width`` before use.  The reference frame is *per
camera* -- 6080x3040 on a OneR, 11904x5952 on an X3, 10752x5376 on an X5 -- so
it is always read from the string and never assumed.  The scale is not always a
reduction either: the X5's high-resolution still mode is wider than its own
reference frame.

That scaling is verified geometrically: on a 5888x2944 X5 still, the equidistant
model's lens radius of 2650.989 scales to 1451.7 px against a 1472 px half-cell,
placing the image circle just inside its half of the frame as it should be.

WHAT IS VERIFIED, AND WHAT IS NOT
--------------------------------
The block structure, the lens count, the reference frame and the scaling rule
are measured.  For the equidistant model the six per-lens values are identified
(radius, centre x, centre y, roll, pitch, yaw) by cross-checking exiftool.

The interior layout of the richer models is *not* yet confirmed.  The names in
MODELS are descriptions of shape, not claims about meaning, and the parameters
are deliberately exposed as a raw tuple rather than as named attributes so that
nothing here reads as a fact it has not earned.  Identifying them is the first
experiment of the rendering work; see docs/formats/insta360.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import metadata

# field number -> (values per lens, trailing global values, short description)
MODELS = {
    metadata.CALIBRATION_EQUIDISTANT: (6, 3, "equidistant"),
    metadata.CALIBRATION_POLY: (16, 1, "polynomial"),
    metadata.CALIBRATION_MEI: (19, 1, "mei"),
    metadata.CALIBRATION_MEI_EXTENDED: (27, 1, "mei-extended"),
}

#: Fallback only, for a string that carries no reference frame of its own.
#: This is the X5's value; a OneR quotes 6080x3040 and an X3 11904x5952, so it
#: is a last resort rather than a property of the format.
REFERENCE_FRAME = (10752, 5376)


class CalibrationError(Exception):
    """A calibration string did not match its expected shape."""


@dataclass(frozen=True)
class Calibration:
    """One parsed calibration string."""

    field: int
    kind: str
    lenses: tuple[tuple[float, ...], ...]
    globals: tuple[float, ...]
    raw: str

    @property
    def lens_count(self) -> int:
        return len(self.lenses)

    @property
    def reference_frame(self) -> tuple[int, int]:
        """The frame the parameters are quoted against.

        The equidistant model carries it in the trailing globals; the richer
        models repeat it at the end of every lens block.
        """
        if self.field == metadata.CALIBRATION_EQUIDISTANT and len(self.globals) >= 2:
            return int(self.globals[0]), int(self.globals[1])
        if self.lenses and len(self.lenses[0]) >= 3:
            return int(self.lenses[0][-3]), int(self.lenses[0][-2])
        return REFERENCE_FRAME

    def scale_for(self, width: int) -> float:
        """Factor converting stored parameters to an image ``width`` pixels wide."""
        reference_width = self.reference_frame[0]
        if reference_width <= 0:
            raise CalibrationError(f"bad reference width {reference_width}")
        return width / reference_width


def parse(text: str, field: int) -> Calibration:
    """Parse one underscore-delimited calibration string from ``field``."""
    parts = text.strip().split("_")
    if len(parts) < 2:
        raise CalibrationError(f"field {field}: only {len(parts)} parts")

    try:
        values = [float(part) for part in parts]
    except ValueError as exc:
        raise CalibrationError(f"field {field}: non-numeric part ({exc})") from exc

    lens_count = int(values[0])
    if lens_count <= 0:
        raise CalibrationError(f"field {field}: lens count {lens_count}")

    if field in MODELS:
        per_lens, n_globals, kind = MODELS[field]
        expected = 1 + per_lens * lens_count + n_globals
        if len(values) != expected:
            raise CalibrationError(
                f"field {field}: expected {expected} parts for {lens_count} lenses, got {len(values)}"
            )
    else:
        # Unknown field: assume one trailing global and split the rest evenly.
        kind = "unknown"
        remaining = len(values) - 2
        if remaining <= 0 or remaining % lens_count:
            raise CalibrationError(f"field {field}: {len(values)} parts do not divide by {lens_count}")
        per_lens = remaining // lens_count

    lenses = tuple(
        tuple(values[1 + i * per_lens : 1 + (i + 1) * per_lens]) for i in range(lens_count)
    )
    return Calibration(
        field=field,
        kind=kind,
        lenses=lenses,
        globals=tuple(values[1 + per_lens * lens_count :]),
        raw=text,
    )


def from_metadata(grouped: dict[int, list[metadata.Field]]) -> dict[int, Calibration]:
    """Parse every calibration string present, keyed by field number.

    Strings that fail to parse are skipped rather than raising, so one changed
    model does not make the others unreadable.
    """
    found: dict[int, Calibration] = {}
    for field in metadata.CALIBRATION_FIELDS:
        text = metadata.first_text(grouped, field)
        if text is None:
            continue
        try:
            found[field] = parse(text, field)
        except CalibrationError:
            continue
    return found


def best(calibrations: dict[int, Calibration]) -> Calibration | None:
    """The richest calibration available, or None."""
    for field in reversed(metadata.CALIBRATION_FIELDS):
        if field in calibrations:
            return calibrations[field]
    return None
