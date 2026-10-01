# 360 photo previews for Nextcloud

Generates previews for 360 camera container formats, so the files appear in Files and in a photo timeline instead of as a generic icon.

Insta360 `.insp` stills are supported today. The camera stores a **dual-fisheye pair**, not a panorama, so a usable thumbnail has to be *projected* rather than extracted, which is why a preview provider is needed at all.

## No new server-side dependency

The whole reader is reimplemented here in PHP: the trailer walk, the protobuf field walk, the lens calibration parse and the equirectangular projection. Pixels go through **GD**, which Nextcloud already requires. Nothing shells out, and the Python library in the parent repository is not called.

Measured over 1,415 stills from three camera bodies, at 256 px wide:

| | |
|---|---|
| Rendered | **1,409** (1,359 projected from the embedded preview, 25 from the full-resolution frame, 25 already-stitched) |
| Declined | 6 (no trailer), handed back to Nextcloud's own JPEG provider |
| Errors | **0** |
| Cost | 41 ms median, 58 ms at p95, 411 ms worst |

The full-resolution fallback is the expensive case by a wide margin (369 ms median, against 41 ms for the embedded preview), which is why it stays a fallback. The camera's own stitch is cheapest at 20 ms, being a colour conversion and nothing else.

A 1024 px preview through the full Nextcloud stack, including PNG encoding and storage, costs roughly half a second. It is generated once and cached.

Re-verified on Nextcloud 35 with the app installed, running against the container's own PHP at `memory_limit=128M`: 305 of 311 rendered, 6 declined for carrying no trailer, **zero errors**, 40 ms median.

### Memory

⚠️ The **full-resolution fallback** is the only path here that can be large. GD decodes to four bytes a pixel whatever size the output is, and offers no way to decode a JPEG at reduced scale, so an 18 MP frame needs about 70 MB and a 72 MP one about 290 MB. The renderer checks the frame's dimensions before decoding and **refuses rather than exhausting the limit**, because running out of memory inside `imagecreatefromstring` is a fatal error that takes the whole request with it instead of raising something catchable.

⚠️ The six trailer-less files fall through to Nextcloud's own JPEG provider, which then has to decode a full-resolution dual-fisheye frame itself. Depending on `preview_max_memory` (core's default is 256 MB, compared against `width * height * 4`) core may refuse them too, or run out of memory. That is a consequence of mapping `.insp` to `image/jpeg`, which makes these files visible to a provider that would otherwise never have been offered them.

## Install

```sh
occ app:enable golblick
```

⚠️ **Then register the file extension**, or nothing changes. Nextcloud stores `.insp` as `application/octet-stream` and never offers it to any image provider. Add `insp` to `config/mimetypemapping.json`, creating the file if it does not exist and *merging* if it does:

```json
{
    "insp": ["image/jpeg"]
}
```

```sh
occ maintenance:mimetype:update-db --repair-filecache
occ files:scan --all          # only needed for files already indexed
```

An app cannot ship this: Nextcloud reads custom mimetype mappings only from its own config directory. The private `registerType()` on the mimetype detector looks like an alternative and is a trap. Calling it before the defaults load makes the loader think mappings are already present and skip **every** built-in type.

### Why `image/jpeg` and not a type of its own

Because a `.insp` genuinely is a JPEG. Everything in front of the proprietary trailer is a complete one, and PHP's own `finfo` reports `image/jpeg` for these files already; Nextcloud disagrees only because its *extension* table has never heard of the format. The mapping above makes the extension agree with content detection rather than inventing a new type.

It is also the only thing that works. Nextcloud Memories chooses what to index from a hardcoded list of image mimetypes, so a bespoke `image/x-…` would be indexed by nothing however good its previews were.

## How it shares `image/jpeg` with Nextcloud's own provider

Nextcloud orders preview providers by the **length of their mimetype regex**, descending. This app registers `/^image\/jpeg$/`, which is longer than core's `/image\/jpeg/` and therefore tried first. It then looks for the Insta360 trailer magic and returns `null` for anything else, so ordinary JPEGs fall straight through to core.

⚠️ That ordering is an implementation detail of Nextcloud, not published API. If it ever changes, the failure is graceful: core renders the frame it finds, which is the unprojected lens pair. A wrong-looking thumbnail was preferred here to a hard dependency on internals.

## What the thumbnail shows

An equirectangular panorama, levelled by the best route the file supports:

| route | what it fixes | stills in the test library |
|---|---|---|
| The camera's own stitch | everything; it was levelled on the device | 48 (X5 only) |
| **Gravity**, from the inertial record | roll **and pitch** | 1,384 (417 from their own record, 967 from another frame of the same shutter press) |
| The lens calibration | the sensor's **mounting angle** only | the fallback when neither of the above is available |

Most stills carry no inertial record of their own, but every one in the test library sits in a burst or bracket where another frame does, and the camera writes the same reading to all of them. The provider looks for that frame in the same folder, never further. Without any levelling a OneR renders 90° on its side, so the calibration route is the floor.

The two lenses hand over across a narrow band about the line where they see equally well, and the hand-over is moved around nearby subjects where the scene allows. The relative orientation of the lenses and a per-camera lens correction come from the calibration and from measurement; see [docs/formats/insta360.md](../docs/formats/insta360.md). ⚠️ Objects within a metre or two of the camera can still break where the lenses meet, because the two lenses see them from slightly different places.

## What installing it changes

⚠️ Mapping `.insp` to `image/jpeg` is what gets the files indexed, and it also tells the rest of Nextcloud that the original file is an ordinary photo:

- Any `.insp` this app declines, such as the six in the test library that carry no trailer, goes to Nextcloud's own JPEG provider, which shows the raw lens pair and may run out of memory doing it (see [Memory](#memory)).
- In Nextcloud Memories, zooming into a `.insp` past the preview's resolution loads the original, which is the lens pair, so the panorama is replaced by two fisheye circles. A fix for that is written for Memories but not yet proposed upstream.
- Viewing a `.insp` as an interactive sphere needs a panorama viewer in Memories, which is in the same state.

## Layout

```
lib/Insta360/     Trailer · Protobuf · Calibration · EmbeddedPreview · Imu · LensProfile   the reader
lib/Render/       Equirectangular · Seam · Orientation                                    the projection
lib/Preview/      Insta360                                                                the provider
```

The reader is a deliberate port of `src/golblick/vendors/insta360/` in the parent repository, kept close enough to compare side by side. The container format itself is documented in `docs/formats/insta360.md`, which is the owner of every measured fact quoted above.

## Licence

AGPL-3.0-or-later, as the Nextcloud app ecosystem requires; the full text is in [COPYING](COPYING). The parent library is MIT.
