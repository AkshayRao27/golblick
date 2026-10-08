"""Command line interface."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from . import imaging, triage
from .errors import FormatError, GolblickError, MissingDependency, ThumbnailError, UnsupportedFile
from .vendors import VENDORS, detect


def _human(size: float) -> str:
    if abs(size) < 1024:
        return f"{int(size)} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        size /= 1024
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TiB"


def _require_vendor(path: str):
    vendor = detect(path)
    if vendor is None:
        raise UnsupportedFile(f"{path}: no registered vendor recognises this file")
    return vendor


def _output_path(args: argparse.Namespace, default_suffix: str) -> Path:
    """Where to write, refusing the one path that would destroy the original.

    Every command that writes leaves the source alone, and the docs promise
    it; a slip in ``-o`` is the only way to break that, so check for it.
    """
    output = Path(args.output) if args.output else Path(args.file).with_suffix(default_suffix)
    if output.resolve() == Path(args.file).resolve():
        raise GolblickError(f"{output}: refusing to write over the file being read")
    return output


def cmd_probe(args: argparse.Namespace) -> int:
    vendor = _require_vendor(args.file)
    info = vendor.describe(args.file)
    trailer = info["trailer"]

    print(f"{args.file}")
    print(f"  vendor      {vendor.NAME}")
    print(f"  trailer     version {trailer.version}, {_human(trailer.size)} "
          f"at offset {trailer.offset}, pad {trailer.pad}")
    print(f"  records     {len(trailer.records)}")
    for record in trailer.records:
        mark = "  (unrecognised)" if record.name.startswith("unknown_") else ""
        print(f"    0x{record.id:04x}  {record.name:<16} {record.size:>9} bytes{mark}")

    if any(info[key] for key in ("serial", "model", "firmware", "dimensions")):
        print("  metadata")
        for key in ("model", "firmware", "serial"):
            print(f"    {key:<11} {info[key] or '-'}")
        if info["dimensions"]:
            width, height = info["dimensions"]
            print(f"    {'dimensions':<11} {width}x{height}")

    calibrations = info["calibrations"]
    if not calibrations:
        return 0

    print(f"  calibration {len(calibrations)} model(s)")
    for field_number in sorted(calibrations):
        model = calibrations[field_number]
        scale = ""
        if info["dimensions"]:
            scale = f", scale x{model.scale_for(info['dimensions'][0]):.6f}"
        reference = model.reference_frame
        print(f"    field {field_number:<4} {model.kind:<13} "
              f"{model.lens_count} lenses x {len(model.lenses[0])} params"
              f", reference {reference[0]}x{reference[1]}{scale}")
        if args.verbose:
            for index, lens in enumerate(model.lenses):
                print(f"        lens {index}: {' '.join(f'{value:g}' for value in lens)}")
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    report = triage.scan(args.directory)

    if args.json:
        print(json.dumps({
            "clips": [
                {
                    "directory": str(clip.directory),
                    "group": clip.group,
                    "vendor": clip.vendor,
                    "status": clip.status,
                    "masters": [str(asset.path) for asset in clip.masters],
                    "proxies": [str(asset.path) for asset in clip.proxies],
                    "bytes": clip.size,
                }
                for clip in report.clips
            ],
            "photos": [str(asset.path) for asset in report.photos],
            "unmatched": [str(path) for path in report.unmatched],
            "redundant_bytes": report.redundant_bytes,
            "at_risk_bytes": report.at_risk_bytes,
        }, indent=2))
        return 0

    orphans = report.of_status(triage.ORPHAN_PROXY)
    paired = report.of_status(triage.PAIRED)
    master_only = report.of_status(triage.MASTER_ONLY)

    print(f"{args.directory}")
    print(f"  {len(report.clips)} clip(s), {len(report.photos)} photo(s)")
    print(f"    paired        {len(paired):>3}")
    print(f"    master only   {len(master_only):>3}")
    print(f"    orphan proxy  {len(orphans):>3}")

    if orphans:
        print()
        print("  ORPHANED PROXIES -- the master is missing, so the low-resolution")
        print("  proxy is the only surviving copy of these clips:")
        for clip in sorted(orphans, key=lambda c: -c.at_risk_bytes):
            for asset in clip.proxies:
                try:
                    shown = asset.path.relative_to(args.directory)
                except ValueError:
                    shown = asset.path
                print(f"    {_human(asset.size):>10}  {shown}")
        print()
        print(f"  {_human(report.at_risk_bytes)} exists only as proxy.")
        print("  Whether that was deliberate is not recorded in the files -- check before deleting.")

    if paired:
        print()
        print(f"  {_human(report.redundant_bytes)} of proxies duplicate a master that is still present.")

    if report.unmatched:
        print()
        print(f"  {len(report.unmatched)} file(s) with a known extension but an unexpected name:")
        for path in report.unmatched[:10]:
            print(f"    {path}")

    return 0


def cmd_thumb(args: argparse.Namespace) -> int:
    vendor = _require_vendor(args.file)
    data = vendor.extract_thumbnail(args.file)
    output = _output_path(args, ".thumb.jpg")
    output.write_bytes(data)
    print(f"{output}  ({_human(len(data))})")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    vendor = _require_vendor(args.file)
    if not hasattr(vendor, "extract_preview"):
        raise UnsupportedFile(f"{vendor.NAME} exposes no full-size preview")

    preview = vendor.extract_preview(args.file)
    default_suffix = ".preview.jpg" if preview.encoding == "jpeg" else ".preview.png"
    output = _output_path(args, default_suffix)

    if preview.encoding == "jpeg":
        # Already a JPEG, so copy it out rather than decoding and re-encoding it.
        data = preview.data
    else:
        data = imaging.write_png(
            imaging.nv12_to_rgb(preview.data, preview.width, preview.height),
            preview.width,
            preview.height,
        )
    output.write_bytes(data)

    print(f"{output}  ({_human(len(data))})")
    print(f"  {preview.width}x{preview.height}  {preview.encoding}  {preview.layout}")
    if not preview.is_stitched:
        print("  This camera stores the lens pair, not a stitch -- it is not viewable as a panorama.")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    """Project a file's lens pair into a viewable equirectangular panorama."""
    # Imported here, not at module scope: rendering needs the `render` extra
    # and the rest of the CLI must keep working without it.
    from . import gpano, render

    _require_render_extra()
    vendor = _require_vendor(args.file)
    if not hasattr(vendor, "extract_source"):
        raise UnsupportedFile(f"{vendor.NAME} exposes no full-resolution frame to project")

    info = vendor.describe(args.file)
    calibrations = info["calibrations"]
    model = calibrations.get(5)
    if model is None:
        raise UnsupportedFile(
            f"{args.file}: no equidistant calibration, so the lens geometry is unknown"
        )

    image, frame = _source_frame(vendor, args.file)
    reader = getattr(vendor, "lens_profile", None)
    profile = reader(args.file) if reader is not None else None
    field_of_view = args.field_of_view or (profile.field_of_view if profile else 194.0)
    radial = profile.radial if profile is not None else ()
    lenses = render.lenses_from_calibration(model, image.shape[1], radial)

    width = args.width
    height = width // 2
    orientation, levelling = _levelling(render, vendor, args.file, model,
                                        "auto" if args.level == "stitch" else args.level)
    if args.level in ("auto", "stitch"):
        try:
            orientation, levelling = _level_to_stitch(
                render, vendor, args.file, image, lenses, field_of_view, orientation)
        except (GolblickError, ValueError) as exc:
            if args.level == "stitch":
                raise GolblickError(f"cannot level against the camera's stitch: {exc}") from exc
            levelling += f" (the camera's own stitch was not usable: {exc})" \
                if not isinstance(exc, _NoStitch) else ""

    pixels, hemispheres = render.equirectangular(
        image, lenses, (width, height), field_of_view, orientation=orientation
    )
    score = render.overlap_agreement(hemispheres)

    xmp = gpano.packet(width, height, software=f"golblick {_version()}")
    output = _output_path(args, ".pano.jpg")
    _write_image(output, pixels, xmp, args.quality)

    print(f"{output}  ({_human(output.stat().st_size)})")
    print(f"  {width}x{height}  equirectangular  from {frame}")
    print(f"  field of view  {field_of_view:g} degrees"
          + ("" if args.field_of_view else " (the camera's measured value)"))
    print(f"  lens model     {'equidistant, measured correction' if radial else 'equidistant'}")
    print(f"  levelling      {levelling}")
    if score is not None:
        print(f"  lens agreement {score:+.3f}  (a wrong convention scores about +0.02)")
    return 0


