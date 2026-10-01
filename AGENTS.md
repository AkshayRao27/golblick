# Notes for coding agents

This project was written almost entirely by LLM coding agents, and contributions made the same way are welcome. This file is the context an agent needs before changing anything. Humans may find [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md) more useful.

## What this is

A Python library and CLI that reads 360-camera container files on Linux (Insta360 `.insp`, `.insv`, `.lrv` so far), extracts what the camera stored, and projects the dual-fisheye pair into an equirectangular panorama with GPano metadata. `nextcloud-app/` is a separate pure-PHP port that shows those files as panoramic previews in Nextcloud.

Read these first, in this order:

1. The vendor contract at the top of [`src/golblick/vendors/__init__.py`](src/golblick/vendors/__init__.py). Everything else follows from it.
2. [`docs/formats/insta360.md`](docs/formats/insta360.md), for what is known about the container and how each fact was measured.
3. [`docs/accuracy.md`](docs/accuracy.md), for what each check can and cannot see.

## Commands

```sh
uv sync --group dev && uv run pytest -q                    # without numpy
uv sync --group dev --extra render && uv run pytest -q     # with the render extra
uv run golblick --help
find nextcloud-app/lib -name '*.php' -exec php -l {} \;     # the PHP has no test suite; lint it
```

Run the tests both ways. The core must pass without numpy installed, and with numpy present a wrongly skipped test is invisible.

## Rules

- The library and CLI have no dependencies. numpy and Pillow are allowed only behind the `render` extra, and only in `render.py` and the CLI's render path.
- Refuse rather than guess. Raise `FormatError` instead of returning a partial or inferred parse. A parser has to prove it understood the layout; the trailer reader's padding search is the model.
- Detect files by content, not extension. `triage` is the one intentional exception, and it is tested.
- Vendor-specific code lives in the vendor's module. Adding a vendor should need a new module and a `VENDORS` entry, nothing else.
- Do not name what has not been verified. Unconfirmed calibration models stay raw tuples. In `docs/formats/`, mark inferred claims as unverified and never upgrade one without a measurement.
- Per-camera values the file does not carry (field of view, lens correction) live in the vendor's lens profile, with how they were measured. The PHP app restates those tables; a test fails if they drift.
- A change to the projection goes into both `src/golblick/render.py` and `nextcloud-app/lib/Render/`, and the two outputs are compared on the same file afterwards.
- Never add real photos or videos, or camera serial numbers, to the repository, including in pasted `probe` output. Fixtures are synthesised in the tests.
- Never develop or test the Nextcloud app against an instance that holds someone's real photos. Use a throwaway one in Docker.
- Commit messages explain why: what was measured, what was rejected, what a decision costs. One line per paragraph, no hard wrapping, and nothing about the people or places in anyone's photos.

## Verification habits that earned their place

Each of these comes from a confident wrong answer in this project's history.

- A claim that something is absent needs the enumeration behind it. A failed HTTPS connection was once reported as "this domain serves no website"; it served one over HTTP.
- A claim that something is universal needs the whole corpus. Run the parser over every file available, not two, and sample across camera models, not just across files.
- Score against something the project did not produce: a camera's embedded stitch, or a vendor's exported panorama. A render scored only against itself proves self-consistency, and a wrong stitch can be self-consistent.
- State each metric's blind spot next to it, and when a number is being driven down, ask what the optimiser can do that the number does not measure.
- A symptom with a shape describes the defect. Print the two disagreeing things side by side before theorising; a sign error and a rotation look different in a table.
- A transformation that does almost nothing is probably not being applied. Make it huge and check it fires.
- Write the index sum out before coding a matrix convention. Rows-as-vectors (`rays @ R`) applies the transpose.
- Test fixtures should be lopsided. A symmetric test cannot catch an asymmetric error, and handedness is invisible to everything except text in the picture.
- When two implementations disagree, reproduce the second one's exact conditions in the first before looking for a bug in the port.
- Measuring the source is not testing the deployment. Nextcloud caches previews on the server and the browser caches them under a URL keyed on the file's etag, so a regenerated preview can sit behind an old one.
- Weight anything measured along the seam by area on the sphere. The seam passes through the poles, where equirectangular pixels crowd.
