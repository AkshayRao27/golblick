# Development

## Setup and tests

```sh
uv sync --group dev && uv run pytest -q                    # without numpy: rendering tests skip
uv sync --group dev --extra render && uv run pytest -q     # with the render extra
```

Run it both ways. The library and CLI promise to run with no dependencies, and that promise is only real if the suite also passes without numpy installed. With numpy present, a test that should have been skipped looks the same as one that passed.

There is no linter configured yet. Match the surrounding style.

## Layout

```
src/kugelblick/
  errors.py            shared exceptions, vendor-neutral names
  triage.py            master/proxy pairing, vendor-neutral
  imaging.py           stdlib-only NV12 decode and PNG writing
  render.py            projection and its accuracy checks; numpy, behind the `render` extra
  gpano.py             GPano XMP: build the packet and embed it in JPEG or PNG; stdlib only
  cli.py               probe, triage, thumb, preview, render, vendors
  vendors/
    __init__.py        the registry, detection, and the vendor contract (read this first)
    insta360/          trailer, metadata, calibration, thumbnail, preview, source, imu, lens, naming
tests/                 pytest; every fixture is synthesised, none is real media
docs/formats/          what is known about each vendor's container, measured or marked unverified
nextcloud-app/         the Nextcloud preview app, a pure-PHP port (AGPL-3.0, not MIT)
```

## Principles

These come from mistakes made while building it.

- The library and CLI stay dependency-free. They have to run anywhere, including in a container with no toolchain. numpy and Pillow arrive only with the `render` extra.
- Refuse rather than guess. A reader that cannot prove it understood a layout raises `FormatError` instead of returning a plausible-looking result. The Insta360 trailer reader tries candidate padding widths and keeps only the one that makes the record walk land exactly on the trailer boundary; keep that property when extending it.
- Detect by content, not extension. `matches()` sniffs the file, so a renamed file is recognised and an impostor is not claimed. The one deliberate exception is `triage`, which classifies by filename because it runs over whole photo libraries and opening every file would cost a lot for nothing.
- Do not name what has not been verified. Calibration models whose interiors are unconfirmed are exposed as raw tuples, not named attributes. In `docs/formats/`, an inferred claim is marked unverified until it is measured.
- Test across cameras, not just across files. Much of what looks like a property of a format turned out to be a property of the camera that wrote the file. A thousand files from one camera are one camera.
- Score against something the project did not produce. A render checked only against itself, or against another render of ours, proves only that the code agrees with itself. See [accuracy.md](accuracy.md).
- Fixtures are synthesised. No real photos or videos go into the repository, and no camera serial numbers, including in pasted `probe` output.

## Adding a vendor

A vendor is a module exposing the names in the contract at the top of [`vendors/__init__.py`](../src/kugelblick/vendors/__init__.py): `NAME`, `DESCRIPTION`, `EXTENSIONS`, `matches`, `classify`, `describe` and `extract_thumbnail`, plus the optional `extract_preview`, `extract_source`, `gravity_up`, `gravity_up_nearby` and `lens_profile`. Listing it in `VENDORS` is the only change needed anywhere else. If something else has to change, the abstraction is wrong, and that is worth raising.

Measured facts about a container go in `docs/formats/<vendor>.md`. Values that a renderer needs but the file does not carry, such as the field of view or a lens correction, go in the vendor's lens profile, with a note on how they were measured.

## The Nextcloud app

`nextcloud-app/` is a separate implementation in PHP, using only GD, so that installing it adds no server-side dependency. It does not call the Python library. It ports the reader, the calibration parse, the projection, the seam routing and the per-camera lens tables. A test fails if the lens tables in the two implementations drift apart.

When changing the projection, change both, then compare their output on the same file. A port can be correct arithmetic and still behave differently: the first PHP reader read the trailer with a single `fread`, which works on a local file and fails through Nextcloud's stream wrappers, which return one 8 KiB chunk per read.

Try it in a throwaway Nextcloud in Docker, never on an instance holding real photos. Installation and the `mimetypemapping.json` entry it needs are in [nextcloud-app/README.md](../nextcloud-app/README.md). Previews are cached on the server and in the browser, so after changing the renderer, clear them with `occ preview:cleanup` and make sure the browser fetches fresh copies before judging the result.