def _levelling(render, vendor, path: str, calibration, mode: str):
    """Pick a levelling route and say which one was used.

    Two routes, and they are not equivalent.  The inertial one knows how the
    camera was actually held, so it fixes pitch as well as roll -- but most
    files carry no inertial record, and the axis mapping is only measured for
    some cameras.  The calibration one corrects the sensor's mounting angle
    only, and works on every file.  Preferring the better route and falling
    back is the whole point of ``auto``.
    """
    if mode == "none":
        return None, "none (--level none)"

    # Prefer the sibling-aware route -- most stills carry no record of their
    # own and take one from another frame of the same shutter press -- but both
    # are optional in the vendor contract, so fall back to the file-only one
    # rather than skipping levelling for a vendor that implements just that.
    reader = getattr(vendor, "gravity_up_nearby", None) or getattr(vendor, "gravity_up", None)

    if mode in ("auto", "imu") and reader is not None:
        try:
            up = reader(path)
        except GolblickError:
            if mode == "imu":
                raise
            note = "no usable inertial record"
        else:
            return render.level(up), "from gravity (inertial record): pitch and roll"
    elif mode == "imu":
        raise UnsupportedFile(f"{vendor.NAME} exposes no inertial record")
    else:
        note = "no inertial record"

    if mode == "calibration":
        note = "asked for"
    return (
        render.body_orientation(calibration),
        f"roll {calibration.body_roll:+.2f} degrees from the calibration "
        f"-- the sensor mounting, not how the camera was held ({note})",
    )


