"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import imaging, triage
from .errors import KugelblickError, UnsupportedFile
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
