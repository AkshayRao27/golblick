"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import calibration, metadata, thumbnail, triage
from .trailer import METADATA, Insta360Error, RECORD_NAMES, read_trailer


def _human(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def cmd_probe(args: argparse.Namespace) -> int:
    trailer = read_trailer(args.file)
    print(f"{args.file}")
    print(f"  trailer     version {trailer.version}, {_human(trailer.size)} "
          f"at offset {trailer.offset}, pad {trailer.pad}")
    print(f"  records     {len(trailer.records)}")
    for record in trailer.records:
        known = "" if record.id in RECORD_NAMES else "  (unrecognised)"
        print(f"    0x{record.id:04x}  {record.name:<16} {record.size:>9} bytes{known}")

    blob = trailer.get(METADATA)
    if blob is None:
        print("  metadata    absent")
        return 0

    grouped = metadata.by_number(blob.data)
    print("  metadata")
    for number, label in (
        (metadata.SERIAL, "serial"),
        (metadata.MODEL, "model"),
        (metadata.FIRMWARE, "firmware"),
    ):
        print(f"    {label:<11} {metadata.first_text(grouped, number) or '-'}")
    dimensions = metadata.dimensions(grouped)
    if dimensions:
        print(f"    {'dimensions':<11} {dimensions[0]}x{dimensions[1]}")

    found = calibration.from_metadata(grouped)
    print(f"  calibration {len(found)} model(s)")
    for field_number in metadata.CALIBRATION_FIELDS:
        model = found.get(field_number)
        if model is None:
            continue
        scale = ""
        if dimensions:
            scale = f", scale x{model.scale_for(dimensions[0]):.6f}"
        print(f"    field {field_number:<4} {model.kind:<13} "
              f"{model.lens_count} lenses x {len(model.lenses[0])} params"
              f", reference {model.reference_frame[0]}x{model.reference_frame[1]}{scale}")
        if args.verbose:
            for index, lens in enumerate(model.lenses):
                print(f"        lens {index}: {' '.join(f'{v:g}' for v in lens)}")
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    report = triage.scan(args.directory)

    if args.json:
        print(json.dumps({
            "clips": [
                {
                    "directory": str(clip.directory),
                    "stamp": clip.stamp,
                    "sequence": clip.sequence,
                    "status": clip.status,
                    "masters": [str(a.path) for a in clip.masters],
                    "proxies": [str(a.path) for a in clip.proxies],
                    "bytes": clip.size,
                }
                for clip in report.clips
            ],
            "photos": [str(a.path) for a in report.photos],
            "unmatched": [str(p) for p in report.unmatched],
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
        print(f"  {len(report.unmatched)} file(s) with an Insta360 extension but an unexpected name:")
        for path in report.unmatched[:10]:
            print(f"    {path}")

    return 0


def cmd_thumb(args: argparse.Namespace) -> int:
    data = thumbnail.extract(args.file)
    if args.output is None:
        output = Path(args.file).with_suffix(".thumb.jpg")
    else:
        output = Path(args.output)
    output.write_bytes(data)
    print(f"{output}  ({_human(len(data))})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insta360",
        description="Inspect and triage Insta360 .insp / .insv files on Linux.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="dump trailer records, metadata and calibration")
    probe.add_argument("file")
    probe.add_argument("-v", "--verbose", action="store_true", help="print calibration parameters")
    probe.set_defaults(func=cmd_probe)

    scan = sub.add_parser("triage", help="pair masters with proxies and report orphans")
    scan.add_argument("directory", type=Path)
    scan.add_argument("--json", action="store_true", help="machine-readable output")
    scan.set_defaults(func=cmd_triage)

    thumb = sub.add_parser("thumb", help="extract the camera's embedded stitched thumbnail")
    thumb.add_argument("file")
    thumb.add_argument("-o", "--output")
    thumb.set_defaults(func=cmd_thumb)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Insta360Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