def cmd_report(args: argparse.Namespace) -> int:
    """A summary of a file that is safe to paste into a public issue.

    Two kinds of issue use it, and the report picks the form: a problem with
    a photo from a camera golblick has been tested with, or a camera it has
    not been tested with, which is worth reporting whether it works or not.
    "Tested" means the camera has a measured lens profile.

    It leaves out what could identify a person: the file's name (Insta360
    names carry the date and time), the folder (people name folders after
    places and trips) and the camera's serial number.  What is left is the
    structure of the file and what golblick made of it.

    Every step reports its own failure and the report carries on, because the
    files people report are the ones that fail somewhere, and where it stops
    is the useful part.
    """
    path = Path(args.file)
    # Longest first, so a full path is replaced whole before its folder is.
    hide = sorted(
        {(str(path), "<file>"), (str(path.resolve()), "<file>"), (path.name, "<file>"),
         (str(path.resolve().parent), "<folder>")} - {("", "<file>"), (".", "<folder>")},
        key=lambda pair: len(pair[0]), reverse=True,
    )

    def clean(exc: BaseException) -> str:
        text = str(exc)
        for value, replacement in hide:
            text = text.replace(value, replacement)
        return text

    info: dict | None = None
    recognised = False
    tested: bool | None = None
    lines = [f"golblick {_version()}, Python {sys.version.split()[0]}"]
    add = lines.append

    def step(label: str, read):
        try:
            return read()
        except Exception as exc:  # noqa: BLE001 -- every failure is part of the report
            add(f"{label:<12} failed: {type(exc).__name__}: {clean(exc)}")
            return None

    size = step("file", lambda: path.stat().st_size)
    if size is None:
        return _print_report(lines, info, recognised, tested, path)
    add(f"{'file':<12} {path.suffix.lower() or '(no extension)'}, {_human(size)}")

    vendor = detect(path)
    if vendor is None:
        add(f"{'vendor':<12} none recognises this file")
        add(f"{'content':<12} {step('content', lambda: _sniff(path)) or '-'}")
        return _print_report(lines, info, recognised, tested, path)
    add(f"{'vendor':<12} {vendor.NAME}")
    recognised = True

    info = step("metadata", lambda: vendor.describe(path))
    if info is None:
        return _print_report(lines, info, recognised, tested, path)
    for key in ("model", "firmware"):
        add(f"{key:<12} {info.get(key) or '-'}")
    if info.get("dimensions"):
        add(f"{'dimensions':<12} {info['dimensions'][0]}x{info['dimensions'][1]}")

    profile, profile_error = None, None
    reader = getattr(vendor, "lens_profile", None)
    if reader is not None:
        try:
            profile = reader(path)
        except Exception as exc:  # noqa: BLE001
            profile_error = exc
    tested = profile is not None
    add(f"{'tested':<12} {'yes' if tested else 'no: golblick has not been tested with this camera'}")

    trailer = info.get("trailer")
    if trailer is not None:
        add(f"{'trailer':<12} version {trailer.version}, {_human(trailer.size)}, pad {trailer.pad}")
        # By id, not file order, so this and the Nextcloud app's report line up.
        for index, record in enumerate(sorted(trailer.records, key=lambda record: record.id)):
            label = "records" if index == 0 else ""
            add(f"{label:<12} 0x{record.id:04x} {record.name:<16} {record.size:>9} bytes")

    calibrations = info.get("calibrations") or {}
    if not calibrations:
        add(f"{'calibration':<12} none")
    for index, number in enumerate(sorted(calibrations)):
        model = calibrations[number]
        reference = model.reference_frame
        label = "calibration" if index == 0 else ""
        add(f"{label:<12} field {number} {model.kind}, {model.lens_count} lenses x "
            f"{len(model.lenses[0])} params, reference {reference[0]}x{reference[1]}")

    if profile_error is not None:
        add(f"{'lens':<12} failed: {type(profile_error).__name__}: {clean(profile_error)}")
    elif profile is None:
        add(f"{'lens':<12} not measured for this camera")
    else:
        correction = f", radial correction ({len(profile.radial)} terms)" if profile.radial else ""
        add(f"{'lens':<12} measured: field of view {profile.field_of_view:g} degrees{correction}")

    for label, name in (("preview", "extract_preview"), ("source", "extract_source")):
        extract = getattr(vendor, name, None)
        if extract is not None:
            image = step(label, lambda extract=extract: extract(path))
            if image is not None:
                add(f"{label:<12} {image.width}x{image.height} {image.encoding} {image.layout}")

    # The same order the renderer tries, so the report says what a render
    # would actually do.
    routes = (
        (getattr(vendor, "gravity_up", None), "gravity, from this file's inertial record"),
        (getattr(vendor, "gravity_up_nearby", None),
         "gravity, from another frame of the same shutter press"),
    )
    levelling = None
    reason = "no inertial reader for this vendor"
    for reader, description in routes:
        if reader is None:
            continue
        try:
            reader(path)
        except Exception as exc:  # noqa: BLE001
            reason = clean(exc)
        else:
            levelling = description
            break
    add(f"{'levelling':<12} {levelling or 'calibration only: ' + reason}")
    return _print_report(lines, info, recognised, tested, path)


