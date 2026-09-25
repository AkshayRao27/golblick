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
| Cost | 30 ms median, 36 ms at p95, 399 ms worst |

A 1024 px preview through the full Nextcloud stack, including PNG encoding and
storage, costs roughly half a second. It is generated once and cached.

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

An equirectangular panorama, levelled for **roll** using the lens calibration
carried in the file — without that a One R renders 90° on its side.

⚠️ It is **not** levelled for pitch. A shot taken with the camera tilted
forward stays tilted. The inertial record that would fix it is present in only
about a third of files, and reading it is not implemented here.

⚠️ The seam between the two lenses is a hard cut, not a blend. At thumbnail
size that is invisible; it is not suitable as an export path.

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
