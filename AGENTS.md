# Notes for coding agents

This project was written almost entirely by LLM coding agents, and contributions made the same way are welcome. This file is the context an agent needs before changing anything. Humans may find [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md) more useful.

## What this is

A Python library and CLI that reads 360-camera container files on Linux (Insta360 `.insp`, `.insv`, `.lrv` so far), extracts what the camera stored, and projects the dual-fisheye pair into an equirectangular panorama with GPano metadata. `nextcloud-app/` is a separate pure-PHP port that shows those files as panoramic previews in Nextcloud, plus a small browser-side sphere viewer.

Read these first, in this order:

1. The vendor contract at the top of [`src/golblick/vendors/__init__.py`](src/golblick/vendors/__init__.py). Everything else follows from it.
2. [`docs/formats/insta360-agent-notes.md`](docs/formats/insta360-agent-notes.md), for what is known about the container, how each fact was measured, and which earlier conclusions were wrong.
3. [`nextcloud-app/AGENT-NOTES.md`](nextcloud-app/AGENT-NOTES.md), before touching the PHP app.

## Where things go

The docs are split by reader. Pages for people stay short and plain; the detail an agent needs lives in notes files. Keep each fact in one place and link to it rather than restating it.

| What | Where |
|---|---|
| Container layout, record ids, calibration, measurements and their method | `docs/formats/<vendor>-agent-notes.md` |
| The same, in a page a person will read to the end | `docs/formats/<vendor>.md` |
| What each check measures, for users | `docs/accuracy.md` |
| Every CLI command | `docs/usage.md` |
| Nextcloud app internals | `nextcloud-app/AGENT-NOTES.md` |
| The vendor contract | the docstring in `src/golblick/vendors/__init__.py` |

When a measurement overturns something in a notes file, record the correction next to it rather than quietly editing the old claim. Several sections of `insta360-agent-notes.md` exist because an earlier confident answer was wrong.

## Commands

```sh
uv sync --group dev && uv run pytest -q                    # without numpy
uv sync --group dev --extra render && uv run pytest -q     # with the render extra
uv run golblick --help
find nextcloud-app/lib -name '*.php' -exec php -l {} \;     # the PHP has no test suite; lint it
(cd nextcloud-app && npm ci && npm run typecheck && npm run build)   # the sphere viewer; commit js/
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
- When checking against a reference, put both sides through the same pipeline. A box filter on one side and Lanczos on the other was once measured as a regression in the thing under test.
- A metric validated on a large effect doesn't transfer to a fine ranking. Lens agreement separates a right projection from a wrong one well, and ranks scene texture, not seam quality.
- Self-consistency can't see an error both halves share. A lens-model error that moves both lenses alike leaves lens agreement unchanged; matching each lens against an outside reference, where it appears alone, is what found it.
- An estimator has to be able to decline, and the decline has to be reachable. Comparing an optimum against a feasible solution of the same problem never fires; a guard needs a margin and a floor, and a test that it can trigger.
- Ghosting is not blur, and a sharpness metric can't see it. The test that catches a 50/50 blend is painting one lens red and the other blue.
- A 2:1 image is not necessarily equirectangular. Two square fisheye cells side by side are also 2:1. Render it and look.
- "Not measured" is a valid answer. Say what was measured and what was assumed, separately, and decompose a number before reporting it (total tilt is mostly the known sensor mounting angle; the residual is what matters).
- A route that does less work cannot cost more. If it measures that way, the cause is outside the code, usually a cold cache.
- A claim about what a system stores is a claim about its write path. Follow the data to whatever filters it, and prefer testing it to reading it.
- A port inherits the original's I/O semantics, not just its arithmetic. Nextcloud's stream wrappers return one 8 KiB chunk per `fread`.
- Check a claim about code with a `grep` before writing it down, and check the reason a comment gives as well as the claim.

## Nextcloud traps

- Clear previews with `occ preview:cleanup`, never by deleting files: the `oc_previews` rows outlive them.
- After copying new PHP into a running container, run `apachectl graceful`. The official image sets `opcache.revalidate_freq=60`, and a newly registered middleware did nothing until Apache restarted.
- Check a setting on the instance you're testing before crediting a fix. Memories' per-user `high_res_cond: never` stops zoom loading the original at all, which makes a broken zoom look fixed.
- With `debug` set, Nextcloud drops the `?v=` cache-busting suffix from scripts, so a rebuilt script can stay cached in the browser indefinitely. Load the page in a headless browser to see what is actually served.
- `sudo -u www-data` strips the environment, so a `php.ini` that reads `memory_limit=${PHP_MEMORY_LIMIT}` silently falls back. Measure under the limit the code will run with.
- Running out of PHP memory is fatal, not catchable. Check dimensions before decoding, as `checkImageMemory()` does in core.
- Mapping a type is a promise about the bytes. Anything downstream that serves originals will now treat the file as that type.
- A standalone harness can't see the integration it was extracted from. Measure in isolation, then confirm on a running server.