def _sniff(path: Path) -> str:
    """What an unrecognised file looks like, from its first and last bytes.

    Two kinds of file turned up in practice: a plain JPEG with none of the
    camera's data (an export, or an edit saved over the original), and a copy
    whose end is zeros, which is damage rather than a format.
    """
    with path.open("rb") as handle:
        head = handle.read(3)
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - 65536))
        tail = handle.read()
    zeros = len(tail) - len(tail.rstrip(b"\0"))
    if zeros >= 1024:
        amount = f"at least {_human(zeros)}" if zeros == len(tail) else _human(zeros)
        return f"the last {amount} are zeros: damaged or incompletely copied"
    if head == b"\xff\xd8\xff":
        if tail.endswith(b"\xff\xd9"):
            return "a complete JPEG with no camera data after it"
        return "begins like a JPEG, but does not end like one"
    return f"begins with {head.hex()}, not a JPEG"


#: The new-issue page; each issue form takes a query parameter per field id.
_ISSUE_FORM = "https://github.com/AkshayRao27/golblick/issues/new"


def _print_report(lines: list[str], info: dict | None, recognised: bool, tested: bool | None,
                  path: Path) -> int:
    """The report on stdout, and on stderr a link that opens the right issue form filled in.

    A camera golblick has been tested with gets the photo-problem form; any
    other camera gets the untested-camera form.  A file no vendor reads is a
    problem if it has one of a vendor's own extensions (a damaged .insp, say)
    and possibly a new camera otherwise.  The titles have one fixed shape each,
    shared with the Nextcloud app, so issues can be sorted at a glance.
    """
    from urllib.parse import urlencode

    from .vendors import owned_extensions

    report = "\n".join(lines)
    print("```")
    print(report)
    print("```")
    if recognised:
        problem = tested is not False
    else:
        problem = path.suffix.lower().lstrip(".") in owned_extensions()
    camera = ", ".join(value for value in (
        (info or {}).get("model") or "unrecognised file", (info or {}).get("firmware")) if value)
    template, prefix = (("photo-problem.yml", "Photo problem") if problem
                        else ("untested-camera.yml", "Untested camera"))
    query = urlencode({
        "template": template,
        "title": f"{prefix}: {camera} (command line)",
        "camera": camera,
        "report": report,
        "where": "Command-line tool",
    })
    if problem:
        intro = ("If something is wrong with this photo, open this link to report it. It fills in "
                 "a GitHub issue with the report; you add what's wrong.")
    else:
        intro = ("golblick hasn't been tested with this camera. A report helps whether the result "
                 "looks right or not: open this link, which fills in a GitHub issue with the report, "
                 "and add how it looks.")
    print(f"\n{intro}\n{_ISSUE_FORM}?{query}", file=sys.stderr)
    return 0


