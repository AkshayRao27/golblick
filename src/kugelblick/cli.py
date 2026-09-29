"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import imaging, triage
from .errors import KugelblickError, MissingDependency, UnsupportedFile
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
    output = Path(args.output) if args.output else Path(args.file).with_suffix(".thumb.jpg")
    output.write_bytes(data)
    print(f"{output}  ({_human(len(data))})")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    vendor = _require_vendor(args.file)
    if not hasattr(vendor, "extract_preview"):
        raise UnsupportedFile(f"{vendor.NAME} exposes no full-size preview")

    preview = vendor.extract_preview(args.file)
    default_suffix = ".preview.jpg" if preview.encoding == "jpeg" else ".preview.png"
    output = Path(args.output) if args.output else Path(args.file).with_suffix(default_suffix)

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

    source = vendor.extract_source(args.file)
    image = _decode_jpeg(source.data)
    lenses = render.lenses_from_calibration(model, source.width)

    width = args.width
    height = width // 2
    orientation, levelling = _levelling(render, vendor, args.file, model, args.level)

    pixels, hemispheres = render.equirectangular(
        image, lenses, (width, height), args.field_of_view, orientation=orientation
    )
    score = render.overlap_agreement(hemispheres)

    xmp = gpano.packet(width, height, software=f"kugelblick {_version()}")
    output = Path(args.output) if args.output else Path(args.file).with_suffix(".pano.jpg")
    _write_image(output, pixels, xmp, args.quality)

    print(f"{output}  ({_human(output.stat().st_size)})")
    print(f"  {width}x{height}  equirectangular  from {source.width}x{source.height}")
    print(f"  field of view  {args.field_of_view:g} degrees (fit it with --field-of-view)")
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
        except KugelblickError:
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
            f"installs: pip install 'kugelblick[render]'"
        )


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("kugelblick")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "dev"


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


def cmd_vendors(args: argparse.Namespace) -> int:
    for vendor in VENDORS:
        extensions = " ".join(sorted(f".{e}" for e in vendor.EXTENSIONS))
        print(f"{vendor.NAME:<12} {vendor.DESCRIPTION}")
        print(f"{'':<12} {extensions}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kugelblick",
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
        description="Needs the 'render' extra: pip install kugelblick[render]",
    )
    pano.add_argument("file")
    pano.add_argument("-o", "--output", help="output path; .png writes PNG, anything else JPEG")
    pano.add_argument("-w", "--width", type=int, default=4096,
                      help="output width in pixels; height is half (default: %(default)s)")
    pano.add_argument("-q", "--quality", type=int, default=92,
                      help="JPEG quality (default: %(default)s)")
    pano.add_argument("-f", "--field-of-view", type=float, default=194.0,
                      help="full angle each lens sees, in degrees. Not carried in the file: "
                           "measured at 194 on a OneR and X5, 192 on an X3 (default: %(default)s)")
    pano.add_argument("--level", choices=("auto", "imu", "calibration", "none"),
                      default="auto",
                      help="auto prefers the inertial record and falls back to the "
                           "calibration; imu and calibration force one and fail rather "
                           "than fall back (default: %(default)s)")
    pano.set_defaults(func=cmd_render)

    listing = sub.add_parser("vendors", help="list supported formats")
    listing.set_defaults(func=cmd_vendors)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KugelblickError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
