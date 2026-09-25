# 360 photo previews — a Nextcloud app

Generates previews for 360 camera container formats, so the files appear in
Files and in a photo timeline instead of as a generic icon.

Insta360 `.insp` stills are supported today. The camera stores a **dual-fisheye
pair**, not a panorama, so a usable thumbnail has to be *projected* rather than
extracted — which is why a preview provider is needed at all.

## No new server-side dependency

The whole reader is reimplemented here in PHP: the trailer walk, the protobuf
field walk, the lens calibration parse and the equirectangular projection.
Pixels go through **GD**, which Nextcloud already requires. Nothing shells out,
and the Python library in the parent repository is not called.

Measured over 1,415 stills from three camera bodies, at 256 px wide:

| | |
|---|---|
| Rendered | **1,409** — 1,359 projected from the embedded preview, 25 from the full-resolution frame, 25 already-stitched |
| Declined | 6 — no trailer; handed back to Nextcloud's own JPEG provider |
| Errors | **0** |
| Cost | 41 ms median, 58 ms at p95, 411 ms worst |

The full-resolution fallback is the expensive case by a wide margin — 369 ms
median against 41 ms for the embedded preview — which is why it stays a
fallback. The camera's own stitch is cheapest at 20 ms, being a colour
conversion and nothing else.

A 1024 px preview through the full Nextcloud stack, including PNG encoding and
storage, costs roughly half a second. It is generated once and cached.

Re-verified on Nextcloud 35 with the app installed, running against the
container's own PHP at `memory_limit=128M`: 305 of 311 rendered, 6 declined for
carrying no trailer, **zero errors**, 40 ms median.

### Memory

⚠️ The **full-resolution fallback** is the only path here that can be large. GD
decodes to four bytes a pixel whatever size the output is, and offers no way to
decode a JPEG at reduced scale, so an 18 MP frame needs about 70 MB and a 72 MP
one about 290 MB. The renderer checks the frame's dimensions before decoding and
**refuses rather than exhausting the limit**, because running out of memory
inside `imagecreatefromstring` is a fatal error that takes the whole request
with it instead of raising something catchable.

⚠️ The six trailer-less files fall through to Nextcloud's own JPEG provider,
which then has to decode a full-resolution dual-fisheye frame itself. Depending
on `preview_max_memory` (core's default is 256 MB, compared against
`width * height * 4`) core may refuse them too, or run out of memory. That is a
consequence of mapping `.insp` to `image/jpeg` — it makes these files visible to
a provider that would otherwise never have been offered them.

## Install

```sh
occ app:enable kugelblick
```

⚠️ **Then register the file extension**, or nothing changes — Nextcloud stores
`.insp` as `application/octet-stream` and never offers it to any image
provider. Add `insp` to `config/mimetypemapping.json`, creating the file if it
does not exist and *merging* if it does:

```json
{
    "insp": ["image/jpeg"]
}
```

```sh
occ maintenance:mimetype:update-db --repair-filecache
occ files:scan --all          # only needed for files already indexed
```

An app cannot ship this: Nextcloud reads custom mimetype mappings only from its
own config directory. The private `registerType()` on the mimetype detector
looks like an alternative and is a trap — calling it before the defaults load
makes the loader think mappings are already present and skip **every** built-in
type.

### Why `image/jpeg` and not a type of its own

Because a `.insp` genuinely is a JPEG. Everything in front of the proprietary
trailer is a complete one, and PHP's own `finfo` reports `image/jpeg` for these
files already; Nextcloud disagrees only because its *extension* table has never
heard of the format. The mapping above makes the extension agree with content
detection rather than inventing a new type.

It is also the only thing that works. Nextcloud Memories chooses what to index
from a hardcoded list of image mimetypes, so a bespoke `image/x-…` would be
indexed by nothing however good its previews were.

## How it shares `image/jpeg` with Nextcloud's own provider

Nextcloud orders preview providers by the **length of their mimetype regex**,
descending. This app registers `/^image\/jpeg$/`, which is longer than core's
`/image\/jpeg/` and therefore tried first. It then looks for the Insta360
trailer magic and returns `null` for anything else, so ordinary JPEGs fall
straight through to core.

⚠️ That ordering is an implementation detail of Nextcloud, not published API.
If it ever changes, the failure is graceful: core renders the frame it finds,
which is the unprojected lens pair. A wrong-looking thumbnail was preferred
here to a hard dependency on internals.

## What the thumbnail shows

An equirectangular panorama, levelled by the best route the file supports.

| route | what it fixes | reaches |
|---|---|---|
| The camera's own stitch | everything; it was levelled on the device | 25 — X5 only |
| **Gravity**, from the inertial record | roll **and pitch** | 379 |
| The lens calibration | the sensor's **mounting angle** only | 1,005 |

Without any of it a One R renders 90° on its side, so the calibration route is
the floor rather than a nicety.

⚠️ **Most files get roll only, and that is visible.** Measured against the
inertial record, what the calibration route leaves uncorrected is a median of
**10.8°** on a One R, with 77% of files over 5°. Flat on a timeline tile; a
wobbling horizon as soon as the panorama is turned in a sphere viewer.

⛔ Gravity reaches about a quarter of the library and no further. 965 of 1,415
stills carry no inertial record at all, and the X3's inertial axes are
**refused rather than guessed** — its readings cannot be reconciled with the
camera's attitude, and a wrong mapping produces a confident, wrong horizon.
Levelling the rest needs the horizon estimated from the image, which nothing
here does yet.

The two lenses are cross-faded over the 14 degrees where both of them see the
scene, so the join is not a visible line. ⚠️ It is a blend and not a parallax
fix: close objects still ghost near the seam, so this is not an export path.

⚠️ This was a hard cut until it was measured, on the reasoning that a seam is
invisible on a timeline tile. That was wrong — Nextcloud serves this same
preview at full viewer size, where the two seam columns were the sharpest in
the whole frame, at 6.6x and 4.1x the median column gradient. After the
cross-fade they are 1.5x and 1.6x, and the sharpest column in the frame is
scene detail rather than a lens boundary.

## Layout

```
lib/Insta360/     Trailer · Protobuf · Calibration · EmbeddedPreview   the reader
lib/Render/       Equirectangular                                      the projection
lib/Preview/      Insta360                                             the provider
```

The reader is a deliberate port of `src/kugelblick/vendors/insta360/` in the
parent repository, kept close enough to compare side by side. The container
format itself is documented in `docs/formats/insta360.md`, which is the owner
of every measured fact quoted above.

## Licence

AGPL-3.0-or-later, as the Nextcloud app ecosystem requires. The parent library
is MIT.