class _NoStitch(GolblickError):
    """The file carries no stitched panorama to level against; not worth a remark."""


def _level_to_stitch(render, vendor, path: str, image, lenses, field_of_view, start):
    """Level against the panorama the camera stitched and levelled itself, where there is one.

    🔴 Preferred over the inertial record whenever it exists, because it is
    ground truth and the record is not: an X5 that logged 13 seconds of being
    turned over rendered upside down from the record's median.  It also makes
    the result face the way the camera's own panorama does.  On the cameras
    measured so far only the X5 embeds a stitch.
    """
    extract = getattr(vendor, "extract_preview", None)
    if extract is None:
        raise _NoStitch("no preview reader")
    try:
        preview = extract(path)
    except ThumbnailError as exc:
        # No preview record, or a OneR or X3 video's keyframe where a still keeps one.
        raise _NoStitch(str(exc)) from exc
    if preview.layout != "equirectangular":
        raise _NoStitch("the preview is not a stitched panorama")

    from PIL import Image

    if preview.encoding == "nv12":
        frame = Image.frombytes("RGB", (preview.width, preview.height),
                                imaging.nv12_to_rgb(preview.data, preview.width, preview.height))
    else:
        frame = Image.open(io.BytesIO(preview.data)).convert("RGB")
    import numpy

    reference = numpy.asarray(frame.resize((512, 256), Image.LANCZOS), numpy.float32)
    orientation, score = render.orientation_from_reference(
        image, lenses, field_of_view, reference, start=start)
    return orientation, f"aligned to the camera's own levelled stitch (agreement {score:.2f})"


def _require_render_extra() -> None:
    """Fail with an instruction, not an ImportError from three frames down."""
    missing = []
    for module, name in (("numpy", "numpy"), ("PIL", "pillow")):
        try:
            __import__(module)
        except ImportError:
            missing.append(name)
    if missing:
        raise MissingDependency(
            f"rendering needs {' and '.join(missing)}, which the 'render' extra "
            f"installs: pip install 'golblick[render]'"
        )


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("golblick")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "dev"


def _source_frame(vendor, path: str):
    """The lens pair to project, decoded, and a line saying what it was.

    A still wraps a JPEG.  A video has no single frame, but a OneR or X3
    stores its opening frame in the trailer as one compressed keyframe per
    lens, so a video renders as that frame -- decoded by ffmpeg, because the
    library carries no video decoder.
    """
    try:
        source = vendor.extract_source(path)
    except FormatError as still:
        reader = getattr(vendor, "extract_keyframes", None)
        if reader is None:
            raise
        try:
            keyframes = reader(path)
        except FormatError as video:
            raise UnsupportedFile(
                f"{path}: no frame to project ({still}; and as a video: {video})") from video
        image = _decode_keyframes(keyframes)
        size = f"{image.shape[1]}x{image.shape[0]}"
        return image, f"the video's opening frame, {size} ({keyframes.codec} keyframes)"
    return _decode_jpeg(source.data), f"{source.width}x{source.height}"


def _decode_keyframes(keyframes):
    """Decode each stream with ffmpeg and put the lenses side by side, as in a still."""
    import shutil
    import subprocess
    from io import BytesIO

    import numpy
    from PIL import Image

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise UnsupportedFile("rendering a video's opening frame needs ffmpeg on the PATH")
    frames = []
    for stream in keyframes.streams:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-f", keyframes.codec, "-i", "pipe:0", "-frames:v", "1",
             "-f", "image2pipe", "-c:v", "png", "pipe:1"],
            input=stream, capture_output=True, check=False,
        )
        if result.returncode != 0 or not result.stdout:
            reason = result.stderr.decode(errors="replace").strip()
            raise FormatError(f"ffmpeg could not decode the keyframe: {reason}")
        frames.append(numpy.asarray(Image.open(BytesIO(result.stdout)).convert("RGB")))
    return frames[0] if len(frames) == 1 else numpy.hstack(frames)


def _decode_jpeg(data: bytes):
    from io import BytesIO

    import numpy
    from PIL import Image

    # The frame is tens of megapixels, which trips Pillow's decompression-bomb
    # guard.  It is our own camera's file and we have already proved the
    # container parses, so raise the ceiling rather than refuse it.
    Image.MAX_IMAGE_PIXELS = None
    return numpy.asarray(Image.open(BytesIO(data)).convert("RGB"))


def _write_image(output: Path, pixels, xmp: bytes, quality: int) -> None:
    from io import BytesIO

    import numpy
    from PIL import Image

    from . import gpano, imaging

    frame = numpy.clip(pixels, 0, 255).astype(numpy.uint8)
    height, width = frame.shape[:2]

    if output.suffix.lower() == ".png":
        # Our own writer, so the XMP goes in exactly the chunk we intend.
        output.write_bytes(imaging.write_png(frame.tobytes(), width, height, xmp=xmp))
        return

    buffer = BytesIO()
    Image.fromarray(frame).save(buffer, format="JPEG", quality=quality, subsampling=0)
    # Pillow encodes the pixels; we write the metadata, so the packet is the
    # one gpano built and not whatever Pillow's XMP support does this release.
    output.write_bytes(gpano.embed_jpeg(buffer.getvalue(), xmp))


def cmd_share(args: argparse.Namespace) -> int:
    """Write copies that are safe to send: no location, dates or serial number."""
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(name) for name in args.files]
    for index, source in enumerate(sources, 1):
        vendor = _require_vendor(str(source))
        clean = getattr(vendor, "shareable", None)
        if clean is None:
            raise UnsupportedFile(f"{source}: {vendor.NAME} cannot make a shareable copy yet")
        data, cleared = clean(source)
        # Insta360's own naming, with the date zeroed: the name carries the
        # date and time otherwise.
        target = out / f"IMG_00000000_000000_00_{index:03d}{source.suffix.lower()}"
        if target.exists():
            raise GolblickError(f"{target}: already exists; choose another folder with -o")
        target.write_bytes(data)
        print(f"{target}  from {source.name}")
        print(f"  cleared: {', '.join(dict.fromkeys(cleared)) or 'nothing to clear'}")
    print("\nThe pictures themselves are unchanged: check that nothing in them is private.",
          file=sys.stderr)
    return 0


def cmd_vendors(args: argparse.Namespace) -> int:
    for vendor in VENDORS:
        extensions = " ".join(sorted(f".{e}" for e in vendor.EXTENSIONS))
        print(f"{vendor.NAME:<12} {vendor.DESCRIPTION}")
        print(f"{'':<12} {extensions}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golblick",
        description="Read, inspect and triage 360 camera files on Linux.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="dump container records, metadata and calibration")
    probe.add_argument("file")
    probe.add_argument("-v", "--verbose", action="store_true", help="print calibration parameters")
    probe.set_defaults(func=cmd_probe)

    scan = sub.add_parser("triage", help="pair masters with proxies and report orphans")
    scan.add_argument("directory", type=Path)
    scan.add_argument("--json", action="store_true", help="machine-readable output")
    scan.set_defaults(func=cmd_triage)

    thumb = sub.add_parser("thumb", help="extract the 320x160 EXIF thumbnail")
    thumb.add_argument("file")
    thumb.add_argument("-o", "--output")
    thumb.set_defaults(func=cmd_thumb)

    full = sub.add_parser("preview", help="extract the camera's own full-size preview")
    full.add_argument("file")
    full.add_argument("-o", "--output")
    full.set_defaults(func=cmd_preview)

    pano = sub.add_parser(
        "render",
        help="project the lens pair into a viewable equirectangular panorama",
        description="Needs the 'render' extra: pip install golblick[render]",
    )
    pano.add_argument("file")
    pano.add_argument("-o", "--output", help="output path; .png writes PNG, anything else JPEG")
    pano.add_argument("-w", "--width", type=int, default=4096,
                      help="output width in pixels; height is half (default: %(default)s)")
    pano.add_argument("-q", "--quality", type=int, default=92,
                      help="JPEG quality (default: %(default)s)")
    pano.add_argument("-f", "--field-of-view", type=float, default=None,
                      help="full angle each lens sees, in degrees. Not carried in the file; "
                           "defaults to the camera's measured value (194 on a OneR and X5, "
                           "192 on an X3), or 194 for a camera nobody has measured")
    pano.add_argument("--level", choices=("auto", "stitch", "imu", "calibration", "none"),
                      default="auto",
                      help="auto aligns to the camera's own levelled stitch where the file "
                           "has one (X5), else uses the inertial record, else the "
                           "calibration; stitch, imu and calibration force one and fail "
                           "rather than fall back (default: %(default)s)")
    pano.set_defaults(func=cmd_render)

    report = sub.add_parser(
        "report",
        help="summarise a file for a GitHub issue (a problem with a photo, or an untested "
             "camera), without its name, folder or serial number",
    )
    report.add_argument("file")
    report.set_defaults(func=cmd_report)

    share = sub.add_parser(
        "share",
        help="copy files for sending to someone else, without location, dates or serial number",
    )
    share.add_argument("files", nargs="+")
    share.add_argument("-o", "--output", default="golblick-share",
                       help="folder for the copies (default: %(default)s)")
    share.set_defaults(func=cmd_share)

    listing = sub.add_parser("vendors", help="list supported formats")
    listing.set_defaults(func=cmd_vendors)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GolblickError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
